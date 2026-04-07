import request from 'supertest';
import { v4 as uuidv4 } from 'uuid';

export type ApiResponse = {
  status: number;
  body: any;
  headers: Record<string, any>;
};

function getRequest() {
  const apiUrl = process.env.API_URL || 'http://localhost:3000';
  return request(apiUrl);
}

async function dispatch(method: string, url: string, body?: any, headers?: Record<string, string>): Promise<ApiResponse> {
  const req = getRequest();
  let r: request.Test;

  switch (method.toUpperCase()) {
    case 'GET':
      r = req.get(url);
      break;
    case 'POST':
      r = req.post(url);
      break;
    case 'PUT':
      r = req.put(url);
      break;
    case 'PATCH':
      r = req.patch(url);
      break;
    case 'DELETE':
      r = req.delete(url);
      break;
    default:
      throw new Error(`Unsupported method: ${method}`);
  }

  if (headers) {
    Object.entries(headers).forEach(([key, value]) => r.set(key, value));
  }

  if (body !== undefined) {
    r.send(body);
  }

  const res = await r;
  return {
    status: res.status,
    body: res.body,
    headers: res.headers,
  };
}

export function idempotencyKey(prefix: string = 'idem'): string {
  return `${prefix}-${uuidv4()}`;
}

export function get(path: string) {
  return dispatch('GET', path, undefined, { 'Content-Type': 'application/json' });
}

export function post(
  path: string,
  body: any,
  idempotencyKeyValue?: string
) {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (idempotencyKeyValue) headers['Idempotency-Key'] = idempotencyKeyValue;
  return dispatch('POST', path, body, headers);
}

export function postState(
  path: string,
  body: any,
  etag: string,
  idempotencyKeyValue?: string
) {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'If-Match': etag,
  };
  if (idempotencyKeyValue) headers['Idempotency-Key'] = idempotencyKeyValue;
  return dispatch('POST', path, body, headers);
}

export function patch(
  path: string,
  body: any,
  etag: string,
  idempotencyKeyValue?: string
) {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'If-Match': etag,
  };
  if (idempotencyKeyValue) headers['Idempotency-Key'] = idempotencyKeyValue;
  return dispatch('PATCH', path, body, headers);
}

export function postRaw(path: string, body: any, headers?: Record<string, string>) {
  return dispatch('POST', path, body, { 'Content-Type': 'application/json', ...(headers || {}) });
}

export function patchRaw(path: string, body: any, headers?: Record<string, string>) {
  return dispatch('PATCH', path, body, { 'Content-Type': 'application/json', ...(headers || {}) });
}

export function getRaw(path: string, headers?: Record<string, string>) {
  return dispatch('GET', path, undefined, headers);
}

export const headersForRole = (_role?: string, _userId?: string) => ({});

export function getAs(path: string, _role?: string, _userId?: string) {
  return get(path);
}

export function postAs(
  path: string,
  body: any,
  _role?: string,
  additionalHeaders?: Record<string, string>,
  _userId?: string
) {
  return dispatch('POST', path, body, { 'Content-Type': 'application/json', ...(additionalHeaders || {}) });
}

export function putAs(path: string, body: any, _role?: string, _userId?: string) {
  return dispatch('PUT', path, body, { 'Content-Type': 'application/json' });
}

export function deleteAs(path: string, _role?: string, _userId?: string) {
  return dispatch('DELETE', path);
}
