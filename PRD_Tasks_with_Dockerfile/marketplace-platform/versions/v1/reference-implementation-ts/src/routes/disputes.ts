import { Router, Request, Response } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { storage, getNextSeq } from '../storage';
import { Dispute, CONSTANTS, OrderStatus } from '../types';
import {
  successResponse, sendError, ERRORS,
  updateOrderDerivedFields, updateTenantDerivedFields,
  applyRiskScoreSideEffects
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

  const { assignment_id, raised_by, reason } = req.body;

  if (!raised_by || !['CUSTOMER', 'WORKER'].includes(raised_by)) {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'raised_by must be CUSTOMER or WORKER');
  }

  if (!reason || typeof reason !== 'string' || reason.trim() === '') {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'reason is required');
  }

  const disputableStatuses: OrderStatus[] = ['COMPLETED', 'FAILED', 'CANCELLED_BY_WORKER', 'REFUNDED', 'DISPUTED'];
  if (!disputableStatuses.includes(order.status)) {
    return sendError(res, ERRORS.ERR_ORDER_NOT_DISPUTABLE);
  }

  if (order.dispute_count >= CONSTANTS.dispute.MAX_DISPUTES_PER_ORDER) {
    return sendError(res, ERRORS.ERR_MAX_DISPUTES_EXCEEDED);
  }

  if (order.order_completion_reference_period_index === null) {
    return sendError(res, ERRORS.ERR_ORDER_NOT_DISPUTABLE);
  }

  const periodsSinceCompletion = tenant.current_period_index - order.order_completion_reference_period_index;
  if (periodsSinceCompletion > CONSTANTS.dispute.FILING_WINDOW_PERIODS) {
    return sendError(res, ERRORS.ERR_DISPUTE_WINDOW_EXPIRED);
  }

  let validAssignmentId: string | null = null;
  if (assignment_id) {
    const assignment = storage.getAssignment(assignment_id);
    if (!assignment || assignment.order_id !== orderId) {
      return sendError(res, ERRORS.ERR_ASSIGNMENT_NOT_FOUND);
    }
    validAssignmentId = assignment_id;
  }

  const id = uuidv4();
  const createdSeq = getNextSeq(tenantId);
  const disputeSequence = order.dispute_count + 1;

  const dispute: Dispute = {
    id,
    tenant_id: tenantId,
    order_id: orderId,
    assignment_id: validAssignmentId,
    raised_by,
    reason: reason.trim(),
    status: 'FILED',
    filed_period_index: tenant.current_period_index,
    resolution_period_index: null,
    original_order_status: order.status,
    dispute_sequence: disputeSequence,
    refund_amount_cents: 0,
    worker_penalty_cents: 0,
    created_seq: createdSeq
  };

  storage.saveDispute(dispute);

  order.dispute_count += 1;
  order.status = 'DISPUTED';
  order.has_open_dispute = true;
  storage.saveOrder(order);

  return successResponse(res, dispute, 201);
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

  const disputes = storage.getDisputesByOrder(orderId);
  return successResponse(res, disputes);
});

router.post('/:disputeId/start-review', (req: Request, res: Response) => {
  const { tenantId, orderId, disputeId } = req.params;

  const tenant = storage.getTenant(tenantId);
  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const order = storage.getOrder(orderId);
  if (!order || order.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_ORDER_NOT_FOUND);
  }

  const dispute = storage.getDispute(disputeId);
  if (!dispute || dispute.order_id !== orderId || dispute.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_DISPUTE_NOT_FOUND);
  }

  if (dispute.status !== 'FILED') {
    return sendError(res, ERRORS.ERR_DISPUTE_NOT_FILED);
  }

  dispute.status = 'UNDER_REVIEW';
  storage.saveDispute(dispute);

  return successResponse(res, dispute);
});

