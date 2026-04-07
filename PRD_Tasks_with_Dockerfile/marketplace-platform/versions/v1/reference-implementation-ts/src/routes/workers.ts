import { Router, Request, Response } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { storage, getNextSeq } from '../storage';
import { Worker, Certification, CONSTANTS } from '../types';
import {
  successResponse, sendError, ERRORS,
  updateWorkerDerivedFields, validateSkills,
  updateTenantDerivedFields
} from '../utils';

const router = Router({ mergeParams: true });

router.post('/', (req: Request, res: Response) => {
  const { tenantId } = req.params;
  const tenant = storage.getTenant(tenantId);

  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const {
    name,
    skills,
    certifications,
    max_active_assignments,
    signup_bonus_debt_cents
  } = req.body;

  if (!name || typeof name !== 'string' || name.trim() === '') {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'name is required');
  }

  if (!skills || !Array.isArray(skills)) {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'skills must be an array');
  }

  if (!validateSkills(skills)) {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'Invalid skills');
  }

  const validatedCertifications: Certification[] = [];
  if (certifications) {
    if (!Array.isArray(certifications)) {
      return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'certifications must be an array');
    }
    for (const cert of certifications) {
      if (!cert.certification_type || typeof cert.certification_type !== 'string') {
        return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'certification_type is required');
      }
      if (typeof cert.certified_period_index !== 'number' || !Number.isInteger(cert.certified_period_index)) {
        return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'certified_period_index must be an integer');
      }
      if (typeof cert.expiry_period_index !== 'number' || !Number.isInteger(cert.expiry_period_index)) {
        return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'expiry_period_index must be an integer');
      }
      validatedCertifications.push({
        certification_type: cert.certification_type,
        certified_period_index: cert.certified_period_index,
        expiry_period_index: cert.expiry_period_index
      });
    }
  }

  let maxAssignments = CONSTANTS.worker.MAX_ACTIVE_ASSIGNMENTS;
  if (max_active_assignments !== undefined) {
    if (typeof max_active_assignments !== 'number' ||
        !Number.isInteger(max_active_assignments) ||
        max_active_assignments < 1) {
      return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'max_active_assignments must be a positive integer');
    }
    maxAssignments = max_active_assignments;
  }

  let bonusDebt = 0;
  if (signup_bonus_debt_cents !== undefined) {
    if (typeof signup_bonus_debt_cents !== 'number' ||
        !Number.isInteger(signup_bonus_debt_cents) ||
        signup_bonus_debt_cents < 0 ||
        signup_bonus_debt_cents > CONSTANTS.debt.MAX_SIGNUP_BONUS_CENTS) {
      return sendError(res, ERRORS.ERR_INVALID_REQUEST, `signup_bonus_debt_cents must be between 0 and ${CONSTANTS.debt.MAX_SIGNUP_BONUS_CENTS}`);
    }
    bonusDebt = signup_bonus_debt_cents;
  }

  const id = uuidv4();
  const createdSeq = getNextSeq(tenantId);

  const worker: Worker = {
    id,
    tenant_id: tenantId,
    name: name.trim(),
    status: 'ACTIVE',
    skills,
    certifications: validatedCertifications,
    max_active_assignments: maxAssignments,
    active_assignment_count: 0,
    is_at_capacity: false,
    risk_score: 0,
    lifetime_orders_completed: 0,
    late_order_count: 0,
    cancellation_count: 0,
    signup_bonus_debt_cents: bonusDebt,
    debt_repaid_cents: 0,
    debt_remaining_cents: bonusDebt,
    debt_satisfied: bonusDebt === 0,
    created_seq: createdSeq
  };

  storage.getWorkerDebtLedger(id);
  storage.getWorkerPerformanceLedger(id);
  storage.getWorkerCapacityLedger(id);

  storage.saveWorker(worker);

  updateTenantDerivedFields(tenant);
  storage.saveTenant(tenant);

  return successResponse(res, worker, 201);
});

router.get('/', (req: Request, res: Response) => {
  const { tenantId } = req.params;
  const tenant = storage.getTenant(tenantId);

  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const workers = storage.getWorkersByTenant(tenantId);

  for (const worker of workers) {
    updateWorkerDerivedFields(worker);
  }

  return successResponse(res, workers);
});

router.get('/:workerId', (req: Request, res: Response) => {
  const { tenantId, workerId } = req.params;
  const tenant = storage.getTenant(tenantId);

  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const worker = storage.getWorker(workerId);

  if (!worker || worker.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_WORKER_NOT_FOUND);
  }

  updateWorkerDerivedFields(worker);
  storage.saveWorker(worker);
  return successResponse(res, worker);
});

