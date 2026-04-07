import request from 'supertest';
import { v4 as uuidv4 } from 'uuid';
import { Role, DEFAULT_ROLE } from './constants';

function getRequest() {
  const apiUrl = process.env.API_URL || 'http://localhost:3000';
  return request(apiUrl);
}

export function generateIdempotencyKey(): string {
  return uuidv4();
}

export function headersForRole(role: Role = DEFAULT_ROLE, actorId?: string): Record<string, string> {
  return {
    'X-Role': role,
    'X-Actor-Id': actorId || `actor-${uuidv4().slice(0, 8)}`,
  };
}

export function getAs(path: string, role: Role = DEFAULT_ROLE, actorId?: string) {
  return getRequest()
    .get(path)
    .set(headersForRole(role, actorId));
}

export function getRaw(path: string, headers?: Record<string, string>) {
  const req = getRequest().get(path);
  if (headers) {
    Object.entries(headers).forEach(([key, value]) => req.set(key, value));
  }
  return req;
}

export interface PostOptions {
  role?: Role;
  actorId?: string;
  idempotencyKey?: string;
  ifMatch?: string;
  skipIdempotencyKey?: boolean;
  skipIfMatch?: boolean;
}

export function postAs(
  path: string,
  body: any,
  options: PostOptions = {}
) {
  const {
    role = DEFAULT_ROLE,
    actorId,
    idempotencyKey,
    ifMatch,
    skipIdempotencyKey = false,
    skipIfMatch = false,
  } = options;

  const req = getRequest()
    .post(path)
    .set(headersForRole(role, actorId));

  if (!skipIdempotencyKey) {
    req.set('Idempotency-Key', idempotencyKey || generateIdempotencyKey());
  }

  if (ifMatch && !skipIfMatch) {
    req.set('If-Match', ifMatch);
  }

  return req.send(body);
}

export function postRaw(path: string, body: any, headers?: Record<string, string>) {
  const req = getRequest().post(path);
  if (headers) {
    Object.entries(headers).forEach(([key, value]) => req.set(key, value));
  }
  return req.send(body);
}

export interface PutOptions {
  role?: Role;
  actorId?: string;
  ifMatch?: string;
  skipIfMatch?: boolean;
}

export function putAs(
  path: string,
  body: any,
  options: PutOptions = {}
) {
  const {
    role = DEFAULT_ROLE,
    actorId,
    ifMatch,
    skipIfMatch = false,
  } = options;

  const req = getRequest()
    .put(path)
    .set(headersForRole(role, actorId));

  if (ifMatch && !skipIfMatch) {
    req.set('If-Match', ifMatch);
  }

  return req.send(body);
}

export function putRaw(path: string, body: any, headers?: Record<string, string>) {
  const req = getRequest().put(path);
  if (headers) {
    Object.entries(headers).forEach(([key, value]) => req.set(key, value));
  }
  return req.send(body);
}

export function deleteAs(path: string, role: Role = DEFAULT_ROLE, actorId?: string) {
  return getRequest()
    .delete(path)
    .set(headersForRole(role, actorId));
}
