import sys
import cv2
import h5py
import numpy as np
import matplotlib.pyplot as plt
import matplotlib as mpl
import framebuffer as fb
from gesture_classifier import dollar
import time
from common import *


mpl.use("TkAgg")


alpha = 0.5
T0 = 30

term_crit = ( cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 10, 1 )
chans = [1,2]
ranges = [0, 256, 0, 256]
nbins = [16,16]

fig = plt.figure(dpi=100)
axes = {}
figshape = (1,2)
axes['raw'] = plt.subplot2grid(figshape, (0, 0))
axes['draw'] = plt.subplot2grid(figshape, (0, 1))
axes['raw'].set_title('raw')
axes['draw'].set_title('-')
axes['draw'].set_xticklabels([])
axes['draw'].set_yticklabels([])

get_imdisp = lambda ax: ax.findobj(mpl.image.AxesImage)[0]

templates_fh = h5py.File('gesture_classifier/libras_templates.hdf5','r')
cap = fb.FrameBuffer(sys.argv[1] if len(sys.argv)>1 else -1, *map(int,sys.argv[2:]))
try:
    imgq = [cap.read()]*3
    imgq_g = [cv2.cvtColor(imgq[0],cv2.COLOR_BGR2GRAY)]*3
    imshape = imgq_g[0].shape
    waypts = []
    MAXLEN = min(imshape)//2
    blobthresh_hi = (min(imshape)//4)**2
    blobthresh_lo = blobthresh_hi//2
    T_move = 100#np.pi*min(imshape)//2

    T = np.ones_like(imgq_g[0])*T0
    bkgnd = imgq_g[0].copy()

    axes['raw'].imshow(bkgnd)
    axes['draw'].plot((),(),'-o',color='b')
    axes['draw'].set_ylim(0,imshape[0])
    axes['draw'].set_xlim(0,imshape[1])  
    fig.set_size_inches((figshape[0]*imshape[0]/100., figshape[1]*imshape[1]/100.))
    fig.tight_layout()
    fig.show()
    blankcanvas = fig.canvas.copy_from_bbox(axes['draw'].bbox)
    # blanktitle = fig.canvas.copy_from_bbox(axes['raw'].title.get_window_extent())

    draw_state = 0
    def onclick(event):
        global draw_state
        draw_state = (draw_state+1)%4

        # fig.canvas.restore_region(blanktitle)
        if draw_state == 0:
            axes['raw'].title.set_text('raw')
        elif draw_state == 1:
            axes['raw'].title.set_text('skin')
        elif draw_state == 2:
            axes['raw'].title.set_text('motion')            
        elif draw_state == 3:
            axes['raw'].title.set_text('backproject')
        fig.canvas.draw()
        # axes['raw'].draw_artist(axes['raw'].title)
        # fig.canvas.blit(axes['raw'].title.get_window_extent())
        # fig.canvas.blit(axes['raw'].bbox.union([axes['raw'].title.get_window_extent()]))
    cid = fig.canvas.mpl_connect('button_press_event', onclick)

    tracking=False
    t_loop=time.time()
    rownums = np.arange(imshape[0],dtype=int)
    colnums = np.arange(imshape[1],dtype=int)
    krn = np.ones((3,3),dtype=np.uint8)
    bkproject = np.zeros_like(bkgnd)
    while imgq[-1].size:
        imgq_g[-1] = cv2.cvtColor(imgq[-1],cv2.COLOR_BGR2GRAY)
        dispimg = imgq[-1].copy()
        
        moving = (cv2.absdiff(imgq_g[0],imgq_g[-1]) > T) & (cv2.absdiff(imgq_g[1],imgq_g[-1]) > T)
        # cv2.medianBlur(moving.view(np.uint8),3,dst=moving.view(np.uint8))

        img_crcb = cv2.cvtColor(imgq[-1],cv2.COLOR_BGR2YCR_CB)
        cr,cb = img_crcb[:,:,1], img_crcb[:,:,2]
        skin = (77 <= cb)&(cb <= 127)
        skin &= (133 <= cr)&(cr <= 173)
        # skin = (60 <= cb)&(cb <= 90)
        # skin &= (165 <= cr)&(cr <= 195)
        cv2.erode(skin.view(np.uint8),krn,dst=skin.view(np.uint8))
        cv2.dilate(skin.view(np.uint8),krn,dst=skin.view(np.uint8),iterations=2)
        cv2.erode(skin.view(np.uint8),krn,dst=skin.view(np.uint8))

        # set up the image to display
        if draw_state == 0:
            dispimg = dispimg
        elif draw_state == 1:
            dispimg[~skin] = 0
        elif draw_state == 2:
            dispimg[moving] = 255
            dispimg[~moving] = 0
        elif draw_state == 3:
            dispimg = cv2.cvtColor(bkproject*255,cv2.COLOR_GRAY2BGR)
            
        movesum = movearea = np.sum(moving)
        if movearea:
            # Calculate bbox of moving pixels
            movesum = movearea
            mov_cols = moving*colnums.reshape(1,-1)
            mov_rows = moving*rownums.reshape(-1,1)
            x0,x1 = np.min(mov_cols[moving]), np.max(mov_cols[moving])+1
            y0,y1 = np.min(mov_rows[moving]), np.max(mov_rows[moving])+1
            movearea = (x1-x0)*(y1-y0)

        if tracking and movearea > blobthresh_lo and movesum > T_move:
            cv2.rectangle(dispimg,(x0,y0),(x1,y1),color=(0,255,0),thickness=2)

            bkproject = cv2.calcBackProject([img_crcb],chans,hist,ranges,1)
            movereg = np.zeros_like(moving)
            movereg[y0:y1,x0:x1] = True
            bkproject &= movereg

            # notice we're using the track_bbox from last iteration
            # for the intitial estimate
            niter, track_bbox = cv2.meanShift(bkproject,track_bbox,term_crit)
            print niter
            x,y,w,h = track_bbox
            x0,y0,x1,y1 = x,y,x+w,y+h

            skin_roi = skin[y0:y1,x0:x1]
            skin_cols = skin_roi*colnums[x0:x1].reshape(1,-1)
            skin_rows = skin_roi*rownums[y0:y1].reshape(-1,1)
            xcom = np.sum(skin_cols)//np.sum(skin_roi)
            ycom = np.sum(skin_rows)//np.sum(skin_roi)

            cv2.rectangle(dispimg,(x0,y0),(x1,y1),color=(0,204,255),thickness=2)
            cv2.circle(dispimg,(xcom,ycom),5,(0,255,0),thickness=-1)
            waypts.append((xcom,ycom))

            print "Skin Tracking:",x0,y0,x1,y1
        elif tracking:
            # x,y = zip(*waypts)
            # matches = dollar.query(x,y,templates_fh)
            # score,theta,clsid = matches[0]
            # print "Class: %s (%.2f)" % (clsid,score)
            print "Npoints:",len(waypts)

            tracking = False
            waypts = []
            axes['draw'].lines[0].remove()
        elif movearea > blobthresh_hi:
            cv2.rectangle(dispimg,(x0,y0),(x1,y1),color=(0,255,0),thickness=2)
            print "Moving:", (x0+x1)//2, (y0+y1)//2, x1-x0, y1-y0
            
            crcb_roi = img_crcb[y0:y1,x0:x1]
            skin_roi = skin[y0:y1,x0:x1]
            if np.sum(skin_roi) > (crcb_roi.size//10):
                tracking = True

                # Estimate hand centroid as the centroid of skin colored pixels
                # inside the bbox of detected movement
                skin_cols = skin_roi*colnums[x0:x1].reshape(1,-1)
                skin_rows = skin_roi*rownums[y0:y1].reshape(-1,1)
                xcom = np.sum(skin_cols)//np.sum(skin_roi)
                ycom = np.sum(skin_rows)//np.sum(skin_roi)
                x0,x1 = np.min(skin_cols[skin_roi]), np.max(skin_cols[skin_roi])+1
                y0,y1 = np.min(skin_rows[skin_roi]), np.max(skin_rows[skin_roi])+1

                # Use the hand centroid estimate as our initial estimate for
                # tracking
                # Estimate the hand's bounding box by taking the minimum
                # vertical length to where the skin ends. If the hand is
                # vertical, this should correspond to the length from the palm
                # to tip of fingers
                h = min(2*min((y1-ycom,ycom-y0)),MAXLEN)
                # w = min(2*min((x1-xcom,xcom-x0)),MAXLEN)
                w = min(x1-x0,MAXLEN)
                # h,w = y1-y0,x1-x0
                # track_bbox = xcom-w//2,ycom-w//2,w,h
                track_bbox = xcom-w//2,ycom-h//2,w,h                
                waypts.append((xcom,ycom))
                
                # Use the skin bbox/centroid to initiate tracking
                hist = cv2.calcHist([crcb_roi], chans, skin_roi.view(np.uint8), nbins, ranges)
                # Normalize to 1 to get the sample PDF
                cv2.normalize(hist, hist, 0, 255, cv2.NORM_MINMAX)

                print "Skin Tracking:",xcom,ycom,w,h
                cv2.rectangle(dispimg,(x0,y0),(x1,y1),color=(0,204,255),thickness=2)
                cv2.circle(dispimg,(xcom,ycom),5,(0,255,0),thickness=-1)
                axes['draw'].add_line(plt.Line2D((),(),marker='o',color='b'))

        get_imdisp(axes['raw']).set_data(dispimg[:,:,::-1])
        axes['raw'].draw_artist(get_imdisp(axes['raw']))
        if waypts:
            fig.canvas.restore_region(blankcanvas)
            axes['draw'].lines[0].set_data(zip(*waypts))
            axes['draw'].draw_artist(axes['draw'].lines[0])
        for ax in axes.values():
            fig.canvas.blit(ax.bbox)

        # Updating threshold depends on current background model
        # so always update this before updating background
        T[~moving] = alpha*T[~moving] + (1-alpha)*5*cv2.absdiff(imgq_g[-1],bkgnd)[~moving]
        # T[moving] = T[moving]
        T[T<T0] = T0

        bkgnd[~moving] = alpha*bkgnd[~moving] + (1-alpha)*imgq_g[-1][~moving]
        bkgnd[moving] = imgq_g[-1][moving]

        # shift buffer left        
        imgq[:-1] = imgq[1:] 
        imgq_g[:-1] = imgq_g[1:]

        t = time.time()-t_loop
        while t < 0.0667: t = time.time()-t_loop
        # print round(1/t,2)

        imgq[-1] = cap.read()
        t_loop = time.time()
        fig.canvas.get_tk_widget().update()

except KeyboardInterrupt:
    pass
finally:
    plt.close(fig)
    cap.close()
    templates_fh.close()
