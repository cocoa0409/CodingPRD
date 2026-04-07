import { Request, Response } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { ApiResponse, ApiError, ApiMeta, CONSTANTS, MarketplaceTenant, Worker, Order, Assignment, Listing, Payout } from './types';
import { storage } from './storage';

export function successResponse<T>(res: Response, data: T, statusCode: number = 200, meta?: Partial<ApiMeta>): void {
  const isArray = Array.isArray(data);
  const response: ApiResponse<T> = {
    meta: {
      api_request_id: uuidv4(),
      api_request_period_index: 0,
      ...meta
    },
    response_type: isArray ? 'array' : 'object',
    data
  };
  res.status(statusCode).json(response);
}

export function errorResponse(res: Response, statusCode: number, errorId: string, message: string, meta?: Partial<ApiMeta>): void {
  const response: ApiResponse<ApiError> = {
    meta: {
      api_request_id: uuidv4(),
      api_request_period_index: 0,
      ...meta
    },
    response_type: 'error',
    data: {
      error_id: errorId,
      message
    }
  };
  res.status(statusCode).json(response);
}

export const ERRORS = {

  ERR_INVALID_REQUEST: { status: 400, id: 'ERR_INVALID_REQUEST', message: 'Invalid request' },
  ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER: { status: 400, id: 'ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER', message: 'Missing or invalid user context header' },
  ERR_IMMUTABLE_FIELD_MODIFIED: { status: 400, id: 'ERR_IMMUTABLE_FIELD_MODIFIED', message: 'Immutable field cannot be modified' },
  ERR_RESERVATION_BELOW_MINIMUM: { status: 400, id: 'ERR_RESERVATION_BELOW_MINIMUM', message: 'Reservation below minimum required' },
  ERR_INVALID_SHARE_PERCENTAGES: { status: 400, id: 'ERR_INVALID_SHARE_PERCENTAGES', message: 'Invalid share percentages' },
  ERR_RELEASE_EXCEEDS_CURRENT: { status: 400, id: 'ERR_RELEASE_EXCEEDS_CURRENT', message: 'Release amount exceeds current reservation' },
  ERR_PAYOUT_BELOW_MINIMUM: { status: 400, id: 'ERR_PAYOUT_BELOW_MINIMUM', message: 'Payout amount below minimum' },

  ERR_INSUFFICIENT_PAYOUT_BUDGET: { status: 402, id: 'ERR_INSUFFICIENT_PAYOUT_BUDGET', message: 'Insufficient payout budget' },
  ERR_INSUFFICIENT_PAYOUT_BUDGET_FOR_RESERVATION: { status: 402, id: 'ERR_INSUFFICIENT_PAYOUT_BUDGET_FOR_RESERVATION', message: 'Insufficient payout budget for reservation' },
  ERR_EXCEEDS_ASSIGNMENT_ENTITLEMENT: { status: 402, id: 'ERR_EXCEEDS_ASSIGNMENT_ENTITLEMENT', message: 'Exceeds assignment entitlement' },
  ERR_PAYOUT_BUDGET_EXHAUSTED_SINCE_REQUEST: { status: 402, id: 'ERR_PAYOUT_BUDGET_EXHAUSTED_SINCE_REQUEST', message: 'Payout budget exhausted since request' },
  ERR_INSUFFICIENT_ASSIGNMENT_RESERVATION: { status: 402, id: 'ERR_INSUFFICIENT_ASSIGNMENT_RESERVATION', message: 'Insufficient assignment reservation' },

  ERR_TENANT_SUSPENDED: { status: 403, id: 'ERR_TENANT_SUSPENDED', message: 'Tenant is suspended' },
  ERR_WORKER_RISK_HOLD_OR_SUSPENDED: { status: 403, id: 'ERR_WORKER_RISK_HOLD_OR_SUSPENDED', message: 'Worker is on risk hold or suspended' },
  ERR_WORKER_NOT_ACTIVE_OR_RISK_HOLD: { status: 403, id: 'ERR_WORKER_NOT_ACTIVE_OR_RISK_HOLD', message: 'Worker is not active or on risk hold' },
  ERR_NOT_ASSIGNED_WORKER: { status: 403, id: 'ERR_NOT_ASSIGNED_WORKER', message: 'Not the assigned worker' },
  ERR_WORKER_NOT_ASSIGNED: { status: 403, id: 'ERR_WORKER_NOT_ASSIGNED', message: 'Worker not assigned to this order' },

  ERR_TENANT_NOT_FOUND: { status: 404, id: 'ERR_TENANT_NOT_FOUND', message: 'Tenant not found' },
  ERR_ORDER_NOT_FOUND: { status: 404, id: 'ERR_ORDER_NOT_FOUND', message: 'Order not found' },
  ERR_WORKER_NOT_FOUND: { status: 404, id: 'ERR_WORKER_NOT_FOUND', message: 'Worker not found' },
  ERR_LISTING_NOT_FOUND: { status: 404, id: 'ERR_LISTING_NOT_FOUND', message: 'Listing not found' },
  ERR_ASSIGNMENT_NOT_FOUND: { status: 404, id: 'ERR_ASSIGNMENT_NOT_FOUND', message: 'Assignment not found' },
  ERR_PAYOUT_NOT_FOUND: { status: 404, id: 'ERR_PAYOUT_NOT_FOUND', message: 'Payout not found' },
  ERR_DISPUTE_NOT_FOUND: { status: 404, id: 'ERR_DISPUTE_NOT_FOUND', message: 'Dispute not found' },
  ERR_RATING_NOT_FOUND: { status: 404, id: 'ERR_RATING_NOT_FOUND', message: 'Rating not found' },

  ERR_CANNOT_REDUCE_BELOW_CONSUMED: { status: 409, id: 'ERR_CANNOT_REDUCE_BELOW_CONSUMED', message: 'Cannot reduce payout credit limit below consumed amount' },
  ERR_TENANT_NOT_ACTIVE: { status: 409, id: 'ERR_TENANT_NOT_ACTIVE', message: 'Tenant is not active' },
  ERR_TENANT_NOT_SUSPENDED: { status: 409, id: 'ERR_TENANT_NOT_SUSPENDED', message: 'Tenant is not suspended' },
  ERR_LISTING_NOT_PUBLISHED: { status: 409, id: 'ERR_LISTING_NOT_PUBLISHED', message: 'Listing is not published' },
  ERR_LISTING_NOT_DRAFT: { status: 409, id: 'ERR_LISTING_NOT_DRAFT', message: 'Listing is not in draft status' },
  ERR_LISTING_NOT_EDITABLE: { status: 409, id: 'ERR_LISTING_NOT_EDITABLE', message: 'Listing is not editable' },
  ERR_LISTING_NOT_PAUSED: { status: 409, id: 'ERR_LISTING_NOT_PAUSED', message: 'Listing is not paused' },
  ERR_LISTING_ALREADY_ARCHIVED: { status: 409, id: 'ERR_LISTING_ALREADY_ARCHIVED', message: 'Listing is already archived' },
  ERR_ORDER_NOT_CANCELLABLE: { status: 409, id: 'ERR_ORDER_NOT_CANCELLABLE', message: 'Order cannot be cancelled' },
  ERR_ORDER_NOT_IN_PROGRESS: { status: 409, id: 'ERR_ORDER_NOT_IN_PROGRESS', message: 'Order is not in progress' },
  ERR_ORDER_NOT_CLOSEABLE: { status: 409, id: 'ERR_ORDER_NOT_CLOSEABLE', message: 'Order cannot be closed' },
  ERR_OPEN_DISPUTE_EXISTS: { status: 409, id: 'ERR_OPEN_DISPUTE_EXISTS', message: 'Open dispute exists' },
  ERR_ORDER_NOT_ASSIGNABLE: { status: 409, id: 'ERR_ORDER_NOT_ASSIGNABLE', message: 'Order is not assignable' },
  ERR_DUPLICATE_ACTIVE_ASSIGNMENT: { status: 409, id: 'ERR_DUPLICATE_ACTIVE_ASSIGNMENT', message: 'Worker already has active assignment for this order' },
  ERR_WORKER_AT_CAPACITY: { status: 409, id: 'ERR_WORKER_AT_CAPACITY', message: 'Worker is at capacity' },
  ERR_ORDER_ALREADY_HAS_ACTIVE_ASSIGNMENT: { status: 409, id: 'ERR_ORDER_ALREADY_HAS_ACTIVE_ASSIGNMENT', message: 'Order already has an active assignment' },
  ERR_WORKER_LACKS_SKILL: { status: 409, id: 'ERR_WORKER_LACKS_SKILL', message: 'Worker lacks required skill' },
  ERR_WORKER_CERTIFICATION_EXPIRED: { status: 409, id: 'ERR_WORKER_CERTIFICATION_EXPIRED', message: 'Worker certification expired' },
  ERR_ASSIGNMENT_NOT_OFFERED: { status: 409, id: 'ERR_ASSIGNMENT_NOT_OFFERED', message: 'Assignment is not in offered status' },
  ERR_ASSIGNMENT_NOT_ACCEPTED: { status: 409, id: 'ERR_ASSIGNMENT_NOT_ACCEPTED', message: 'Assignment is not in accepted status' },
  ERR_ASSIGNMENT_NOT_IN_PROGRESS: { status: 409, id: 'ERR_ASSIGNMENT_NOT_IN_PROGRESS', message: 'Assignment is not in progress' },
  ERR_ASSIGNMENT_NOT_CANCELLABLE: { status: 409, id: 'ERR_ASSIGNMENT_NOT_CANCELLABLE', message: 'Assignment cannot be cancelled' },
  ERR_ASSIGNMENT_NOT_COMPLETED: { status: 409, id: 'ERR_ASSIGNMENT_NOT_COMPLETED', message: 'Assignment is not completed' },
  ERR_CANNOT_REDUCE_BELOW_ACTIVE_ASSIGNMENTS: { status: 409, id: 'ERR_CANNOT_REDUCE_BELOW_ACTIVE_ASSIGNMENTS', message: 'Cannot reduce max assignments below active count' },
  ERR_WORKER_NOT_SUSPENDED: { status: 409, id: 'ERR_WORKER_NOT_SUSPENDED', message: 'Worker is not suspended' },
  ERR_WORKER_NOT_UNDER_RISK_HOLD: { status: 409, id: 'ERR_WORKER_NOT_UNDER_RISK_HOLD', message: 'Worker is not under risk hold' },
  ERR_ORDER_NOT_DISPUTABLE: { status: 409, id: 'ERR_ORDER_NOT_DISPUTABLE', message: 'Order is not disputable' },
  ERR_DISPUTE_WINDOW_EXPIRED: { status: 409, id: 'ERR_DISPUTE_WINDOW_EXPIRED', message: 'Dispute window has expired' },
  ERR_MAX_DISPUTES_EXCEEDED: { status: 409, id: 'ERR_MAX_DISPUTES_EXCEEDED', message: 'Maximum disputes exceeded' },
  ERR_DISPUTE_NOT_FILED: { status: 409, id: 'ERR_DISPUTE_NOT_FILED', message: 'Dispute is not in filed status' },
  ERR_DISPUTE_NOT_UNDER_REVIEW: { status: 409, id: 'ERR_DISPUTE_NOT_UNDER_REVIEW', message: 'Dispute is not under review' },
  ERR_DISPUTE_NOT_WITHDRAWABLE: { status: 409, id: 'ERR_DISPUTE_NOT_WITHDRAWABLE', message: 'Dispute cannot be withdrawn' },
  ERR_ORDER_NOT_COMPLETED: { status: 409, id: 'ERR_ORDER_NOT_COMPLETED', message: 'Order is not completed' },
  ERR_RATING_NOT_MODERATABLE: { status: 409, id: 'ERR_RATING_NOT_MODERATABLE', message: 'Rating cannot be moderated' },
  ERR_PAYOUT_NOT_REQUESTED: { status: 409, id: 'ERR_PAYOUT_NOT_REQUESTED', message: 'Payout is not in requested status' },
  ERR_PAYOUT_NOT_APPROVED: { status: 409, id: 'ERR_PAYOUT_NOT_APPROVED', message: 'Payout is not approved' },
  ERR_PAYOUT_NOT_SENT: { status: 409, id: 'ERR_PAYOUT_NOT_SENT', message: 'Payout is not sent' },
  ERR_PAYOUT_NOT_CANCELLABLE: { status: 409, id: 'ERR_PAYOUT_NOT_CANCELLABLE', message: 'Payout cannot be cancelled' },
  ERR_FINAL_AMOUNT_MISMATCH: { status: 409, id: 'ERR_FINAL_AMOUNT_MISMATCH', message: 'Final payout amount does not match remaining entitlement' },
  ERR_IDEMPOTENCY_CONFLICT: { status: 409, id: 'ERR_IDEMPOTENCY_CONFLICT', message: 'Idempotency conflict - different body for same key' },
};

