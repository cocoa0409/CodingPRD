const express = require('express');
const router = express.Router({ mergeParams: true });
const db = require('../db/database');
const { authorize } = require('../middleware/auth');
const { createSuccessResponse, createErrorResponse, generateUUID, getTimestamp } = require('../utils/response');
const { serializeMedicalResource } = require('../utils/serializers');

// POST /treatment-plans/:planId/medical-resources - Create a Medical Resource
router.post('/', authorize('AttendingPhysician'), (req, res) => {
  const plan = db.prepare('SELECT * FROM treatment_plans WHERE id = ?').get(req.params.planId);

  if (!plan) {
    const error = createErrorResponse('ERR_PLAN_NOT_FOUND', 'Treatment plan not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  const { resource_name, resource_model, operating_cost_per_minute } = req.body;

  const id = generateUUID();
  const now = getTimestamp();

  db.prepare(`
    INSERT INTO medical_resources (id, plan_id, resource_name, resource_model, operating_cost_per_minute, created_at, updated_at, version)
    VALUES (?, ?, ?, ?, ?, ?, ?, 1)
  `).run(id, req.params.planId, resource_name, resource_model, operating_cost_per_minute, now, now);

  const resource = db.prepare('SELECT * FROM medical_resources WHERE id = ?').get(id);
  res.status(201).json(createSuccessResponse(serializeMedicalResource(resource), 'object'));
});

// GET /treatment-plans/:planId/medical-resources - List Medical Resources
router.get('/', (req, res) => {
  const plan = db.prepare('SELECT * FROM treatment_plans WHERE id = ?').get(req.params.planId);

  if (!plan) {
    const error = createErrorResponse('ERR_PLAN_NOT_FOUND', 'Treatment plan not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  const limit = Math.min(Math.max(parseInt(req.query.limit) || 10, 1), 100);
  const offset = Math.max(parseInt(req.query.offset) || 0, 0);

  const resources = db.prepare('SELECT * FROM medical_resources WHERE plan_id = ? ORDER BY created_at ASC LIMIT ? OFFSET ?')
    .all(req.params.planId, limit, offset);
  const totalCount = db.prepare('SELECT COUNT(*) as count FROM medical_resources WHERE plan_id = ?').get(req.params.planId).count;

  const response = createSuccessResponse(
    resources.map(serializeMedicalResource),
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

// GET /treatment-plans/:planId/medical-resources/:resourceId - Get a specific Medical Resource
router.get('/:resourceId', (req, res) => {
  const resource = db.prepare('SELECT * FROM medical_resources WHERE id = ? AND plan_id = ?')
    .get(req.params.resourceId, req.params.planId);

  if (!resource) {
    const error = createErrorResponse('ERR_RESOURCE_NOT_FOUND', 'Medical resource not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  res.json(createSuccessResponse(serializeMedicalResource(resource), 'object'));
});

// POST /treatment-plans/:planId/medical-resources/:resourceId/certifications - Add a certification
router.post('/:resourceId/certifications', authorize('AttendingPhysician'), (req, res) => {
  const resource = db.prepare('SELECT * FROM medical_resources WHERE id = ? AND plan_id = ?')
    .get(req.params.resourceId, req.params.planId);

  if (!resource) {
    const error = createErrorResponse('ERR_RESOURCE_NOT_FOUND', 'Medical resource not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  // OCC version check
  if (req.body.version !== undefined && req.body.version !== resource.version) {
    const error = createErrorResponse('ERR_STALE_DATA', 'Version mismatch - data has been modified', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const { name, applied_date } = req.body;

  // Validate certification name
  const validCertifications = ['BSL-3_CERTIFIED', 'CARDIAC_CATHETERIZATION_LAB'];
  if (!validCertifications.includes(name)) {
    const error = createErrorResponse('ERR_INVALID_REQUEST', 'Invalid certification name', 400);
    return res.status(error.statusCode).json(error.body);
  }

  const id = generateUUID();

  db.prepare('INSERT INTO resource_certifications (id, resource_id, name, applied_date) VALUES (?, ?, ?, ?)')
    .run(id, req.params.resourceId, name, applied_date);

  // Ensure updated_at moves forward even under same-millisecond operations
  const prevUpdatedAt = resource.updated_at;
  let now = getTimestamp();
  if (prevUpdatedAt && now === prevUpdatedAt) {
    const bump = new Date(new Date(now).getTime() + 1).toISOString();
    now = bump;
  }
  db.prepare('UPDATE medical_resources SET updated_at = ?, version = version + 1 WHERE id = ?')
    .run(now, req.params.resourceId);

  const updatedResource = db.prepare('SELECT * FROM medical_resources WHERE id = ?').get(req.params.resourceId);
  res.json(createSuccessResponse(serializeMedicalResource(updatedResource), 'object'));
});

module.exports = router;
