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
  isAssignmentHighBiorisk,
  calculateCumulativeUsageAtMinute,
  getMaintenanceThreshold
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

function priorUsageSinceMaintenance(planId, resourceId, cutoffMinute) {
  const maintRows = db.prepare('SELECT at_minute FROM maintenance_events WHERE plan_id = ? AND resource_id = ? ORDER BY at_minute DESC').all(planId, resourceId);
  const baseline = (maintRows.find(m => m.at_minute <= cutoffMinute) || { at_minute: 0 }).at_minute || 0;

  const primaries = db.prepare(`
    SELECT id, procedure_id FROM assignments
    WHERE plan_id = ? AND resource_id = ? AND status IN ('PENDING_SCHEDULE','PROTOCOL_APPROVED','SCHEDULED','COMPLETED')
  `).all(planId, resourceId);

  const potentialSecondaries = db.prepare(`
    SELECT id, procedure_id, secondary_resource_ids FROM assignments
    WHERE plan_id = ? AND status IN ('PENDING_SCHEDULE','PROTOCOL_APPROVED','SCHEDULED','COMPLETED')
  `).all(planId);
  const secondaries = potentialSecondaries.filter(a => {
    if (!a.secondary_resource_ids) return false;
    try {
      const arr = typeof a.secondary_resource_ids === 'string' ? JSON.parse(a.secondary_resource_ids) : a.secondary_resource_ids;
      return Array.isArray(arr) && arr.includes(resourceId);
    } catch {
      return false;
    }
  }).map(a => ({ id: a.id, procedure_id: a.procedure_id }));

  const involved = [...primaries, ...secondaries]
    .map(a => {
      const p = db.prepare('SELECT start_minute, end_minute FROM procedures WHERE id = ?').get(a.procedure_id);
      if (!p) return null;
      return { start_minute: p.start_minute, end_minute: p.end_minute };
    })
    .filter(Boolean)
    .filter(a => a.start_minute < cutoffMinute)
    .sort((a, b) => a.start_minute - b.start_minute);

  let total = 0;
  for (const a of involved) {
    const segStart = Math.max(a.start_minute, baseline);
    const segEnd = Math.min(a.end_minute, cutoffMinute);
    if (segEnd > segStart) total += (segEnd - segStart);
  }
  return total;
}

