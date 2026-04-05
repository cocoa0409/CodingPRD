const Decimal = require('decimal.js');
const db = require('../db/database');
const CONSTANTS = require('../config/constants');

function roundToTwoDecimals(value) {
  return Math.round(value * 100) / 100;
}

function getMaintenanceThreshold(resourceId) {
  const resource = db.prepare('SELECT maintenance_threshold_override FROM medical_resources WHERE id = ?').get(resourceId);
  if (!resource) return CONSTANTS.MAX_OPERATING_MINUTES_BEFORE_DEEP_CLEAN;

  if (resource.maintenance_threshold_override !== null && resource.maintenance_threshold_override !== undefined) {
    return resource.maintenance_threshold_override;
  }
  return CONSTANTS.MAX_OPERATING_MINUTES_BEFORE_DEEP_CLEAN;
}

function getMostRecentServicingBefore(planId, resourceId, beforeMinute) {
  const allEvents = db.prepare(`
    SELECT at_minute FROM maintenance_events
    WHERE plan_id = ? AND resource_id = ?
    ORDER BY at_minute DESC
  `).all(planId, resourceId);

  const validEvents = allEvents.filter(e => e.at_minute <= beforeMinute);
  
  return validEvents.length > 0 ? validEvents[0].at_minute : null;
}

function getServicingEventsInRange(planId, resourceId, startMinute, endMinute) {
  const events = db.prepare(`
    SELECT at_minute FROM maintenance_events
    WHERE plan_id = ? AND resource_id = ? AND at_minute >= ? AND at_minute < ?
    ORDER BY at_minute ASC
  `).all(planId, resourceId, startMinute, endMinute);

  return events.map(e => e.at_minute);
}

function calculateProcedureDuration(procedureId) {
  const procedure = db.prepare('SELECT start_minute, end_minute FROM procedures WHERE id = ?').get(procedureId);
  if (!procedure) return 0;
  return procedure.end_minute - procedure.start_minute;
}

function calculateCumulativeUsageAtMinute(planId, resourceId, atMinute, excludeAssignmentId = null, onlyBeforeMinute = null) {
  const baselineMinute = getMostRecentServicingBefore(planId, resourceId, atMinute);
  const baseline = baselineMinute !== null ? baselineMinute : 0;

  const rawAssignments = db.prepare(`
    SELECT id, procedure_id, resource_id, secondary_resource_ids
    FROM assignments
    WHERE plan_id = ? AND status IN ('PENDING_SCHEDULE', 'PROTOCOL_APPROVED', 'SCHEDULED', 'COMPLETED')
  `).all(planId);
  const rows = rawAssignments
    .map(a => {
      const p = db.prepare('SELECT start_minute, end_minute FROM procedures WHERE id = ?').get(a.procedure_id);
      if (!p) return null;
      return { ...a, start_minute: p.start_minute, end_minute: p.end_minute };
    })
    .filter(Boolean)
    .sort((x, y) => x.start_minute - y.start_minute);

  let assignments = rows.filter(row => {
    if (excludeAssignmentId && row.id === excludeAssignmentId) return false;
    if (row.resource_id === resourceId) return true;
    if (row.secondary_resource_ids) {
      try {
        const secondaries = typeof row.secondary_resource_ids === 'string'
          ? JSON.parse(row.secondary_resource_ids)
          : row.secondary_resource_ids;
        return Array.isArray(secondaries) && secondaries.includes(resourceId);
      } catch (e) {
        return false;
      }
    }
    return false;
  });

  const hasCutoff = (onlyBeforeMinute !== null && onlyBeforeMinute !== undefined);
  const cutoffMinute = hasCutoff ? onlyBeforeMinute : Number.POSITIVE_INFINITY;
  if (hasCutoff) {
    assignments = assignments.filter(a => a.start_minute < cutoffMinute);
  }

  let cumulative = 0;
  for (const a of assignments) {
    const segStart = Math.max(a.start_minute, baseline);
    const segEnd = Math.min(a.end_minute, cutoffMinute);
    if (segEnd > segStart) {
      cumulative += (segEnd - segStart);
    }
  }

  return cumulative;
}

