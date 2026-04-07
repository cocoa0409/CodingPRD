import { Router, Request, Response } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { storage, getNextSeq } from '../storage';
import { Payout, CONSTANTS, MarketplaceTenant } from '../types';
import {
  successResponse, sendError, ERRORS,
  updateTenantDerivedFields, updateWorkerDerivedFields,
  updateAssignmentDerivedFields, calculateRemainingEntitlement
} from '../utils';

const router = Router({ mergeParams: true });

router.post('/', (req: Request, res: Response) => {
  const { tenantId, workerId } = req.params;
  const idempotencyKey = req.headers['idempotency-key'] as string;

  if (!idempotencyKey) {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'Idempotency-Key header is required');
  }

  const { assignment_id, requested_amount_cents, payout_type } = req.body;

  if (!assignment_id || typeof assignment_id !== 'string') {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'assignment_id is required');
  }

  if (requested_amount_cents === undefined ||
      typeof requested_amount_cents !== 'number' ||
      !Number.isInteger(requested_amount_cents) ||
      requested_amount_cents <= 0) {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'requested_amount_cents must be a positive integer');
  }

  if (!payout_type || !['NORMAL', 'INSTANT', 'ADJUSTMENT', 'FINAL'].includes(payout_type)) {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'Invalid payout_type');
  }

  const tenant = storage.getTenant(tenantId);
  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  if (tenant.status === 'SUSPENDED') {
    return sendError(res, ERRORS.ERR_TENANT_SUSPENDED);
  }

  const worker = storage.getWorker(workerId);
  if (!worker || worker.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_WORKER_NOT_FOUND);
  }

  if (worker.status === 'RISK_HOLD' || worker.status === 'SUSPENDED' || worker.status === 'DEACTIVATED') {
    return sendError(res, ERRORS.ERR_WORKER_RISK_HOLD_OR_SUSPENDED);
  }

  if (requested_amount_cents < CONSTANTS.payout.MINIMUM_PAYOUT_CENTS) {
    return sendError(res, ERRORS.ERR_PAYOUT_BELOW_MINIMUM);
  }

  const assignment = storage.getAssignment(assignment_id);
  if (!assignment || assignment.tenant_id !== tenantId || assignment.worker_id !== workerId) {
    return sendError(res, ERRORS.ERR_ASSIGNMENT_NOT_FOUND);
  }

  if (assignment.status !== 'COMPLETED') {
    return sendError(res, ERRORS.ERR_ASSIGNMENT_NOT_COMPLETED);
  }

  const existingRecord = storage.getIdempotencyRecord(
    tenantId,
    workerId,
    assignment_id,
    'POST /payouts',
    idempotencyKey
  );

  if (existingRecord) {

    const currentBody = JSON.stringify({ assignment_id, requested_amount_cents, payout_type });
    if (existingRecord.request_body === currentBody) {

      return successResponse(res, existingRecord.response, 200);
    } else {
      return sendError(res, ERRORS.ERR_IDEMPOTENCY_CONFLICT);
    }
  }

  updateAssignmentDerivedFields(assignment);
  const remainingEntitlement = calculateRemainingEntitlement(assignment);

  if (payout_type === 'FINAL') {
    if (requested_amount_cents !== remainingEntitlement) {
      return sendError(res, ERRORS.ERR_FINAL_AMOUNT_MISMATCH);
    }
  }

  if (requested_amount_cents > remainingEntitlement) {
    return sendError(res, ERRORS.ERR_EXCEEDS_ASSIGNMENT_ENTITLEMENT);
  }

  updateTenantDerivedFields(tenant);

  if (tenant.is_payout_exhausted) {
    return sendError(res, ERRORS.ERR_INSUFFICIENT_PAYOUT_BUDGET);
  }

  const availableBudget = Math.max(0, tenant.payout_available_cents);

  updateWorkerDerivedFields(worker);

  const unproratedAmount = Math.min(requested_amount_cents, remainingEntitlement, availableBudget);

  let approvedAmount = unproratedAmount;
  let prorationFactor = 1.0;
  let isProrated = false;

  let debtRepaymentPortion = 0;
  let cashPortion = approvedAmount;

  if (worker.debt_remaining_cents > 0) {
    debtRepaymentPortion = Math.min(approvedAmount, worker.debt_remaining_cents);
    cashPortion = approvedAmount - debtRepaymentPortion;
  }

  let instantFee = 0;
  if (payout_type === 'INSTANT') {
    instantFee = Math.floor(cashPortion * CONSTANTS.payout.INSTANT_FEE_PERCENT / 100);
  }

  const netPayout = cashPortion - instantFee;

  const budgetDraw = payout_type === 'INSTANT' ? netPayout : cashPortion;

  const payoutsForAssignment = storage.getPayoutsByAssignment(assignment_id);
  const committedDraws = payoutsForAssignment
    .filter(p => ['REQUESTED', 'APPROVED', 'SENT'].includes(p.status))
    .reduce((sum, p) => sum + p.budget_draw_amount_cents, 0);

  const availableReserve = assignment.reserved_earnings_current_cents - committedDraws;

  if (budgetDraw > availableReserve) {
    return sendError(res, ERRORS.ERR_INSUFFICIENT_ASSIGNMENT_RESERVATION);
  }

  adjustWorkerDebtLedger(workerId, debtRepaymentPortion);

  const id = uuidv4();
  const createdSeq = getNextSeq(tenantId);

  const payout: Payout = {
    id,
    tenant_id: tenantId,
    worker_id: workerId,
    assignment_id,
    status: 'REQUESTED',
    payout_type,
    requested_amount_cents,
    unprorated_amount_cents: unproratedAmount,
    approved_amount_cents: approvedAmount,
    debt_repayment_portion_cents: debtRepaymentPortion,
    cash_portion_cents: cashPortion,
    instant_payout_fee_cents: instantFee,
    net_payout_cents: netPayout,
    budget_draw_amount_cents: budgetDraw,
    proration_factor: prorationFactor,
    is_prorated: isProrated,
    created_seq: createdSeq
  };

  storage.savePayout(payout);

  storage.saveIdempotencyRecord({
    key: idempotencyKey,
    tenant_id: tenantId,
    worker_id: workerId,
    assignment_id,
    endpoint: 'POST /payouts',
    request_body: JSON.stringify({ assignment_id, requested_amount_cents, payout_type }),
    response: payout
  });

  return successResponse(res, payout, 201);
});

