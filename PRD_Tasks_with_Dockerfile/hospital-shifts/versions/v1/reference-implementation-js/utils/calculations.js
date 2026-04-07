const Decimal = require('decimal.js');
const db = require('../db/database');
const CONSTANTS = require('../config/constants');

function roundToTwoDecimals(value) {
  return Math.round(value * 100) / 100;
}

function calculateProcedureDuration(procedureId) {
  const procedure = db.prepare('SELECT start_minute, end_minute FROM procedures WHERE id = ?').get(procedureId);
  if (!procedure) return 0;
  return procedure.end_minute - procedure.start_minute;
}

function calculateAssignmentMinutesForResource(planId, resourceId, excludeAssignmentId = null, upToProcedureId = null) {
  let query = `
    SELECT a.id, a.procedure_id, p.start_minute
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

function calculateProvisionalCost(resourceId, procedureId, totalAssignmentMinutes) {
  const resource = db.prepare('SELECT operating_cost_per_minute FROM medical_resources WHERE id = ?').get(resourceId);
  if (!resource) return 0;

  const procedureDurationMinutes = calculateProcedureDuration(procedureId);
  const procedureMinutes = procedureDurationMinutes;

  const prevMinutes = totalAssignmentMinutes - procedureMinutes;
  const totalRiskMinutes = Math.max(0, totalAssignmentMinutes - CONSTANTS.MAX_OPERATING_MINUTES_BEFORE_DEEP_CLEAN);
  const previousRiskMinutes = Math.max(0, prevMinutes - CONSTANTS.MAX_OPERATING_MINUTES_BEFORE_DEEP_CLEAN);
  const newRiskMinutes = totalRiskMinutes - previousRiskMinutes;
  const standardMinutes = procedureMinutes - newRiskMinutes;

  const costPerMinute = new Decimal(resource.operating_cost_per_minute);
  const standardCost = new Decimal(standardMinutes).times(costPerMinute);
  const riskCost = new Decimal(newRiskMinutes).times(costPerMinute).times(CONSTANTS.RISK_SURCHARGE_MULTIPLIER);

  return roundToTwoDecimals(standardCost.plus(riskCost).toNumber());
}

function isAssignmentHighBiorisk(totalAssignmentMinutes, procedureId) {
  const procedureDurationMinutes = calculateProcedureDuration(procedureId);
  const procedureMinutes = procedureDurationMinutes;
  const prevMinutes = totalAssignmentMinutes - procedureMinutes;
  const totalRiskMinutes = Math.max(0, totalAssignmentMinutes - CONSTANTS.MAX_OPERATING_MINUTES_BEFORE_DEEP_CLEAN);
  const previousRiskMinutes = Math.max(0, prevMinutes - CONSTANTS.MAX_OPERATING_MINUTES_BEFORE_DEEP_CLEAN);
  const newRiskMinutes = totalRiskMinutes - previousRiskMinutes;
  return newRiskMinutes > 0;
}

module.exports = {
  roundToTwoDecimals,
  calculateProcedureDuration,
  calculateAssignmentMinutesForResource,
  calculateProvisionalCost,
  isAssignmentHighBiorisk
};
