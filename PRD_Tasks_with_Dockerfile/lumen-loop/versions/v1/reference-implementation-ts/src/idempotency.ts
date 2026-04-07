import stringify from "fast-json-stable-stringify";
import type { Db } from "./db";
import { badRequest } from "./errors";

export type IdempotentResult = { status: number; body: unknown };

export function requestHash(method: string, path: string, body: unknown): string {
  return stringify({ method, path, body });
}

export function runIdempotent(
  db: Db,
  programScope: string,
  idempotencyKey: string,
  reqHash: string,
  action: () => IdempotentResult
): IdempotentResult {
  const existing = db
    .prepare(
      `SELECT request_hash, response_status, response_body
       FROM idempotency_keys
       WHERE program_scope = ? AND idempotency_key = ?`
    )
    .get(programScope, idempotencyKey) as
    | { request_hash: string; response_status: number; response_body: string }
    | undefined;

  if (existing) {
    if (existing.request_hash !== reqHash) {
      throw badRequest("ERR_IDEMPOTENCY_CONFLICT", "Idempotency key conflict");
    }
    return { status: existing.response_status, body: JSON.parse(existing.response_body) };
  }

  const result = action();
  db.prepare(
    `INSERT INTO idempotency_keys (program_scope, idempotency_key, request_hash, response_status, response_body)
     VALUES (?, ?, ?, ?, ?)`
  ).run(programScope, idempotencyKey, reqHash, result.status, JSON.stringify(result.body));
  return result;
}