export function sendError(res: Response, error: { status: number; id: string; message: string }, customMessage?: string): void {
  errorResponse(res, error.status, error.id, customMessage || error.message);
}

export function updateTenantDerivedFields(tenant: MarketplaceTenant): void {
  const ledger = storage.getPayoutBudgetLedger(tenant.id);

  tenant.payout_consumed_cents = ledger.finalized_paid_cents;
  tenant.payout_reserved_cents = ledger.provisional_reserved_cents;
  tenant.recovered_clawbacks_cents = ledger.recovered_clawbacks_cents;

  tenant.payout_available_cents =
    tenant.payout_credit_limit_cents
    + ledger.recovered_clawbacks_cents
    - ledger.finalized_paid_cents
    - ledger.provisional_reserved_cents;

  tenant.is_payout_exhausted = tenant.payout_available_cents <= 0;

  tenant.is_payout_critical =
    tenant.payout_available_cents <
    (tenant.payout_credit_limit_cents * CONSTANTS.budget.EXHAUSTION_BUFFER_PERCENT / 100);

  tenant.aggregate_risk_score = calculateAggregateRiskScore(tenant.id);

  checkAndApplyTenantSuspension(tenant);
}

export function calculateAggregateRiskScore(tenantId: string): number {
  const workers = storage.getWorkersByTenant(tenantId)
    .filter(w => w.status === 'ACTIVE' || w.status === 'RISK_HOLD' || w.status === 'SUSPENDED');

  if (workers.length === 0) return 0;

  let weightedSum = 0;
  let totalWeight = 0;

  for (const worker of workers) {
    const weight = Math.max(1, worker.lifetime_orders_completed);
    weightedSum += worker.risk_score * weight;
    totalWeight += weight;
  }

  return Math.min(100, Math.max(0, Math.floor(weightedSum / totalWeight)));
}

