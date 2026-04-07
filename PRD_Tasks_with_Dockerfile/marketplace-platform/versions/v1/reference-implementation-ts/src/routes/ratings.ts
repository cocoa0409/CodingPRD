import { Router, Request, Response } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { storage, getNextSeq } from '../storage';
import { Rating, CONSTANTS } from '../types';
import {
  successResponse, sendError, ERRORS,
  updateOrderDerivedFields, applyRiskScoreSideEffects
} from '../utils';

const router = Router({ mergeParams: true });

router.post('/', (req: Request, res: Response) => {
  const { tenantId, orderId } = req.params;

  const tenant = storage.getTenant(tenantId);
  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const order = storage.getOrder(orderId);
  if (!order || order.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_ORDER_NOT_FOUND);
  }

  if (order.status !== 'COMPLETED' && order.status !== 'CLOSED' &&
      order.status !== 'DISPUTED' && order.status !== 'REFUNDED') {
    return sendError(res, ERRORS.ERR_ORDER_NOT_COMPLETED);
  }

  const { worker_id, rating_value, comment } = req.body;

  if (!worker_id || typeof worker_id !== 'string') {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'worker_id is required');
  }

  const worker = storage.getWorker(worker_id);
  if (!worker || worker.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_WORKER_NOT_FOUND);
  }

  if (rating_value === undefined ||
      typeof rating_value !== 'number' ||
      !Number.isInteger(rating_value) ||
      rating_value < 1 ||
      rating_value > 5) {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'rating_value must be an integer between 1 and 5');
  }

  let validComment: string | null = null;
  if (comment !== undefined) {
    if (typeof comment !== 'string') {
      return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'comment must be a string');
    }
    validComment = comment.trim() || null;
  }

  const id = uuidv4();
  const createdSeq = getNextSeq(tenantId);

  const existingRatings = storage.getRatingsByOrder(orderId)
    .filter(r => r.status === 'PUBLISHED');

  let varianceFromOrderAverage = 0;
  if (existingRatings.length > 0) {
    const sum = existingRatings.reduce((acc, r) => acc + r.rating_value, 0);
    const avg = sum / existingRatings.length;
    varianceFromOrderAverage = rating_value - avg;
  }

  const isLowRating = rating_value <= 2;

  const rating: Rating = {
    id,
    tenant_id: tenantId,
    order_id: orderId,
    worker_id,
    rating_value,
    comment: validComment,
    status: 'PENDING_MODERATION',
    variance_from_order_average: varianceFromOrderAverage,
    is_low_rating: isLowRating,
    created_seq: createdSeq
  };

  storage.saveRating(rating);

  updateOrderDerivedFields(order);
  storage.saveOrder(order);

  return successResponse(res, rating, 201);
});

router.get('/', (req: Request, res: Response) => {
  const { tenantId, orderId } = req.params;

  const tenant = storage.getTenant(tenantId);
  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const order = storage.getOrder(orderId);
  if (!order || order.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_ORDER_NOT_FOUND);
  }

  const ratings = storage.getRatingsByOrder(orderId);
  return successResponse(res, ratings);
});

router.post('/:ratingId/moderate', (req: Request, res: Response) => {
  const { tenantId, orderId, ratingId } = req.params;

  const tenant = storage.getTenant(tenantId);
  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const order = storage.getOrder(orderId);
  if (!order || order.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_ORDER_NOT_FOUND);
  }

  const rating = storage.getRating(ratingId);
  if (!rating || rating.order_id !== orderId || rating.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_RATING_NOT_FOUND);
  }

  const { action } = req.body;

  if (!action || !['HIDE', 'PUBLISH', 'REMOVE'].includes(action)) {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'action must be HIDE, PUBLISH, or REMOVE');
  }

  if (rating.status === 'REMOVED') {
    return sendError(res, ERRORS.ERR_RATING_NOT_MODERATABLE);
  }

  switch (action) {
    case 'HIDE':
      if (rating.status !== 'PENDING_MODERATION' && rating.status !== 'PUBLISHED') {
        return sendError(res, ERRORS.ERR_RATING_NOT_MODERATABLE);
      }
      rating.status = 'HIDDEN';
      break;

    case 'PUBLISH':
      if (rating.status !== 'PENDING_MODERATION' && rating.status !== 'HIDDEN') {
        return sendError(res, ERRORS.ERR_RATING_NOT_MODERATABLE);
      }

      if (rating.status === 'PENDING_MODERATION') {
        const perfLedger = storage.getWorkerPerformanceLedger(rating.worker_id);
        perfLedger.rating_count += 1;
        perfLedger.cumulative_rating_deficit += (5 - rating.rating_value);
        storage.saveWorkerPerformanceLedger(perfLedger);

        const worker = storage.getWorker(rating.worker_id);
        if (worker) {
          applyRiskScoreSideEffects(worker, tenant);
        }
      }
      rating.status = 'PUBLISHED';
      break;

    case 'REMOVE':
      if (rating.status !== 'HIDDEN' && rating.status !== 'PUBLISHED') {
        return sendError(res, ERRORS.ERR_RATING_NOT_MODERATABLE);
      }
      rating.status = 'REMOVED';
      break;
  }

  storage.saveRating(rating);

  updateOrderDerivedFields(order);
  storage.saveOrder(order);

  return successResponse(res, rating);
});

export default router;