function calculateAssignmentMinutesForResource(planId, resourceId, excludeAssignmentId = null, upToProcedureId = null) {
  const rawAssignments = db.prepare(`
    SELECT id, procedure_id, resource_id, secondary_resource_ids
    FROM assignments
    WHERE plan_id = ? AND status IN ('PENDING_SCHEDULE', 'PROTOCOL_APPROVED', 'SCHEDULED', 'COMPLETED')
  `).all(planId);
  const rows = rawAssignments
    .map(a => {
      const p = db.prepare('SELECT start_minute FROM procedures WHERE id = ?').get(a.procedure_id);
      if (!p) return null;
      return { ...a, start_minute: p.start_minute };
    })
    .filter(Boolean)
    .sort((x, y) => x.start_minute - y.start_minute);

  const limitStartMinute = upToProcedureId
    ? (db.prepare('SELECT start_minute FROM procedures WHERE id = ?').get(upToProcedureId)?.start_minute ?? null)
    : null;

  let totalMinutes = 0;
  for (const row of rows) {
    if (excludeAssignmentId && row.id === excludeAssignmentId) continue;

    if (limitStartMinute !== null && row.start_minute >= limitStartMinute) break;

    let involved = row.resource_id === resourceId;
    if (!involved && row.secondary_resource_ids) {
      try {
        const secondaries = typeof row.secondary_resource_ids === 'string'
          ? JSON.parse(row.secondary_resource_ids)
          : row.secondary_resource_ids;
        involved = Array.isArray(secondaries) && secondaries.includes(resourceId);
      } catch (e) {
        involved = false;
      }
    }
    if (!involved) continue;

    totalMinutes += calculateProcedureDuration(row.procedure_id);
  }

  return totalMinutes;
}

function calculateProvisionalCost(resourceId, procedureId, totalAssignmentMinutes, planId = null, excludeAssignmentId = null) {
  const resource = db.prepare('SELECT operating_cost_per_minute FROM medical_resources WHERE id = ?').get(resourceId);
  if (!resource) return 0;

  const procedure = db.prepare('SELECT plan_id, start_minute, end_minute FROM procedures WHERE id = ?').get(procedureId);
  if (!procedure) return 0;

  const actualPlanId = planId || procedure.plan_id;
  const threshold = getMaintenanceThreshold(resourceId);
  const costPerMinute = new Decimal(resource.operating_cost_per_minute);

  const procStart = procedure.start_minute;
  const procEnd = procedure.end_minute;

  const onlyBeforeMinute = excludeAssignmentId ? procStart : null;
  let cumulativeUsageAtStart = calculateCumulativeUsageAtMinute(
    actualPlanId,
    resourceId,
    procStart,
    excludeAssignmentId,
    onlyBeforeMinute
  );

  if (cumulativeUsageAtStart === 0) {
    const mostRecentMaint = getMostRecentServicingBefore(actualPlanId, resourceId, procStart);
    const priorMinutesSimple = calculateAssignmentMinutesForResource(actualPlanId, resourceId, excludeAssignmentId, procedureId);
    if (mostRecentMaint === null && priorMinutesSimple > 0) {
      cumulativeUsageAtStart = priorMinutesSimple;
    }
  }

  let totalCost = new Decimal(0);
  const procedureDuration = procEnd - procStart;

  for (let minute = 0; minute < procedureDuration; minute++) {
    const currentUsage = cumulativeUsageAtStart + minute;

    if (currentUsage >= threshold) {
      totalCost = totalCost.plus(costPerMinute.times(CONSTANTS.RISK_SURCHARGE_MULTIPLIER));
    } else {
      totalCost = totalCost.plus(costPerMinute);
    }
  }

  return roundToTwoDecimals(totalCost.toNumber());
}

function isAssignmentHighBiorisk(totalAssignmentMinutes, procedureId, resourceId = null, planId = null, excludeAssignmentId = null) {
  if (!resourceId) {
    const procedureDurationMinutes = calculateProcedureDuration(procedureId);
    const prevMinutes = totalAssignmentMinutes - procedureDurationMinutes;
    const totalRiskMinutes = Math.max(0, totalAssignmentMinutes - CONSTANTS.MAX_OPERATING_MINUTES_BEFORE_DEEP_CLEAN);
    const previousRiskMinutes = Math.max(0, prevMinutes - CONSTANTS.MAX_OPERATING_MINUTES_BEFORE_DEEP_CLEAN);
    const newRiskMinutes = totalRiskMinutes - previousRiskMinutes;
    return newRiskMinutes > 0;
  }

  const procedure = db.prepare('SELECT plan_id, start_minute, end_minute FROM procedures WHERE id = ?').get(procedureId);
  if (!procedure) return false;

  const actualPlanId = planId || procedure.plan_id;
  const threshold = getMaintenanceThreshold(resourceId);
  const procStart = procedure.start_minute;
  const procEnd = procedure.end_minute;

  const onlyBeforeMinute = excludeAssignmentId ? procStart : null;
  const cumulativeUsageAtStart = calculateCumulativeUsageAtMinute(
    actualPlanId,
    resourceId,
    procStart,
    excludeAssignmentId,
    onlyBeforeMinute
  );

  const procedureDuration = procEnd - procStart;
  for (let minute = 0; minute < procedureDuration; minute++) {
    const currentUsage = cumulativeUsageAtStart + minute;
    if (currentUsage >= threshold) {
      return true;
    }
  }

  return false;
}

module.exports = {
  roundToTwoDecimals,
  calculateProcedureDuration,
  calculateAssignmentMinutesForResource,
  calculateProvisionalCost,
  isAssignmentHighBiorisk,
  calculateCumulativeUsageAtMinute,
  getMaintenanceThreshold,
  getMostRecentServicingBefore,
  getServicingEventsInRange
};
