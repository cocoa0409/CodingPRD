import type { Db } from "./db";
import { badRequest } from "./errors";
import type { ActorType } from "./types";

export function ensureActiveSession(
  db: Db,
  programId: string,
  sessionId: string,
  actorId: string,
  actorType: ActorType
) {
  const row = db
    .prepare(
      `SELECT session_id
       FROM sessions
       WHERE program_id = ? AND session_id = ? AND actor_id = ? AND actor_type = ? AND session_status = 'ACTIVE'`
    )
    .get(programId, sessionId, actorId, actorType) as { session_id: string } | undefined;
  if (!row) throw badRequest("ERR_SESSION_NOT_ACTIVE", "Session not active");
}