export function updateWorkerDerivedFields(worker: Worker): void {
  const debtLedger = storage.getWorkerDebtLedger(worker.id);
  const capacityLedger = storage.getWorkerCapacityLedger(worker.id);
  const perfLedger = storage.getWorkerPerformanceLedger(worker.id);

  worker.debt_repaid_cents = debtLedger.applied_amount_cents;
  worker.debt_remaining_cents = Math.max(0, worker.signup_bonus_debt_cents - debtLedger.applied_amount_cents);
  worker.debt_satisfied = worker.debt_remaining_cents <= 0;

  const activeAssignments = storage.getActiveAssignmentsByWorker(worker.id);
  worker.active_assignment_count = activeAssignments.length;
  worker.is_at_capacity = worker.active_assignment_count >= worker.max_active_assignments;

  worker.lifetime_orders_completed = perfLedger.total_assignments_completed;
  worker.late_order_count = perfLedger.total_assignments_late;
  worker.cancellation_count = perfLedger.total_assignments_cancelled;

  worker.risk_score = calculateWorkerRiskScore(worker.id);
}

export function calculateWorkerRiskScore(workerId: string): number {
  const ledger = storage.getWorkerPerformanceLedger(workerId);

  let lateRate = 0;
  if (ledger.total_assignments_completed > 0) {
    lateRate = ledger.total_assignments_late / ledger.total_assignments_completed;
  }

  const totalAttempts = ledger.total_assignments_completed + ledger.total_assignments_cancelled;
  let cancelRate = 0;
  if (totalAttempts > 0) {
    cancelRate = ledger.total_assignments_cancelled / totalAttempts;
  }

  let ratingRate = 0;
  if (ledger.rating_count > 0) {
    const avgDeficit = ledger.cumulative_rating_deficit / ledger.rating_count;
    ratingRate = avgDeficit / 4.0;
  }

  const rawChronicRisk =
    (lateRate * CONSTANTS.risk.WEIGHT_LATE_COMPLETION) +
    (cancelRate * CONSTANTS.risk.WEIGHT_CANCELLATION) +
    (ratingRate * CONSTANTS.risk.WEIGHT_LOW_RATING);

  const dataPoints = totalAttempts;
  let stabilizedChronicRisk: number;
  if (dataPoints < CONSTANTS.risk.MIN_DATA_POINTS_FOR_STABILITY) {
    const weight = dataPoints / CONSTANTS.risk.MIN_DATA_POINTS_FOR_STABILITY;
    stabilizedChronicRisk =
      (rawChronicRisk * weight) +
      (CONSTANTS.risk.DEFAULT_CHRONIC_SCORE * (1 - weight));
  } else {
    stabilizedChronicRisk = rawChronicRisk;
  }

  const acutePenalty = ledger.dispute_loss_count * CONSTANTS.risk.DISPUTE_LOST_PENALTY;

  return Math.min(100, Math.max(0, Math.floor(stabilizedChronicRisk + acutePenalty)));
}

