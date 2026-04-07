import { Router, Request, Response } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { storage, getNextSeq } from '../storage';
import { Order, CONSTANTS } from '../types';
import {
  successResponse, sendError, ERRORS,
  updateOrderDerivedFields, updateTenantDerivedFields,
  releaseAssignmentReservation, updateAssignmentDerivedFields,
  applyRiskScoreSideEffects
} from '../utils';

const router = Router({ mergeParams: true });

router.post('/', (req: Request, res: Response) => {
  const { tenantId } = req.params;
  const tenant = storage.getTenant(tenantId);

  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  if (tenant.status === 'SUSPENDED') {
    return sendError(res, ERRORS.ERR_TENANT_SUSPENDED);
  }

  if (tenant.status !== 'ACTIVE') {
    return sendError(res, ERRORS.ERR_TENANT_NOT_ACTIVE);
  }

  const { listing_id, external_customer_id } = req.body;

  if (!listing_id || typeof listing_id !== 'string') {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'listing_id is required');
  }

  if (!external_customer_id || typeof external_customer_id !== 'string') {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'external_customer_id is required');
  }

  const listing = storage.getListing(listing_id);
  if (!listing || listing.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_LISTING_NOT_FOUND);
  }

  if (listing.status !== 'PUBLISHED') {
    return sendError(res, ERRORS.ERR_LISTING_NOT_PUBLISHED);
  }

  const id = uuidv4();
  const createdSeq = getNextSeq(tenantId);

  const quotedPriceCents = Math.floor(listing.base_price_cents * listing.surge_multiplier);
  const platformFeeCents = 0;
  const workerEarningsCapCents = quotedPriceCents;

  const order: Order = {
    id,
    tenant_id: tenantId,
    listing_id,
    external_customer_id,
    status: 'PENDING_MATCHING',
    created_period_index: tenant.current_period_index,
    expected_completion_period_index: tenant.current_period_index + listing.customer_sla_periods,
    completion_period_index: null,
    order_completion_reference_period_index: null,
    is_late: false,
    is_sla_breached: false,
    quoted_price_cents: quotedPriceCents,
    final_price_cents: quotedPriceCents,
    platform_fee_cents: platformFeeCents,
    worker_earnings_cap_cents: workerEarningsCapCents,
    total_payout_approved_cents: 0,
    total_payout_cleared_cents: 0,
    active_assignment_count: 0,
    has_open_dispute: false,
    dispute_count: 0,
    can_dispute: false,
    rating_count: 0,
    average_rating: 0,
    created_seq: createdSeq
  };

  storage.saveOrder(order);
  return successResponse(res, order, 201);
});

router.get('/', (req: Request, res: Response) => {
  const { tenantId } = req.params;
  const tenant = storage.getTenant(tenantId);

  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const orders = storage.getOrdersByTenant(tenantId);

  for (const order of orders) {
    updateOrderDerivedFields(order);
  }

  return successResponse(res, orders);
});

router.get('/:orderId', (req: Request, res: Response) => {
  const { tenantId, orderId } = req.params;
  const tenant = storage.getTenant(tenantId);

  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const order = storage.getOrder(orderId);

  if (!order || order.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_ORDER_NOT_FOUND);
  }

  updateOrderDerivedFields(order);
  storage.saveOrder(order);
  return successResponse(res, order);
});

router.post('/:orderId/cancel', (req: Request, res: Response) => {
  const { tenantId, orderId } = req.params;
  const tenant = storage.getTenant(tenantId);

  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const order = storage.getOrder(orderId);

  if (!order || order.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_ORDER_NOT_FOUND);
  }

  const { cancelled_by, reason } = req.body;

  if (!cancelled_by || !['CUSTOMER', 'SYSTEM'].includes(cancelled_by)) {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'cancelled_by must be CUSTOMER or SYSTEM');
  }

  const cancellableStatuses = ['PENDING_MATCHING', 'ASSIGNED', 'IN_PROGRESS'];
  if (!cancellableStatuses.includes(order.status)) {
    return sendError(res, ERRORS.ERR_ORDER_NOT_CANCELLABLE);
  }

  if (cancelled_by === 'CUSTOMER') {
    order.status = 'CANCELLED_BY_CUSTOMER';
  } else {
    order.status = 'CANCELLED_BY_CUSTOMER';
  }

  order.order_completion_reference_period_index = tenant.current_period_index;

  const assignments = storage.getAssignmentsByOrder(orderId);
  for (const assignment of assignments) {
    if (!['COMPLETED', 'CANCELLED_BY_WORKER', 'CANCELLED_BY_SYSTEM', 'EXPIRED'].includes(assignment.status)) {
      assignment.status = 'CANCELLED_BY_SYSTEM';

      releaseAssignmentReservation(assignment);
      storage.saveAssignment(assignment);
    }
  }

  updateOrderDerivedFields(order);
  storage.saveOrder(order);

  updateTenantDerivedFields(tenant);
  storage.saveTenant(tenant);

  return successResponse(res, order);
});

