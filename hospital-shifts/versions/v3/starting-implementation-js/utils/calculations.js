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

  let query = `
    SELECT a.id, a.procedure_id, p.start_minute, p.end_minute
    FROM assignments a
    JOIN procedures p ON a.procedure_id = p.id
    WHERE a.plan_id = ? AND a.resource_id = ?
    AND a.status IN ('PENDING_SCHEDULE', 'PROTOCOL_APPROVED', 'SCHEDULED')
  `;
  const params = [planId, resourceId];

  if (excludeAssignmentId) {
    query += ' AND a.id != ?';
    params.push(excludeAssignmentId);
  }

  query += ' ORDER BY p.start_minute ASC';
  const allAssignments = db.prepare(query).all(...params);

  let assignments = allAssignments;
  if (onlyBeforeMinute !== null) {
    assignments = allAssignments.filter(a => a.start_minute < onlyBeforeMinute);
  }

  let cumulative = 0;
  let currentBaseline = baseline;

  for (const assignment of assignments) {
    if (assignment.end_minute <= currentBaseline) {
      continue;
    }

    const allMaintenanceEvents = db.prepare(`
      SELECT at_minute FROM maintenance_events
      WHERE plan_id = ? AND resource_id = ?
      ORDER BY at_minute DESC
    `).all(planId, resourceId);
    
    const maintenanceAfterFiltered = allMaintenanceEvents.filter(e => 
      e.at_minute > assignment.end_minute && e.at_minute <= atMinute
    );
    const maintenanceAfter = maintenanceAfterFiltered.length > 0 ? maintenanceAfterFiltered[0] : null;

    if (maintenanceAfter) {
      cumulative = 0;
      currentBaseline = maintenanceAfter.at_minute;
    } else {
      const contributionStart = Math.max(assignment.start_minute, currentBaseline);
      const contribution = assignment.end_minute - contributionStart;
      cumulative += contribution;
    }
  }

  return cumulative;
}

function calculateAssignmentMinutesForResource(planId, resourceId, excludeAssignmentId = null, upToProcedureId = null) {
  let query = `
    SELECT a.id, a.procedure_id, p.start_minute, p.end_minute
    FROM assignments a
    JOIN procedures p ON a.procedure_id = p.id
    WHERE a.plan_id = ? AND a.resource_id = ?
    AND a.status IN ('PENDING_SCHEDULE', 'PROTOCOL_APPROVED', 'SCHEDULED')
  `;

  const params = [planId, resourceId];

  if (excludeAssignmentId) {
    query += ' AND a.id != ?';
    params.push(excludeAssignmentId);
  }

  query += ' ORDER BY p.start_minute ASC';

  const assignments = db.prepare(query).all(...params);

  let totalMinutes = 0;
  let limitStartMinute = null;
  if (upToProcedureId) {
    const limitProc = db.prepare('SELECT start_minute FROM procedures WHERE id = ?').get(upToProcedureId);
    if (limitProc) limitStartMinute = limitProc.start_minute;
  }
  for (const assignment of assignments) {
    if (limitStartMinute !== null && assignment.start_minute >= limitStartMinute) break;
    totalMinutes += calculateProcedureDuration(assignment.procedure_id);
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
  const cumulativeUsageAtStart = calculateCumulativeUsageAtMinute(
    actualPlanId,
    resourceId,
    procStart,
    excludeAssignmentId,
    onlyBeforeMinute
  );

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
  getMaintenanceThreshold,
  getMostRecentServicingBefore,
  getServicingEventsInRange
};
