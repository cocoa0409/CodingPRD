import { Router, Request, Response } from 'express';
import crypto from 'crypto';
import db from '../db/schema';
import {
  roleMiddleware, studioLoader, idempotencyMiddleware, ifMatchMiddleware, requireIfMatch,
  requireRole, storeIdempotency
} from '../middleware';
import {
  getMix, createMix, updateMixEntries, submitMix, approveMix,
  publishMix, unpublishMix, freezeMix, archiveMix, validateEntries
} from '../services/mix.service';
import { getStudioWithDerived } from '../services/studio.service';
import { ERROR_CODES, MixKind, MixEntry } from '../types';

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

function mapErrorToResponse(error: string): { status: number; code: string } {
  const errorMap: Record<string, { status: number; code: string }> = {
    NOT_FOUND: { status: 404, code: ERROR_CODES.NOT_FOUND },
    INVALID_STATE: { status: 409, code: ERROR_CODES.INVALID_STATE },
    POSTURE_BLOCKED: { status: 409, code: ERROR_CODES.POSTURE_BLOCKED },
    ROLE_FORBIDDEN: { status: 403, code: ERROR_CODES.ROLE_FORBIDDEN },
    CYCLE_STALE: { status: 409, code: ERROR_CODES.CYCLE_STALE },
    TOKEN_BUDGET_EXCEEDED: { status: 409, code: ERROR_CODES.TOKEN_BUDGET_EXCEEDED },
    ENTRY_LIMIT: { status: 400, code: ERROR_CODES.ENTRY_LIMIT },
    ENTRY_DUPLICATE_PUBLIC: { status: 400, code: ERROR_CODES.ENTRY_DUPLICATE_PUBLIC },
    ENTRY_ADJACENT_DUPLICATE: { status: 400, code: ERROR_CODES.ENTRY_ADJACENT_DUPLICATE },
    SPOTLIGHT_NOT_ALLOWED: { status: 400, code: ERROR_CODES.SPOTLIGHT_NOT_ALLOWED },
    SPOTLIGHT_CAP_EXCEEDED: { status: 400, code: ERROR_CODES.SPOTLIGHT_CAP_EXCEEDED },
    ASSET_NOT_ACTIVE: { status: 409, code: ERROR_CODES.ASSET_NOT_ACTIVE },
    ASSET_QUARANTINED: { status: 409, code: ERROR_CODES.ASSET_QUARANTINED },
    CLEARANCE_REQUIRED: { status: 409, code: ERROR_CODES.CLEARANCE_REQUIRED },
    CLEARANCE_SUSPENDED: { status: 409, code: ERROR_CODES.CLEARANCE_SUSPENDED },
    CLEARANCE_POLICY_MISMATCH: { status: 409, code: ERROR_CODES.CLEARANCE_POLICY_MISMATCH },
    DISPUTE_BLOCKING: { status: 409, code: ERROR_CODES.DISPUTE_BLOCKING },
  };
  return errorMap[error] || { status: 400, code: ERROR_CODES.BAD_REQUEST };
}

