const express = require('express');
const router = express.Router({ mergeParams: true });
const db = require('../db/database');
const { authorize } = require('../middleware/auth');
const { createSuccessResponse, createErrorResponse, generateUUID, getTimestamp } = require('../utils/response');
const { serializeAssignment, serializeOverrideAuthorization } = require('../utils/serializers');
const {
  calculateProcedureDuration,
  calculateAssignmentMinutesForResource,
  calculateProvisionalCost,
  isAssignmentHighBiorisk
} = require('../utils/calculations');
const {
  incrementBudgetLedger,
  decrementBudgetLedger,
  incrementSafetyLedger,
  decrementSafetyLedger,
  updateBudgetLedger,
  updateSafetyLedger
} = require('../utils/ledger');
const CONSTANTS = require('../config/constants');

router.post('/', authorize('AttendingPhysician'), (req, res) => {
  const plan = db.prepare('SELECT * FROM treatment_plans WHERE id = ?').get(req.params.planId);

  if (!plan) {
    const error = createErrorResponse('ERR_PLAN_NOT_FOUND', 'Treatment plan not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (plan.status !== 'ACTIVE') {
    const error = createErrorResponse('ERR_PLAN_NOT_ACTIVE', 'Plan must be ACTIVE to create assignments', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const { procedure_id, resource_id, override_protocol_check } = req.body;

  if (override_protocol_check !== undefined && typeof override_protocol_check !== 'boolean') {
    const error = createErrorResponse('ERR_INVALID_REQUEST', 'override_protocol_check must be a boolean', 400);
    return res.status(error.statusCode).json(error.body);
  }

  const overrideCheck = override_protocol_check || false;

  const procedure = db.prepare('SELECT * FROM procedures WHERE id = ? AND plan_id = ?')
    .get(procedure_id, req.params.planId);

  if (!procedure) {
    const error = createErrorResponse('ERR_PROCEDURE_NOT_FOUND', 'Procedure not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (procedure.status !== 'PENDING') {
    const error = createErrorResponse('ERR_PROCEDURE_NOT_PENDING', 'Procedure must be PENDING', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const resource = db.prepare('SELECT * FROM medical_resources WHERE id = ? AND plan_id = ?')
    .get(resource_id, req.params.planId);

  if (!resource) {
    const error = createErrorResponse('ERR_RESOURCE_NOT_FOUND', 'Medical resource not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (procedure.required_certification !== 'NONE') {
    const certifications = db.prepare('SELECT * FROM resource_certifications WHERE resource_id = ?').all(resource_id);
    const now = new Date();
    const hasValidCert = certifications.some(cert =>
      cert.name === procedure.required_certification && new Date(cert.applied_date) <= now
    );

    if (!hasValidCert) {
      const error = createErrorResponse('ERR_CERTIFICATION_MISMATCH', 'Resource lacks required certification', 400);
      return res.status(error.statusCode).json(error.body);
    }
  }

  const committed = db.prepare(`
    SELECT * FROM assignments WHERE plan_id = ? AND status IN ('PENDING_SCHEDULE','PROTOCOL_APPROVED','SCHEDULED','COMPLETED')
  `).all(req.params.planId);
  const committedResourceIds = new Set(
    committed
      .filter(a => {
        const pr = db.prepare('SELECT rotation_id FROM procedures WHERE id = ?').get(a.procedure_id);
        return pr && pr.rotation_id === procedure.rotation_id;
      })
      .map(a => a.resource_id)
  );
  if (committedResourceIds.size > 0) {
    const pairings = db.prepare('SELECT * FROM infection_risk_pairings WHERE plan_id = ?').all(req.params.planId);
    const conflict = pairings.some(p =>
      (p.resource_id_1 === resource_id && committedResourceIds.has(p.resource_id_2)) ||
      (p.resource_id_2 === resource_id && committedResourceIds.has(p.resource_id_1))
    );
    if (conflict) {
      const error = createErrorResponse('ERR_INFECTION_RISK', 'Infection risk pairing constraint violated', 409);
      return res.status(error.statusCode).json(error.body);
    }
  }

  const allPairings = db.prepare('SELECT * FROM infection_risk_pairings WHERE plan_id = ?').all(req.params.planId);
  const relevantPairings = allPairings.filter(p =>
    (p.resource_id_1 === resource_id || p.resource_id_2 === resource_id) &&
    p.quarantine_until_minute !== null &&
    p.quarantine_until_minute !== undefined
  );

  for (const pairing of relevantPairings) {
    if (procedure.start_minute < pairing.quarantine_until_minute) {
      const error = createErrorResponse('ERR_PAIRING_QUARANTINE_ACTIVE', 'A resource pairing\'s quarantine period blocks this assignment', 409);
      return res.status(error.statusCode).json(error.body);
    }
  }

  const allActiveHolds = db.prepare(`
    SELECT * FROM resource_holds
    WHERE plan_id = ? AND resource_id = ? AND status = 'ACTIVE'
  `).all(req.params.planId, resource_id);

  const activeHolds = allActiveHolds.filter(hold =>
    hold.start_minute < procedure.end_minute && procedure.start_minute < hold.end_minute
  );

  if (activeHolds.length > 0) {
    const error = createErrorResponse('ERR_RESOURCE_ON_HOLD', 'The resource is unavailable due to an active hold overlapping the procedure window', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const allAssignments = db.prepare(`
    SELECT a.*, p.procedure_type, p.start_minute, p.end_minute
    FROM assignments a
    JOIN procedures p ON a.procedure_id = p.id
    WHERE a.plan_id = ? AND a.resource_id = ? AND a.status IN ('PENDING_SCHEDULE', 'PROTOCOL_APPROVED', 'SCHEDULED', 'COMPLETED')
  `).all(req.params.planId, resource_id);

  for (const assignment of allAssignments) {
    const sterilizationMinutes = procedure.procedure_type === assignment.procedure_type ? 0 : CONSTANTS.MANDATORY_STERILIZATION_MINUTES;

    if (procedure.start_minute < assignment.end_minute + sterilizationMinutes &&
        assignment.start_minute < procedure.end_minute + sterilizationMinutes) {
      
      const maintenanceInGap = db.prepare(`
        SELECT * FROM maintenance_events
        WHERE plan_id = ? AND resource_id = ?
        AND at_minute > ? AND at_minute <= ?
      `).all(req.params.planId, resource_id, assignment.end_minute, procedure.start_minute);

      if (maintenanceInGap.length === 0) {
        const error = createErrorResponse('ERR_STERILIZATION_TIME_VIOLATION', 'Resource scheduling conflict', 409);
        return res.status(error.statusCode).json(error.body);
      }
    }
  }

  const isBiorisk = isAssignmentHighBiorisk(null, procedure_id, resource_id, req.params.planId, null);
  const provisionalCost = calculateProvisionalCost(resource_id, procedure_id, null, req.params.planId, null);

  const safetyLedger = db.prepare('SELECT safety_score FROM safety_ledgers WHERE plan_id = ?').get(req.params.planId);
  let scoreAfterPenalty = safetyLedger.safety_score;

  if (isBiorisk) {
    scoreAfterPenalty += CONSTANTS.HIGH_BIORISK_PENALTY;
  }

  const safetyThresholdBreached = scoreAfterPenalty >= CONSTANTS.SAFETY_SCORE_THRESHOLD_LOCK;

  if (isBiorisk && safetyThresholdBreached && !overrideCheck) {
    const error = createErrorResponse('ERR_SAFETY_SCORE_THRESHOLD_BREACHED', 'Safety score threshold breached', 403);
    return res.status(error.statusCode).json(error.body);
  }

  const budgetLedger = db.prepare('SELECT provisional_debits, finalized_debits FROM budget_ledgers WHERE plan_id = ?')
    .get(req.params.planId);
  const costBalance = plan.total_budget - budgetLedger.provisional_debits - budgetLedger.finalized_debits;

  if (costBalance < provisionalCost) {
    const error = createErrorResponse('ERR_INSUFFICIENT_BUDGET', 'Insufficient budget for assignment', 402);
    return res.status(error.statusCode).json(error.body);
  }

  const id = generateUUID();
  const now = getTimestamp();
  const protocolOverridePenaltyApplied = overrideCheck && isBiorisk && safetyThresholdBreached;

  db.prepare(`
    INSERT INTO assignments (id, plan_id, procedure_id, resource_id, status, override_protocol_check,
      protocol_override_penalty_applied, is_high_biorisk, provisional_cost, created_at, updated_at, version)
    VALUES (?, ?, ?, ?, 'PENDING_SCHEDULE', ?, ?, ?, ?, ?, ?, 1)
  `).run(id, req.params.planId, procedure_id, resource_id, overrideCheck ? 1 : 0,
    protocolOverridePenaltyApplied ? 1 : 0, isBiorisk ? 1 : 0, provisionalCost, now, now);

  db.prepare('UPDATE procedures SET status = ?, updated_at = ?, version = version + 1 WHERE id = ?')
    .run('SCHEDULED', getTimestamp(), procedure_id);

  incrementBudgetLedger(req.params.planId, 'provisional_debits', provisionalCost);
  if (isBiorisk) {
    incrementSafetyLedger(req.params.planId, CONSTANTS.HIGH_BIORISK_PENALTY);
  }
  if (protocolOverridePenaltyApplied) {
    incrementSafetyLedger(req.params.planId, CONSTANTS.PROTOCOL_OVERRIDE_PENALTY);
  }
  updateBudgetLedger(req.params.planId, true);
  if (isBiorisk || protocolOverridePenaltyApplied) {
    updateSafetyLedger(req.params.planId, true);
  }

  const assignment = db.prepare('SELECT * FROM assignments WHERE id = ?').get(id);
  res.status(201).json(createSuccessResponse(serializeAssignment(assignment), 'object'));
});

router.get('/', (req, res) => {
  const plan = db.prepare('SELECT * FROM treatment_plans WHERE id = ?').get(req.params.planId);

  if (!plan) {
    const error = createErrorResponse('ERR_PLAN_NOT_FOUND', 'Treatment plan not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  const limit = Math.min(Math.max(parseInt(req.query.limit) || 10, 1), 100);
  const offset = Math.max(parseInt(req.query.offset) || 0, 0);

  const assignments = db.prepare('SELECT * FROM assignments WHERE plan_id = ? ORDER BY created_at ASC LIMIT ? OFFSET ?')
    .all(req.params.planId, limit, offset);
  const totalCount = db.prepare('SELECT COUNT(*) as count FROM assignments WHERE plan_id = ?').get(req.params.planId).count;

  const response = createSuccessResponse(
    assignments.map(serializeAssignment),
    'array',
    {
      limit,
      offset,
      total_count: totalCount,
      has_more: offset + limit < totalCount
    }
  );

  res.json(response);
});

router.get('/:assignmentId', (req, res) => {
  const assignment = db.prepare('SELECT * FROM assignments WHERE id = ? AND plan_id = ?')
    .get(req.params.assignmentId, req.params.planId);

  if (!assignment) {
    const error = createErrorResponse('ERR_ASSIGNMENT_NOT_FOUND', 'Assignment not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  res.json(createSuccessResponse(serializeAssignment(assignment), 'object'));
});

router.post('/:assignmentId/protocol-approve', authorize('ChargeNurse'), (req, res) => {
  const assignment = db.prepare('SELECT * FROM assignments WHERE id = ? AND plan_id = ?')
    .get(req.params.assignmentId, req.params.planId);

  if (!assignment) {
    const error = createErrorResponse('ERR_ASSIGNMENT_NOT_FOUND', 'Assignment not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (req.body.version !== undefined && req.body.version !== assignment.version) {
    const error = createErrorResponse('ERR_STALE_DATA', 'Version mismatch - data has been modified', 409);
    return res.status(error.statusCode).json(error.body);
  }

  if (assignment.status !== 'PENDING_SCHEDULE') {
    const error = createErrorResponse('ERR_ASSIGNMENT_NOT_PENDING_SCHEDULE', 'Assignment must be in PENDING_SCHEDULE state', 409);
    return res.status(error.statusCode).json(error.body);
  }

  db.prepare('UPDATE assignments SET status = ?, updated_at = ?, version = version + 1 WHERE id = ?')
    .run('PROTOCOL_APPROVED', getTimestamp(), req.params.assignmentId);

  const updatedAssignment = db.prepare('SELECT * FROM assignments WHERE id = ?').get(req.params.assignmentId);
  res.json(createSuccessResponse(serializeAssignment(updatedAssignment), 'object'));
});

router.post('/:assignmentId/schedule', authorize('ChargeNurse'), (req, res) => {
  const assignment = db.prepare('SELECT * FROM assignments WHERE id = ? AND plan_id = ?')
    .get(req.params.assignmentId, req.params.planId);

  if (!assignment) {
    const error = createErrorResponse('ERR_ASSIGNMENT_NOT_FOUND', 'Assignment not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (req.body.version !== undefined && req.body.version !== assignment.version) {
    const error = createErrorResponse('ERR_STALE_DATA', 'Version mismatch - data has been modified', 409);
    return res.status(error.statusCode).json(error.body);
  }

  if (assignment.status !== 'PROTOCOL_APPROVED') {
    const error = createErrorResponse('ERR_ASSIGNMENT_NOT_PROTOCOL_APPROVED', 'Assignment must be in PROTOCOL_APPROVED state', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const procedure = db.prepare('SELECT * FROM procedures WHERE id = ?').get(assignment.procedure_id);

  if (procedure.status !== 'SCHEDULED') {
    const error = createErrorResponse('ERR_PROCEDURE_NOT_SCHEDULED', 'Procedure must be in SCHEDULED state', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const rotationProcedures = db.prepare('SELECT id FROM procedures WHERE rotation_id = ?').all(procedure.rotation_id);
  const rotationProcedureIds = rotationProcedures.map(p => p.id);

  if (rotationProcedureIds.length > 0) {
    const committedAll = db.prepare(`
      SELECT * FROM assignments WHERE plan_id = ? AND status IN ('PENDING_SCHEDULE','PROTOCOL_APPROVED','SCHEDULED','COMPLETED') AND id != ?
    `).all(req.params.planId, assignment.id);
    const otherResourceIds = new Set(
      committedAll
        .filter(a => {
          const pr = db.prepare('SELECT rotation_id FROM procedures WHERE id = ?').get(a.procedure_id);
          return pr && pr.rotation_id === procedure.rotation_id;
        })
        .map(a => a.resource_id)
    );
    if (otherResourceIds.size > 0) {
      const pairings = db.prepare('SELECT * FROM infection_risk_pairings WHERE plan_id = ?').all(req.params.planId);
      const conflict = pairings.some(p =>
        (p.resource_id_1 === assignment.resource_id && otherResourceIds.has(p.resource_id_2)) ||
        (p.resource_id_2 === assignment.resource_id && otherResourceIds.has(p.resource_id_1))
      );
      if (conflict) {
        const error = createErrorResponse('ERR_INFECTION_RISK', 'Infection risk pairing constraint violated', 409);
        return res.status(error.statusCode).json(error.body);
      }
    }
  }

  const allPairingsSchedule = db.prepare('SELECT * FROM infection_risk_pairings WHERE plan_id = ?').all(req.params.planId);
  const relevantPairingsSchedule = allPairingsSchedule.filter(p =>
    (p.resource_id_1 === assignment.resource_id || p.resource_id_2 === assignment.resource_id) &&
    p.quarantine_until_minute !== null &&
    p.quarantine_until_minute !== undefined
  );

  for (const pairing of relevantPairingsSchedule) {
    if (procedure.start_minute < pairing.quarantine_until_minute) {
      const error = createErrorResponse('ERR_PAIRING_QUARANTINE_ACTIVE', 'A resource pairing\'s quarantine period blocks this assignment', 409);
      return res.status(error.statusCode).json(error.body);
    }
  }

  const allActiveHoldsSchedule = db.prepare(`
    SELECT * FROM resource_holds
    WHERE plan_id = ? AND resource_id = ? AND status = 'ACTIVE'
  `).all(req.params.planId, assignment.resource_id);

  const activeHoldsSchedule = allActiveHoldsSchedule.filter(hold =>
    hold.start_minute < procedure.end_minute && procedure.start_minute < hold.end_minute
  );

  if (activeHoldsSchedule.length > 0) {
    const error = createErrorResponse('ERR_RESOURCE_ON_HOLD', 'The resource is unavailable due to an active hold overlapping the procedure window', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const planForAuth = db.prepare('SELECT * FROM treatment_plans WHERE id = ?').get(req.params.planId);
  let requiresAuth = false;
  if (planForAuth.policies) {
    try {
      const policies = typeof planForAuth.policies === 'string' ? JSON.parse(planForAuth.policies) : planForAuth.policies;
      requiresAuth = policies.require_admin_auth_for_overrides === true;
    } catch (e) {
    }
  }

  if (requiresAuth && assignment.override_protocol_check && assignment.protocol_override_penalty_applied) {
    const authExists = db.prepare('SELECT * FROM override_authorizations WHERE assignment_id = ?').get(assignment.id);
    if (!authExists) {
      const error = createErrorResponse('ERR_OVERRIDE_NOT_AUTHORIZED', 'Administrative authorization is required before this risky override can be scheduled', 409);
      return res.status(error.statusCode).json(error.body);
    }
  }

  const newCost = calculateProvisionalCost(
    assignment.resource_id, 
    assignment.procedure_id, 
    null, 
    assignment.plan_id, 
    assignment.id
  );
  const costDifference = newCost - assignment.provisional_cost;
  const isBioriskNow = isAssignmentHighBiorisk(
    null, 
    assignment.procedure_id, 
    assignment.resource_id, 
    assignment.plan_id, 
    assignment.id
  );
  const wasBiorisk = Boolean(assignment.is_high_biorisk);

  const plan = db.prepare('SELECT total_budget FROM treatment_plans WHERE id = ?').get(req.params.planId);
  const budgetLedger = db.prepare('SELECT provisional_debits, finalized_debits FROM budget_ledgers WHERE plan_id = ?')
    .get(req.params.planId);
  const availableBalance = plan.total_budget - budgetLedger.provisional_debits - budgetLedger.finalized_debits;

  if (availableBalance < costDifference) {
    const error = createErrorResponse('ERR_INSUFFICIENT_BUDGET', 'Insufficient budget for cost increase', 402);
    return res.status(error.statusCode).json(error.body);
  }

  const updateResult = db.prepare(
    'UPDATE assignments SET status = ?, provisional_cost = ?, is_high_biorisk = ?, updated_at = ?, version = version + 1 WHERE id = ? AND status = ?'
  ).run('SCHEDULED', newCost, isBioriskNow ? 1 : 0, getTimestamp(), req.params.assignmentId, 'PROTOCOL_APPROVED');

  if (updateResult.changes === 0) {
    const error = createErrorResponse('ERR_ASSIGNMENT_NOT_PROTOCOL_APPROVED', 'Assignment must be in PROTOCOL_APPROVED state', 409);
    return res.status(error.statusCode).json(error.body);
  }

  db.prepare('UPDATE procedures SET status = ?, updated_at = ?, version = version + 1 WHERE id = ?')
    .run('ASSIGNED', getTimestamp(), assignment.procedure_id);

  if (costDifference >= 0) {
    incrementBudgetLedger(req.params.planId, 'provisional_debits', costDifference);
  } else {
    decrementBudgetLedger(req.params.planId, 'provisional_debits', Math.abs(costDifference));
  }
  if (isBioriskNow && !wasBiorisk) {
    incrementSafetyLedger(req.params.planId, CONSTANTS.HIGH_BIORISK_PENALTY);
  } else if (!isBioriskNow && wasBiorisk) {
    decrementSafetyLedger(req.params.planId, CONSTANTS.HIGH_BIORISK_PENALTY);
  }
  const budgetChanged = costDifference !== 0;
  const safetyChanged = (isBioriskNow && !wasBiorisk) || (!isBioriskNow && wasBiorisk);
  if (budgetChanged) updateBudgetLedger(req.params.planId, true);
  if (safetyChanged) updateSafetyLedger(req.params.planId, true);

  const updatedAssignment = db.prepare('SELECT * FROM assignments WHERE id = ?').get(req.params.assignmentId);
  res.json(createSuccessResponse(serializeAssignment(updatedAssignment), 'object'));
});

router.post('/:assignmentId/reject', authorize('ChargeNurse'), (req, res) => {
  const assignment = db.prepare('SELECT * FROM assignments WHERE id = ? AND plan_id = ?')
    .get(req.params.assignmentId, req.params.planId);

  if (!assignment) {
    const error = createErrorResponse('ERR_ASSIGNMENT_NOT_FOUND', 'Assignment not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (req.body.version !== undefined && req.body.version !== assignment.version) {
    const error = createErrorResponse('ERR_STALE_DATA', 'Version mismatch - data has been modified', 409);
    return res.status(error.statusCode).json(error.body);
  }

  if (assignment.status !== 'PENDING_SCHEDULE') {
    const error = createErrorResponse('ERR_ASSIGNMENT_NOT_PENDING_SCHEDULE', 'Assignment must be in PENDING_SCHEDULE state', 409);
    return res.status(error.statusCode).json(error.body);
  }

  db.prepare('UPDATE assignments SET status = ?, updated_at = ?, version = version + 1 WHERE id = ?')
    .run('REJECTED', getTimestamp(), req.params.assignmentId);

  db.prepare('UPDATE procedures SET status = ?, updated_at = ?, version = version + 1 WHERE id = ?')
    .run('PENDING', getTimestamp(), assignment.procedure_id);

  decrementBudgetLedger(req.params.planId, 'provisional_debits', assignment.provisional_cost);
  let safetyAdjusted = false;
  if (assignment.is_high_biorisk) {
    decrementSafetyLedger(req.params.planId, CONSTANTS.HIGH_BIORISK_PENALTY);
    safetyAdjusted = true;
  }
  if (assignment.protocol_override_penalty_applied) {
    decrementSafetyLedger(req.params.planId, CONSTANTS.PROTOCOL_OVERRIDE_PENALTY);
    safetyAdjusted = true;
  }
  updateBudgetLedger(req.params.planId, true);
  if (safetyAdjusted) updateSafetyLedger(req.params.planId, true);

  const updatedAssignment = db.prepare('SELECT * FROM assignments WHERE id = ?').get(req.params.assignmentId);
  res.json(createSuccessResponse(serializeAssignment(updatedAssignment), 'object'));
});

router.post('/:assignmentId/cancel', authorize('ChargeNurse'), (req, res) => {
  const assignment = db.prepare('SELECT * FROM assignments WHERE id = ? AND plan_id = ?')
    .get(req.params.assignmentId, req.params.planId);

  if (!assignment) {
    const error = createErrorResponse('ERR_ASSIGNMENT_NOT_FOUND', 'Assignment not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (req.body.version !== undefined && req.body.version !== assignment.version) {
    const error = createErrorResponse('ERR_STALE_DATA', 'Version mismatch - data has been modified', 409);
    return res.status(error.statusCode).json(error.body);
  }

  if (!['PENDING_SCHEDULE', 'PROTOCOL_APPROVED', 'SCHEDULED'].includes(assignment.status)) {
    const error = createErrorResponse('ERR_ASSIGNMENT_NOT_CANCELLABLE', 'Assignment cannot be cancelled in current state', 409);
    return res.status(error.statusCode).json(error.body);
  }

  db.prepare('UPDATE assignments SET status = ?, updated_at = ?, version = version + 1 WHERE id = ?')
    .run('CANCELLED', getTimestamp(), req.params.assignmentId);

  decrementBudgetLedger(req.params.planId, 'provisional_debits', assignment.provisional_cost);
  let safetyAdjustedCancel = false;
  if (assignment.is_high_biorisk) {
    decrementSafetyLedger(req.params.planId, CONSTANTS.HIGH_BIORISK_PENALTY);
    safetyAdjustedCancel = true;
  }
  if (assignment.protocol_override_penalty_applied) {
    decrementSafetyLedger(req.params.planId, CONSTANTS.PROTOCOL_OVERRIDE_PENALTY);
    safetyAdjustedCancel = true;
  }
  updateBudgetLedger(req.params.planId, true);
  if (safetyAdjustedCancel) updateSafetyLedger(req.params.planId, true);

  db.prepare('UPDATE procedures SET status = ?, updated_at = ?, version = version + 1 WHERE id = ?')
    .run('PENDING', getTimestamp(), assignment.procedure_id);

  const procedure = db.prepare('SELECT rotation_id FROM procedures WHERE id = ?').get(assignment.procedure_id);
  const rotation = db.prepare('SELECT * FROM ward_rotations WHERE id = ?').get(procedure.rotation_id);

  if (rotation.status === 'READY_FOR_ASSIGNMENT') {
    db.prepare('UPDATE ward_rotations SET status = ?, updated_at = ?, version = version + 1 WHERE id = ?')
      .run('PLANNING', getTimestamp(), rotation.id);
  }

  const updatedAssignment = db.prepare('SELECT * FROM assignments WHERE id = ?').get(req.params.assignmentId);
  res.json(createSuccessResponse(serializeAssignment(updatedAssignment), 'object'));
});

router.post('/:assignmentId/override-authorize', authorize('HospitalAdministrator'), (req, res) => {
  const assignment = db.prepare('SELECT * FROM assignments WHERE id = ? AND plan_id = ?')
    .get(req.params.assignmentId, req.params.planId);

  if (!assignment) {
    const error = createErrorResponse('ERR_ASSIGNMENT_NOT_FOUND', 'Assignment not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (!['PENDING_SCHEDULE', 'PROTOCOL_APPROVED'].includes(assignment.status)) {
    const error = createErrorResponse('ERR_ASSIGNMENT_NOT_PENDING_OR_APPROVED', 'Authorization can only be granted for assignments in PENDING_SCHEDULE or PROTOCOL_APPROVED status', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const plan = db.prepare('SELECT * FROM treatment_plans WHERE id = ?').get(req.params.planId);
  let requiresAuth = false;
  if (plan.policies) {
    try {
      const policies = typeof plan.policies === 'string' ? JSON.parse(plan.policies) : plan.policies;
      requiresAuth = policies.require_admin_auth_for_overrides === true;
    } catch (e) {
    }
  }

  const isRiskyOverride = assignment.override_protocol_check && assignment.protocol_override_penalty_applied;

  if (!requiresAuth || !isRiskyOverride) {
    const error = createErrorResponse('ERR_OVERRIDE_NOT_REQUIRED', 'Authorization cannot be granted (either feature not enabled, or override not risky, or already authorized)', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const existingAuth = db.prepare('SELECT * FROM override_authorizations WHERE assignment_id = ?').get(assignment.id);
  if (existingAuth) {
    const error = createErrorResponse('ERR_OVERRIDE_ALREADY_AUTHORIZED', 'An authorization already exists for this assignment', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const id = generateUUID();
  const now = getTimestamp();
  const authorizedBy = req.user.userId;

  db.prepare(`
    INSERT INTO override_authorizations (id, plan_id, assignment_id, authorized_by_user_id, created_at)
    VALUES (?, ?, ?, ?, ?)
  `).run(id, req.params.planId, assignment.id, authorizedBy, now);

  const auth = db.prepare('SELECT * FROM override_authorizations WHERE id = ?').get(id);
  res.status(201).json(createSuccessResponse(serializeOverrideAuthorization(auth), 'object'));
});

module.exports = router;
