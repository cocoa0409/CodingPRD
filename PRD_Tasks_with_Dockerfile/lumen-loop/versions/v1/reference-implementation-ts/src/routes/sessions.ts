import type express from "express";
import type { Db } from "../db";
import { z } from "zod";
import { badRequest, notFound } from "../errors";
import { newId } from "../ids";
import { runMutating } from "./helpers";
import { sessionResponse } from "./responses";
import type { RequestWithCtx } from "../app";

export function registerSessionsRoutes(
  app: express.Express,
  db: Db,
  requireSessionIfNeeded: (req: RequestWithCtx, programId: string) => void
) {
  app.post("/programs/:program_id/sessions", (req, res, next) => {
    const programId = req.params.program_id;
    runMutating(
      db,
      requireSessionIfNeeded,
      req,
      res,
      next,
      { programScope: programId, programIdForSessionCheck: programId, sessionExempt: true },
      () => {
        const body = z
          .object({
            actor_id: z.string().min(1),
            actor_type: z.enum(["Customer", "Support", "Ops", "System"]),
          })
          .safeParse(req.body);
        if (!body.success) throw badRequest("ERR_INVALID_REQUEST", "Invalid request body");

        const sessionId = newId("session");
        db.prepare(
          `INSERT INTO sessions (session_id, program_id, actor_id, actor_type, session_status)
           VALUES (?, ?, ?, ?, 'ACTIVE')`
        ).run(sessionId, programId, body.data.actor_id, body.data.actor_type);

        const row = db
          .prepare(
            `SELECT session_id, actor_id, actor_type, session_status
             FROM sessions WHERE program_id = ? AND session_id = ?`
          )
          .get(programId, sessionId) as any;
        return { status: 201, body: sessionResponse(row) };
      }
    );
  });

  app.get("/programs/:program_id/sessions/:session_id", (req, res, next) => {
    try {
      const row = db
        .prepare(
          `SELECT session_id, actor_id, actor_type, session_status
           FROM sessions WHERE program_id = ? AND session_id = ?`
        )
        .get(req.params.program_id, req.params.session_id) as any;
      if (!row) throw notFound("Session not found");
      res.json(sessionResponse(row));
    } catch (e) {
      next(e);
    }
  });

  app.post("/programs/:program_id/sessions/:session_id/end", (req, res, next) => {
    const programId = req.params.program_id;
    const sessionId = req.params.session_id;
    runMutating(
      db,
      requireSessionIfNeeded,
      req,
      res,
      next,
      { programScope: programId, programIdForSessionCheck: programId },
      () => {
        const existing = db
          .prepare(
            `SELECT session_id, actor_id, actor_type, session_status
             FROM sessions WHERE program_id = ? AND session_id = ?`
          )
          .get(programId, sessionId) as any;
        if (!existing) throw notFound("Session not found");
        if (existing.session_status !== "ACTIVE") {
          throw badRequest("ERR_INVALID_STATE_TRANSITION", "Invalid state transition");
        }
        db.prepare(`UPDATE sessions SET session_status = 'ENDED' WHERE program_id = ? AND session_id = ?`).run(
          programId,
          sessionId
        );
        const row = db
          .prepare(
            `SELECT session_id, actor_id, actor_type, session_status
             FROM sessions WHERE program_id = ? AND session_id = ?`
          )
          .get(programId, sessionId) as any;
        return { status: 200, body: sessionResponse(row) };
      }
    );
  });
}
