import request from 'supertest';
import { ActorType, DEFAULT_ACTOR_TYPE } from './constants';

export type ActorContext = {
  actor_id?: string;
  actor_type?: ActorType;
  session_id?: string;
  idempotency_key?: string;
};

export function getRequest() {
  const apiUrl = process.env.API_URL || 'http://localhost:3000';
  return request(apiUrl);
}

export function headersForContext(ctx: ActorContext): Record<string, string> {
  const headers: Record<string, string> = {};

  if (ctx.actor_id !== undefined) headers['X_Actor_Id'] = ctx.actor_id;
  if (ctx.actor_type !== undefined) headers['X_Actor_Type'] = ctx.actor_type;
  if (ctx.session_id !== undefined) headers['X_Session_Id'] = ctx.session_id;
  if (ctx.idempotency_key !== undefined) headers['Idempotency_Key'] = ctx.idempotency_key;

  return headers;
}

export function get(path: string, ctx: ActorContext = {}) {
  const finalCtx: ActorContext = {
    actor_id: ctx.actor_id,
    actor_type: ctx.actor_type ?? DEFAULT_ACTOR_TYPE,
    session_id: ctx.session_id,
    idempotency_key: ctx.idempotency_key
  };
  return getRequest().get(path).set(headersForContext(finalCtx));
}

export function post(path: string, body: any, ctx: ActorContext = {}, additionalHeaders?: Record<string, string>) {
  const finalCtx: ActorContext = {
    actor_id: ctx.actor_id,
    actor_type: ctx.actor_type ?? DEFAULT_ACTOR_TYPE,
    session_id: ctx.session_id,
    idempotency_key: ctx.idempotency_key
  };
  const req = getRequest().post(path).set(headersForContext(finalCtx));
  if (additionalHeaders) req.set(additionalHeaders);
  return req.send(body);
}

export function put(path: string, body: any, ctx: ActorContext = {}, additionalHeaders?: Record<string, string>) {
  const finalCtx: ActorContext = {
    actor_id: ctx.actor_id,
    actor_type: ctx.actor_type ?? DEFAULT_ACTOR_TYPE,
    session_id: ctx.session_id,
    idempotency_key: ctx.idempotency_key
  };
  const req = getRequest().put(path).set(headersForContext(finalCtx));
  if (additionalHeaders) req.set(additionalHeaders);
  return req.send(body);
}

export function del(path: string, ctx: ActorContext = {}, additionalHeaders?: Record<string, string>) {
  const finalCtx: ActorContext = {
    actor_id: ctx.actor_id,
    actor_type: ctx.actor_type ?? DEFAULT_ACTOR_TYPE,
    session_id: ctx.session_id,
    idempotency_key: ctx.idempotency_key
  };
  const req = getRequest().delete(path).set(headersForContext(finalCtx));
  if (additionalHeaders) req.set(additionalHeaders);
  return req;
}