router.get('/', (req: Request, res: Response) => {
  const { tenantId, workerId } = req.params;

  const tenant = storage.getTenant(tenantId);
  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const worker = storage.getWorker(workerId);
  if (!worker || worker.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_WORKER_NOT_FOUND);
  }

  const payouts = storage.getPayoutsByWorker(workerId);
  return successResponse(res, payouts);
});

router.post('/:payoutId/approve', (req: Request, res: Response) => {
  const { tenantId, workerId, payoutId } = req.params;

  const tenant = storage.getTenant(tenantId);
  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const worker = storage.getWorker(workerId);
  if (!worker || worker.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_WORKER_NOT_FOUND);
  }

  let payout = storage.getPayout(payoutId);
  if (!payout || payout.tenant_id !== tenantId || payout.worker_id !== workerId) {
    return sendError(res, ERRORS.ERR_PAYOUT_NOT_FOUND);
  }

  if (payout.status !== 'REQUESTED') {
    return sendError(res, ERRORS.ERR_PAYOUT_NOT_REQUESTED);
  }

  rebalancePendingPayouts(tenant);
  payout = storage.getPayout(payoutId)!;

  updateTenantDerivedFields(tenant);
  storage.saveTenant(tenant);

  if (tenant.is_payout_exhausted && payout.budget_draw_amount_cents > 0) {
    return sendError(res, ERRORS.ERR_PAYOUT_BUDGET_EXHAUSTED_SINCE_REQUEST);
  }

  const fundablePayouts = getFundablePayoutIds(tenant);
  if (!fundablePayouts.has(payout.id)) {
    return sendError(res, ERRORS.ERR_PAYOUT_BUDGET_EXHAUSTED_SINCE_REQUEST);
  }

  payout.status = 'APPROVED';
  storage.savePayout(payout);

  return successResponse(res, payout);
});

router.post('/:payoutId/send', (req: Request, res: Response) => {
  const { tenantId, workerId, payoutId } = req.params;

  const tenant = storage.getTenant(tenantId);
  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const worker = storage.getWorker(workerId);
  if (!worker || worker.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_WORKER_NOT_FOUND);
  }

  const payout = storage.getPayout(payoutId);
  if (!payout || payout.tenant_id !== tenantId || payout.worker_id !== workerId) {
    return sendError(res, ERRORS.ERR_PAYOUT_NOT_FOUND);
  }

  if (payout.status !== 'APPROVED') {
    return sendError(res, ERRORS.ERR_PAYOUT_NOT_APPROVED);
  }

  payout.status = 'SENT';
  storage.savePayout(payout);

  return successResponse(res, payout);
});

