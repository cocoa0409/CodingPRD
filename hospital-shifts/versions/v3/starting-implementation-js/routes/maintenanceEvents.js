const express = require('express');
const router = express.Router({ mergeParams: true });
const db = require('../db/database');
const { authorize } = require('../middleware/auth');
const { createSuccessResponse, createErrorResponse, generateUUID, getTimestamp } = require('../utils/response');
const { serializeMaintenanceEvent } = require('../utils/serializers');

router.post('/', authorize('ChargeNurse'), (req, res) => {
  const plan = db.prepare('SELECT * FROM treatment_plans WHERE id = ?').get(req.params.planId);

  if (!plan) {
    const error = createErrorResponse('ERR_PLAN_NOT_FOUND', 'Treatment plan not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  const { resource_id, at_minute } = req.body;

  if (at_minute === undefined || at_minute === null || at_minute < 0) {
    const error = createErrorResponse('ERR_INVALID_EVENT_MINUTE', 'The at_minute value is invalid', 400);
    return res.status(error.statusCode).json(error.body);
  }

  const resource = db.prepare('SELECT * FROM medical_resources WHERE id = ? AND plan_id = ?')
    .get(resource_id, req.params.planId);

  if (!resource) {
    const error = createErrorResponse('ERR_RESOURCE_NOT_FOUND', 'Medical resource not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  const allActiveHolds = db.prepare(`
    SELECT * FROM resource_holds
    WHERE plan_id = ? AND resource_id = ? AND status = 'ACTIVE'
  `).all(req.params.planId, resource_id);

  const conflictingHolds = allActiveHolds.filter(hold => 
    at_minute >= hold.start_minute && at_minute < hold.end_minute
  );

  if (conflictingHolds.length > 0) {
    const error = createErrorResponse('ERR_MAINTENANCE_EVENT_CONFLICT', 'Maintenance event cannot be created at the specified minute due to overlapping hold or assignment', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const allNonTerminalAssignments = db.prepare(`
    SELECT a.*, p.start_minute, p.end_minute FROM assignments a
    JOIN procedures p ON a.procedure_id = p.id
    WHERE a.plan_id = ? AND a.resource_id = ?
    AND a.status IN ('PENDING_SCHEDULE', 'PROTOCOL_APPROVED', 'SCHEDULED')
  `).all(req.params.planId, resource_id);

  const conflictingAssignments = allNonTerminalAssignments.filter(assignment =>
    at_minute >= assignment.start_minute && at_minute < assignment.end_minute
  );

  if (conflictingAssignments.length > 0) {
    const error = createErrorResponse('ERR_MAINTENANCE_EVENT_CONFLICT', 'Maintenance event cannot be created at the specified minute due to overlapping hold or assignment', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const id = generateUUID();
  const now = getTimestamp();

  db.prepare(`
    INSERT INTO maintenance_events (id, plan_id, resource_id, at_minute, created_at, version)
    VALUES (?, ?, ?, ?, ?, 1)
  `).run(id, req.params.planId, resource_id, at_minute, now);

  const event = db.prepare('SELECT * FROM maintenance_events WHERE id = ?').get(id);
  res.status(201).json(createSuccessResponse(serializeMaintenanceEvent(event), 'object'));
});

router.get('/', (req, res) => {
  const plan = db.prepare('SELECT * FROM treatment_plans WHERE id = ?').get(req.params.planId);

  if (!plan) {
    const error = createErrorResponse('ERR_PLAN_NOT_FOUND', 'Treatment plan not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  const limit = Math.min(Math.max(parseInt(req.query.limit) || 10, 1), 100);
  const offset = Math.max(parseInt(req.query.offset) || 0, 0);

  const events = db.prepare('SELECT * FROM maintenance_events WHERE plan_id = ? ORDER BY created_at ASC LIMIT ? OFFSET ?')
    .all(req.params.planId, limit, offset);
  const totalCount = db.prepare('SELECT COUNT(*) as count FROM maintenance_events WHERE plan_id = ?').get(req.params.planId).count;

  const response = createSuccessResponse(
    events.map(serializeMaintenanceEvent),
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

router.get('/:id', (req, res) => {
  const plan = db.prepare('SELECT * FROM treatment_plans WHERE id = ?').get(req.params.planId);

  if (!plan) {
    const error = createErrorResponse('ERR_PLAN_NOT_FOUND', 'Treatment plan not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  const event = db.prepare('SELECT * FROM maintenance_events WHERE id = ? AND plan_id = ?')
    .get(req.params.id, req.params.planId);

  if (!event) {
    const error = createErrorResponse('ERR_MAINTENANCE_EVENT_NOT_FOUND', 'The requested maintenance event does not exist or does not belong to the specified plan', 404);
    return res.status(error.statusCode).json(error.body);
  }

  res.json(createSuccessResponse(serializeMaintenanceEvent(event), 'object'));
});

module.exports = router;
