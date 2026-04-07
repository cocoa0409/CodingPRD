import type { Request } from "express";
import { z } from "zod";
import { badRequest, forbidden } from "./errors";
import { ActorTypes, type ActorType } from "./types";

export type RequestContext = {
  actorId: string;
  actorType: ActorType;
  sessionId: string | null;
  idempotencyKey: string | null;
};

export function readContext(req: Request): RequestContext {
  const actorId = req.header("X_Actor_Id")?.trim();
  const actorType = req.header("X_Actor_Type")?.trim();
  const sessionId = req.header("X_Session_Id")?.trim() ?? null;
  const idempotencyKey = req.header("Idempotency_Key")?.trim() ?? null;

  const actorTypeParsed = z.enum(ActorTypes).safeParse(actorType);
  if (!actorId || !actorTypeParsed.success) {
    throw badRequest(
      "ERR_MISSING_OR_INVALID_CONTEXT_HEADER",
      "Missing or invalid context header"
    );
  }
  if (sessionId === "") {
    throw badRequest(
      "ERR_MISSING_OR_INVALID_CONTEXT_HEADER",
      "Missing or invalid context header"
    );
  }
  if (idempotencyKey === "") {
    throw badRequest("ERR_INVALID_REQUEST", "Idempotency_Key must be non-empty if provided");
  }

  return {
    actorId,
    actorType: actorTypeParsed.data,
    sessionId,
    idempotencyKey,
  };
}

export function requireOps(ctx: RequestContext) {
  if (ctx.actorType !== "Ops") throw forbidden("Forbidden for actor");
}
