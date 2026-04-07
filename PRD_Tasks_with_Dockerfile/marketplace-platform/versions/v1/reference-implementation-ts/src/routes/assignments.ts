import { Router, Request, Response } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { storage, getNextSeq } from '../storage';
import { Assignment, CONSTANTS } from '../types';
import {
  successResponse, sendError, ERRORS,
  updateAssignmentDerivedFields, updateOrderDerivedFields,
  updateWorkerDerivedFields, updateTenantDerivedFields,
  releaseAssignmentReservation,
  calculateExpectedEarnings, applyRiskScoreSideEffects
} from '../utils';

const router = Router({ mergeParams: true });

router.post('/', (req: Request, res: Response) => {
  const { tenantId, orderId } = req.params;

  const tenant = storage.getTenant(tenantId);
  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  if (tenant.status === 'SUSPENDED') {
    return sendError(res, ERRORS.ERR_TENANT_SUSPENDED);
  }

  const order = storage.getOrder(orderId);
  if (!order || order.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_ORDER_NOT_FOUND);
  }

  const { worker_id, share_percentage, reserved_earnings_initial_cents } = req.body;

  if (!worker_id || typeof worker_id !== 'string') {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'worker_id is required');
  }

  const worker = storage.getWorker(worker_id);
  if (!worker || worker.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_WORKER_NOT_FOUND);
  }

  if (worker.status !== 'ACTIVE') {
    return sendError(res, ERRORS.ERR_WORKER_RISK_HOLD_OR_SUSPENDED);
  }

  if (order.status !== 'PENDING_MATCHING') {
    return sendError(res, ERRORS.ERR_ORDER_NOT_ASSIGNABLE);
  }

  const existingAssignments = storage.getAssignmentsByOrder(orderId);
  const workerHasActive = existingAssignments.some(a =>
    a.worker_id === worker_id &&
    !['CANCELLED_BY_WORKER', 'CANCELLED_BY_SYSTEM', 'EXPIRED'].includes(a.status)
  );
  if (workerHasActive) {
    return sendError(res, ERRORS.ERR_DUPLICATE_ACTIVE_ASSIGNMENT);
  }

  if (share_percentage !== undefined) {
    if (typeof share_percentage !== 'number' ||
        !Number.isInteger(share_percentage) ||
        share_percentage < 1 ||
        share_percentage > 100) {
      return sendError(res, ERRORS.ERR_INVALID_SHARE_PERCENTAGES);
    }

    const hasUndefinedShares = existingAssignments.some(a => a.share_percentage === null);
    const hasDefinedShares = existingAssignments.some(a => a.share_percentage !== null);

    if (hasUndefinedShares && existingAssignments.length > 0) {
      return sendError(res, ERRORS.ERR_INVALID_SHARE_PERCENTAGES, 'Cannot mix defined and undefined share percentages');
    }

    const currentTotal = existingAssignments
      .filter(a => a.share_percentage !== null)
      .reduce((sum, a) => sum + (a.share_percentage || 0), 0);

    if (currentTotal + share_percentage > 100) {
      return sendError(res, ERRORS.ERR_INVALID_SHARE_PERCENTAGES, 'Total share percentages exceed 100');
    }
  } else {

    const hasDefinedShares = existingAssignments.some(a => a.share_percentage !== null);
    if (hasDefinedShares) {
      return sendError(res, ERRORS.ERR_INVALID_SHARE_PERCENTAGES, 'All assignments must have share_percentage when any does');
    }
  }

  if (reserved_earnings_initial_cents === undefined ||
      typeof reserved_earnings_initial_cents !== 'number' ||
      !Number.isInteger(reserved_earnings_initial_cents) ||
      reserved_earnings_initial_cents < 0) {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'reserved_earnings_initial_cents must be a non-negative integer');
  }

  const listing = storage.getListing(order.listing_id);
  if (!listing) {
    return sendError(res, ERRORS.ERR_LISTING_NOT_FOUND);
  }

  if (order.quoted_price_cents >= CONSTANTS.worker.SPECIALTY_REQUIRED_THRESHOLD_PRICE) {
    if (!worker.skills.includes(listing.category)) {
      return sendError(res, ERRORS.ERR_WORKER_LACKS_SKILL);
    }
  }

  if (listing.category === 'HOME_SERVICE') {
    const hasValidCert = worker.certifications.some(cert =>
      cert.certification_type === 'HOME_SERVICE_VERIFIED' &&
      cert.certified_period_index <= tenant.current_period_index &&
      tenant.current_period_index < cert.expiry_period_index
    );
    if (!hasValidCert) {
      return sendError(res, ERRORS.ERR_WORKER_CERTIFICATION_EXPIRED);
    }
  }

  const tempAssignment: Assignment = {
    id: uuidv4(),
    tenant_id: tenantId,
    order_id: orderId,
    worker_id,
    status: 'OFFERED',
    share_percentage: share_percentage ?? null,
    expected_earnings_cents: 0,
    reserved_earnings_initial_cents,
    reserved_earnings_current_cents: reserved_earnings_initial_cents,
    released_earnings_cents: 0,
    earnings_adequacy_ratio: 0,
    requires_adjustment: false,
    is_surplus_release_eligible: false,
    suggested_release_amount_cents: 0,
    payout_requested_cents: 0,
    payout_cleared_cents: 0,
    created_seq: getNextSeq(tenantId)
  };

  storage.saveAssignment(tempAssignment);
  tempAssignment.expected_earnings_cents = calculateExpectedEarnings(tempAssignment);

  const minimumRequired = Math.floor(tempAssignment.expected_earnings_cents * CONSTANTS.budget.MINIMUM_FACTOR);
  if (reserved_earnings_initial_cents < minimumRequired) {

    storage.assignments.delete(tempAssignment.id);
    return sendError(res, ERRORS.ERR_RESERVATION_BELOW_MINIMUM);
  }

  const ledger = storage.getPayoutBudgetLedger(tenantId);
  updateTenantDerivedFields(tenant);

  if (tenant.payout_available_cents < reserved_earnings_initial_cents) {

    storage.assignments.delete(tempAssignment.id);
    return sendError(res, ERRORS.ERR_INSUFFICIENT_PAYOUT_BUDGET_FOR_RESERVATION);
  }

  ledger.provisional_reserved_cents += reserved_earnings_initial_cents;
  storage.savePayoutBudgetLedger(ledger);

  updateAssignmentDerivedFields(tempAssignment);
  storage.saveAssignment(tempAssignment);

  updateTenantDerivedFields(tenant);
  storage.saveTenant(tenant);

  return successResponse(res, tempAssignment, 201);
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

  const assignments = storage.getAssignmentsByOrder(orderId);

  for (const assignment of assignments) {
    updateAssignmentDerivedFields(assignment);
  }

  return successResponse(res, assignments);
});