export function updateOrderDerivedFields(order: Order): void {
  const tenant = storage.getTenant(order.tenant_id);
  if (!tenant) return;

  const listing = storage.getListing(order.listing_id);
  if (!listing) return;

  if (order.completion_period_index !== null) {
    order.is_late =
      (order.completion_period_index - order.expected_completion_period_index) >
      CONSTANTS.sla.LATE_COMPLETION_MIN_PERIODS;
  } else {
    order.is_late = false;
  }
  order.is_sla_breached = order.is_late;

  const activeAssignments = storage.getActiveAssignmentsByOrder(order.id);
  order.active_assignment_count = activeAssignments.length;

  const disputes = storage.getDisputesByOrder(order.id);
  order.has_open_dispute = disputes.some(d =>
    d.status === 'FILED' || d.status === 'UNDER_REVIEW'
  );

  order.can_dispute = canOrderBeDisputed(order, tenant);

  const assignments = storage.getAssignmentsByOrder(order.id);
  order.total_payout_approved_cents = 0;
  order.total_payout_cleared_cents = 0;

  for (const assignment of assignments) {
    const payouts = storage.getPayoutsByAssignment(assignment.id);
    for (const payout of payouts) {
      if (payout.status === 'APPROVED' || payout.status === 'SENT' || payout.status === 'CLEARED') {
        order.total_payout_approved_cents += payout.approved_amount_cents;
      }
      if (payout.status === 'CLEARED') {
        order.total_payout_cleared_cents += payout.net_payout_cents;
      }
    }
  }

  const ratings = storage.getRatingsByOrder(order.id);
  order.rating_count = ratings.filter(r => r.status === 'PUBLISHED').length;
  if (order.rating_count > 0) {
    const sum = ratings
      .filter(r => r.status === 'PUBLISHED')
      .reduce((acc, r) => acc + r.rating_value, 0);
    order.average_rating = sum / order.rating_count;
  } else {
    order.average_rating = 0;
  }
}