router.post('/:disputeId/resolve-customer', (req: Request, res: Response) => {
  const { tenantId, orderId, disputeId } = req.params;

  const tenant = storage.getTenant(tenantId);
  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const order = storage.getOrder(orderId);
  if (!order || order.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_ORDER_NOT_FOUND);
  }

  const dispute = storage.getDispute(disputeId);
  if (!dispute || dispute.order_id !== orderId || dispute.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_DISPUTE_NOT_FOUND);
  }

  if (dispute.status !== 'UNDER_REVIEW') {
    return sendError(res, ERRORS.ERR_DISPUTE_NOT_UNDER_REVIEW);
  }

  const { refund_amount_cents, worker_penalty_cents } = req.body;

  if (refund_amount_cents === undefined ||
      typeof refund_amount_cents !== 'number' ||
      !Number.isInteger(refund_amount_cents) ||
      refund_amount_cents < 0) {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'refund_amount_cents must be a non-negative integer');
  }

  let penalty = 0;
  if (worker_penalty_cents !== undefined) {
    if (typeof worker_penalty_cents !== 'number' ||
        !Number.isInteger(worker_penalty_cents) ||
        worker_penalty_cents < 0) {
      return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'worker_penalty_cents must be a non-negative integer');
    }
    penalty = worker_penalty_cents;
  }

  dispute.status = 'RESOLVED_CUSTOMER';
  dispute.resolution_period_index = tenant.current_period_index;
  dispute.refund_amount_cents = refund_amount_cents;
  dispute.worker_penalty_cents = penalty;

  storage.saveDispute(dispute);

  if (order.status === 'COMPLETED' || order.status === 'DISPUTED') {
    order.status = 'REFUNDED';
  }
  order.has_open_dispute = false;
  storage.saveOrder(order);

  const creditedAmount = Math.max(0, Math.floor(refund_amount_cents - penalty));
  if (creditedAmount > 0) {
    const ledger = storage.getPayoutBudgetLedger(tenantId);
    ledger.recovered_clawbacks_cents += creditedAmount;
    storage.savePayoutBudgetLedger(ledger);
  }

  if (dispute.assignment_id) {
    const assignment = storage.getAssignment(dispute.assignment_id);
    if (assignment) {
      const perfLedger = storage.getWorkerPerformanceLedger(assignment.worker_id);
      perfLedger.dispute_loss_count += 1;
      storage.saveWorkerPerformanceLedger(perfLedger);

      const worker = storage.getWorker(assignment.worker_id);
      if (worker) {
        if (penalty > 0) {
          worker.signup_bonus_debt_cents += penalty;
        }
        applyRiskScoreSideEffects(worker, tenant);
      }
    }
  }

  updateTenantDerivedFields(tenant);
  storage.saveTenant(tenant);

  updateOrderDerivedFields(order);
  storage.saveOrder(order);

  return successResponse(res, dispute);
});

router.post('/:disputeId/resolve-worker', (req: Request, res: Response) => {
  const { tenantId, orderId, disputeId } = req.params;

  const tenant = storage.getTenant(tenantId);
  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const order = storage.getOrder(orderId);
  if (!order || order.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_ORDER_NOT_FOUND);
  }

  const dispute = storage.getDispute(disputeId);
  if (!dispute || dispute.order_id !== orderId || dispute.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_DISPUTE_NOT_FOUND);
  }

  if (dispute.status !== 'UNDER_REVIEW') {
    return sendError(res, ERRORS.ERR_DISPUTE_NOT_UNDER_REVIEW);
  }

  dispute.status = 'RESOLVED_WORKER';
  dispute.resolution_period_index = tenant.current_period_index;
  storage.saveDispute(dispute);

  const openDisputes = storage.getDisputesByOrder(orderId)
    .filter(d => d.id !== disputeId && (d.status === 'FILED' || d.status === 'UNDER_REVIEW'));

  if (openDisputes.length === 0) {

    order.status = 'COMPLETED';
    order.has_open_dispute = false;
  }

  storage.saveOrder(order);
  updateOrderDerivedFields(order);

  return successResponse(res, dispute);
});

router.post('/:disputeId/withdraw', (req: Request, res: Response) => {
  const { tenantId, orderId, disputeId } = req.params;

  const tenant = storage.getTenant(tenantId);
  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const order = storage.getOrder(orderId);
  if (!order || order.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_ORDER_NOT_FOUND);
  }

  const dispute = storage.getDispute(disputeId);
  if (!dispute || dispute.order_id !== orderId || dispute.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_DISPUTE_NOT_FOUND);
  }

  if (!['FILED', 'UNDER_REVIEW'].includes(dispute.status)) {
    return sendError(res, ERRORS.ERR_DISPUTE_NOT_WITHDRAWABLE);
  }

  dispute.status = 'CANCELLED';
  dispute.resolution_period_index = tenant.current_period_index;
  storage.saveDispute(dispute);

  const openDisputes = storage.getDisputesByOrder(orderId)
    .filter(d => d.id !== disputeId && (d.status === 'FILED' || d.status === 'UNDER_REVIEW'));

  if (openDisputes.length === 0) {
    order.status = dispute.original_order_status;
    order.has_open_dispute = false;
  }

  storage.saveOrder(order);
  updateOrderDerivedFields(order);

  return successResponse(res, dispute);
});

export default router;
