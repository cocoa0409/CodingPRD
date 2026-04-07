import { Request, Response, NextFunction } from 'express';
import crypto from 'crypto';
import { db } from '../db/schema';
import { ApiError, ErrorCodes, IdempotencyKeyRow } from '../types';

function hashPayload(payload: any): string {
  return crypto.createHash('sha256').update(JSON.stringify(payload)).digest('hex');
}

function ensureWorkspaceLedgerRow(workspaceId: string) {
  db.prepare(`
    INSERT INTO workspace_ledger_versions (workspace_id, version)
    VALUES (?, 0)
    ON CONFLICT(workspace_id) DO NOTHING
  `).run(workspaceId);
}

function getWorkspaceLedgerVersion(workspaceId: string): number {
  ensureWorkspaceLedgerRow(workspaceId);
  const row = db.prepare(`SELECT version FROM workspace_ledger_versions WHERE workspace_id = ?`).get(workspaceId) as { version: number } | undefined;
  return row?.version ?? 0;
}

function bumpWorkspaceLedgerVersion(workspaceId: string): number {
  ensureWorkspaceLedgerRow(workspaceId);
  const row = db.prepare(`
    UPDATE workspace_ledger_versions
    SET version = version + 1
    WHERE workspace_id = ?
    RETURNING version
  `).get(workspaceId) as { version: number } | undefined;

  return row?.version ?? getWorkspaceLedgerVersion(workspaceId);
}

export function idempotencyMiddleware(req: Request, res: Response, next: NextFunction) {
  const idempotencyKey = req.context?.idempotencyKey;
  const workspaceId = req.params.workspace_id;

  if (!workspaceId || req.method === 'GET') {
    return next();
  }

  const path = `${req.baseUrl}${req.path}`;
  const payloadHash = hashPayload(req.body);

  if (idempotencyKey) {
    const existing = db.prepare(`
      SELECT * FROM idempotency_keys
      WHERE workspace_id = ? AND idempotency_key = ? AND path = ?
    `).get(workspaceId, idempotencyKey, path) as IdempotencyKeyRow | undefined;

    if (existing) {
      if (existing.payload_hash !== payloadHash) {
        throw new ApiError(
          ErrorCodes.IDEMPOTENCY_CONFLICT,
          'Idempotency key was used with a different request',
          409
        );
      }

      const currentLedgerVersion = getWorkspaceLedgerVersion(workspaceId);
      if (currentLedgerVersion !== existing.ledger_version) {
        throw new ApiError(
          ErrorCodes.IDEMPOTENCY_CONFLICT,
          'Idempotency key conflicts because the ledger changed',
          409
        );
      }

      const cachedResponse = JSON.parse(existing.response);
      return res.status(cachedResponse.statusCode).json(cachedResponse.body);
    }
  }

  const originalJson = res.json.bind(res);
  res.json = function(body: any) {

    if (res.statusCode >= 200 && res.statusCode < 300) {
      try {
        const ledgerVersion = bumpWorkspaceLedgerVersion(workspaceId);

        if (idempotencyKey) {
          db.prepare(`
            INSERT INTO idempotency_keys (workspace_id, idempotency_key, path, payload_hash, ledger_version, response)
            VALUES (?, ?, ?, ?, ?, ?)
          `).run(
            workspaceId,
            idempotencyKey,
            path,
            payloadHash,
            ledgerVersion,
            JSON.stringify({ statusCode: res.statusCode, body })
          );
        }
      } catch (e) {

      }
    } else if (idempotencyKey && res.statusCode >= 400 && res.statusCode < 500) {

      try {
        const ledgerVersion = getWorkspaceLedgerVersion(workspaceId);
        db.prepare(`
          INSERT INTO idempotency_keys (workspace_id, idempotency_key, path, payload_hash, ledger_version, response)
          VALUES (?, ?, ?, ?, ?, ?)
        `).run(
          workspaceId,
          idempotencyKey,
          path,
          payloadHash,
          ledgerVersion,
          JSON.stringify({ statusCode: res.statusCode, body })
        );
      } catch (e) {

      }
    }
    return originalJson(body);
  };

  next();
}
