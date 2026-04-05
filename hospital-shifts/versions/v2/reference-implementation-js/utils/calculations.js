const Decimal = require('decimal.js');
const db = require('../db/database');
const CONSTANTS = require('../config/constants');

function roundToTwoDecimals(value) {
  return Math.round(value * 100) / 100;
}

// Get the maintenance threshold for a resource (resource-specific or default)
function getMaintenanceThreshold(resourceId) {
  const resource = db.prepare('SELECT maintenance_threshold_override FROM medical_resources WHERE id = ?').get(resourceId);
  if (!resource) return CONSTANTS.MAX_OPERATING_MINUTES_BEFORE_DEEP_CLEAN;

  if (resource.maintenance_threshold_override !== null && resource.maintenance_threshold_override !== undefined) {
    return resource.maintenance_threshold_override;
  }
  return CONSTANTS.MAX_OPERATING_MINUTES_BEFORE_DEEP_CLEAN;
}

// Get the most recent servicing event for a resource at or before a given minute
function getMostRecentServicingBefore(planId, resourceId, beforeMinute) {
  const allEvents = db.prepare(`
    SELECT at_minute FROM maintenance_events
    WHERE plan_id = ? AND resource_id = ?
    ORDER BY at_minute DESC
  `).all(planId, resourceId);

  // Filter in JavaScript to avoid database WHERE clause parsing issues
  const validEvents = allEvents.filter(e => e.at_minute <= beforeMinute);
  
  return validEvents.length > 0 ? validEvents[0].at_minute : null;
}

// Get all servicing events for a resource in a given range
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

// Helper to calculate cumulative usage at a specific minute for a resource
// considering maintenance events and which assignments to include
function calculateCumulativeUsageAtMinute(planId, resourceId, atMinute, excludeAssignmentId = null, onlyBeforeMinute = null) {
  // Find the baseline (most recent maintenance at or before atMinute)
  const baselineMinute = getMostRecentServicingBefore(planId, resourceId, atMinute);
  const baseline = baselineMinute !== null ? baselineMinute : 0;

  // Get all non-terminal assignments for this resource
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

  // Apply chronological filtering if needed (for schedule mode)
  let assignments = allAssignments;
  if (onlyBeforeMinute !== null) {
    assignments = allAssignments.filter(a => a.start_minute < onlyBeforeMinute);
  }

  // Walk through assignments chronologically, tracking maintenance resets
  let cumulative = 0;
  let currentBaseline = baseline;

  for (const assignment of assignments) {
    // Skip assignments that ended at or before the current baseline
    if (assignment.end_minute <= currentBaseline) {
      continue;
    }

    // Check for maintenance events between this assignment's end and our target minute
    // Use JavaScript filtering to avoid database WHERE clause parsing issues
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
      // Found a maintenance event after this assignment - reset
      cumulative = 0;
      currentBaseline = maintenanceAfter.at_minute;
    } else {
      // No maintenance reset - accumulate this assignment's contribution
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
    // If upToProcedureId specified, only count assignments that start before that procedure
    if (limitStartMinute !== null && assignment.start_minute >= limitStartMinute) break;
    totalMinutes += calculateProcedureDuration(assignment.procedure_id);
  }

  return totalMinutes;
}

// Calculate cost for a procedure considering maintenance events and usage-based pricing
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

  // Calculate cumulative usage at the start of this procedure
  // For proposal mode (excludeAssignmentId=null): count ALL non-terminal assignments
  // For schedule mode (excludeAssignmentId=targetId): count only assignments before this one
  const onlyBeforeMinute = excludeAssignmentId ? procStart : null;
  const cumulativeUsageAtStart = calculateCumulativeUsageAtMinute(
    actualPlanId,
    resourceId,
    procStart,
    excludeAssignmentId,
    onlyBeforeMinute
  );

  // Calculate the cost for the current procedure minute-by-minute
  let totalCost = new Decimal(0);
  const procedureDuration = procEnd - procStart;

  for (let minute = 0; minute < procedureDuration; minute++) {
    const currentUsage = cumulativeUsageAtStart + minute;

    if (currentUsage >= threshold) {
      // Bio-risk surcharge applies
      totalCost = totalCost.plus(costPerMinute.times(CONSTANTS.RISK_SURCHARGE_MULTIPLIER));
    } else {
      // Standard rate
      totalCost = totalCost.plus(costPerMinute);
    }
  }

  return roundToTwoDecimals(totalCost.toNumber());
}

// Check if a procedure will incur bio-risk charges
function isAssignmentHighBiorisk(totalAssignmentMinutes, procedureId, resourceId = null, planId = null, excludeAssignmentId = null) {
  if (!resourceId) {
    // Fallback to old simple calculation if resourceId not provided
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

  // Calculate cumulative usage at the start of this procedure
  // For proposal mode (excludeAssignmentId=null): count ALL non-terminal assignments
  // For schedule mode (excludeAssignmentId=targetId): count only assignments before this one
  const onlyBeforeMinute = excludeAssignmentId ? procStart : null;
  const cumulativeUsageAtStart = calculateCumulativeUsageAtMinute(
    actualPlanId,
    resourceId,
    procStart,
    excludeAssignmentId,
    onlyBeforeMinute
  );

  // Check if ANY minute of this procedure falls into bio-risk range
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
