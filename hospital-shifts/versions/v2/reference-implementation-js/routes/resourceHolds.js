const express = require('express');
const router = express.Router({ mergeParams: true });
const db = require('../db/database');
const { authorize } = require('../middleware/auth');
const { createSuccessResponse, createErrorResponse, generateUUID, getTimestamp } = require('../utils/response');
const { serializeResourceHold } = require('../utils/serializers');

// POST /treatment-plans/:planId/resource-holds - Create a resource hold
router.post('/', authorize('ChargeNurse'), (req, res) => {
  const plan = db.prepare('SELECT * FROM treatment_plans WHERE id = ?').get(req.params.planId);

  if (!plan) {
    const error = createErrorResponse('ERR_PLAN_NOT_FOUND', 'Treatment plan not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  const { resource_id, start_minute, end_minute, reason } = req.body;

  // Validate hold window
  if (start_minute === undefined || start_minute === null || end_minute === undefined || end_minute === null || end_minute <= start_minute) {
    const error = createErrorResponse('ERR_INVALID_HOLD_MINUTES', 'The hold time window is invalid', 400);
    return res.status(error.statusCode).json(error.body);
  }

  // Validate resource exists
  const resource = db.prepare('SELECT * FROM medical_resources WHERE id = ? AND plan_id = ?')
    .get(resource_id, req.params.planId);

  if (!resource) {
    const error = createErrorResponse('ERR_RESOURCE_NOT_FOUND', 'Medical resource not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  // Check for conflicts with already-committed assignments
  // Hold window [start_minute, end_minute) must not overlap with assignment windows [proc.start, proc.end)
  // Half-open intervals overlap if: hold_start < assignment_end AND assignment_start < hold_end
  // Edge-touching is allowed: hold can end exactly where assignment starts, or start exactly where assignment ends
  // Use JavaScript filtering to avoid database WHERE clause parsing issues
  const allNonTerminalAssignments = db.prepare(`
    SELECT a.*, p.start_minute, p.end_minute FROM assignments a
    JOIN procedures p ON a.procedure_id = p.id
    WHERE a.plan_id = ? AND a.resource_id = ?
    AND a.status IN ('PENDING_SCHEDULE', 'PROTOCOL_APPROVED', 'SCHEDULED')
  `).all(req.params.planId, resource_id);

  const conflictingAssignments = allNonTerminalAssignments.filter(assignment =>
    start_minute < assignment.end_minute && assignment.start_minute < end_minute
  );

  if (conflictingAssignments.length > 0) {
    const error = createErrorResponse('ERR_HOLD_CONFLICTS_WITH_ASSIGNMENT', 'The hold cannot be created because it overlaps with an already-committed assignment', 409);
    return res.status(error.statusCode).json(error.body);
  }

  // Create the hold
  const id = generateUUID();
  const now = getTimestamp();

  db.prepare(`
    INSERT INTO resource_holds (id, plan_id, resource_id, start_minute, end_minute, reason, status, created_at, updated_at, version)
    VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, 1)
  `).run(id, req.params.planId, resource_id, start_minute, end_minute, reason || null, now, now);

  const hold = db.prepare('SELECT * FROM resource_holds WHERE id = ?').get(id);
  res.status(201).json(createSuccessResponse(serializeResourceHold(hold), 'object'));
});

// GET /treatment-plans/:planId/resource-holds - List resource holds
router.get('/', (req, res) => {
  const plan = db.prepare('SELECT * FROM treatment_plans WHERE id = ?').get(req.params.planId);

  if (!plan) {
    const error = createErrorResponse('ERR_PLAN_NOT_FOUND', 'Treatment plan not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  const limit = Math.min(Math.max(parseInt(req.query.limit) || 10, 1), 100);
  const offset = Math.max(parseInt(req.query.offset) || 0, 0);

  const holds = db.prepare('SELECT * FROM resource_holds WHERE plan_id = ? ORDER BY created_at ASC LIMIT ? OFFSET ?')
    .all(req.params.planId, limit, offset);
  const totalCount = db.prepare('SELECT COUNT(*) as count FROM resource_holds WHERE plan_id = ?').get(req.params.planId).count;

  const response = createSuccessResponse(
    holds.map(serializeResourceHold),
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

// GET /treatment-plans/:planId/resource-holds/:holdId - Get a specific hold
router.get('/:holdId', (req, res) => {
  // First check if plan exists
  const plan = db.prepare('SELECT * FROM treatment_plans WHERE id = ?').get(req.params.planId);

  if (!plan) {
    const error = createErrorResponse('ERR_PLAN_NOT_FOUND', 'Treatment plan not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  const hold = db.prepare('SELECT * FROM resource_holds WHERE id = ? AND plan_id = ?')
    .get(req.params.holdId, req.params.planId);

  if (!hold) {
    const error = createErrorResponse('ERR_RESOURCE_HOLD_NOT_FOUND', 'The requested resource hold does not exist or does not belong to the specified plan', 404);
    return res.status(error.statusCode).json(error.body);
  }

  res.json(createSuccessResponse(serializeResourceHold(hold), 'object'));
});

// POST /treatment-plans/:planId/resource-holds/:holdId/cancel - Cancel a hold
router.post('/:holdId/cancel', authorize('ChargeNurse'), (req, res) => {
  const hold = db.prepare('SELECT * FROM resource_holds WHERE id = ? AND plan_id = ?')
    .get(req.params.holdId, req.params.planId);

  if (!hold) {
    const error = createErrorResponse('ERR_RESOURCE_HOLD_NOT_FOUND', 'The requested resource hold does not exist or does not belong to the specified plan', 404);
    return res.status(error.statusCode).json(error.body);
  }

  // OCC version check
  if (req.body.version !== undefined && req.body.version !== hold.version) {
    const error = createErrorResponse('ERR_STALE_DATA', 'Version mismatch - data has been modified', 409);
    return res.status(error.statusCode).json(error.body);
  }

  // Check if hold is in ACTIVE status
  if (hold.status !== 'ACTIVE') {
    const error = createErrorResponse('ERR_HOLD_NOT_ACTIVE', 'The hold cannot be cancelled because it is not in ACTIVE status', 409);
    return res.status(error.statusCode).json(error.body);
  }

  // Cancel the hold
  db.prepare('UPDATE resource_holds SET status = ?, updated_at = ?, version = version + 1 WHERE id = ?')
    .run('CANCELLED', getTimestamp(), req.params.holdId);

  const updatedHold = db.prepare('SELECT * FROM resource_holds WHERE id = ?').get(req.params.holdId);
  res.json(createSuccessResponse(serializeResourceHold(updatedHold), 'object'));
});

module.exports = router;