router.post('/:payoutId/confirm-cleared', (req: Request, res: Response) => {
  const { tenantId, workerId, payoutId } = req.params;

  const tenant = storage.getTenant(tenantId);
  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const worker = storage.getWorker(workerId);
  if (!worker || worker.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_WORKER_NOT_FOUND);
  }

  const payout = storage.getPayout(payoutId);
  if (!payout || payout.tenant_id !== tenantId || payout.worker_id !== workerId) {
    return sendError(res, ERRORS.ERR_PAYOUT_NOT_FOUND);
  }

  if (payout.status !== 'SENT') {
    return sendError(res, ERRORS.ERR_PAYOUT_NOT_SENT);
  }

  const assignment = storage.getAssignment(payout.assignment_id);
  if (!assignment || assignment.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_ASSIGNMENT_NOT_FOUND);
  }

  updateAssignmentDerivedFields(assignment);
  const remainingEntitlement = calculateRemainingEntitlement(assignment);
  if (payout.net_payout_cents > remainingEntitlement) {
    return sendError(res, ERRORS.ERR_EXCEEDS_ASSIGNMENT_ENTITLEMENT);
  }

  payout.status = 'CLEARED';

  const ledger = storage.getPayoutBudgetLedger(tenantId);
  ledger.finalized_paid_cents += payout.net_payout_cents;
  ledger.provisional_reserved_cents -= payout.budget_draw_amount_cents;
  storage.savePayoutBudgetLedger(ledger);
  storage.savePayout(payout);

  const appliedDraw = Math.min(payout.budget_draw_amount_cents, assignment.reserved_earnings_current_cents);
  assignment.reserved_earnings_current_cents -= appliedDraw;

  updateTenantDerivedFields(tenant);
  storage.saveTenant(tenant);

  updateWorkerDerivedFields(worker);
  storage.saveWorker(worker);

  updateAssignmentDerivedFields(assignment);
  storage.saveAssignment(assignment);

  return successResponse(res, payout);
});

router.post('/:payoutId/cancel', (req: Request, res: Response) => {
  const { tenantId, workerId, payoutId } = req.params;

  const tenant = storage.getTenant(tenantId);
  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const worker = storage.getWorker(workerId);
  if (!worker || worker.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_WORKER_NOT_FOUND);
  }

  const payout = storage.getPayout(payoutId);
  if (!payout || payout.tenant_id !== tenantId || payout.worker_id !== workerId) {
    return sendError(res, ERRORS.ERR_PAYOUT_NOT_FOUND);
  }

  if (!['REQUESTED', 'APPROVED', 'HELD'].includes(payout.status)) {
    return sendError(res, ERRORS.ERR_PAYOUT_NOT_CANCELLABLE);
  }

  payout.status = 'CANCELLED';
  storage.savePayout(payout);

  if (payout.debt_repayment_portion_cents > 0) {
    adjustWorkerDebtLedger(workerId, -payout.debt_repayment_portion_cents);
  }

  return successResponse(res, payout);
});

router.post('/:payoutId/fail', (req: Request, res: Response) => {
  const { tenantId, workerId, payoutId } = req.params;

  const tenant = storage.getTenant(tenantId);
  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const worker = storage.getWorker(workerId);
  if (!worker || worker.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_WORKER_NOT_FOUND);
  }

  const payout = storage.getPayout(payoutId);
  if (!payout || payout.tenant_id !== tenantId || payout.worker_id !== workerId) {
    return sendError(res, ERRORS.ERR_PAYOUT_NOT_FOUND);
  }

  if (payout.status !== 'SENT') {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'Payout must be in SENT status to fail');
  }

  payout.status = 'FAILED';

  if (payout.debt_repayment_portion_cents > 0) {
    adjustWorkerDebtLedger(workerId, -payout.debt_repayment_portion_cents);
  }

  storage.savePayout(payout);

  return successResponse(res, payout);
});

export default router;

