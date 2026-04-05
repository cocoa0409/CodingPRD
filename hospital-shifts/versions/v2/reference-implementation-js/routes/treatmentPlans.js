const express = require('express');
const router = express.Router();
const db = require('../db/database');
const { authorize } = require('../middleware/auth');
const { createSuccessResponse, createErrorResponse, generateUUID, getTimestamp } = require('../utils/response');
const { serializeTreatmentPlan } = require('../utils/serializers');

// POST /treatment-plans - Create a new Treatment Plan
router.post('/', authorize('ChargeNurse'), (req, res) => {
  const { plan_name, total_budget, policies } = req.body;

  // Strict type validation
  if (!plan_name || typeof plan_name !== 'string' || Array.isArray(plan_name) || typeof plan_name === 'object') {
    const error = createErrorResponse('ERR_INVALID_REQUEST', 'plan_name must be a string', 400);
    return res.status(error.statusCode).json(error.body);
  }

  if (total_budget === undefined || total_budget === null || typeof total_budget !== 'number' || Array.isArray(total_budget) || typeof total_budget === 'object') {
    const error = createErrorResponse('ERR_INVALID_REQUEST', 'total_budget must be a number', 400);
    return res.status(error.statusCode).json(error.body);
  }

  const id = generateUUID();
  const now = getTimestamp();

  // Serialize policies to JSON string if provided
  const policiesJson = policies ? JSON.stringify(policies) : null;

  db.prepare(`
    INSERT INTO treatment_plans (id, plan_name, status, total_budget, cost_balance, patient_safety_score, policies, created_at, updated_at, version)
    VALUES (?, ?, 'PLANNING', ?, ?, 0, ?, ?, ?, 1)
  `).run(id, plan_name, total_budget, total_budget, policiesJson, now, now);

  db.prepare('INSERT INTO budget_ledgers (plan_id, provisional_debits, finalized_debits) VALUES (?, 0.0, 0.0)').run(id);
  db.prepare('INSERT INTO safety_ledgers (plan_id, safety_score) VALUES (?, 0)').run(id);

  const plan = db.prepare('SELECT * FROM treatment_plans WHERE id = ?').get(id);
  res.status(201).json(createSuccessResponse(serializeTreatmentPlan(plan), 'object'));
});

// GET /treatment-plans - List all Treatment Plans
router.get('/', (req, res) => {
  const limit = Math.min(Math.max(parseInt(req.query.limit) || 10, 1), 100);
  const offset = Math.max(parseInt(req.query.offset) || 0, 0);

  const plans = db.prepare('SELECT * FROM treatment_plans ORDER BY created_at ASC LIMIT ? OFFSET ?').all(limit, offset);
  const totalCount = db.prepare('SELECT COUNT(*) as count FROM treatment_plans').get().count;

  const response = createSuccessResponse(
    plans.map(serializeTreatmentPlan),
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

// GET /treatment-plans/:planId - Get a specific Treatment Plan
router.get('/:planId', (req, res) => {
  const plan = db.prepare('SELECT * FROM treatment_plans WHERE id = ?').get(req.params.planId);

  if (!plan) {
    const error = createErrorResponse('ERR_PLAN_NOT_FOUND', 'Treatment plan not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  res.json(createSuccessResponse(serializeTreatmentPlan(plan), 'object'));
});

// POST /treatment-plans/:planId/activate - Activate a plan
router.post('/:planId/activate', authorize('ChargeNurse'), (req, res) => {
  const plan = db.prepare('SELECT * FROM treatment_plans WHERE id = ?').get(req.params.planId);

  if (!plan) {
    const error = createErrorResponse('ERR_PLAN_NOT_FOUND', 'Treatment plan not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  // OCC version check
  if (req.body.version !== undefined && req.body.version !== plan.version) {
    const error = createErrorResponse('ERR_STALE_DATA', 'Version mismatch - data has been modified', 409);
    return res.status(error.statusCode).json(error.body);
  }

  if (plan.status !== 'PLANNING') {
    const error = createErrorResponse('ERR_PLAN_NOT_IN_PLANNING', 'Plan must be in PLANNING state to activate', 409);
    return res.status(error.statusCode).json(error.body);
  }

  db.prepare('UPDATE treatment_plans SET status = ?, updated_at = ?, version = version + 1 WHERE id = ?')
    .run('ACTIVE', getTimestamp(), req.params.planId);

  const updatedPlan = db.prepare('SELECT * FROM treatment_plans WHERE id = ?').get(req.params.planId);
  res.json(createSuccessResponse(serializeTreatmentPlan(updatedPlan), 'object'));
});

// POST /treatment-plans/:planId/initiate-final-review - Initiate final review
router.post('/:planId/initiate-final-review', authorize('ChargeNurse'), (req, res) => {
  const plan = db.prepare('SELECT * FROM treatment_plans WHERE id = ?').get(req.params.planId);

  if (!plan) {
    const error = createErrorResponse('ERR_PLAN_NOT_FOUND', 'Treatment plan not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  // OCC version check
  if (req.body.version !== undefined && req.body.version !== plan.version) {
    const error = createErrorResponse('ERR_STALE_DATA', 'Version mismatch - data has been modified', 409);
    return res.status(error.statusCode).json(error.body);
  }

  if (plan.status !== 'ACTIVE') {
    const error = createErrorResponse('ERR_PLAN_NOT_ACTIVE', 'Plan must be ACTIVE', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const unresolvedAssignments = db.prepare(`
    SELECT * FROM assignments
    WHERE plan_id = ? AND status IN ('PENDING_SCHEDULE', 'PROTOCOL_APPROVED')
  `).all(req.params.planId);

  if (unresolvedAssignments.length > 0) {
    const error = createErrorResponse('ERR_UNRESOLVED_ASSIGNMENTS_EXIST', 'Cannot initiate final review with unresolved assignments', 409);
    return res.status(error.statusCode).json(error.body);
  }

  db.prepare('UPDATE treatment_plans SET status = ?, updated_at = ?, version = version + 1 WHERE id = ?')
    .run('FINAL_REVIEW_PENDING', getTimestamp(), req.params.planId);

  const updatedPlan = db.prepare('SELECT * FROM treatment_plans WHERE id = ?').get(req.params.planId);
  res.json(createSuccessResponse(serializeTreatmentPlan(updatedPlan), 'object'));
});

module.exports = router;
