const express = require('express');
const router = express.Router({ mergeParams: true });
const db = require('../db/database');
const { authorize } = require('../middleware/auth');
const { createSuccessResponse, createErrorResponse, generateUUID, getTimestamp } = require('../utils/response');
const { serializeInfectionRiskPairing } = require('../utils/serializers');

router.post('/', authorize('ChargeNurse'), (req, res) => {
  const plan = db.prepare('SELECT * FROM treatment_plans WHERE id = ?').get(req.params.planId);

  if (!plan) {
    const error = createErrorResponse('ERR_PLAN_NOT_FOUND', 'Treatment plan not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  if (plan.status !== 'ACTIVE') {
    const error = createErrorResponse('ERR_PLAN_NOT_ACTIVE', 'Plan must be ACTIVE to create pairings', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const { resource_id_1, resource_id_2, reason } = req.body;

  if (resource_id_1 === resource_id_2) {
    const error = createErrorResponse('ERR_SELF_PAIRING', 'Cannot pair a resource with itself', 400);
    return res.status(error.statusCode).json(error.body);
  }

  const resource1 = db.prepare('SELECT * FROM medical_resources WHERE id = ? AND plan_id = ?')
    .get(resource_id_1, req.params.planId);
  const resource2 = db.prepare('SELECT * FROM medical_resources WHERE id = ? AND plan_id = ?')
    .get(resource_id_2, req.params.planId);

  if (!resource1 || !resource2) {
    const error = createErrorResponse('ERR_RESOURCE_NOT_FOUND', 'One or both resources not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  const allPairings = db.prepare('SELECT * FROM infection_risk_pairings WHERE plan_id = ?')
    .all(req.params.planId);
  const existingPairing = allPairings.find(p =>
    (p.resource_id_1 === resource_id_1 && p.resource_id_2 === resource_id_2) ||
    (p.resource_id_1 === resource_id_2 && p.resource_id_2 === resource_id_1)
  );

  if (existingPairing) {
    const error = createErrorResponse('ERR_DUPLICATE_PAIRING', 'This pairing already exists', 409);
    return res.status(error.statusCode).json(error.body);
  }

  const id = generateUUID();
  const now = getTimestamp();

  db.prepare(`
    INSERT INTO infection_risk_pairings (id, plan_id, resource_id_1, resource_id_2, reason, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
  `).run(id, req.params.planId, resource_id_1, resource_id_2, reason, now);

  const pairing = db.prepare('SELECT * FROM infection_risk_pairings WHERE id = ?').get(id);
  res.status(201).json(createSuccessResponse(serializeInfectionRiskPairing(pairing), 'object'));
});

router.get('/', (req, res) => {
  const plan = db.prepare('SELECT * FROM treatment_plans WHERE id = ?').get(req.params.planId);

  if (!plan) {
    const error = createErrorResponse('ERR_PLAN_NOT_FOUND', 'Treatment plan not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  const limit = Math.min(Math.max(parseInt(req.query.limit) || 10, 1), 100);
  const offset = Math.max(parseInt(req.query.offset) || 0, 0);

  const pairings = db.prepare('SELECT * FROM infection_risk_pairings WHERE plan_id = ? ORDER BY created_at ASC LIMIT ? OFFSET ?')
    .all(req.params.planId, limit, offset);
  const totalCount = db.prepare('SELECT COUNT(*) as count FROM infection_risk_pairings WHERE plan_id = ?')
    .get(req.params.planId).count;

  const response = createSuccessResponse(
    pairings.map(serializeInfectionRiskPairing),
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

router.get('/:pairingId', (req, res) => {
  const pairing = db.prepare('SELECT * FROM infection_risk_pairings WHERE id = ? AND plan_id = ?')
    .get(req.params.pairingId, req.params.planId);

  if (!pairing) {
    const error = createErrorResponse('ERR_PAIRING_NOT_FOUND', 'Infection risk pairing not found', 404);
    return res.status(error.statusCode).json(error.body);
  }

  res.json(createSuccessResponse(serializeInfectionRiskPairing(pairing), 'object'));
});

module.exports = router;