function rebalancePendingPayouts(tenant: MarketplaceTenant): void {
  updateTenantDerivedFields(tenant);
  storage.saveTenant(tenant);

  const pendingPayouts = storage.getPayoutsByTenant(tenant.id)
    .filter(p => ['REQUESTED', 'APPROVED', 'HELD'].includes(p.status));

  if (pendingPayouts.length === 0) {
    return;
  }

  const threshold = tenant.payout_credit_limit_cents * CONSTANTS.budget.PRORATION_TRIGGER_PERCENT / 100;
  const totalUnprorated = pendingPayouts.reduce(
    (sum, payout) => sum + (payout.unprorated_amount_cents ?? payout.approved_amount_cents),
    0
  );

  let prorationFactor = 1.0;
  if (
    tenant.is_payout_critical &&
    tenant.payout_consumed_cents >= threshold &&
    totalUnprorated > 0
  ) {
    prorationFactor = Math.min(1.0, tenant.payout_available_cents / totalUnprorated);
  }

  const applyProration = prorationFactor < 1.0;

  for (const payout of pendingPayouts) {
    const baseAmount = payout.unprorated_amount_cents ?? payout.approved_amount_cents;
    const newApprovedAmount = applyProration ? Math.floor(baseAmount * prorationFactor) : baseAmount;
    payout.approved_amount_cents = newApprovedAmount;
    const oldDebtPortion = payout.debt_repayment_portion_cents;
    const newDebtPortion = Math.min(oldDebtPortion, newApprovedAmount);
    payout.debt_repayment_portion_cents = newDebtPortion;
    const newCashPortion = newApprovedAmount - newDebtPortion;
    payout.cash_portion_cents = newCashPortion;
    payout.instant_payout_fee_cents = payout.payout_type === 'INSTANT'
      ? Math.floor(newCashPortion * CONSTANTS.payout.INSTANT_FEE_PERCENT / 100)
      : 0;
    payout.net_payout_cents = payout.cash_portion_cents - payout.instant_payout_fee_cents;
    payout.budget_draw_amount_cents = payout.payout_type === 'INSTANT'
      ? payout.net_payout_cents
      : payout.cash_portion_cents;
    payout.is_prorated = applyProration;
    payout.proration_factor = applyProration ? prorationFactor : 1.0;

    if (newDebtPortion !== oldDebtPortion) {
      adjustWorkerDebtLedger(payout.worker_id, newDebtPortion - oldDebtPortion);
    }

    storage.savePayout(payout);
  }
}

function getPayoutPriorityKey(payout: Payout): { priorityTier: number; createdSeq: number } {
  const assignment = storage.getAssignment(payout.assignment_id);
  if (!assignment) {
    return { priorityTier: Number.MAX_SAFE_INTEGER, createdSeq: payout.created_seq };
  }

  const order = storage.getOrder(assignment.order_id);
  if (!order) {
    return { priorityTier: Number.MAX_SAFE_INTEGER, createdSeq: payout.created_seq };
  }

  const listing = storage.getListing(order.listing_id);
  if (!listing) {
    return { priorityTier: Number.MAX_SAFE_INTEGER, createdSeq: payout.created_seq };
  }

  return { priorityTier: listing.priority_tier, createdSeq: payout.created_seq };
}

function getFundablePayoutIds(tenant: MarketplaceTenant): Set<string> {
  const pending = storage.getPayoutsByTenant(tenant.id)
    .filter(p => ['REQUESTED', 'APPROVED', 'HELD'].includes(p.status))
    .map(p => {
      const key = getPayoutPriorityKey(p);
      return { payout: p, priorityTier: key.priorityTier, createdSeq: key.createdSeq };
    })
    .sort((a, b) => {
      if (a.priorityTier !== b.priorityTier) {
        return a.priorityTier - b.priorityTier;
      }
      return a.createdSeq - b.createdSeq;
    });

  let remainingBudget = Math.max(0, tenant.payout_available_cents);
  const fundable = new Set<string>();

  for (const entry of pending) {
    const draw = Math.max(0, entry.payout.budget_draw_amount_cents);

    if (entry.payout.status === 'REQUESTED') {
      if (draw === 0 || remainingBudget >= draw) {
        fundable.add(entry.payout.id);
        if (draw > 0) {
          remainingBudget -= draw;
        }
      } else {
        break;
      }
    } else if (draw > 0) {
      remainingBudget = Math.max(0, remainingBudget - draw);
    }
  }

  return fundable;
}

function adjustWorkerDebtLedger(workerId: string, delta: number): void {
  if (delta === 0) {
    return;
  }

  const ledger = storage.getWorkerDebtLedger(workerId);
  ledger.applied_amount_cents = Math.max(0, ledger.applied_amount_cents + delta);
  storage.saveWorkerDebtLedger(ledger);

  const worker = storage.getWorker(workerId);
  if (worker) {
    updateWorkerDerivedFields(worker);
    storage.saveWorker(worker);
  }
}