router.post('/:orderId/mark-completed', (req: Request, res: Response) => {
  const { tenantId, orderId } = req.params;
  const tenant = storage.getTenant(tenantId);

  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const order = storage.getOrder(orderId);

  if (!order || order.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_ORDER_NOT_FOUND);
  }

  if (order.status !== 'IN_PROGRESS') {
    return sendError(res, ERRORS.ERR_ORDER_NOT_IN_PROGRESS);
  }

  const activeAssignments = storage.getActiveAssignmentsByOrder(orderId);
  if (activeAssignments.length === 0) {
    return sendError(res, ERRORS.ERR_WORKER_NOT_ASSIGNED);
  }

  const requestingWorkerId = req.header('x-user-id');
  if (!requestingWorkerId) {
    return sendError(res, ERRORS.ERR_WORKER_NOT_ASSIGNED);
  }

  const workerAssignment = activeAssignments.find(
    assignment => assignment.worker_id === requestingWorkerId && assignment.status === 'IN_PROGRESS'
  );
  if (!workerAssignment) {
    return sendError(res, ERRORS.ERR_WORKER_NOT_ASSIGNED);
  }

  order.status = 'COMPLETED';
  order.completion_period_index = tenant.current_period_index;
  order.order_completion_reference_period_index = tenant.current_period_index;

  for (const assignment of activeAssignments) {
    if (assignment.status === 'IN_PROGRESS') {
      assignment.status = 'COMPLETED';

      const perfLedger = storage.getWorkerPerformanceLedger(assignment.worker_id);
      perfLedger.total_assignments_completed += 1;

      if (order.completion_period_index !== null &&
          (order.completion_period_index - order.expected_completion_period_index) > CONSTANTS.sla.LATE_COMPLETION_MIN_PERIODS) {
        perfLedger.total_assignments_late += 1;
      }

      storage.saveWorkerPerformanceLedger(perfLedger);
      updateAssignmentDerivedFields(assignment);
      storage.saveAssignment(assignment);

      const worker = storage.getWorker(assignment.worker_id);
      if (worker) {
        applyRiskScoreSideEffects(worker, tenant);
      }
    }
  }

  const listing = storage.getListing(order.listing_id);
  if (listing) {
    listing.completed_order_count += 1;
    storage.saveListing(listing);
  }

  updateOrderDerivedFields(order);
  storage.saveOrder(order);

  return successResponse(res, order);
});

router.post('/:orderId/close', (req: Request, res: Response) => {
  const { tenantId, orderId } = req.params;
  const tenant = storage.getTenant(tenantId);

  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const order = storage.getOrder(orderId);

  if (!order || order.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_ORDER_NOT_FOUND);
  }

  const disputes = storage.getDisputesByOrder(orderId);
  const openDisputes = disputes.filter(d =>
    d.status === 'FILED' || d.status === 'UNDER_REVIEW'
  );
  if (openDisputes.length > 0) {
    return sendError(res, ERRORS.ERR_OPEN_DISPUTE_EXISTS);
  }

  const closeableStatuses = ['COMPLETED', 'FAILED', 'CANCELLED_BY_CUSTOMER', 'CANCELLED_BY_WORKER', 'REFUNDED'];
  if (!closeableStatuses.includes(order.status)) {
    return sendError(res, ERRORS.ERR_ORDER_NOT_CLOSEABLE);
  }

  const assignments = storage.getAssignmentsByOrder(orderId);
  const nonTerminalAssignments = assignments.filter(a =>
    !['COMPLETED', 'CANCELLED_BY_WORKER', 'CANCELLED_BY_SYSTEM', 'EXPIRED'].includes(a.status)
  );
  if (nonTerminalAssignments.length > 0) {
    return sendError(res, ERRORS.ERR_ORDER_NOT_CLOSEABLE);
  }

  for (const assignment of assignments) {
    const payouts = storage.getPayoutsByAssignment(assignment.id);
    const nonTerminalPayouts = payouts.filter(p =>
      !['CLEARED', 'FAILED', 'CANCELLED'].includes(p.status)
    );
    if (nonTerminalPayouts.length > 0) {
      return sendError(res, ERRORS.ERR_ORDER_NOT_CLOSEABLE);
    }
  }

  order.status = 'CLOSED';
  order.can_dispute = false;

  storage.saveOrder(order);
  return successResponse(res, order);
});

export default router;
