import express from "express";
import type { Db } from "./db";
import { ApiError } from "./errors";
import { readContext } from "./http";
import { ensureActiveSession } from "./sessions";

export type RequestWithCtx = express.Request & { ctx?: ReturnType<typeof readContext> };

export function createApp(db: Db) {
  const app = express();
  app.use(express.json({ limit: "1mb" }));

  app.use((req, _res, next) => {
    try {
      (req as RequestWithCtx).ctx = readContext(req);
      next();
    } catch (e) {
      next(e);
    }
  });

  function requireSessionIfNeeded(req: RequestWithCtx, programId: string) {
    const ctx = req.ctx!;
    const needsSession = ctx.actorType === "Customer" || ctx.actorType === "Support" || ctx.actorType === "Ops";
    if (!needsSession) return;
    if (!ctx.sessionId) {
      throw new ApiError(400, "ERR_MISSING_OR_INVALID_CONTEXT_HEADER", "Missing or invalid context header");
    }
    ensureActiveSession(db, programId, ctx.sessionId, ctx.actorId, ctx.actorType);
  }

  (app as any).requireSessionIfNeeded = requireSessionIfNeeded;

  return app;
}
