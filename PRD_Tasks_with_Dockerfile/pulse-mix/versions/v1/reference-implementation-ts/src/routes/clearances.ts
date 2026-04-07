import { Router, Request, Response } from 'express';
import crypto from 'crypto';
import db from '../db/schema';
import {
  roleMiddleware, studioLoader, idempotencyMiddleware, ifMatchMiddleware,
  requireRole, storeIdempotency
} from '../middleware';
import {
  getClearance, createClearance, grantClearance, suspendClearance, revokeClearance
} from '../services/clearance.service';
import { ERROR_CODES, ClearancePolicy } from '../types';

const router = Router();

function checkIdempotencySync(req: Request, res: Response, studioId: string, cycleIndex: number): boolean {
  if (req.method !== 'POST' || !req.idempotencyKey) return false;

  const method = req.method;
  const path = req.originalUrl;
  const bodyStr = JSON.stringify(req.body || {});
  const bodyHash = crypto.createHash('sha256').update(bodyStr).digest('hex');

  const existing = db.prepare(`
    SELECT * FROM idempotency_keys
    WHERE key = ? AND studio_id = ? AND cycle_index = ? AND method = ? AND path = ?
  `).get(req.idempotencyKey, studioId, cycleIndex, method, path) as {
    request_body_hash: string;
    response_status: number;
    response_body: string;
  } | undefined;

  if (existing) {
    if (existing.request_body_hash !== bodyHash) {
      res.status(409).json({
        error: { code: ERROR_CODES.IDEMPOTENCY_REPLAY_MISMATCH, message: 'Idempotency key reused with different request body' }
      });
      return true;
    }
    res.status(existing.response_status).json(JSON.parse(existing.response_body));
    return true;
  }

  return false;
}

router.post('/:studio_id/clearances',
  roleMiddleware,
  studioLoader,
  idempotencyMiddleware,
  requireRole('legal'),
  (req: Request, res: Response) => {
    const studio = req.studio!;

    const idempResult = checkIdempotencySync(req, res, studio.id, studio.cycle_index);
    if (idempResult) return;

    const { asset_id, policy } = req.body;

    if (!asset_id || typeof asset_id !== 'string') {
      res.status(400).json({
        error: { code: ERROR_CODES.BAD_REQUEST, message: 'asset_id is required' }
      });
      return;
    }

    if (!policy || !['FULL', 'PROMO'].includes(policy)) {
      res.status(400).json({
        error: { code: ERROR_CODES.BAD_REQUEST, message: 'policy must be FULL or PROMO' }
      });
      return;
    }

    const result = createClearance(studio.id, asset_id, policy as ClearancePolicy);

    if ('error' in result) {
      if (result.error === 'NOT_FOUND') {
        res.status(404).json({
          error: { code: ERROR_CODES.NOT_FOUND, message: 'Asset not found' }
        });
        return;
      }
      if (result.error === 'CLEARANCE_ALREADY_EXISTS') {
        res.status(409).json({
          error: { code: ERROR_CODES.CLEARANCE_ALREADY_EXISTS, message: 'Clearance already exists for this asset' }
        });
        return;
      }
      res.status(400).json({
        error: { code: ERROR_CODES.BAD_REQUEST, message: result.error }
      });
      return;
    }

    const responseBody = { data: result, effects: [] };

    if (req.idempotencyKey) {
      storeIdempotency(
        studio.id,
        studio.cycle_index,
        req.idempotencyKey,
        req.method,
        req.originalUrl,
        req.body,
        201,
        responseBody
      );
    }

    res.status(201).json(responseBody);
  }
);

router.post('/:studio_id/clearances/:clearance_id/grant',
  roleMiddleware,
  studioLoader,
  idempotencyMiddleware,
  ifMatchMiddleware,
  requireRole('legal'),
  (req: Request, res: Response) => {
    const studio = req.studio!;
    const clearanceId = req.params.clearance_id;

    const clearance = getClearance(clearanceId);
    if (!clearance || clearance.studio_id !== studio.id) {
      res.status(404).json({
        error: { code: ERROR_CODES.NOT_FOUND, message: 'Clearance not found' }
      });
      return;
    }

    const idempResult = checkIdempotencySync(req, res, studio.id, studio.cycle_index);
    if (idempResult) return;

    if (req.ifMatch !== undefined && req.ifMatch !== clearance.version) {
      res.status(412).json({
        error: { code: ERROR_CODES.VERSION_CONFLICT, message: 'Version mismatch' }
      });
      return;
    }

    const result = grantClearance(clearanceId, studio.id);

    if ('error' in result) {
      if (result.error === 'NOT_FOUND') {
        res.status(404).json({
          error: { code: ERROR_CODES.NOT_FOUND, message: 'Clearance not found' }
        });
        return;
      }
      if (result.error === 'POSTURE_BLOCKED') {
        res.status(409).json({
          error: { code: ERROR_CODES.POSTURE_BLOCKED, message: 'Cannot grant clearance while studio is in HALT posture' }
        });
        return;
      }
      if (result.error === 'INVALID_STATE') {
        res.status(409).json({
          error: { code: ERROR_CODES.INVALID_STATE, message: 'Cannot grant a revoked clearance' }
        });
        return;
      }
      res.status(400).json({
        error: { code: ERROR_CODES.BAD_REQUEST, message: result.error }
      });
      return;
    }

    const responseBody = { data: result.clearance, effects: result.effects };

    if (req.idempotencyKey) {
      storeIdempotency(
        studio.id,
        studio.cycle_index,
        req.idempotencyKey,
        req.method,
        req.originalUrl,
        req.body,
        200,
        responseBody
      );
    }

    res.json(responseBody);
  }
);

