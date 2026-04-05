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

  const { resource_name, resource_model, operating_cost_per_minute, maintenance_threshold_override, sterilization_buffer_override, setup_overhead_minutes, teardown_overhead_minutes } = req.body;

  // Reject attempts to manually set status on creation (non-normative field)
  if (req.body.status !== undefined) {
    const error = createErrorResponse('ERR_INVALID_REQUEST', 'status field is not allowed on resource creation', 400);
    return res.status(error.statusCode).json(error.body);
  }

  // Validate maintenance_threshold_override if provided
  if (maintenance_threshold_override !== undefined && maintenance_threshold_override !== null) {
    if (typeof maintenance_threshold_override !== 'number' || maintenance_threshold_override < 0) {
      const error = createErrorResponse('ERR_INVALID_THRESHOLD', 'The maintenance_threshold_override value is invalid', 400);
      return res.status(error.statusCode).json(error.body);
    }
  }

  // Validate sterilization_buffer_override if provided
  if (sterilization_buffer_override !== undefined && sterilization_buffer_override !== null) {
    if (!Number.isInteger(sterilization_buffer_override) || sterilization_buffer_override < 0) {
      const error = createErrorResponse('ERR_INVALID_REQUEST', 'The sterilization_buffer_override value is invalid', 400);
      return res.status(error.statusCode).json(error.body);
    }
  }

  // Validate overhead minutes (default to 0)
  const setupOverhead = setup_overhead_minutes !== undefined ? setup_overhead_minutes : 0;
  const teardownOverhead = teardown_overhead_minutes !== undefined ? teardown_overhead_minutes : 0;

  if (typeof setupOverhead !== 'number' || setupOverhead < 0 || !Number.isInteger(setupOverhead) ||
      typeof teardownOverhead !== 'number' || teardownOverhead < 0 || !Number.isInteger(teardownOverhead)) {
    const error = createErrorResponse('ERR_INVALID_REQUEST', 'Overhead minutes must be non-negative integers', 400);
    return res.status(error.statusCode).json(error.body);
  }

  const id = generateUUID();
  const now = getTimestamp();

  db.prepare(`
    INSERT INTO medical_resources (id, plan_id, resource_name, resource_model, operating_cost_per_minute, maintenance_threshold_override, sterilization_buffer_override, setup_overhead_minutes, teardown_overhead_minutes, status, created_at, updated_at, version)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'AVAILABLE', ?, ?, 1)
  `).run(
    id,
    req.params.planId,
    resource_name,
    resource_model,
    operating_cost_per_minute,
    maintenance_threshold_override !== undefined ? maintenance_threshold_override : null,
    sterilization_buffer_override !== undefined ? sterilization_buffer_override : null,
    setupOverhead,
    teardownOverhead,
    now,
    now
  );

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

