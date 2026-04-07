import { Router, Request, Response } from 'express';
import {
  roleMiddleware, studioLoader, idempotencyMiddleware, ifMatchMiddleware, requireIfMatch,
  requireRole, checkIdempotency, storeIdempotency
} from '../middleware';
import {
  getAsset, createAsset, updateAsset, activateAsset, legalDurationCorrection,
  recalculateMixTokenCosts
} from '../services/asset.service';
import { getStudioWithDerived, shedBudget, getStudioEffect } from '../services/studio.service';
import { Effect, ERROR_CODES } from '../types';

const router = Router();

router.post('/:studio_id/assets',
  roleMiddleware,
  studioLoader,
  idempotencyMiddleware,
  requireRole('curator'),
  (req: Request, res: Response) => {
    const studio = req.studio!;

    
    const idempResult = checkIdempotencySync(req, res, studio.id, studio.cycle_index);
    if (idempResult) return;

    const { title, duration_sec } = req.body;

    if (!title || typeof title !== 'string') {
      res.status(400).json({
        error: { code: ERROR_CODES.BAD_REQUEST, message: 'title is required' }
      });
      return;
    }

    if (typeof duration_sec !== 'number' || duration_sec <= 0) {
      res.status(400).json({
        error: { code: ERROR_CODES.BAD_REQUEST, message: 'duration_sec must be a positive number' }
      });
      return;
    }

    const asset = createAsset(studio.id, title, duration_sec);

    const responseBody = { data: asset, effects: [] };

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

router.get('/:studio_id/assets/:asset_id',
  roleMiddleware,
  studioLoader,
  (req: Request, res: Response) => {
    const asset = getAsset(req.params.asset_id);
    if (!asset || asset.studio_id !== req.studioId) {
      res.status(404).json({
        error: { code: ERROR_CODES.NOT_FOUND, message: 'Asset not found' }
      });
      return;
    }
    res.json({ data: asset });
  }
);

router.patch('/:studio_id/assets/:asset_id',
  roleMiddleware,
  studioLoader,
  ifMatchMiddleware,
  requireIfMatch,
  (req: Request, res: Response) => {
    const asset = getAsset(req.params.asset_id);
    if (!asset || asset.studio_id !== req.studioId) {
      res.status(404).json({
        error: { code: ERROR_CODES.NOT_FOUND, message: 'Asset not found' }
      });
      return;
    }

    
    if (req.ifMatch !== asset.version) {
      res.status(412).json({
        error: { code: ERROR_CODES.VERSION_CONFLICT, message: 'Version mismatch' }
      });
      return;
    }

    const { title, duration_sec } = req.body;
    const role = req.role!;

    
    if (role === 'curator') {
      if (asset.status !== 'DRAFT') {
        res.status(409).json({
          error: { code: ERROR_CODES.INVALID_STATE, message: 'Curator can only edit DRAFT assets' }
        });
        return;
      }

      const updates: { title?: string; duration_sec?: number } = {};
      if (title !== undefined) updates.title = title;
      if (duration_sec !== undefined) updates.duration_sec = duration_sec;

      const updated = updateAsset(asset.id, updates);
      res.json({ data: updated, effects: [] });
      return;
    }

    
    if (role === 'legal') {
      if (asset.status !== 'ACTIVE' && asset.status !== 'QUARANTINED') {
        res.status(409).json({
          error: { code: ERROR_CODES.INVALID_STATE, message: 'Legal can only correct duration on ACTIVE or QUARANTINED assets' }
        });
        return;
      }

      if (duration_sec === undefined || typeof duration_sec !== 'number') {
        res.status(400).json({
          error: { code: ERROR_CODES.BAD_REQUEST, message: 'duration_sec is required for legal correction' }
        });
        return;
      }

      const result = legalDurationCorrection(asset.id, duration_sec);
      if ('error' in result) {
        res.status(409).json({
          error: { code: ERROR_CODES.INVALID_STATE, message: result.error }
        });
        return;
      }

      
      const tokenEffects = recalculateMixTokenCosts(asset.id);
      result.effects.push(...tokenEffects);

      
      const shedEffects = shedBudget(req.studioId!);
      result.effects.push(...shedEffects);

      if (shedEffects.length > 0 || tokenEffects.length > 0) {
        result.effects.push(getStudioEffect(req.studioId!));
      }

      res.json({ data: result.asset, effects: dedupeEffects(result.effects) });
      return;
    }

    res.status(403).json({
      error: { code: ERROR_CODES.ROLE_FORBIDDEN, message: 'This action is not allowed for your role' }
    });
  }
);

router.post('/:studio_id/assets/:asset_id/activate',
  roleMiddleware,
  studioLoader,
  idempotencyMiddleware,
  ifMatchMiddleware,
  requireRole('curator'),
  (req: Request, res: Response) => {
    const studio = req.studio!;
    const asset = getAsset(req.params.asset_id);

    if (!asset || asset.studio_id !== req.studioId) {
      res.status(404).json({
        error: { code: ERROR_CODES.NOT_FOUND, message: 'Asset not found' }
      });
      return;
    }

    
    const idempResult = checkIdempotencySync(req, res, studio.id, studio.cycle_index);
    if (idempResult) return;

    
    if (req.ifMatch !== undefined && req.ifMatch !== asset.version) {
      res.status(412).json({
        error: { code: ERROR_CODES.VERSION_CONFLICT, message: 'Version mismatch' }
      });
      return;
    }

    const result = activateAsset(asset.id);

    if ('error' in result) {
      const errorMap: Record<string, { status: number; code: string }> = {
        NOT_FOUND: { status: 404, code: ERROR_CODES.NOT_FOUND },
        INVALID_STATE: { status: 409, code: ERROR_CODES.INVALID_STATE },
        POSTURE_BLOCKED: { status: 409, code: ERROR_CODES.POSTURE_BLOCKED },
        CLEARANCE_REQUIRED: { status: 409, code: ERROR_CODES.CLEARANCE_REQUIRED },
        DISPUTE_BLOCKING: { status: 409, code: ERROR_CODES.DISPUTE_BLOCKING },
      };
      const err = errorMap[result.error] || { status: 400, code: ERROR_CODES.BAD_REQUEST };
      res.status(err.status).json({
        error: { code: err.code, message: result.error }
      });
      return;
    }

    const responseBody = { data: result.asset, effects: result.effects };

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

function checkIdempotencySync(req: Request, res: Response, studioId: string, cycleIndex: number): boolean {
  if (req.method !== 'POST' || !req.idempotencyKey) return false;

  const crypto = require('crypto');
  const db = require('../db/schema').default;

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

function dedupeEffects(effects: Effect[]): Effect[] {
  const mergedByKey = new Map<string, Effect>();
  const order: string[] = [];

  for (const effect of effects) {
    const key = `${effect.type}:${effect.id}`;
    const existing = mergedByKey.get(key);
    if (!existing) {
      mergedByKey.set(key, { ...effect });
      order.push(key);
      continue;
    }

    const merged: Effect = { ...existing };
    for (const [k, v] of Object.entries(effect) as [keyof Effect, unknown][]) {
      if (v !== undefined) {
        (merged as any)[k] = v;
      }
    }
    merged.version = Math.max(existing.version, effect.version);
    mergedByKey.set(key, merged);
  }

  return order.map((k) => mergedByKey.get(k)!).filter(Boolean);
}

export default router;
