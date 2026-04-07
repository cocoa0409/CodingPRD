import request from 'supertest';
import { v4 as uuidv4 } from 'uuid';
import { Role, DEFAULT_ROLE, HEADERS } from './constants';

function getRequest() {
  const apiUrl = process.env.API_URL || 'http://localhost:3000';
  return request(apiUrl);
}

export function generateIdempotencyKey(prefix: string = 'ik'): string {
  return `${prefix}-${uuidv4()}`;
}

export const headersForRole = (role: Role = DEFAULT_ROLE) => ({
  [HEADERS.ACTOR_ROLE]: role,
});

export const headersWithIdempotency = (
  role: Role = DEFAULT_ROLE,
  idempotencyKey?: string
) => ({
  [HEADERS.ACTOR_ROLE]: role,
  [HEADERS.IDEMPOTENCY_KEY]: idempotencyKey || generateIdempotencyKey(),
});

export const headersWithIfMatch = (
  role: Role = DEFAULT_ROLE,
  etag: string,
  idempotencyKey?: string
) => ({
  [HEADERS.ACTOR_ROLE]: role,
  [HEADERS.IDEMPOTENCY_KEY]: idempotencyKey || generateIdempotencyKey(),
  [HEADERS.IF_MATCH]: etag,
});

export function getAs(path: string, role: Role = DEFAULT_ROLE) {
  return getRequest().get(path).set(headersForRole(role));
}

export function postAs(
  path: string,
  body: any,
  role: Role = DEFAULT_ROLE,
  idempotencyKey?: string,
  additionalHeaders?: Record<string, string>
) {
  const req = getRequest()
    .post(path)
    .set(headersWithIdempotency(role, idempotencyKey));
  if (additionalHeaders) {
    Object.entries(additionalHeaders).forEach(([key, value]) => {
      req.set(key, value);
    });
  }
  return req.send(body);
}

export function postWithIfMatch(
  path: string,
  body: any,
  etag: string,
  role: Role = DEFAULT_ROLE,
  idempotencyKey?: string
) {
  return getRequest()
    .post(path)
    .set(headersWithIfMatch(role, etag, idempotencyKey))
    .send(body);
}

export function getRaw(path: string, headers?: Record<string, string>) {
  const req = getRequest().get(path);
  if (headers) {
    Object.entries(headers).forEach(([key, value]) => req.set(key, value));
  }
  return req;
}

export function postRaw(path: string, body: any, headers?: Record<string, string>) {
  const req = getRequest().post(path);
  if (headers) {
    Object.entries(headers).forEach(([key, value]) => req.set(key, value));
  }
  return req.send(body);
}

export function putAs(path: string, body: any, role: Role = DEFAULT_ROLE) {
  return getRequest().put(path).set(headersForRole(role)).send(body);
}

export function deleteAs(path: string, role: Role = DEFAULT_ROLE) {
  return getRequest().delete(path).set(headersForRole(role));
}