export function canOrderBeDisputed(order: Order, tenant: MarketplaceTenant): boolean {
  const validStatuses = ['COMPLETED', 'FAILED', 'CANCELLED_BY_WORKER', 'REFUNDED', 'DISPUTED'];
  if (!validStatuses.includes(order.status)) return false;

  if (order.dispute_count >= CONSTANTS.dispute.MAX_DISPUTES_PER_ORDER) return false;

  if (order.order_completion_reference_period_index === null) return false;

  const periodsSinceCompletion = tenant.current_period_index - order.order_completion_reference_period_index;
  if (periodsSinceCompletion > CONSTANTS.dispute.FILING_WINDOW_PERIODS) return false;

  return true;
}

export function updateAssignmentDerivedFields(assignment: Assignment): void {
  const order = storage.getOrder(assignment.order_id);
  if (!order) return;

  assignment.expected_earnings_cents = calculateExpectedEarnings(assignment);

  if (assignment.expected_earnings_cents <= 0) {

    assignment.earnings_adequacy_ratio = Infinity;
    assignment.requires_adjustment = false;
    assignment.is_surplus_release_eligible = false;
    assignment.suggested_release_amount_cents = 0;
  } else {
    const minimumRequired = assignment.expected_earnings_cents * CONSTANTS.budget.MINIMUM_FACTOR;
    assignment.earnings_adequacy_ratio = assignment.reserved_earnings_current_cents / minimumRequired;
    assignment.requires_adjustment = assignment.earnings_adequacy_ratio <= CONSTANTS.budget.CRITICAL_THRESHOLD;
    assignment.is_surplus_release_eligible = assignment.earnings_adequacy_ratio > CONSTANTS.budget.SURPLUS_RELEASE_THRESHOLD;

    if (assignment.is_surplus_release_eligible) {
      const targetReservation = Math.floor(assignment.expected_earnings_cents * CONSTANTS.budget.MINIMUM_FACTOR);
      assignment.suggested_release_amount_cents = Math.max(0, assignment.reserved_earnings_current_cents - targetReservation);
    } else {
      assignment.suggested_release_amount_cents = 0;
    }
  }

  const payouts = storage.getPayoutsByAssignment(assignment.id);
  assignment.payout_requested_cents = payouts
    .filter(p => p.status !== 'CANCELLED' && p.status !== 'FAILED')
    .reduce((acc, p) => acc + p.requested_amount_cents, 0);
  assignment.payout_cleared_cents = payouts
    .filter(p => p.status === 'CLEARED')
    .reduce((acc, p) => acc + p.net_payout_cents, 0);
}