router.post('/:assignmentId/accept', (req: Request, res: Response) => {
  const { tenantId, orderId, assignmentId } = req.params;

  const tenant = storage.getTenant(tenantId);
  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const order = storage.getOrder(orderId);
  if (!order || order.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_ORDER_NOT_FOUND);
  }

  const assignment = storage.getAssignment(assignmentId);
  if (!assignment || assignment.order_id !== orderId || assignment.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_ASSIGNMENT_NOT_FOUND);
  }

  const worker = storage.getWorker(assignment.worker_id);
  if (!worker) {
    return sendError(res, ERRORS.ERR_WORKER_NOT_FOUND);
  }

  if (worker.status !== 'ACTIVE') {
    return sendError(res, ERRORS.ERR_WORKER_RISK_HOLD_OR_SUSPENDED);
  }

  if (assignment.status !== 'OFFERED') {
    return sendError(res, ERRORS.ERR_ASSIGNMENT_NOT_OFFERED);
  }

  updateWorkerDerivedFields(worker);
  if (worker.is_at_capacity) {
    return sendError(res, ERRORS.ERR_WORKER_AT_CAPACITY);
  }

  const activeAssignments = storage.getActiveAssignmentsByOrder(orderId);
  if (activeAssignments.length > 0) {
    return sendError(res, ERRORS.ERR_ORDER_ALREADY_HAS_ACTIVE_ASSIGNMENT);
  }

  assignment.status = 'ACCEPTED';
  storage.saveAssignment(assignment);

  if (order.status === 'PENDING_MATCHING') {
    order.status = 'ASSIGNED';
    storage.saveOrder(order);
  }

  updateWorkerDerivedFields(worker);
  storage.saveWorker(worker);

  updateAssignmentDerivedFields(assignment);
  return successResponse(res, assignment);
});

router.post('/:assignmentId/start', (req: Request, res: Response) => {
  const { tenantId, orderId, assignmentId } = req.params;

  const tenant = storage.getTenant(tenantId);
  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const order = storage.getOrder(orderId);
  if (!order || order.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_ORDER_NOT_FOUND);
  }

  const assignment = storage.getAssignment(assignmentId);
  if (!assignment || assignment.order_id !== orderId || assignment.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_ASSIGNMENT_NOT_FOUND);
  }

  if (assignment.status !== 'ACCEPTED') {
    return sendError(res, ERRORS.ERR_ASSIGNMENT_NOT_ACCEPTED);
  }

  assignment.status = 'IN_PROGRESS';
  storage.saveAssignment(assignment);

  if (order.status === 'ASSIGNED') {
    order.status = 'IN_PROGRESS';
    storage.saveOrder(order);
  }

  updateAssignmentDerivedFields(assignment);
  return successResponse(res, assignment);
});

