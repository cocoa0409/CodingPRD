import { Router, Request, Response } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { storage, getNextSeq } from '../storage';
import { MarketplaceTenant, CONSTANTS } from '../types';
import {
  successResponse, sendError, ERRORS,
  updateTenantDerivedFields, checkAndApplyTenantSuspension
} from '../utils';

const router = Router();

router.post('/', (req: Request, res: Response) => {
  const { name, payout_credit_limit_cents } = req.body;

  if (!name || typeof name !== 'string' || name.trim() === '') {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'name is required');
  }

  if (payout_credit_limit_cents === undefined ||
      typeof payout_credit_limit_cents !== 'number' ||
      payout_credit_limit_cents < 0 ||
      !Number.isInteger(payout_credit_limit_cents)) {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'payout_credit_limit_cents must be a non-negative integer');
  }

  const id = uuidv4();
  const tenant: MarketplaceTenant = {
    id,
    name: name.trim(),
    payout_credit_limit_cents,
    current_period_index: CONSTANTS.clock.MIN_PERIOD_INDEX,
    payout_consumed_cents: 0,
    payout_reserved_cents: 0,
    payout_available_cents: payout_credit_limit_cents,
    recovered_clawbacks_cents: 0,
    is_payout_critical: payout_credit_limit_cents === 0,
    is_payout_exhausted: payout_credit_limit_cents === 0,
    aggregate_risk_score: 0,
    status: 'ACTIVE',
    term_end_period_index: null,
    created_seq: getNextSeq(id)
  };

  storage.getPayoutBudgetLedger(id);

  storage.saveTenant(tenant);
  return successResponse(res, tenant, 201);
});

router.get('/', (req: Request, res: Response) => {
  const tenants = storage.getAllTenants();
  return successResponse(res, tenants);
});

router.get('/:tenantId', (req: Request, res: Response) => {
  const { tenantId } = req.params;
  const tenant = storage.getTenant(tenantId);

  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  updateTenantDerivedFields(tenant);
  storage.saveTenant(tenant);
  return successResponse(res, tenant);
});

router.put('/:tenantId', (req: Request, res: Response) => {
  const { tenantId } = req.params;
  const tenant = storage.getTenant(tenantId);

  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const { payout_credit_limit_cents } = req.body;

  if (payout_credit_limit_cents !== undefined) {
    if (typeof payout_credit_limit_cents !== 'number' ||
        payout_credit_limit_cents < 0 ||
        !Number.isInteger(payout_credit_limit_cents)) {
      return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'payout_credit_limit_cents must be a non-negative integer');
    }

    const ledger = storage.getPayoutBudgetLedger(tenantId);
    const minRequired = ledger.finalized_paid_cents + ledger.provisional_reserved_cents - ledger.recovered_clawbacks_cents;

    if (payout_credit_limit_cents < minRequired) {
      return sendError(res, ERRORS.ERR_CANNOT_REDUCE_BELOW_CONSUMED);
    }

    tenant.payout_credit_limit_cents = payout_credit_limit_cents;
  }

  updateTenantDerivedFields(tenant);
  storage.saveTenant(tenant);
  return successResponse(res, tenant);
});

router.post('/:tenantId/clock/advance', (req: Request, res: Response) => {
  const { tenantId } = req.params;
  const tenant = storage.getTenant(tenantId);

  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const { by_periods } = req.body;

  if (by_periods === undefined ||
      typeof by_periods !== 'number' ||
      !Number.isInteger(by_periods) ||
      by_periods < 1 ||
      by_periods > CONSTANTS.clock.MAX_ADVANCE_BY) {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, `by_periods must be an integer between 1 and ${CONSTANTS.clock.MAX_ADVANCE_BY}`);
  }

  tenant.current_period_index += by_periods;

  if (tenant.term_end_period_index !== null &&
      tenant.current_period_index >= tenant.term_end_period_index) {
    tenant.status = 'CLOSED';
  }

  const orders = storage.getOrdersByTenant(tenantId);
  for (const order of orders) {
    if (order.order_completion_reference_period_index !== null) {
      const periodsSinceCompletion = tenant.current_period_index - order.order_completion_reference_period_index;
      if (periodsSinceCompletion > CONSTANTS.dispute.FILING_WINDOW_PERIODS) {
        order.can_dispute = false;
        storage.saveOrder(order);
      }
    }
  }

  updateTenantDerivedFields(tenant);
  storage.saveTenant(tenant);
  return successResponse(res, tenant);
});

router.post('/:tenantId/suspend', (req: Request, res: Response) => {
  const { tenantId } = req.params;
  const tenant = storage.getTenant(tenantId);

  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  if (tenant.status !== 'ACTIVE') {
    return sendError(res, ERRORS.ERR_TENANT_NOT_ACTIVE);
  }

  tenant.status = 'SUSPENDED';
  storage.saveTenant(tenant);
  return successResponse(res, tenant);
});

router.post('/:tenantId/reinstate', (req: Request, res: Response) => {
  const { tenantId } = req.params;
  const tenant = storage.getTenant(tenantId);

  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  if (tenant.status !== 'SUSPENDED') {
    return sendError(res, ERRORS.ERR_TENANT_NOT_SUSPENDED);
  }

  tenant.status = 'ACTIVE';
  updateTenantDerivedFields(tenant);
  storage.saveTenant(tenant);
  return successResponse(res, tenant);
});

export default router;