export function calculateExpectedEarnings(assignment: Assignment): number {
  const order = storage.getOrder(assignment.order_id);
  if (!order) return 0;

  const allAssignments = storage.getAssignmentsByOrder(order.id);
  const totalWorkerEarningsCap = order.worker_earnings_cap_cents;

  const hasDefinedShares = allAssignments.some(a => a.share_percentage !== null);

  if (hasDefinedShares) {

    if (assignment.share_percentage === null) return 0;
    return Math.floor(totalWorkerEarningsCap * assignment.share_percentage / 100);
  } else {

    const n = allAssignments.length;
    if (n === 0) return totalWorkerEarningsCap;

    const base = Math.floor(100 / n);
    const remainder = 100 - (base * n);

    const sorted = [...allAssignments].sort((a, b) => a.created_seq - b.created_seq);
    const idx = sorted.findIndex(a => a.id === assignment.id);

    const share = idx < remainder ? base + 1 : base;
    return Math.floor(totalWorkerEarningsCap * share / 100);
  }
}

export function calculateRemainingEntitlement(assignment: Assignment): number {
  const expected = assignment.expected_earnings_cents;
  const cleared = assignment.payout_cleared_cents;
  return Math.max(0, expected - cleared);
}

export function getListingPriorityTier(listing: Listing): number {
  const categoryPriority: Record<string, number> = {
    'HOME_SERVICE': 0,
    'RIDESHARE': 1,
    'DELIVERY': 2,
    'TASK': 3
  };

  const priority =
    categoryPriority[listing.category] === undefined
      ? 3
      : categoryPriority[listing.category];

  return priority * 1000 + listing.created_seq;
}