router.post('/:assignmentId/complete', (req: Request, res: Response) => {
  const { tenantId, orderId, assignmentId } = req.params;

  const tenant = storage.getTenant(tenantId);
  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const order = storage.getOrder(orderId);
  if (!order || order.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_ORDER_NOT_FOUND);
  }

  const assignment = storage.getAssignment(assignmentId);
  if (!assignment || assignment.order_id !== orderId || assignment.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_ASSIGNMENT_NOT_FOUND);
  }

  if (assignment.status !== 'IN_PROGRESS') {
    return sendError(res, ERRORS.ERR_ASSIGNMENT_NOT_IN_PROGRESS);
  }

  assignment.status = 'COMPLETED';
  storage.saveAssignment(assignment);

  order.status = 'COMPLETED';
  order.completion_period_index = tenant.current_period_index;
  order.order_completion_reference_period_index = tenant.current_period_index;

  const worker = storage.getWorker(assignment.worker_id);
  if (worker) {
    const perfLedger = storage.getWorkerPerformanceLedger(worker.id);
    perfLedger.total_assignments_completed += 1;

    if (order.completion_period_index !== null &&
        (order.completion_period_index - order.expected_completion_period_index) > CONSTANTS.sla.LATE_COMPLETION_MIN_PERIODS) {
      perfLedger.total_assignments_late += 1;
    }

    storage.saveWorkerPerformanceLedger(perfLedger);
    applyRiskScoreSideEffects(worker, tenant);
  }

  const listing = storage.getListing(order.listing_id);
  if (listing) {
    listing.completed_order_count += 1;
    storage.saveListing(listing);
  }

  updateOrderDerivedFields(order);
  storage.saveOrder(order);

  updateAssignmentDerivedFields(assignment);

  updateTenantDerivedFields(tenant);
  storage.saveTenant(tenant);

  return successResponse(res, { assignment, order });
});

router.post('/:assignmentId/cancel', (req: Request, res: Response) => {
  const { tenantId, orderId, assignmentId } = req.params;

  const tenant = storage.getTenant(tenantId);
  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const order = storage.getOrder(orderId);
  if (!order || order.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_ORDER_NOT_FOUND);
  }

  const assignment = storage.getAssignment(assignmentId);
  if (!assignment || assignment.order_id !== orderId || assignment.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_ASSIGNMENT_NOT_FOUND);
  }

  const cancellableStatuses = ['OFFERED', 'ACCEPTED', 'IN_PROGRESS'];
  if (!cancellableStatuses.includes(assignment.status)) {
    return sendError(res, ERRORS.ERR_ASSIGNMENT_NOT_CANCELLABLE);
  }

  const wasActive = ['ACCEPTED', 'IN_PROGRESS'].includes(assignment.status);
  assignment.status = 'CANCELLED_BY_WORKER';

  releaseAssignmentReservation(assignment);
  storage.saveAssignment(assignment);

  if (wasActive) {
    const worker = storage.getWorker(assignment.worker_id);
    if (worker) {
      const perfLedger = storage.getWorkerPerformanceLedger(worker.id);
      perfLedger.total_assignments_cancelled += 1;
      storage.saveWorkerPerformanceLedger(perfLedger);
      applyRiskScoreSideEffects(worker, tenant);
    }

    if (order.status === 'ASSIGNED' || order.status === 'IN_PROGRESS') {
      order.status = 'CANCELLED_BY_WORKER';
      order.order_completion_reference_period_index = tenant.current_period_index;
      storage.saveOrder(order);
    }
  }

  updateOrderDerivedFields(order);
  storage.saveOrder(order);

  updateTenantDerivedFields(tenant);
  storage.saveTenant(tenant);

  updateAssignmentDerivedFields(assignment);
  return successResponse(res, assignment);
});

router.post('/:assignmentId/release-surplus', (req: Request, res: Response) => {
  const { tenantId, orderId, assignmentId } = req.params;

  const tenant = storage.getTenant(tenantId);
  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const order = storage.getOrder(orderId);
  if (!order || order.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_ORDER_NOT_FOUND);
  }

  const assignment = storage.getAssignment(assignmentId);
  if (!assignment || assignment.order_id !== orderId || assignment.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_ASSIGNMENT_NOT_FOUND);
  }

  const { release_amount_cents } = req.body;

  if (release_amount_cents === undefined ||
      typeof release_amount_cents !== 'number' ||
      !Number.isInteger(release_amount_cents) ||
      release_amount_cents < 0) {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'release_amount_cents must be a non-negative integer');
  }

  updateAssignmentDerivedFields(assignment);

  if (release_amount_cents > assignment.suggested_release_amount_cents) {
    return sendError(res, ERRORS.ERR_RELEASE_EXCEEDS_CURRENT);
  }

  const ledger = storage.getPayoutBudgetLedger(tenantId);
  ledger.provisional_reserved_cents -= release_amount_cents;
  storage.savePayoutBudgetLedger(ledger);

  assignment.reserved_earnings_current_cents -= release_amount_cents;
  assignment.released_earnings_cents += release_amount_cents;

  updateAssignmentDerivedFields(assignment);
  storage.saveAssignment(assignment);

  updateTenantDerivedFields(tenant);
  storage.saveTenant(tenant);

  return successResponse(res, assignment);
});

export default router;
