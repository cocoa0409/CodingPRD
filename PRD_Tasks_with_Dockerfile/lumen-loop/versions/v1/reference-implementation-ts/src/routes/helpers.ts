import type express from "express";
import { requestHash, runIdempotent } from "../idempotency";
import type { Db } from "../db";
import type { RequestWithCtx } from "../app";
import { badRequest } from "../errors";
import { readContext } from "../http";
import { recomputeAvailability, recomputePosture } from "../domain";

export type MutateResult = { status: number; body: unknown };

export type MutateOptions = {
  programScope: string;
  programIdForSessionCheck?: string;
  sessionExempt?: boolean;
};

export function runMutating(
  db: Db,
  requireSessionIfNeeded: (req: RequestWithCtx, programId: string) => void,
  req: RequestWithCtx,
  res: express.Response,
  next: express.NextFunction,
  opts: MutateOptions,
  action: () => MutateResult
) {
  try {
    const ctx = req.ctx ?? readContext(req);
    if (!opts.sessionExempt && opts.programIdForSessionCheck) {
      requireSessionIfNeeded(req, opts.programIdForSessionCheck);
    }

    const idemKey = ctx.idempotencyKey;
    const reqHash = requestHash(req.method, req.path, req.body ?? null);
    const tx = db.transaction(() => {
      if (opts.programScope !== "__global__") {
        const exists = db
          .prepare(`SELECT 1 AS ok FROM programs WHERE program_id = ? LIMIT 1`)
          .get(opts.programScope) as { ok: 1 } | undefined;
        if (exists) {
          recomputeAvailability(db, opts.programScope);
          recomputePosture(db, opts.programScope);
        }
      }
      if (idemKey) {
        return runIdempotent(db, opts.programScope, idemKey, reqHash, action);
      }
      return action();
    });

    const result = tx();
    res.status(result.status).json(result.body);
  } catch (e) {
    next(e);
  }
}

export function ensureNonEmptyParam(name: string, value: string | undefined) {
  if (!value) throw badRequest("ERR_INVALID_REQUEST", `Missing ${name}`);
}
