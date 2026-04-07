import { Router, Request, Response } from 'express';
import crypto from 'crypto';
import db from '../db/schema';
import {
  roleMiddleware, studioLoader, idempotencyMiddleware, ifMatchMiddleware,
  requireRole, storeIdempotency
} from '../middleware';
import { createDispute, getDispute, resolveDispute, voidDispute } from '../services/dispute.service';
import { ERROR_CODES, DisputeSeverity, DisputeTargetType } from '../types';

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

router.post('/:studio_id/disputes',
  roleMiddleware,
  studioLoader,
  idempotencyMiddleware,
  requireRole('legal'),
  (req: Request, res: Response) => {
    const studio = req.studio!;

    const idempResult = checkIdempotencySync(req, res, studio.id, studio.cycle_index);
    if (idempResult) return;

    const { target_type, target_id, severity } = req.body;

    if (!target_type || !['ASSET', 'MIX'].includes(target_type)) {
      res.status(400).json({
        error: { code: ERROR_CODES.BAD_REQUEST, message: 'target_type must be ASSET or MIX' }
      });
      return;
    }

    if (!target_id || typeof target_id !== 'string') {
      res.status(400).json({
        error: { code: ERROR_CODES.BAD_REQUEST, message: 'target_id is required' }
      });
      return;
    }

    if (!severity || !['LOW', 'HIGH'].includes(severity)) {
      res.status(400).json({
        error: { code: ERROR_CODES.BAD_REQUEST, message: 'severity must be LOW or HIGH' }
      });
      return;
    }

    const result = createDispute(
      studio.id,
      target_type as DisputeTargetType,
      target_id,
      severity as DisputeSeverity
    );

    if ('error' in result) {
      if (result.error === 'NOT_FOUND') {
        res.status(404).json({
          error: { code: ERROR_CODES.NOT_FOUND, message: 'Target not found' }
        });
        return;
      }
      res.status(400).json({
        error: { code: ERROR_CODES.BAD_REQUEST, message: result.error }
      });
      return;
    }

    const responseBody = { data: result.dispute, effects: result.effects };

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

router.post('/:studio_id/disputes/:dispute_id/resolve',
  roleMiddleware,
  studioLoader,
  idempotencyMiddleware,
  ifMatchMiddleware,
  requireRole('legal'),
  (req: Request, res: Response) => {
    const studio = req.studio!;
    const disputeId = req.params.dispute_id;

    const dispute = getDispute(disputeId);
    if (!dispute || dispute.studio_id !== studio.id) {
      res.status(404).json({
        error: { code: ERROR_CODES.NOT_FOUND, message: 'Dispute not found' }
      });
      return;
    }

    const idempResult = checkIdempotencySync(req, res, studio.id, studio.cycle_index);
    if (idempResult) return;

    if (req.ifMatch !== undefined && req.ifMatch !== dispute.version) {
      res.status(412).json({
        error: { code: ERROR_CODES.VERSION_CONFLICT, message: 'Version mismatch' }
      });
      return;
    }

    const { resolution } = req.body;

    if (!resolution || !['UPHELD', 'DISMISSED', 'VOID'].includes(resolution)) {
      res.status(400).json({
        error: { code: ERROR_CODES.BAD_REQUEST, message: 'resolution must be UPHELD, DISMISSED, or VOID' }
      });
      return;
    }

    let result;
    if (resolution === 'VOID') {
      result = voidDispute(disputeId);
    } else {
      result = resolveDispute(disputeId, resolution as 'UPHELD' | 'DISMISSED');
    }

    if ('error' in result) {
      if (result.error === 'NOT_FOUND') {
        res.status(404).json({
          error: { code: ERROR_CODES.NOT_FOUND, message: 'Dispute not found' }
        });
        return;
      }
      if (result.error === 'INVALID_STATE') {
        res.status(409).json({
          error: { code: ERROR_CODES.INVALID_STATE, message: 'Dispute is not in an open or escalated state' }
        });
        return;
      }
      res.status(400).json({
        error: { code: ERROR_CODES.BAD_REQUEST, message: result.error }
      });
      return;
    }

    const responseBody = { data: result.dispute, effects: result.effects };

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
