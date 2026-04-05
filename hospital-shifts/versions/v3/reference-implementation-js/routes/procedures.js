const express = require('express');
const router = express.Router({ mergeParams: true });
const db = require('../db/database');
const { authorize } = require('../middleware/auth');
const { createSuccessResponse, createErrorResponse, generateUUID, getTimestamp } = require('../utils/response');
const { serializeProcedure } = require('../utils/serializers');

// POST /treatment-plans/:planId/ward-rotations/:rotationId/procedures - Create a new Procedure
router.post('/', authorize('AttendingPhysician'), (req, res) => {
  const plan = db.prepare('SELECT * FROM treatment_plans WHERE id = ?').get(req.params.planId);

  if (!plan) {
    const error = createErrorResponse('ERR_PLAN_NOT_FOUND', 'Treatment plan not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (plan.status !== 'ACTIVE') {
    const error = createErrorResponse('ERR_PLAN_NOT_ACTIVE', 'Plan must be ACTIVE to create procedures', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const rotation = db.prepare('SELECT * FROM ward_rotations WHERE id = ? AND plan_id = ?')
    .get(req.params.rotationId, req.params.planId);

  if (!rotation) {
    const error = createErrorResponse('ERR_ROTATION_NOT_FOUND', 'Ward rotation not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  // Prevent creating procedures in terminal rotations
  if (['CANCELLED', 'COMPLETED'].includes(rotation.status)) {
    const error = createErrorResponse('ERR_ILLEGAL_ROTATION_STATE_TRANSITION', 'Cannot create procedure in terminal rotation', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const { procedure_type, start_minute, end_minute, required_certification, secondary_resource_requirements } = req.body;

  if (!Number.isInteger(start_minute) || !Number.isInteger(end_minute) || end_minute <= start_minute) {
    const error = createErrorResponse('ERR_INVALID_PROCEDURE_MINUTES', 'Invalid procedure minutes: end must be greater than start', 400);
    return res.status(error.statusCode).json(error.body);
  }

  // Validate certification enum
  const certification = required_certification || 'NONE';
  const validCertifications = ['BSL-3_CERTIFIED', 'CARDIAC_CATHETERIZATION_LAB', 'NONE'];
  if (!validCertifications.includes(certification)) {
    const error = createErrorResponse('ERR_INVALID_REQUEST', 'Invalid required_certification value', 400);
    return res.status(error.statusCode).json(error.body);
  }

  // Validate secondary requirements if provided
  let secondaryReqsJson = null;
  if (secondary_resource_requirements) {
    if (!Array.isArray(secondary_resource_requirements) || !secondary_resource_requirements.every(r => validCertifications.includes(r))) {
      const error = createErrorResponse('ERR_INVALID_REQUEST', 'Invalid secondary_resource_requirements value', 400);
      return res.status(error.statusCode).json(error.body);
    }
    secondaryReqsJson = JSON.stringify(secondary_resource_requirements);
  }

  const id = generateUUID();
  const now = getTimestamp();
  const duration = end_minute - start_minute;

  db.prepare(`
    INSERT INTO procedures (id, plan_id, rotation_id, procedure_type, status, required_certification, secondary_resource_requirements, start_minute, end_minute, duration_minutes, created_at, updated_at, version)
    VALUES (?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?, ?, ?, 1)
  `).run(id, req.params.planId, req.params.rotationId, procedure_type, certification, secondaryReqsJson, start_minute, end_minute, duration, now, now);

  const procedure = db.prepare('SELECT * FROM procedures WHERE id = ?').get(id);
  res.status(201).json(createSuccessResponse(serializeProcedure(procedure), 'object'));
});

// GET /treatment-plans/:planId/ward-rotations/:rotationId/procedures - List Procedures
router.get('/', (req, res) => {
  const limit = Math.min(Math.max(parseInt(req.query.limit) || 10, 1), 100);
  const offset = Math.max(parseInt(req.query.offset) || 0, 0);

  const procedures = db.prepare('SELECT * FROM procedures WHERE plan_id = ? AND rotation_id = ? ORDER BY created_at ASC LIMIT ? OFFSET ?')
    .all(req.params.planId, req.params.rotationId, limit, offset);
  const totalCount = db.prepare('SELECT COUNT(*) as count FROM procedures WHERE plan_id = ? AND rotation_id = ?')
    .get(req.params.planId, req.params.rotationId).count;

  const response = createSuccessResponse(
    procedures.map(serializeProcedure),
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

// GET /treatment-plans/:planId/ward-rotations/:rotationId/procedures/:procedureId - Get a specific Procedure
router.get('/:procedureId', (req, res) => {
  const procedure = db.prepare('SELECT * FROM procedures WHERE id = ? AND rotation_id = ? AND plan_id = ?')
    .get(req.params.procedureId, req.params.rotationId, req.params.planId);

  if (!procedure) {
    const error = createErrorResponse('ERR_PROCEDURE_NOT_FOUND', 'Procedure not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  res.json(createSuccessResponse(serializeProcedure(procedure), 'object'));
});

// POST /treatment-plans/:planId/ward-rotations/:rotationId/procedures/:procedureId/cancel - Cancel a Procedure
router.post('/:procedureId/cancel', authorize('AttendingPhysician'), (req, res) => {
  // Follow §2.8 - validate hierarchically: plan -> rotation -> procedure
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

  const procedure = db.prepare('SELECT * FROM procedures WHERE id = ? AND rotation_id = ? AND plan_id = ?')
    .get(req.params.procedureId, req.params.rotationId, req.params.planId);
  if (!procedure) {
    const error = createErrorResponse('ERR_PROCEDURE_NOT_FOUND', 'Procedure not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  // OCC version check
  if (req.body.version !== undefined && req.body.version !== procedure.version) {
    const error = createErrorResponse('ERR_STALE_DATA', 'Version mismatch - data has been modified', 409);
    return res.status(error.statusCode).json(error.body);
  }

  if (procedure.status !== 'PENDING') {
    const error = createErrorResponse('ERR_PROCEDURE_NOT_PENDING_FOR_CANCEL', 'Can only cancel PENDING procedures', 409);
    return res.status(error.statusCode).json(error.body);
  }

  db.prepare('UPDATE procedures SET status = ?, updated_at = ?, version = version + 1 WHERE id = ?')
    .run('CANCELLED', getTimestamp(), req.params.procedureId);

  // Check if rotation should be completed
  const allProcedures = db.prepare('SELECT * FROM procedures WHERE rotation_id = ?').all(req.params.rotationId);
  const allTerminal = allProcedures.every(p => ['COMPLETED', 'CANCELLED'].includes(p.status));

  if (allTerminal) {
    db.prepare('UPDATE ward_rotations SET status = ?, updated_at = ?, version = version + 1 WHERE id = ?')
      .run('COMPLETED', getTimestamp(), req.params.rotationId);
  }

  const updatedProcedure = db.prepare('SELECT * FROM procedures WHERE id = ?').get(req.params.procedureId);
  res.json(createSuccessResponse(serializeProcedure(updatedProcedure), 'object'));
});

module.exports = router;