export function checkAndApplyRiskHold(worker: Worker): void {
  if (worker.risk_score >= CONSTANTS.risk.AUTO_DEACTIVATE_THRESHOLD) {
    if (worker.status !== 'DEACTIVATED') {
      worker.status = 'DEACTIVATED';

      const assignments = storage.getAssignmentsByWorker(worker.id);
      for (const assignment of assignments) {
        if (!['COMPLETED', 'CANCELLED_BY_WORKER', 'CANCELLED_BY_SYSTEM', 'EXPIRED'].includes(assignment.status)) {
          assignment.status = 'CANCELLED_BY_SYSTEM';
          storage.saveAssignment(assignment);

          releaseAssignmentReservation(assignment);
        }
      }

      const payouts = storage.getPayoutsByWorker(worker.id);
      for (const payout of payouts) {
        if (['REQUESTED', 'APPROVED', 'HELD'].includes(payout.status)) {
          payout.status = 'CANCELLED';
          storage.savePayout(payout);
        }
      }
    }
  } else if (worker.risk_score >= CONSTANTS.risk.RISK_HOLD_THRESHOLD) {
    if (worker.status === 'ACTIVE') {
      worker.status = 'RISK_HOLD';

      const payouts = storage.getPayoutsByWorker(worker.id);
      for (const payout of payouts) {
        if (payout.status === 'REQUESTED') {
          payout.status = 'HELD';
          storage.savePayout(payout);
        }
      }
    }
  }
}

export function applyRiskScoreSideEffects(worker: Worker, tenant: MarketplaceTenant): void {
  updateWorkerDerivedFields(worker);
  storage.saveWorker(worker);

  const previousStatus = worker.status;

  updateTenantDerivedFields(tenant);
  storage.saveTenant(tenant);

  checkAndApplyRiskHold(worker);

  if (worker.status !== previousStatus) {
    storage.saveWorker(worker);
    updateTenantDerivedFields(tenant);
    storage.saveTenant(tenant);
  }
}

export function releaseAssignmentReservation(assignment: Assignment): void {
  const tenant = storage.getTenant(assignment.tenant_id);
  if (!tenant) return;

  const ledger = storage.getPayoutBudgetLedger(tenant.id);
  ledger.provisional_reserved_cents -= assignment.reserved_earnings_current_cents;
  assignment.released_earnings_cents += assignment.reserved_earnings_current_cents;
  assignment.reserved_earnings_current_cents = 0;

  storage.savePayoutBudgetLedger(ledger);
  updateTenantDerivedFields(tenant);
  storage.saveTenant(tenant);
}

export function checkAndApplyTenantSuspension(tenant: MarketplaceTenant): void {
  if (tenant.aggregate_risk_score >= CONSTANTS.risk.AUTO_DEACTIVATE_THRESHOLD && tenant.status === 'ACTIVE') {
    tenant.status = 'SUSPENDED';
  }
}

export function isValidUUID(str: string): boolean {
  const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  return uuidRegex.test(str);
}

export function validateCategory(category: string): boolean {
  return ['DELIVERY', 'HOME_SERVICE', 'RIDESHARE', 'TASK'].includes(category);
}

export function validateSkills(skills: string[]): boolean {
  if (!Array.isArray(skills)) return false;
  return skills.every(skill => validateCategory(skill));
}