// POST /treatment-plans/:planId/medical-resources/:resourceId/decommission - Initiate decommissioning
router.post('/:resourceId/decommission', authorize('HospitalAdministrator'), (req, res) => {
  const plan = db.prepare('SELECT * FROM treatment_plans WHERE id = ?').get(req.params.planId);
  if (!plan) {
    const error = createErrorResponse('ERR_PLAN_NOT_FOUND', 'Treatment plan not found', 404);
    return res.status(error.statusCode).json(error.body);
  }
  if (plan.status !== 'ACTIVE') {
    const error = createErrorResponse('ERR_PLAN_NOT_ACTIVE', 'The plan must be ACTIVE to modify resources', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const resource = db.prepare('SELECT * FROM medical_resources WHERE id = ? AND plan_id = ?').get(req.params.resourceId, req.params.planId);
  if (!resource) {
    const error = createErrorResponse('ERR_RESOURCE_NOT_FOUND', 'Medical resource not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  // OCC
  if (req.body.version !== undefined && req.body.version !== resource.version) {
    const error = createErrorResponse('ERR_STALE_DATA', 'Version mismatch - data has been modified', 409);
    return res.status(error.statusCode).json(error.body);
  }

  if (resource.status === 'DECOMMISSIONED') {
    const error = createErrorResponse('ERR_RESOURCE_ALREADY_DECOMMISSIONED', 'Resource already decommissioned', 409);
    return res.status(error.statusCode).json(error.body);
  }

  // Check outstanding commitments (non-terminal assignments)
  // Must check BOTH primary and secondary roles
  const allAssignments = db.prepare(`
    SELECT id, resource_id, secondary_resource_ids FROM assignments
    WHERE plan_id = ? AND status IN ('PENDING_SCHEDULE','PROTOCOL_APPROVED','SCHEDULED')
  `).all(req.params.planId);
  
  // Filter in JavaScript to check both primary and secondary roles
  const resourceCommitments = allAssignments.filter(a => {
    if (a.resource_id === resource.id) return true;
    if (a.secondary_resource_ids) {
      try {
        const secondaries = typeof a.secondary_resource_ids === 'string' 
          ? JSON.parse(a.secondary_resource_ids) 
          : a.secondary_resource_ids;
        return secondaries.includes(resource.id);
      } catch (e) {
        return false;
      }
    }
    return false;
  });
  const activeAssignments = resourceCommitments.length;

  const now = getTimestamp();
  if (activeAssignments === 0) {
    db.prepare('UPDATE medical_resources SET status = ?, updated_at = ?, version = version + 1 WHERE id = ?')
      .run('DECOMMISSIONED', now, resource.id);
  } else {
    db.prepare('UPDATE medical_resources SET status = ?, updated_at = ?, version = version + 1 WHERE id = ?')
      .run('DECOMMISSIONING_PENDING', now, resource.id);
  }

  const updated = db.prepare('SELECT * FROM medical_resources WHERE id = ?').get(resource.id);
  res.json(createSuccessResponse(serializeMedicalResource(updated), 'object'));
});

// POST /treatment-plans/:planId/medical-resources/:resourceId/cancel-decommissioning - Cancel pending decommissioning
router.post('/:resourceId/cancel-decommissioning', authorize('HospitalAdministrator'), (req, res) => {
  const plan = db.prepare('SELECT * FROM treatment_plans WHERE id = ?').get(req.params.planId);
  if (!plan) {
    const error = createErrorResponse('ERR_PLAN_NOT_FOUND', 'Treatment plan not found', 404);
    return res.status(error.statusCode).json(error.body);
  }
  if (plan.status !== 'ACTIVE') {
    const error = createErrorResponse('ERR_PLAN_NOT_ACTIVE', 'The plan must be ACTIVE to modify resources', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const resource = db.prepare('SELECT * FROM medical_resources WHERE id = ? AND plan_id = ?').get(req.params.resourceId, req.params.planId);
  if (!resource) {
    const error = createErrorResponse('ERR_RESOURCE_NOT_FOUND', 'Medical resource not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  // OCC
  if (req.body.version !== undefined && req.body.version !== resource.version) {
    const error = createErrorResponse('ERR_STALE_DATA', 'Version mismatch - data has been modified', 409);
    return res.status(error.statusCode).json(error.body);
  }

  if (resource.status !== 'DECOMMISSIONING_PENDING') {
    const error = createErrorResponse('ERR_DECOMMISSIONING_NOT_PENDING', 'Decommissioning is not pending for this resource', 409);
    return res.status(error.statusCode).json(error.body);
  }

  db.prepare('UPDATE medical_resources SET status = ?, updated_at = ?, version = version + 1 WHERE id = ?')
    .run('AVAILABLE', getTimestamp(), resource.id);

  const updated = db.prepare('SELECT * FROM medical_resources WHERE id = ?').get(resource.id);
  res.json(createSuccessResponse(serializeMedicalResource(updated), 'object'));
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