function checkAndCompleteDecommissioning(planId, resourceId) {
  const resource = db.prepare('SELECT * FROM medical_resources WHERE id = ? AND plan_id = ?').get(resourceId, planId);
  
  if (!resource || resource.status !== 'DECOMMISSIONING_PENDING') {
    return;
  }
  
  const remainingAssignments = db.prepare(`
    SELECT id, resource_id, secondary_resource_ids FROM assignments
    WHERE plan_id = ? AND status IN ('PENDING_SCHEDULE', 'PROTOCOL_APPROVED', 'SCHEDULED')
  `).all(planId);
  
  const resourceCommitments = remainingAssignments.filter(a => {
    if (a.resource_id === resourceId) return true;
    if (a.secondary_resource_ids) {
      try {
        const secondaries = typeof a.secondary_resource_ids === 'string' 
          ? JSON.parse(a.secondary_resource_ids) 
          : a.secondary_resource_ids;
        return secondaries.includes(resourceId);
      } catch (e) {
        return false;
      }
    }
    return false;
  });
  const count = resourceCommitments.length;
  
  if (count === 0) {
    db.prepare('UPDATE medical_resources SET status = ?, updated_at = ?, version = version + 1 WHERE id = ?')
      .run('DECOMMISSIONED', getTimestamp(), resourceId);
  }
}

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

  const { procedure_id, resource_id, override_protocol_check, secondary_resource_ids } = req.body;

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

  let secondaryRequirements = [];
  if (procedure.secondary_resource_requirements) {
    try {
      secondaryRequirements = typeof procedure.secondary_resource_requirements === 'string' 
        ? JSON.parse(procedure.secondary_resource_requirements) 
        : procedure.secondary_resource_requirements;
    } catch (e) { secondaryRequirements = []; }
  }

  const providedSecondaryIds = secondary_resource_ids || [];
  

  if (secondaryRequirements.length !== providedSecondaryIds.length) {
    const error = createErrorResponse('ERR_INVALID_REQUEST', 'Mismatch between required and provided secondary resources', 400);
    return res.status(error.statusCode).json(error.body);
  }

  const allResourceIds = [resource_id, ...providedSecondaryIds];
  if (new Set(allResourceIds).size !== allResourceIds.length) {
    const error = createErrorResponse('ERR_INVALID_REQUEST', 'All resource IDs must be unique within a proposal', 400);
    return res.status(error.statusCode).json(error.body);
  }

  const resource = db.prepare('SELECT * FROM medical_resources WHERE id = ? AND plan_id = ?')
    .get(resource_id, req.params.planId);

  if (!resource) {
    const error = createErrorResponse('ERR_RESOURCE_NOT_FOUND', 'Medical resource not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (['DECOMMISSIONED', 'DECOMMISSIONING_PENDING'].includes(resource.status)) {
    const error = createErrorResponse('ERR_RESOURCE_DECOMMISSIONED', 'Resource is decommissioned or pending decommissioning', 409);
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

  const secondaryResources = [];
  for (let i = 0; i < providedSecondaryIds.length; i++) {
    const secondaryId = providedSecondaryIds[i];
    const secondaryResource = db.prepare('SELECT * FROM medical_resources WHERE id = ? AND plan_id = ?')
      .get(secondaryId, req.params.planId);

    if (!secondaryResource) {
      const error = createErrorResponse('ERR_RESOURCE_NOT_FOUND', `Secondary resource ${secondaryId} not found`, 404);
      return res.status(error.statusCode).json(error.body);
    }

    if (secondaryResource.status !== 'AVAILABLE') {
      const error = createErrorResponse('ERR_RESOURCE_DECOMMISSIONED', `Secondary resource ${secondaryId} is not available`, 409);
      return res.status(error.statusCode).json(error.body);
    }

    const requiredCert = secondaryRequirements[i];
    if (requiredCert && requiredCert !== 'NONE') {
      const certifications = db.prepare('SELECT * FROM resource_certifications WHERE resource_id = ?').all(secondaryId);
      const now = new Date();
      const hasValidCert = certifications.some(cert =>
        cert.name === requiredCert && new Date(cert.applied_date) <= now
      );

      if (!hasValidCert) {
        const error = createErrorResponse('ERR_CERTIFICATION_MISMATCH', `Secondary resource ${secondaryId} lacks required certification ${requiredCert}`, 400);
        return res.status(error.statusCode).json(error.body);
      }
    }
    secondaryResources.push(secondaryResource);
  }

  const allResources = [{ id: resource_id, ...resource }, ...secondaryResources.map(r => ({ id: r.id, ...r }))];


  for (const rsc of allResources) {
    const rscId = rsc.id;
    
    const setup = rsc.setup_overhead_minutes || 0;
    const teardown = rsc.teardown_overhead_minutes || 0;
    const occupancyStart = procedure.start_minute - setup;
    const occupancyEnd = procedure.end_minute + teardown;

    
    const committed = db.prepare(`
      SELECT * FROM assignments WHERE plan_id = ? AND status IN ('PENDING_SCHEDULE','PROTOCOL_APPROVED','SCHEDULED','COMPLETED')
    `).all(req.params.planId);
    
    const committedResourceIds = new Set();
    for (const a of committed) {
      const pr = db.prepare('SELECT rotation_id FROM procedures WHERE id = ?').get(a.procedure_id);
      if (pr && pr.rotation_id === procedure.rotation_id) {
        committedResourceIds.add(a.resource_id);
        if (a.secondary_resource_ids) {
          try {
            const secondaries = typeof a.secondary_resource_ids === 'string' 
              ? JSON.parse(a.secondary_resource_ids) 
              : a.secondary_resource_ids;
            secondaries.forEach(sid => committedResourceIds.add(sid));
          } catch (e) {}
        }
      }
    }
    
    if (committedResourceIds.size > 0) {
      const pairings = db.prepare('SELECT * FROM infection_risk_pairings WHERE plan_id = ?').all(req.params.planId);
      const conflict = pairings.some(p =>
        (p.resource_id_1 === rscId && committedResourceIds.has(p.resource_id_2)) ||
        (p.resource_id_2 === rscId && committedResourceIds.has(p.resource_id_1))
      );
      if (conflict) {
        const error = createErrorResponse('ERR_INFECTION_RISK', 'Infection risk pairing constraint violated', 409);
        return res.status(error.statusCode).json(error.body);
      }
    }

    const allPairings = db.prepare('SELECT * FROM infection_risk_pairings WHERE plan_id = ?').all(req.params.planId);
    const relevantPairings = allPairings.filter(p =>
      (p.resource_id_1 === rscId || p.resource_id_2 === rscId) &&
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
    `).all(req.params.planId, rscId);

    const activeHolds = allActiveHolds.filter(hold =>
      hold.start_minute < occupancyEnd && occupancyStart < hold.end_minute
    );

    if (activeHolds.length > 0) {
      const error = createErrorResponse('ERR_RESOURCE_ON_HOLD', 'The resource is unavailable due to an active hold overlapping the procedure window', 409);
      return res.status(error.statusCode).json(error.body);
    }

    const allAssignments = db.prepare(`
      SELECT a.*, p.procedure_type, p.start_minute, p.end_minute
      FROM assignments a
      JOIN procedures p ON a.procedure_id = p.id
      WHERE a.plan_id = ? AND a.status IN ('PENDING_SCHEDULE', 'PROTOCOL_APPROVED', 'SCHEDULED', 'COMPLETED')
    `).all(req.params.planId);
    
    const resourceAssignments = allAssignments.filter(a => {
      if (a.resource_id === rscId) return true;
      if (a.secondary_resource_ids) {
        try {
          const secondaries = typeof a.secondary_resource_ids === 'string' 
            ? JSON.parse(a.secondary_resource_ids) 
            : a.secondary_resource_ids;
          return secondaries.includes(rscId);
        } catch (e) {
          return false;
        }
      }
      return false;
    });

    for (const assignment of resourceAssignments) {
      const assignmentSetup = rsc.setup_overhead_minutes || 0;
      const assignmentTeardown = rsc.teardown_overhead_minutes || 0;
      const assignmentOccupancyStart = assignment.start_minute - assignmentSetup;
      const assignmentOccupancyEnd = assignment.end_minute + assignmentTeardown;

      const baseBuffer = (rsc.sterilization_buffer_override !== null && rsc.sterilization_buffer_override !== undefined)
        ? rsc.sterilization_buffer_override
        : CONSTANTS.MANDATORY_STERILIZATION_MINUTES;
      const sterilizationMinutes = procedure.procedure_type === assignment.procedure_type ? 0 : baseBuffer;

      if (occupancyStart < assignmentOccupancyEnd + sterilizationMinutes &&
          assignmentOccupancyStart < occupancyEnd + sterilizationMinutes) {
        
        const earlierEnd = Math.min(occupancyEnd, assignmentOccupancyEnd);
        const laterStart = Math.max(occupancyStart, assignmentOccupancyStart);
        
        let maintenanceCheckStart, maintenanceCheckEnd;
        if (occupancyStart < assignmentOccupancyStart) {
          maintenanceCheckStart = occupancyEnd;
          maintenanceCheckEnd = assignmentOccupancyStart;
        } else {
          maintenanceCheckStart = assignmentOccupancyEnd;
          maintenanceCheckEnd = occupancyStart;
        }
        
        const maintenanceInGap = db.prepare(`
          SELECT * FROM maintenance_events
          WHERE plan_id = ? AND resource_id = ?
          AND at_minute > ? AND at_minute <= ?
        `).all(req.params.planId, rscId, maintenanceCheckStart, maintenanceCheckEnd);

        if (maintenanceInGap.length === 0) {
          const error = createErrorResponse('ERR_STERILIZATION_TIME_VIOLATION', 'Resource scheduling conflict', 409);
          return res.status(error.statusCode).json(error.body);
        }
      }
    }
  }


  let totalProvisionalCost = 0;
  let totalBioriskPenalty = 0;
  let anyResourceCrossesThreshold = false;
  const crossingResourceIds = [];

  const resourceIdsForCalc = [resource_id, ...providedSecondaryIds];
  const procStart = procedure.start_minute;
  const procEnd = procedure.end_minute;
  const procDuration = procEnd - procStart;
  const debugPerResource = [];
  for (const rscId of resourceIdsForCalc) {
    const cost = calculateProvisionalCost(rscId, procedure_id, null, req.params.planId, null);
    totalProvisionalCost += cost;

    const threshold = getMaintenanceThreshold(rscId);
    const cumAtStart = calculateCumulativeUsageAtMinute(req.params.planId, rscId, procStart, null, null);
    const crosses = (cumAtStart >= threshold) || (cumAtStart + procDuration > threshold);
    debugPerResource.push({ resource_id: rscId, cum_at_start: cumAtStart, threshold, duration: procDuration, crosses });
    if (crosses) {
      totalBioriskPenalty += CONSTANTS.HIGH_BIORISK_PENALTY;
      anyResourceCrossesThreshold = true;
      crossingResourceIds.push(rscId);
    }
  }

  const safetyLedger = db.prepare('SELECT safety_score FROM safety_ledgers WHERE plan_id = ?').get(req.params.planId);
  const scoreAfterBioriskPenalty = safetyLedger.safety_score + totalBioriskPenalty;
  const safetyThresholdBreached = scoreAfterBioriskPenalty >= CONSTANTS.SAFETY_SCORE_THRESHOLD_LOCK;

  if (anyResourceCrossesThreshold && safetyThresholdBreached && !overrideCheck) {
    const error = createErrorResponse('ERR_SAFETY_SCORE_THRESHOLD_BREACHED', 'Safety score threshold breached', 403);
    return res.status(error.statusCode).json(error.body);
  }

  const budgetLedger = db.prepare('SELECT provisional_debits, finalized_debits FROM budget_ledgers WHERE plan_id = ?').get(req.params.planId);
  const availableBalance = plan.total_budget - budgetLedger.provisional_debits - budgetLedger.finalized_debits;
  
  if (availableBalance < totalProvisionalCost) {
    const error = createErrorResponse('ERR_INSUFFICIENT_BUDGET', 'Insufficient budget for assignment', 402);
    return res.status(error.statusCode).json(error.body);
  }

  const id = generateUUID();
  const now = getTimestamp();
  const protocolOverridePenaltyApplied = overrideCheck && anyResourceCrossesThreshold && safetyThresholdBreached;
  const secondaryIdsJson = providedSecondaryIds.length > 0 ? JSON.stringify(providedSecondaryIds) : null;
  const crossingIdsJson = crossingResourceIds.length > 0 ? JSON.stringify(crossingResourceIds) : null;
  const bioriskDebugJson = JSON.stringify(debugPerResource);
  const proposalBioriskResourceCount = crossingResourceIds.length;

  
  db.prepare(`
    INSERT INTO assignments (id, plan_id, procedure_id, resource_id, secondary_resource_ids, status, override_protocol_check,
      protocol_override_penalty_applied, is_high_biorisk, proposal_biorisk_resource_count, provisional_cost, biorisk_crossing_resource_ids, biorisk_debug, created_at, updated_at, version)
    VALUES (?, ?, ?, ?, ?, 'PENDING_SCHEDULE', ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
  `).run(id, req.params.planId, procedure_id, resource_id, secondaryIdsJson, overrideCheck ? 1 : 0,
    protocolOverridePenaltyApplied ? 1 : 0, anyResourceCrossesThreshold ? 1 : 0, proposalBioriskResourceCount, totalProvisionalCost, crossingIdsJson, bioriskDebugJson, now, now);

  db.prepare('UPDATE procedures SET status = ?, updated_at = ?, version = version + 1 WHERE id = ?')
    .run('SCHEDULED', getTimestamp(), procedure_id);

  incrementBudgetLedger(req.params.planId, 'provisional_debits', totalProvisionalCost);
  updateBudgetLedger(req.params.planId, true);

  if (totalBioriskPenalty > 0) {
    incrementSafetyLedger(req.params.planId, totalBioriskPenalty);
  }
  if (protocolOverridePenaltyApplied) {
    incrementSafetyLedger(req.params.planId, CONSTANTS.PROTOCOL_OVERRIDE_PENALTY);
  }
  if (totalBioriskPenalty > 0 || protocolOverridePenaltyApplied) {
    updateSafetyLedger(req.params.planId, true);
  }

  const assignment = db.prepare('SELECT * FROM assignments WHERE id = ?').get(id);
  res.status(201).json(createSuccessResponse(serializeAssignment(assignment), 'object'));
});

router.post('/:assignmentId/reallocate', authorize('ChargeNurse'), (req, res) => {
  const plan = db.prepare('SELECT * FROM treatment_plans WHERE id = ?').get(req.params.planId);
  if (!plan) {
    const error = createErrorResponse('ERR_PLAN_NOT_FOUND', 'Treatment plan not found', 404);
    return res.status(error.statusCode).json(error.body);
  }
  if (plan.status !== 'ACTIVE') {
    const error = createErrorResponse('ERR_PLAN_NOT_ACTIVE', 'Plan must be ACTIVE to reallocate assignments', 409);
    return res.status(error.statusCode).json(error.body);
  }

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

  if (!['PENDING_SCHEDULE', 'PROTOCOL_APPROVED'].includes(assignment.status)) {
    const error = createErrorResponse('ERR_ASSIGNMENT_NOT_REALLOCATABLE', 'Assignment is not in a reallocatable state', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const { new_resource_id } = req.body;
  
  if (req.body.secondary_resource_ids !== undefined) {
    const error = createErrorResponse('ERR_INVALID_REQUEST', 'Secondary resources cannot be changed via reallocation', 400);
    return res.status(error.statusCode).json(error.body);
  }
  
  let existingSecondaryIds = [];
  if (assignment.secondary_resource_ids) {
    try {
      existingSecondaryIds = typeof assignment.secondary_resource_ids === 'string' 
        ? JSON.parse(assignment.secondary_resource_ids) 
        : assignment.secondary_resource_ids;
    } catch (e) { existingSecondaryIds = []; }
  }
  
  if (new_resource_id === assignment.resource_id) {
    const error = createErrorResponse('ERR_INVALID_REQUEST', 'Cannot reallocate assignment to the same resource', 400);
    return res.status(error.statusCode).json(error.body);
  }
  
  if (existingSecondaryIds.includes(new_resource_id)) {
    const error = createErrorResponse('ERR_INVALID_REQUEST', 'New primary resource cannot be identical to existing secondary resources', 400);
    return res.status(error.statusCode).json(error.body);
  }
  
  const procedure = db.prepare('SELECT * FROM procedures WHERE id = ?').get(assignment.procedure_id);
  if (!procedure) {
    const error = createErrorResponse('ERR_PROCEDURE_NOT_FOUND', 'Procedure not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  const newResource = db.prepare('SELECT * FROM medical_resources WHERE id = ? AND plan_id = ?')
    .get(new_resource_id, req.params.planId);
  if (!newResource) {
    const error = createErrorResponse('ERR_RESOURCE_NOT_FOUND', 'Medical resource not found', 404);
    return res.status(error.statusCode).json(error.body);
  }
  if (['DECOMMISSIONED', 'DECOMMISSIONING_PENDING'].includes(newResource.status)) {
    const error = createErrorResponse('ERR_RESOURCE_DECOMMISSIONED', 'Resource is decommissioned or pending decommissioning', 409);
    return res.status(error.statusCode).json(error.body);
  }

  if (procedure.required_certification !== 'NONE') {
    const certifications = db.prepare('SELECT * FROM resource_certifications WHERE resource_id = ?').all(new_resource_id);
    const now = new Date();
    const hasValidCert = certifications.some(cert =>
      cert.name === procedure.required_certification && new Date(cert.applied_date) <= now
    );
    if (!hasValidCert) {
      const error = createErrorResponse('ERR_CERTIFICATION_MISMATCH', 'Resource lacks required certification', 400);
      return res.status(error.statusCode).json(error.body);
    }
  }

  const committedAll = db.prepare(`
    SELECT * FROM assignments WHERE plan_id = ? AND status IN ('PENDING_SCHEDULE','PROTOCOL_APPROVED','SCHEDULED','COMPLETED') AND id != ?
  `).all(req.params.planId, assignment.id);
  const committedResourceIds = new Set();
  for (const a of committedAll) {
    const pr = db.prepare('SELECT rotation_id FROM procedures WHERE id = ?').get(a.procedure_id);
    if (pr && pr.rotation_id === procedure.rotation_id) {
      committedResourceIds.add(a.resource_id);
      if (a.secondary_resource_ids) {
        try {
          const secondaries = typeof a.secondary_resource_ids === 'string' 
            ? JSON.parse(a.secondary_resource_ids) 
            : a.secondary_resource_ids;
          secondaries.forEach(sid => committedResourceIds.add(sid));
        } catch (e) {}
      }
    }
  }
  if (committedResourceIds.size > 0) {
    const pairings = db.prepare('SELECT * FROM infection_risk_pairings WHERE plan_id = ?').all(req.params.planId);
    const conflict = pairings.some(p =>
      (p.resource_id_1 === new_resource_id && committedResourceIds.has(p.resource_id_2)) ||
      (p.resource_id_2 === new_resource_id && committedResourceIds.has(p.resource_id_1))
    );
    if (conflict) {
      const error = createErrorResponse('ERR_INFECTION_RISK', 'Infection risk pairing constraint violated', 409);
      return res.status(error.statusCode).json(error.body);
    }
  }

  const allPairings = db.prepare('SELECT * FROM infection_risk_pairings WHERE plan_id = ?').all(req.params.planId);
  const relevantPairings = allPairings.filter(p =>
    (p.resource_id_1 === new_resource_id || p.resource_id_2 === new_resource_id) &&
    p.quarantine_until_minute !== null &&
    p.quarantine_until_minute !== undefined
  );
  for (const pairing of relevantPairings) {
    if (procedure.start_minute < pairing.quarantine_until_minute) {
      const error = createErrorResponse('ERR_PAIRING_QUARANTINE_ACTIVE', 'A resource pairing\'s quarantine period blocks this assignment', 409);
      return res.status(error.statusCode).json(error.body);
    }
  }

  const newSetup = newResource.setup_overhead_minutes || 0;
  const newTeardown = newResource.teardown_overhead_minutes || 0;
  const newOccupancyStart = procedure.start_minute - newSetup;
  const newOccupancyEnd = procedure.end_minute + newTeardown;
  
  const allActiveHolds = db.prepare(`
    SELECT * FROM resource_holds
    WHERE plan_id = ? AND resource_id = ? AND status = 'ACTIVE'
  `).all(req.params.planId, new_resource_id);
  const activeHolds = allActiveHolds.filter(hold =>
    hold.start_minute < newOccupancyEnd && newOccupancyStart < hold.end_minute
  );
  if (activeHolds.length > 0) {
    const error = createErrorResponse('ERR_RESOURCE_ON_HOLD', 'The resource is unavailable due to an active hold overlapping the procedure window', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const allAssignmentsOnNew = db.prepare(`
    SELECT a.*, p.procedure_type, p.start_minute, p.end_minute
    FROM assignments a
    JOIN procedures p ON a.procedure_id = p.id
    WHERE a.plan_id = ? AND a.status IN ('PENDING_SCHEDULE', 'PROTOCOL_APPROVED', 'SCHEDULED', 'COMPLETED')
  `).all(req.params.planId);
  
  const resourceAssignments = allAssignmentsOnNew.filter(a => {
    if (a.resource_id === new_resource_id) return true;
    if (a.secondary_resource_ids) {
      try {
        const secondaries = typeof a.secondary_resource_ids === 'string' 
          ? JSON.parse(a.secondary_resource_ids) 
          : a.secondary_resource_ids;
        return secondaries.includes(new_resource_id);
      } catch (e) {
        return false;
      }
    }
    return false;
  });
  
  for (const other of resourceAssignments) {
    const otherSetup = newResource.setup_overhead_minutes || 0;
    const otherTeardown = newResource.teardown_overhead_minutes || 0;
    const otherOccupancyStart = other.start_minute - otherSetup;
    const otherOccupancyEnd = other.end_minute + otherTeardown;
    
    const baseBuffer = (newResource.sterilization_buffer_override !== null && newResource.sterilization_buffer_override !== undefined)
      ? newResource.sterilization_buffer_override
      : CONSTANTS.MANDATORY_STERILIZATION_MINUTES;
    const sterilizationMinutes = procedure.procedure_type === other.procedure_type ? 0 : baseBuffer;

    if (newOccupancyStart < otherOccupancyEnd + sterilizationMinutes &&
        otherOccupancyStart < newOccupancyEnd + sterilizationMinutes) {
      let maintenanceCheckStart, maintenanceCheckEnd;
      if (newOccupancyStart < otherOccupancyStart) {
        maintenanceCheckStart = newOccupancyEnd;
        maintenanceCheckEnd = otherOccupancyStart;
      } else {
        maintenanceCheckStart = otherOccupancyEnd;
        maintenanceCheckEnd = newOccupancyStart;
      }
      
      const maintenanceInGap = db.prepare(`
        SELECT * FROM maintenance_events
        WHERE plan_id = ? AND resource_id = ? AND at_minute > ? AND at_minute <= ?
      `).all(req.params.planId, new_resource_id, maintenanceCheckStart, maintenanceCheckEnd);
      if (maintenanceInGap.length === 0) {
        const error = createErrorResponse('ERR_STERILIZATION_TIME_VIOLATION', 'Resource scheduling conflict', 409);
        return res.status(error.statusCode).json(error.body);
      }
    }
  }

  const involvedResourceIds = [new_resource_id, ...existingSecondaryIds];
  let newProvisionalCost = 0;
  let crossingResourceIds = [];
  for (const rid of involvedResourceIds) {
    const cost = calculateProvisionalCost(rid, assignment.procedure_id, null, req.params.planId, null);
    newProvisionalCost += cost;
    const proc = db.prepare('SELECT start_minute, end_minute FROM procedures WHERE id = ?').get(assignment.procedure_id);
    const thr = getMaintenanceThreshold(rid);
    const cum = calculateCumulativeUsageAtMinute(req.params.planId, rid, proc.start_minute, null, null);
    const dur = proc.end_minute - proc.start_minute;
    const crosses = (cum >= thr) || (cum + dur > thr - 1);
    if (crosses) crossingResourceIds.push(rid);
  }

  const newPenaltyCount = crossingResourceIds.length;
  const isBioriskNew = newPenaltyCount > 0;
  const wasBiorisk = Boolean(assignment.is_high_biorisk);
  let priorPenaltyCount = wasBiorisk ? 1 : 0;
  if (assignment.biorisk_crossing_resource_ids) {
    try {
      const prior = typeof assignment.biorisk_crossing_resource_ids === 'string'
        ? JSON.parse(assignment.biorisk_crossing_resource_ids)
        : assignment.biorisk_crossing_resource_ids;
      if (Array.isArray(prior)) priorPenaltyCount = prior.length;
    } catch (e) {}
  }

  const wasOverridePenaltyApplied = Boolean(assignment.protocol_override_penalty_applied);
  const oldResourceId = assignment.resource_id;
  const costDiff = newProvisionalCost - assignment.provisional_cost;

  if (costDiff > 0) {
    const budgetLedger = db.prepare('SELECT provisional_debits, finalized_debits FROM budget_ledgers WHERE plan_id = ?').get(req.params.planId);
    const availableBalance = plan.total_budget - budgetLedger.provisional_debits - budgetLedger.finalized_debits;
    
    if (availableBalance < costDiff) {
      const error = createErrorResponse('ERR_INSUFFICIENT_BUDGET', 'Insufficient budget for cost increase', 402);
      return res.status(error.statusCode).json(error.body);
    }
  }

  const now = getTimestamp();
  const crossingIdsJson = crossingResourceIds.length > 0 ? JSON.stringify(crossingResourceIds) : null;
  const newProposalBioriskResourceCount = crossingResourceIds.length;
  const updateResult = db.prepare(
    'UPDATE assignments SET resource_id = ?, provisional_cost = ?, is_high_biorisk = ?, biorisk_crossing_resource_ids = ?, proposal_biorisk_resource_count = ?, override_protocol_check = 0, protocol_override_penalty_applied = 0, updated_at = ?, version = version + 1 WHERE id = ? AND status IN (\'PENDING_SCHEDULE\', \'PROTOCOL_APPROVED\')'
  ).run(new_resource_id, newProvisionalCost, isBioriskNew ? 1 : 0, crossingIdsJson, newProposalBioriskResourceCount, now, assignment.id);

  if (updateResult.changes === 0) {
    const error = createErrorResponse('ERR_ASSIGNMENT_NOT_REALLOCATABLE', 'Assignment is not in a reallocatable state', 409);
    return res.status(error.statusCode).json(error.body);
  }

  if (costDiff !== 0) {
    if (costDiff > 0) {
      incrementBudgetLedger(req.params.planId, 'provisional_debits', costDiff);
    } else {
      decrementBudgetLedger(req.params.planId, 'provisional_debits', Math.abs(costDiff));
    }
    updateBudgetLedger(req.params.planId, true);
  }

  let safetyAdjusted = false;
  
  const penaltyDelta = (newPenaltyCount - priorPenaltyCount) * CONSTANTS.HIGH_BIORISK_PENALTY;
  if (penaltyDelta > 0) {
    incrementSafetyLedger(req.params.planId, penaltyDelta);
    safetyAdjusted = true;
  } else if (penaltyDelta < 0) {
    decrementSafetyLedger(req.params.planId, Math.abs(penaltyDelta));
    safetyAdjusted = true;
  }

  if (wasOverridePenaltyApplied) {
    decrementSafetyLedger(req.params.planId, CONSTANTS.PROTOCOL_OVERRIDE_PENALTY);
    safetyAdjusted = true;
  }

  if (safetyAdjusted) {
    updateSafetyLedger(req.params.planId, true);
  }

  checkAndCompleteDecommissioning(req.params.planId, oldResourceId);

  const updatedAssignment = db.prepare('SELECT * FROM assignments WHERE id = ?').get(assignment.id);
  res.json(createSuccessResponse(serializeAssignment(updatedAssignment), 'object'));
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
    const otherResourceIds = new Set();
    for (const a of committedAll) {
      const pr = db.prepare('SELECT rotation_id FROM procedures WHERE id = ?').get(a.procedure_id);
      if (pr && pr.rotation_id === procedure.rotation_id) {
        otherResourceIds.add(a.resource_id);
        if (a.secondary_resource_ids) {
          try {
            const secondaries = typeof a.secondary_resource_ids === 'string' 
              ? JSON.parse(a.secondary_resource_ids) 
              : a.secondary_resource_ids;
            secondaries.forEach(sid => otherResourceIds.add(sid));
          } catch (e) {}
        }
      }
    }
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

  const assignmentResource = db.prepare('SELECT setup_overhead_minutes, teardown_overhead_minutes FROM medical_resources WHERE id = ?').get(assignment.resource_id);
  const assignmentSetup = assignmentResource?.setup_overhead_minutes || 0;
  const assignmentTeardown = assignmentResource?.teardown_overhead_minutes || 0;
  const assignmentOccupancyStart = procedure.start_minute - assignmentSetup;
  const assignmentOccupancyEnd = procedure.end_minute + assignmentTeardown;
  
  const allActiveHoldsSchedule = db.prepare(`
    SELECT * FROM resource_holds
    WHERE plan_id = ? AND resource_id = ? AND status = 'ACTIVE'
  `).all(req.params.planId, assignment.resource_id);

  const activeHoldsSchedule = allActiveHoldsSchedule.filter(hold =>
    hold.start_minute < assignmentOccupancyEnd && assignmentOccupancyStart < hold.end_minute
  );

  if (activeHoldsSchedule.length > 0) {
    const error = createErrorResponse('ERR_RESOURCE_ON_HOLD', 'The resource is unavailable due to an active hold overlapping the procedure window', 409);
    return res.status(error.statusCode).json(error.body);
  }

  let secondaryIdsSchedule = [];
  if (assignment.secondary_resource_ids) {
    try {
      secondaryIdsSchedule = typeof assignment.secondary_resource_ids === 'string'
        ? JSON.parse(assignment.secondary_resource_ids)
        : assignment.secondary_resource_ids;
    } catch (e) { secondaryIdsSchedule = []; }
  }
  for (const sid of secondaryIdsSchedule) {
    const secRes = db.prepare('SELECT setup_overhead_minutes, teardown_overhead_minutes FROM medical_resources WHERE id = ?').get(sid);
    const secSetup = secRes?.setup_overhead_minutes || 0;
    const secTeardown = secRes?.teardown_overhead_minutes || 0;
    const secOccStart = procedure.start_minute - secSetup;
    const secOccEnd = procedure.end_minute + secTeardown;
    const holds = db.prepare(`
      SELECT * FROM resource_holds
      WHERE plan_id = ? AND resource_id = ? AND status = 'ACTIVE'
    `).all(req.params.planId, sid);
    const overlapping = holds.filter(h => h.start_minute < secOccEnd && secOccStart < h.end_minute);
    if (overlapping.length > 0) {
      const error = createErrorResponse('ERR_RESOURCE_ON_HOLD', 'The resource is unavailable due to an active hold overlapping the procedure window', 409);
      return res.status(error.statusCode).json(error.body);
    }
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

  const involvedForSchedule = [assignment.resource_id, ...secondaryIdsSchedule];
  let newCost = 0;
  let scheduleCrossingIds = [];
  const procSched = db.prepare('SELECT start_minute, end_minute FROM procedures WHERE id = ?').get(assignment.procedure_id);
  const schedStart = procSched.start_minute;
  const schedDur = procSched.end_minute - procSched.start_minute;
  for (const rid of involvedForSchedule) {
    newCost += calculateProvisionalCost(rid, assignment.procedure_id, null, assignment.plan_id, assignment.id);
    const thr = getMaintenanceThreshold(rid);
    const cum = calculateCumulativeUsageAtMinute(assignment.plan_id, rid, schedStart, assignment.id, schedStart);
    const crosses = (cum >= thr) || (cum + schedDur > thr);
    if (crosses) scheduleCrossingIds.push(rid);
  }
  let reservedAtProposal = assignment.provisional_cost || 0;
  const costDifference = newCost - reservedAtProposal;
  const isBioriskNow = scheduleCrossingIds.length > 0;
  const wasBiorisk = Boolean(assignment.is_high_biorisk);

  const plan = db.prepare('SELECT total_budget FROM treatment_plans WHERE id = ?').get(req.params.planId);
  const budgetLedger = db.prepare('SELECT provisional_debits, finalized_debits FROM budget_ledgers WHERE plan_id = ?')
    .get(req.params.planId);
  const availableBalance = plan.total_budget - budgetLedger.provisional_debits - budgetLedger.finalized_debits;

  if (availableBalance < costDifference) {
    const error = createErrorResponse('ERR_INSUFFICIENT_BUDGET', 'Insufficient budget for cost increase', 402);
    return res.status(error.statusCode).json(error.body);
  }

  const crossingJsonSchedule = scheduleCrossingIds.length > 0 ? JSON.stringify(scheduleCrossingIds) : null;
  const updateResult = db.prepare(
    'UPDATE assignments SET status = ?, provisional_cost = ?, is_high_biorisk = ?, biorisk_crossing_resource_ids = ?, updated_at = ?, version = version + 1 WHERE id = ? AND status = ?'
  ).run('SCHEDULED', newCost, isBioriskNow ? 1 : 0, crossingJsonSchedule, getTimestamp(), req.params.assignmentId, 'PROTOCOL_APPROVED');

  if (updateResult.changes === 0) {
    const error = createErrorResponse('ERR_ASSIGNMENT_NOT_PROTOCOL_APPROVED', 'Assignment must be in PROTOCOL_APPROVED state', 409);
    return res.status(error.statusCode).json(error.body);
  }

  db.prepare('UPDATE procedures SET status = ?, updated_at = ?, version = version + 1 WHERE id = ?')
    .run('ASSIGNED', getTimestamp(), assignment.procedure_id);

  if (costDifference !== 0) {
    if (costDifference > 0) {
      incrementBudgetLedger(req.params.planId, 'provisional_debits', costDifference);
    } else {
      decrementBudgetLedger(req.params.planId, 'provisional_debits', Math.abs(costDifference));
    }
  }
  
  const bioriskCountAtProposal = assignment.proposal_biorisk_resource_count || 0;
  
  const bioriskCountNow = scheduleCrossingIds.length;
  
  const penaltyDelta = (bioriskCountNow - bioriskCountAtProposal) * CONSTANTS.HIGH_BIORISK_PENALTY;
  
  if (penaltyDelta > 0) {
    incrementSafetyLedger(req.params.planId, penaltyDelta);
  } else if (penaltyDelta < 0) {
    decrementSafetyLedger(req.params.planId, Math.abs(penaltyDelta));
  }
  const budgetChanged = costDifference !== 0;
  const safetyChanged = penaltyDelta !== 0;
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

  
  let secondaryIds = [];
  if (assignment.secondary_resource_ids) {
    try {
      secondaryIds = typeof assignment.secondary_resource_ids === 'string' 
        ? JSON.parse(assignment.secondary_resource_ids) 
        : assignment.secondary_resource_ids;
    } catch (e) { secondaryIds = []; }
  }

  decrementBudgetLedger(req.params.planId, 'provisional_debits', assignment.provisional_cost);
  updateBudgetLedger(req.params.planId, true);
  
  let safetyAdjusted = false;
  
  const penaltyCount = assignment.proposal_biorisk_resource_count || 0;
  const totalBioriskPenalty = penaltyCount * CONSTANTS.HIGH_BIORISK_PENALTY;

  if (totalBioriskPenalty > 0) {
    decrementSafetyLedger(req.params.planId, totalBioriskPenalty);
    safetyAdjusted = true;
  } else if (secondaryIds.length === 0 && assignment.is_high_biorisk) {
    decrementSafetyLedger(req.params.planId, CONSTANTS.HIGH_BIORISK_PENALTY);
    safetyAdjusted = true;
  }
  
  if (assignment.protocol_override_penalty_applied) {
    decrementSafetyLedger(req.params.planId, CONSTANTS.PROTOCOL_OVERRIDE_PENALTY);
    safetyAdjusted = true;
  }
  
  if (safetyAdjusted) updateSafetyLedger(req.params.planId, true);

  checkAndCompleteDecommissioning(req.params.planId, assignment.resource_id);
  for (const secId of secondaryIds) {
    checkAndCompleteDecommissioning(req.params.planId, secId);
  }

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

  
  let secondaryIds = [];
  if (assignment.secondary_resource_ids) {
    try {
      secondaryIds = typeof assignment.secondary_resource_ids === 'string' 
        ? JSON.parse(assignment.secondary_resource_ids) 
        : assignment.secondary_resource_ids;
    } catch (e) { secondaryIds = []; }
  }

  decrementBudgetLedger(req.params.planId, 'provisional_debits', assignment.provisional_cost);
  updateBudgetLedger(req.params.planId, true);
  
  let safetyAdjustedCancel = false;
  
  const penaltyCountCancel = assignment.proposal_biorisk_resource_count || 0;
  const totalBioriskPenaltyCancel = penaltyCountCancel * CONSTANTS.HIGH_BIORISK_PENALTY;
  
  if (totalBioriskPenaltyCancel > 0) {
    decrementSafetyLedger(req.params.planId, totalBioriskPenaltyCancel);
    safetyAdjustedCancel = true;
  } else if (secondaryIds.length === 0 && assignment.is_high_biorisk && penaltyCountCancel === 0) {
    decrementSafetyLedger(req.params.planId, CONSTANTS.HIGH_BIORISK_PENALTY);
    safetyAdjustedCancel = true;
  }
  
  if (assignment.protocol_override_penalty_applied) {
    decrementSafetyLedger(req.params.planId, CONSTANTS.PROTOCOL_OVERRIDE_PENALTY);
    safetyAdjustedCancel = true;
  }
  
  if (safetyAdjustedCancel) updateSafetyLedger(req.params.planId, true);

  db.prepare('UPDATE procedures SET status = ?, updated_at = ?, version = version + 1 WHERE id = ?')
    .run('PENDING', getTimestamp(), assignment.procedure_id);

  const procedure = db.prepare('SELECT rotation_id FROM procedures WHERE id = ?').get(assignment.procedure_id);
  const rotation = db.prepare('SELECT * FROM ward_rotations WHERE id = ?').get(procedure.rotation_id);

  if (rotation.status === 'READY_FOR_ASSIGNMENT') {
    db.prepare('UPDATE ward_rotations SET status = ?, updated_at = ?, version = version + 1 WHERE id = ?')
      .run('PLANNING', getTimestamp(), rotation.id);
  }

  checkAndCompleteDecommissioning(req.params.planId, assignment.resource_id);
  for (const secId of secondaryIds) {
    checkAndCompleteDecommissioning(req.params.planId, secId);
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