router.put('/:workerId', (req: Request, res: Response) => {
  const { tenantId, workerId } = req.params;
  const tenant = storage.getTenant(tenantId);

  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const worker = storage.getWorker(workerId);

  if (!worker || worker.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_WORKER_NOT_FOUND);
  }

  const { skills, certifications, max_active_assignments } = req.body;

  if (skills !== undefined) {
    if (!Array.isArray(skills) || !validateSkills(skills)) {
      return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'Invalid skills');
    }
    worker.skills = skills;
  }

  if (certifications !== undefined) {
    if (!Array.isArray(certifications)) {
      return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'certifications must be an array');
    }
    const validatedCerts: Certification[] = [];
    for (const cert of certifications) {
      if (!cert.certification_type || typeof cert.certification_type !== 'string') {
        return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'certification_type is required');
      }
      if (typeof cert.certified_period_index !== 'number' || !Number.isInteger(cert.certified_period_index)) {
        return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'certified_period_index must be an integer');
      }
      if (typeof cert.expiry_period_index !== 'number' || !Number.isInteger(cert.expiry_period_index)) {
        return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'expiry_period_index must be an integer');
      }
      validatedCerts.push({
        certification_type: cert.certification_type,
        certified_period_index: cert.certified_period_index,
        expiry_period_index: cert.expiry_period_index
      });
    }
    worker.certifications = validatedCerts;
  }

  if (max_active_assignments !== undefined) {
    if (typeof max_active_assignments !== 'number' ||
        !Number.isInteger(max_active_assignments) ||
        max_active_assignments < 1) {
      return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'max_active_assignments must be a positive integer');
    }

    updateWorkerDerivedFields(worker);
    if (max_active_assignments < worker.active_assignment_count) {
      return sendError(res, ERRORS.ERR_CANNOT_REDUCE_BELOW_ACTIVE_ASSIGNMENTS);
    }

    worker.max_active_assignments = max_active_assignments;
  }

  updateWorkerDerivedFields(worker);
  storage.saveWorker(worker);
  return successResponse(res, worker);
});

router.post('/:workerId/suspend', (req: Request, res: Response) => {
  const { tenantId, workerId } = req.params;
  const tenant = storage.getTenant(tenantId);

  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const worker = storage.getWorker(workerId);

  if (!worker || worker.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_WORKER_NOT_FOUND);
  }

  if (worker.status !== 'ACTIVE' && worker.status !== 'RISK_HOLD') {
    return sendError(res, ERRORS.ERR_WORKER_NOT_ACTIVE_OR_RISK_HOLD);
  }

  worker.status = 'SUSPENDED';
  storage.saveWorker(worker);

  updateTenantDerivedFields(tenant);
  storage.saveTenant(tenant);

  return successResponse(res, worker);
});

router.post('/:workerId/risk-hold/clear', (req: Request, res: Response) => {
  const { tenantId, workerId } = req.params;
  const tenant = storage.getTenant(tenantId);

  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const worker = storage.getWorker(workerId);

  if (!worker || worker.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_WORKER_NOT_FOUND);
  }

  if (worker.status !== 'RISK_HOLD') {
    return sendError(res, ERRORS.ERR_WORKER_NOT_UNDER_RISK_HOLD);
  }

  worker.status = 'ACTIVE';

  const payouts = storage.getPayoutsByWorker(workerId);
  for (const payout of payouts) {
    if (payout.status === 'HELD') {
      payout.status = 'REQUESTED';
      storage.savePayout(payout);
    }
  }

  updateWorkerDerivedFields(worker);
  storage.saveWorker(worker);

  updateTenantDerivedFields(tenant);
  storage.saveTenant(tenant);

  return successResponse(res, worker);
});

router.post('/:workerId/reinstate', (req: Request, res: Response) => {
  const { tenantId, workerId } = req.params;
  const tenant = storage.getTenant(tenantId);

  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const worker = storage.getWorker(workerId);

  if (!worker || worker.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_WORKER_NOT_FOUND);
  }

  if (worker.status !== 'SUSPENDED') {
    return sendError(res, ERRORS.ERR_WORKER_NOT_SUSPENDED);
  }

  worker.status = 'ACTIVE';
  updateWorkerDerivedFields(worker);
  storage.saveWorker(worker);

  updateTenantDerivedFields(tenant);
  storage.saveTenant(tenant);

  return successResponse(res, worker);
});

router.post('/:workerId/deactivate', (req: Request, res: Response) => {
  const { tenantId, workerId } = req.params;
  const tenant = storage.getTenant(tenantId);

  if (!tenant) {
    return sendError(res, ERRORS.ERR_TENANT_NOT_FOUND);
  }

  const worker = storage.getWorker(workerId);

  if (!worker || worker.tenant_id !== tenantId) {
    return sendError(res, ERRORS.ERR_WORKER_NOT_FOUND);
  }

  if (worker.status === 'DEACTIVATED') {
    return sendError(res, ERRORS.ERR_INVALID_REQUEST, 'Worker is already deactivated');
  }

  worker.status = 'DEACTIVATED';

  const assignments = storage.getAssignmentsByWorker(workerId);
  for (const assignment of assignments) {
    if (!['COMPLETED', 'CANCELLED_BY_WORKER', 'CANCELLED_BY_SYSTEM', 'EXPIRED'].includes(assignment.status)) {
      assignment.status = 'CANCELLED_BY_SYSTEM';
      const { releaseAssignmentReservation } = require('../utils');
      releaseAssignmentReservation(assignment);
      storage.saveAssignment(assignment);
    }
  }

  const payouts = storage.getPayoutsByWorker(workerId);
  for (const payout of payouts) {
    if (['REQUESTED', 'APPROVED', 'HELD'].includes(payout.status)) {
      payout.status = 'CANCELLED';
      storage.savePayout(payout);
    }
  }

  storage.saveWorker(worker);

  updateTenantDerivedFields(tenant);
  storage.saveTenant(tenant);

  return successResponse(res, worker);
});

export default router;