router.post('/:studio_id/clearances/:clearance_id/suspend',
  roleMiddleware,
  studioLoader,
  idempotencyMiddleware,
  ifMatchMiddleware,
  requireRole('legal'),
  (req: Request, res: Response) => {
    const studio = req.studio!;
    const clearanceId = req.params.clearance_id;

    const clearance = getClearance(clearanceId);
    if (!clearance || clearance.studio_id !== studio.id) {
      res.status(404).json({
        error: { code: ERROR_CODES.NOT_FOUND, message: 'Clearance not found' }
      });
      return;
    }

    const idempResult = checkIdempotencySync(req, res, studio.id, studio.cycle_index);
    if (idempResult) return;

    if (req.ifMatch !== undefined && req.ifMatch !== clearance.version) {
      res.status(412).json({
        error: { code: ERROR_CODES.VERSION_CONFLICT, message: 'Version mismatch' }
      });
      return;
    }

    const result = suspendClearance(clearanceId, studio.id);

    if ('error' in result) {
      if (result.error === 'NOT_FOUND') {
        res.status(404).json({
          error: { code: ERROR_CODES.NOT_FOUND, message: 'Clearance not found' }
        });
        return;
      }
      if (result.error === 'INVALID_STATE') {
        res.status(409).json({
          error: { code: ERROR_CODES.INVALID_STATE, message: 'Cannot suspend a revoked clearance' }
        });
        return;
      }
      res.status(400).json({
        error: { code: ERROR_CODES.BAD_REQUEST, message: result.error }
      });
      return;
    }

    const responseBody = { data: result.clearance, effects: result.effects };

    if (req.idempotencyKey) {
      storeIdempotency(
        studio.id,
        studio.cycle_index,
        req.idempotencyKey,
        req.method,
        req.originalUrl,
        req.body,
        200,
        responseBody
      );
    }

    res.json(responseBody);
  }
);

router.post('/:studio_id/clearances/:clearance_id/revoke',
  roleMiddleware,
  studioLoader,
  idempotencyMiddleware,
  ifMatchMiddleware,
  requireRole('legal'),
  (req: Request, res: Response) => {
    const studio = req.studio!;
    const clearanceId = req.params.clearance_id;

    const clearance = getClearance(clearanceId);
    if (!clearance || clearance.studio_id !== studio.id) {
      res.status(404).json({
        error: { code: ERROR_CODES.NOT_FOUND, message: 'Clearance not found' }
      });
      return;
    }

    const idempResult = checkIdempotencySync(req, res, studio.id, studio.cycle_index);
    if (idempResult) return;

    if (req.ifMatch !== undefined && req.ifMatch !== clearance.version) {
      res.status(412).json({
        error: { code: ERROR_CODES.VERSION_CONFLICT, message: 'Version mismatch' }
      });
      return;
    }

    const result = revokeClearance(clearanceId, studio.id, false);

    if ('error' in result) {
      if (result.error === 'NOT_FOUND') {
        res.status(404).json({
          error: { code: ERROR_CODES.NOT_FOUND, message: 'Clearance not found' }
        });
        return;
      }
      if (result.error === 'INVALID_STATE') {
        res.status(409).json({
          error: { code: ERROR_CODES.INVALID_STATE, message: 'Clearance is already revoked' }
        });
        return;
      }
      res.status(400).json({
        error: { code: ERROR_CODES.BAD_REQUEST, message: result.error }
      });
      return;
    }

    const responseBody = { data: result.clearance, effects: result.effects };

    if (req.idempotencyKey) {
      storeIdempotency(
        studio.id,
        studio.cycle_index,
        req.idempotencyKey,
        req.method,
        req.originalUrl,
        req.body,
        200,
        responseBody
      );
    }

    res.json(responseBody);
  }
);

export default router;
