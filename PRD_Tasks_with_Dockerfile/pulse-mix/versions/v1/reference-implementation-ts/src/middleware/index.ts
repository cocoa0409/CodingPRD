import { Request, Response, NextFunction } from 'express';
import crypto from 'crypto';
import db from '../db/schema';
import { Role, ERROR_CODES, StudioRow } from '../types';

declare global {
  namespace Express {
    interface Request {
      role?: Role;
      studioId?: string;
      studio?: StudioRow;
      ifMatch?: number;
      idempotencyKey?: string;
    }
  }
}

export function roleMiddleware(req: Request, res: Response, next: NextFunction): void {
  const role = req.headers['x-studio-role'] as string;
  if (!role || !['curator', 'manager', 'legal'].includes(role)) {
    res.status(400).json({
      error: { code: ERROR_CODES.BAD_REQUEST, message: 'Invalid or missing X-Studio-Role header' }
    });
    return;
  }
  req.role = role as Role;
  next();
}

export function requireRole(...roles: Role[]) {
  return (req: Request, res: Response, next: NextFunction): void => {
    if (!req.role || !roles.includes(req.role)) {
      res.status(403).json({
        error: { code: ERROR_CODES.ROLE_FORBIDDEN, message: `This action requires one of roles: ${roles.join(', ')}` }
      });
      return;
    }
    next();
  };
}

export function studioLoader(req: Request, res: Response, next: NextFunction): void {
  const studioId = req.params.studio_id;
  if (!studioId) {
    next();
    return;
  }

  const studio = db.prepare('SELECT * FROM studios WHERE id = ?').get(studioId) as StudioRow | undefined;
  if (!studio) {
    res.status(404).json({
      error: { code: ERROR_CODES.NOT_FOUND, message: `Studio ${studioId} not found` }
    });
    return;
  }

  req.studioId = studioId;
  req.studio = studio;
  next();
}

export function ifMatchMiddleware(req: Request, res: Response, next: NextFunction): void {
  const ifMatch = req.headers['if-match'] as string;
  if (ifMatch) {
    const version = parseInt(ifMatch, 10);
    if (isNaN(version)) {
      res.status(400).json({
        error: { code: ERROR_CODES.BAD_REQUEST, message: 'If-Match must be a valid integer' }
      });
      return;
    }
    req.ifMatch = version;
  }
  next();
}

export function requireIfMatch(req: Request, res: Response, next: NextFunction): void {
  if (req.ifMatch === undefined) {
    res.status(428).json({
      error: { code: ERROR_CODES.MISSING_IF_MATCH, message: 'If-Match header is required' }
    });
    return;
  }
  next();
}

function hashBody(body: unknown): string {
  const str = JSON.stringify(body || {});
  return crypto.createHash('sha256').update(str).digest('hex');
}

export function idempotencyMiddleware(req: Request, res: Response, next: NextFunction): void {
  if (req.method !== 'POST') {
    next();
    return;
  }

  const key = req.headers['idempotency-key'] as string;
  if (!key) {
    res.status(400).json({
      error: { code: ERROR_CODES.MISSING_IDEMPOTENCY_KEY, message: 'Idempotency-Key header is required for POST requests' }
    });
    return;
  }

  req.idempotencyKey = key;
  next();
}

export function checkIdempotency(studioId: string, cycleIndex: number) {
  return (req: Request, res: Response, next: NextFunction): void => {
    if (req.method !== 'POST' || !req.idempotencyKey) {
      next();
      return;
    }

    const method = req.method;
    const path = req.originalUrl;
    const bodyHash = hashBody(req.body);

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
        return;
      }
      res.status(existing.response_status).json(JSON.parse(existing.response_body));
      return;
    }

    next();
  };
}

export function storeIdempotency(
  studioId: string,
  cycleIndex: number,
  key: string,
  method: string,
  path: string,
  body: unknown,
  responseStatus: number,
  responseBody: unknown
): void {
  const bodyHash = hashBody(body);
  db.prepare(`
    INSERT OR REPLACE INTO idempotency_keys
    (key, studio_id, cycle_index, method, path, request_body_hash, response_status, response_body)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
  `).run(key, studioId, cycleIndex, method, path, bodyHash, responseStatus, JSON.stringify(responseBody));
}

export function clearIdempotencyForCycle(studioId: string, cycleIndex: number): void {
  db.prepare('DELETE FROM idempotency_keys WHERE studio_id = ? AND cycle_index = ?').run(studioId, cycleIndex);
}