router.post('/:studio_id/mixes',
  roleMiddleware,
  studioLoader,
  idempotencyMiddleware,
  (req: Request, res: Response) => {
    const studio = req.studio!;
    const role = req.role!;

    
    const { title, kind } = req.body;

    if (!title || typeof title !== 'string') {
      res.status(400).json({
        error: { code: ERROR_CODES.BAD_REQUEST, message: 'title is required' }
      });
      return;
    }

    if (!kind || !['PUBLIC', 'INTERNAL', 'EVIDENCE'].includes(kind)) {
      res.status(400).json({
        error: { code: ERROR_CODES.BAD_REQUEST, message: 'kind must be PUBLIC, INTERNAL, or EVIDENCE' }
      });
      return;
    }

    
    if (kind === 'EVIDENCE' && role !== 'legal') {
      res.status(403).json({
        error: { code: ERROR_CODES.ROLE_FORBIDDEN, message: 'Only legal can create EVIDENCE mixes' }
      });
      return;
    }

    if ((kind === 'PUBLIC' || kind === 'INTERNAL') && role !== 'curator') {
      res.status(403).json({
        error: { code: ERROR_CODES.ROLE_FORBIDDEN, message: 'Only curator can create PUBLIC or INTERNAL mixes' }
      });
      return;
    }

    const idempResult = checkIdempotencySync(req, res, studio.id, studio.cycle_index);
    if (idempResult) return;

    const mix = createMix(studio.id, title, kind as MixKind);

    const responseBody = { data: mix, effects: [] };

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

router.get('/:studio_id/mixes/:mix_id',
  roleMiddleware,
  studioLoader,
  (req: Request, res: Response) => {
    const mix = getMix(req.params.mix_id);
    if (!mix || mix.studio_id !== req.studioId) {
      res.status(404).json({
        error: { code: ERROR_CODES.NOT_FOUND, message: 'Mix not found' }
      });
      return;
    }
    res.json({ data: mix });
  }
);

router.put('/:studio_id/mixes/:mix_id/entries',
  roleMiddleware,
  studioLoader,
  ifMatchMiddleware,
  requireIfMatch,
  (req: Request, res: Response) => {
    const mix = getMix(req.params.mix_id);
    if (!mix || mix.studio_id !== req.studioId) {
      res.status(404).json({
        error: { code: ERROR_CODES.NOT_FOUND, message: 'Mix not found' }
      });
      return;
    }

    if (req.ifMatch !== mix.version) {
      res.status(412).json({
        error: { code: ERROR_CODES.VERSION_CONFLICT, message: 'Version mismatch' }
      });
      return;
    }

    const role = req.role!;

    
    if (mix.kind === 'EVIDENCE' && role !== 'legal') {
      res.status(403).json({
        error: { code: ERROR_CODES.ROLE_FORBIDDEN, message: 'Only legal can edit EVIDENCE mixes' }
      });
      return;
    }

    if ((mix.kind === 'PUBLIC' || mix.kind === 'INTERNAL') && role !== 'curator') {
      res.status(403).json({
        error: { code: ERROR_CODES.ROLE_FORBIDDEN, message: 'Only curator can edit PUBLIC or INTERNAL mixes' }
      });
      return;
    }

    const { entries } = req.body;

    if (!Array.isArray(entries)) {
      res.status(400).json({
        error: { code: ERROR_CODES.BAD_REQUEST, message: 'entries must be an array' }
      });
      return;
    }

    
    for (const entry of entries) {
      if (!entry.asset_id || typeof entry.asset_id !== 'string') {
        res.status(400).json({
          error: { code: ERROR_CODES.BAD_REQUEST, message: 'Each entry must have asset_id' }
        });
        return;
      }
      if (!entry.slot || !['NORMAL', 'SPOTLIGHT'].includes(entry.slot)) {
        res.status(400).json({
          error: { code: ERROR_CODES.BAD_REQUEST, message: 'Each entry must have slot (NORMAL or SPOTLIGHT)' }
        });
        return;
      }
    }

    const result = updateMixEntries(mix.id, entries as MixEntry[]);

    if ('error' in result) {
      const err = mapErrorToResponse(result.error);
      res.status(err.status).json({
        error: { code: err.code, message: result.error }
      });
      return;
    }

    res.json({ data: result.mix, effects: result.effects });
  }
);

router.post('/:studio_id/mixes/:mix_id/submit',
  roleMiddleware,
  studioLoader,
  idempotencyMiddleware,
  ifMatchMiddleware,
  requireRole('curator'),
  (req: Request, res: Response) => {
    const studio = req.studio!;
    const mix = getMix(req.params.mix_id);

    if (!mix || mix.studio_id !== req.studioId) {
      res.status(404).json({
        error: { code: ERROR_CODES.NOT_FOUND, message: 'Mix not found' }
      });
      return;
    }

    const idempResult = checkIdempotencySync(req, res, studio.id, studio.cycle_index);
    if (idempResult) return;

    if (req.ifMatch !== undefined && req.ifMatch !== mix.version) {
      res.status(412).json({
        error: { code: ERROR_CODES.VERSION_CONFLICT, message: 'Version mismatch' }
      });
      return;
    }

    const result = submitMix(mix.id);

    if ('error' in result) {
      const err = mapErrorToResponse(result.error);
      res.status(err.status).json({
        error: { code: err.code, message: result.error }
      });
      return;
    }

    const responseBody = { data: result.mix, effects: result.effects };

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

router.post('/:studio_id/mixes/:mix_id/approve',
  roleMiddleware,
  studioLoader,
  idempotencyMiddleware,
  ifMatchMiddleware,
  requireRole('manager'),
  (req: Request, res: Response) => {
    const studio = req.studio!;
    const mix = getMix(req.params.mix_id);

    if (!mix || mix.studio_id !== req.studioId) {
      res.status(404).json({
        error: { code: ERROR_CODES.NOT_FOUND, message: 'Mix not found' }
      });
      return;
    }

    const idempResult = checkIdempotencySync(req, res, studio.id, studio.cycle_index);
    if (idempResult) return;

    if (req.ifMatch !== undefined && req.ifMatch !== mix.version) {
      res.status(412).json({
        error: { code: ERROR_CODES.VERSION_CONFLICT, message: 'Version mismatch' }
      });
      return;
    }

    const result = approveMix(mix.id);

    if ('error' in result) {
      const err = mapErrorToResponse(result.error);
      res.status(err.status).json({
        error: { code: err.code, message: result.error }
      });
      return;
    }

    const responseBody = { data: result.mix, effects: result.effects };

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

router.post('/:studio_id/mixes/:mix_id/publish',
  roleMiddleware,
  studioLoader,
  idempotencyMiddleware,
  ifMatchMiddleware,
  (req: Request, res: Response) => {
    const studio = req.studio!;
    const role = req.role!;
    const mix = getMix(req.params.mix_id);

    if (!mix || mix.studio_id !== req.studioId) {
      res.status(404).json({
        error: { code: ERROR_CODES.NOT_FOUND, message: 'Mix not found' }
      });
      return;
    }

    
    if (mix.kind === 'EVIDENCE' && role !== 'legal') {
      res.status(403).json({
        error: { code: ERROR_CODES.ROLE_FORBIDDEN, message: 'Only legal can publish EVIDENCE mixes' }
      });
      return;
    }

    if ((mix.kind === 'PUBLIC' || mix.kind === 'INTERNAL') && role !== 'manager') {
      res.status(403).json({
        error: { code: ERROR_CODES.ROLE_FORBIDDEN, message: 'Only manager can publish PUBLIC or INTERNAL mixes' }
      });
      return;
    }

    const idempResult = checkIdempotencySync(req, res, studio.id, studio.cycle_index);
    if (idempResult) return;

    if (req.ifMatch !== undefined && req.ifMatch !== mix.version) {
      res.status(412).json({
        error: { code: ERROR_CODES.VERSION_CONFLICT, message: 'Version mismatch' }
      });
      return;
    }

    const result = publishMix(mix.id, role as 'manager' | 'legal');

    if ('error' in result) {
      const err = mapErrorToResponse(result.error);
      res.status(err.status).json({
        error: { code: err.code, message: result.error }
      });
      return;
    }

    const responseBody = { data: result.mix, effects: result.effects };

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

router.post('/:studio_id/mixes/:mix_id/unpublish',
  roleMiddleware,
  studioLoader,
  idempotencyMiddleware,
  ifMatchMiddleware,
  (req: Request, res: Response) => {
    const studio = req.studio!;
    const role = req.role!;
    const mix = getMix(req.params.mix_id);

    if (!mix || mix.studio_id !== req.studioId) {
      res.status(404).json({
        error: { code: ERROR_CODES.NOT_FOUND, message: 'Mix not found' }
      });
      return;
    }

    
    if (role !== 'manager' && role !== 'legal') {
      res.status(403).json({
        error: { code: ERROR_CODES.ROLE_FORBIDDEN, message: 'Only manager or legal can unpublish mixes' }
      });
      return;
    }

    const idempResult = checkIdempotencySync(req, res, studio.id, studio.cycle_index);
    if (idempResult) return;

    if (req.ifMatch !== undefined && req.ifMatch !== mix.version) {
      res.status(412).json({
        error: { code: ERROR_CODES.VERSION_CONFLICT, message: 'Version mismatch' }
      });
      return;
    }

    const result = unpublishMix(mix.id, role as 'manager' | 'legal');

    if ('error' in result) {
      const err = mapErrorToResponse(result.error);
      res.status(err.status).json({
        error: { code: err.code, message: result.error }
      });
      return;
    }

    const responseBody = { data: result.mix, effects: result.effects };

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

router.post('/:studio_id/mixes/:mix_id/freeze',
  roleMiddleware,
  studioLoader,
  idempotencyMiddleware,
  ifMatchMiddleware,
  requireRole('legal'),
  (req: Request, res: Response) => {
    const studio = req.studio!;
    const mix = getMix(req.params.mix_id);

    if (!mix || mix.studio_id !== req.studioId) {
      res.status(404).json({
        error: { code: ERROR_CODES.NOT_FOUND, message: 'Mix not found' }
      });
      return;
    }

    const idempResult = checkIdempotencySync(req, res, studio.id, studio.cycle_index);
    if (idempResult) return;

    if (req.ifMatch !== undefined && req.ifMatch !== mix.version) {
      res.status(412).json({
        error: { code: ERROR_CODES.VERSION_CONFLICT, message: 'Version mismatch' }
      });
      return;
    }

    const result = freezeMix(mix.id);

    if ('error' in result) {
      const err = mapErrorToResponse(result.error);
      res.status(err.status).json({
        error: { code: err.code, message: result.error }
      });
      return;
    }

    const responseBody = { data: result.mix, effects: result.effects };

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

router.post('/:studio_id/mixes/:mix_id/archive',
  roleMiddleware,
  studioLoader,
  idempotencyMiddleware,
  ifMatchMiddleware,
  (req: Request, res: Response) => {
    const studio = req.studio!;
    const role = req.role!;
    const mix = getMix(req.params.mix_id);

    if (!mix || mix.studio_id !== req.studioId) {
      res.status(404).json({
        error: { code: ERROR_CODES.NOT_FOUND, message: 'Mix not found' }
      });
      return;
    }

    const idempResult = checkIdempotencySync(req, res, studio.id, studio.cycle_index);
    if (idempResult) return;

    if (req.ifMatch !== undefined && req.ifMatch !== mix.version) {
      res.status(412).json({
        error: { code: ERROR_CODES.VERSION_CONFLICT, message: 'Version mismatch' }
      });
      return;
    }

    if (role !== 'manager') {
      res.status(403).json({
        error: { code: ERROR_CODES.ROLE_FORBIDDEN, message: 'Only manager can archive mixes' }
      });
      return;
    }

    const result = archiveMix(mix.id);

    if ('error' in result) {
      const err = mapErrorToResponse(result.error);
      res.status(err.status).json({
        error: { code: err.code, message: result.error }
      });
      return;
    }

    const responseBody = { data: result.mix, effects: result.effects };

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
