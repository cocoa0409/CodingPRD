const express = require('express');
const router = express.Router({ mergeParams: true });
const db = require('../db/database');
const { authorize } = require('../middleware/auth');
const { createSuccessResponse, createErrorResponse, generateUUID, getTimestamp } = require('../utils/response');
const { serializeWardRotation } = require('../utils/serializers');
const { decrementBudgetLedger, decrementSafetyLedger } = require('../utils/ledger');
const CONSTANTS = require('../config/constants');

// POST /treatment-plans/:planId/ward-rotations - Create a new Ward Rotation
router.post('/', authorize('AttendingPhysician'), (req, res) => {
  const plan = db.prepare('SELECT * FROM treatment_plans WHERE id = ?').get(req.params.planId);

  if (!plan) {
    const error = createErrorResponse('ERR_PLAN_NOT_FOUND', 'Treatment plan not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (plan.status !== 'ACTIVE') {
    const error = createErrorResponse('ERR_PLAN_NOT_ACTIVE', 'Plan must be ACTIVE to create rotations', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const { name, start_minute, end_minute } = req.body;

  if (!Number.isInteger(start_minute) || !Number.isInteger(end_minute) || end_minute <= start_minute) {
    const error = createErrorResponse('ERR_INVALID_ROTATION_MINUTES', 'Invalid rotation minutes: end must be greater than start', 400);
    return res.status(error.statusCode).json(error.body);
  }

  const id = generateUUID();
  const now = getTimestamp();

  db.prepare(`
    INSERT INTO ward_rotations (id, plan_id, name, status, start_minute, end_minute, created_at, updated_at, version)
    VALUES (?, ?, ?, 'PLANNING', ?, ?, ?, ?, 1)
  `).run(id, req.params.planId, name, start_minute, end_minute, now, now);

  const rotation = db.prepare('SELECT * FROM ward_rotations WHERE id = ?').get(id);
  res.status(201).json(createSuccessResponse(serializeWardRotation(rotation), 'object'));
});

// GET /treatment-plans/:planId/ward-rotations - List Ward Rotations
router.get('/', (req, res) => {
  const plan = db.prepare('SELECT * FROM treatment_plans WHERE id = ?').get(req.params.planId);

  if (!plan) {
    const error = createErrorResponse('ERR_PLAN_NOT_FOUND', 'Treatment plan not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  const limit = Math.min(Math.max(parseInt(req.query.limit) || 10, 1), 100);
  const offset = Math.max(parseInt(req.query.offset) || 0, 0);

  const rotations = db.prepare('SELECT * FROM ward_rotations WHERE plan_id = ? ORDER BY created_at ASC LIMIT ? OFFSET ?')
    .all(req.params.planId, limit, offset);
  const totalCount = db.prepare('SELECT COUNT(*) as count FROM ward_rotations WHERE plan_id = ?').get(req.params.planId).count;

  const response = createSuccessResponse(
    rotations.map(serializeWardRotation),
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

// GET /treatment-plans/:planId/ward-rotations/:rotationId - Get a specific Ward Rotation
router.get('/:rotationId', (req, res) => {
  const plan = db.prepare('SELECT * FROM treatment_plans WHERE id = ?').get(req.params.planId);

  if (!plan) {
    const error = createErrorResponse('ERR_PLAN_NOT_FOUND', 'Treatment plan not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  const rotation = db.prepare('SELECT * FROM ward_rotations WHERE id = ? AND plan_id = ?')
    .get(req.params.rotationId, req.params.planId);

  if (!rotation) {
    const error = createErrorResponse('ERR_ROTATION_NOT_FOUND', 'Ward rotation not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  res.json(createSuccessResponse(serializeWardRotation(rotation), 'object'));
});

// PUT /treatment-plans/:planId/ward-rotations/:rotationId - Update a Ward Rotation's status
router.put('/:rotationId', authorize('ChargeNurse'), (req, res) => {
  const plan = db.prepare('SELECT * FROM treatment_plans WHERE id = ?').get(req.params.planId);

  if (!plan || plan.status !== 'ACTIVE') {
    const error = createErrorResponse('ERR_PLAN_NOT_ACTIVE', 'Plan must be ACTIVE to update rotations', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const rotation = db.prepare('SELECT * FROM ward_rotations WHERE id = ? AND plan_id = ?')
    .get(req.params.rotationId, req.params.planId);

  if (!rotation) {
    const error = createErrorResponse('ERR_ROTATION_NOT_FOUND', 'Ward rotation not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  // OCC check
  if (req.body.version !== undefined && req.body.version !== rotation.version) {
    const error = createErrorResponse('ERR_STALE_DATA', 'Resource version mismatch', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const { status } = req.body;

  // CANCELLED and COMPLETED are terminal states - no transitions allowed
  if (['CANCELLED', 'COMPLETED'].includes(rotation.status)) {
    const error = createErrorResponse('ERR_ILLEGAL_ROTATION_STATE_TRANSITION', 'Cannot transition from terminal state', 409);
    return res.status(error.statusCode).json(error.body);
  }

  if (status === 'READY_FOR_ASSIGNMENT') {
    if (rotation.status !== 'PLANNING') {
      const error = createErrorResponse('ERR_ILLEGAL_ROTATION_STATE_TRANSITION', 'Can only transition to READY_FOR_ASSIGNMENT from PLANNING', 409);
      return res.status(error.statusCode).json(error.body);
    }

    const procedures = db.prepare('SELECT * FROM procedures WHERE rotation_id = ?').all(req.params.rotationId);
    if (procedures.length === 0 || !procedures.every(p => p.status === 'ASSIGNED')) {
      const error = createErrorResponse('ERR_PROCEDURES_NOT_ASSIGNED', 'All procedures must be ASSIGNED', 409);
      return res.status(error.statusCode).json(error.body);
    }
  }

  if (status === 'CANCELLED') {
    if (!['PLANNING', 'READY_FOR_ASSIGNMENT'].includes(rotation.status)) {
      const error = createErrorResponse('ERR_ILLEGAL_ROTATION_STATE_TRANSITION', 'Can only cancel from PLANNING or READY_FOR_ASSIGNMENT', 409);
      return res.status(error.statusCode).json(error.body);
    }

    // Cascade cancellation
    const procedures = db.prepare('SELECT * FROM procedures WHERE rotation_id = ? AND status != ?')
      .all(req.params.rotationId, 'CANCELLED');

    let budgetChanged = false;
    let safetyChanged = false;

    for (const procedure of procedures) {
      const assignments = db.prepare('SELECT * FROM assignments WHERE procedure_id = ? AND status IN (?, ?, ?)')
        .all(procedure.id, 'PENDING_SCHEDULE', 'PROTOCOL_APPROVED', 'SCHEDULED');

      for (const assignment of assignments) {
        decrementBudgetLedger(req.params.planId, 'provisional_debits', assignment.provisional_cost);
        budgetChanged = true;
        if (assignment.is_high_biorisk) {
          decrementSafetyLedger(req.params.planId, CONSTANTS.HIGH_BIORISK_PENALTY);
          safetyChanged = true;
        }
        if (assignment.protocol_override_penalty_applied) {
          decrementSafetyLedger(req.params.planId, CONSTANTS.PROTOCOL_OVERRIDE_PENALTY);
          safetyChanged = true;
        }

        db.prepare('UPDATE assignments SET status = ?, updated_at = ?, version = version + 1 WHERE id = ?')
          .run('CANCELLED', getTimestamp(), assignment.id);
      }

      db.prepare('UPDATE procedures SET status = ?, updated_at = ?, version = version + 1 WHERE id = ?')
        .run('CANCELLED', getTimestamp(), procedure.id);
    }

    // After cascading, sync plan derived fields per-ledger to ensure proper version bumps
    const { updateBudgetLedger, updateSafetyLedger } = require('../utils/ledger');
    if (budgetChanged) updateBudgetLedger(req.params.planId, true);
    if (safetyChanged) updateSafetyLedger(req.params.planId, true);
  }

  db.prepare('UPDATE ward_rotations SET status = ?, updated_at = ?, version = version + 1 WHERE id = ?')
    .run(status, getTimestamp(), req.params.rotationId);

  const updatedRotation = db.prepare('SELECT * FROM ward_rotations WHERE id = ?').get(req.params.rotationId);
  res.json(createSuccessResponse(serializeWardRotation(updatedRotation), 'object'));
});

module.exports = router;
