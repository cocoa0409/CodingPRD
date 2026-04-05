const express = require('express');
const router = express.Router({ mergeParams: true });
const Decimal = require('decimal.js');
const db = require('../db/database');
const { authorize } = require('../middleware/auth');
const { createSuccessResponse, createErrorResponse, getTimestamp } = require('../utils/response');
const { serializeTreatmentPlan } = require('../utils/serializers');
const {
  calculateProcedureDuration,
  calculateProvisionalCost,
  isAssignmentHighBiorisk,
  roundToTwoDecimals,
  getMaintenanceThreshold,
  getMostRecentServicingBefore
} = require('../utils/calculations');
const { 
  updateBudgetLedger, 
  updateSafetyLedger,
  incrementBudgetLedger,
  decrementBudgetLedger,
  incrementSafetyLedger, 
  decrementSafetyLedger 
} = require('../utils/ledger');
const CONSTANTS = require('../config/constants');

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

router.post('/', authorize('HospitalAdministrator'), (req, res) => {
  const plan = db.prepare('SELECT * FROM treatment_plans WHERE id = ?').get(req.params.planId);

  if (!plan) {
    const error = createErrorResponse('ERR_PLAN_NOT_FOUND', 'Treatment plan not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (req.body.version !== undefined && req.body.version !== plan.version) {
    const error = createErrorResponse('ERR_STALE_DATA', 'Version mismatch - data has been modified', 409);
    return res.status(error.statusCode).json(error.body);
  }

  if (plan.status !== 'FINAL_REVIEW_PENDING') {
    const error = createErrorResponse('ERR_PLAN_NOT_READY_FOR_FINALIZATION', 'Plan must be in FINAL_REVIEW_PENDING state', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const assignmentsToComplete = db.prepare(`
    SELECT a.*, p.start_minute, p.end_minute
    FROM assignments a
    JOIN procedures p ON a.procedure_id = p.id
    WHERE a.plan_id = ? AND a.status = 'SCHEDULED'
    ORDER BY p.start_minute ASC, a.id ASC
  `).all(req.params.planId);

  let totalFinalizedDebits = new Decimal(0);

  for (const assignment of assignmentsToComplete) {
    const procStart = assignment.start_minute;
    const procEnd = assignment.end_minute;
    
    let secondaryIds = [];
    if (assignment.secondary_resource_ids) {
      try {
        secondaryIds = typeof assignment.secondary_resource_ids === 'string' 
          ? JSON.parse(assignment.secondary_resource_ids) 
          : assignment.secondary_resource_ids;
      } catch (e) { secondaryIds = []; }
    }
    
    const allResourceIds = [assignment.resource_id, ...secondaryIds];
    
    let totalCost = new Decimal(0);
    let anyResourceCrossesThreshold = false;
    
    for (const resourceId of allResourceIds) {
      const threshold = getMaintenanceThreshold(resourceId);
      const resource = db.prepare('SELECT operating_cost_per_minute FROM medical_resources WHERE id = ?').get(resourceId);
      const costPerMinute = new Decimal(resource.operating_cost_per_minute);

      const cumulativeAtStart = require('../utils/calculations').calculateCumulativeUsageAtMinute(
        req.params.planId,
        resourceId,
        procStart,
        assignment.id,
        procStart
      );

      let resourceCost = new Decimal(0);
      const procedureDuration = procEnd - procStart;
      for (let minute = 0; minute < procedureDuration; minute++) {
        const currentUsage = cumulativeAtStart + minute;
        if (currentUsage >= threshold) {
          resourceCost = resourceCost.plus(costPerMinute.times(CONSTANTS.RISK_SURCHARGE_MULTIPLIER));
        } else {
          resourceCost = resourceCost.plus(costPerMinute);
        }
      }

      totalCost = totalCost.plus(resourceCost);

      if (cumulativeAtStart >= threshold || (cumulativeAtStart + procedureDuration > threshold)) {
        anyResourceCrossesThreshold = true;
      }
    }
    
    const finalCost = roundToTwoDecimals(totalCost.toNumber());
    const isNowBiorisk = anyResourceCrossesThreshold;
    const wasBiorisk = assignment.is_high_biorisk;

    totalFinalizedDebits = totalFinalizedDebits.plus(finalCost);

    db.prepare('UPDATE assignments SET final_cost = ?, is_high_biorisk = ?, status = ?, updated_at = ?, version = version + 1 WHERE id = ?')
      .run(finalCost, isNowBiorisk ? 1 : 0, 'COMPLETED', getTimestamp(), assignment.id);

    db.prepare('UPDATE procedures SET status = ?, updated_at = ?, version = version + 1 WHERE id = ?')
      .run('COMPLETED', getTimestamp(), assignment.procedure_id);

    let secondaryIdsForDecommissioning = [];
    if (assignment.secondary_resource_ids) {
      try {
        secondaryIdsForDecommissioning = typeof assignment.secondary_resource_ids === 'string' 
          ? JSON.parse(assignment.secondary_resource_ids) 
          : assignment.secondary_resource_ids;
      } catch (e) { secondaryIdsForDecommissioning = []; }
    }
    checkAndCompleteDecommissioning(req.params.planId, assignment.resource_id);
    for (const secId of secondaryIdsForDecommissioning) {
      checkAndCompleteDecommissioning(req.params.planId, secId);
    }

    incrementBudgetLedger(req.params.planId, 'finalized_debits', finalCost);
    updateBudgetLedger(req.params.planId, true);

    decrementBudgetLedger(req.params.planId, 'provisional_debits', assignment.provisional_cost);
    updateBudgetLedger(req.params.planId, true);

    if (isNowBiorisk && !wasBiorisk) {
      incrementSafetyLedger(req.params.planId, CONSTANTS.HIGH_BIORISK_PENALTY);
      updateSafetyLedger(req.params.planId, true);
    } else if (!isNowBiorisk && wasBiorisk) {
      decrementSafetyLedger(req.params.planId, CONSTANTS.HIGH_BIORISK_PENALTY);
      updateSafetyLedger(req.params.planId, true);
    }

    const procedure = db.prepare('SELECT rotation_id FROM procedures WHERE id = ?').get(assignment.procedure_id);
    const allProcedures = db.prepare('SELECT * FROM procedures WHERE rotation_id = ?').all(procedure.rotation_id);
    const allDone = allProcedures.every(p => ['COMPLETED', 'CANCELLED'].includes(p.status));

    if (allDone) {
      db.prepare('UPDATE ward_rotations SET status = ?, updated_at = ?, version = version + 1 WHERE id = ?')
        .run('COMPLETED', getTimestamp(), procedure.rotation_id);
    }
  }

  const finalDebitsValue = roundToTwoDecimals(totalFinalizedDebits.toNumber());
  if (finalDebitsValue > plan.total_budget) {
    const error = createErrorResponse('ERR_FINALIZATION_EXCEEDS_BUDGET', 'Finalization costs exceed total budget', 402);
    return res.status(error.statusCode).json(error.body);
  }

  db.prepare('UPDATE budget_ledgers SET provisional_debits = 0.0 WHERE plan_id = ?')
    .run(req.params.planId);
  updateBudgetLedger(req.params.planId, true);

  db.prepare('UPDATE treatment_plans SET status = ?, updated_at = ?, version = version + 1 WHERE id = ?')
    .run('COMPLETED', getTimestamp(), req.params.planId);

  const completedPlan = db.prepare('SELECT * FROM treatment_plans WHERE id = ?').get(req.params.planId);
  res.json(createSuccessResponse(serializeTreatmentPlan(completedPlan), 'object'));
});

module.exports = router;
