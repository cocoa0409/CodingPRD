import request from 'supertest';
import { v4 as uuidv4 } from 'uuid';
import { Role, DEFAULT_ROLE } from './constants';

export const headersForRole = (role: Role = DEFAULT_ROLE, userId?: string) => ({
  'X-User-Role': role,
  'X-User-ID': userId || uuidv4()
});

function getRequest() {
  const apiUrl = process.env.API_URL || 'http://localhost:3000';
  return request(apiUrl);
}

function dispatch(
  method: string,
  requestPath: string,
  body?: any,
  headers?: Record<string, string>
) {
  const req = getRequest();
  let r: request.Test;

  switch (method.toUpperCase()) {
    case 'GET':
      r = req.get(requestPath);
      break;
    case 'POST':
      r = req.post(requestPath);
      break;
    case 'PUT':
      r = req.put(requestPath);
      break;
    case 'PATCH':
      r = req.patch(requestPath);
      break;
    case 'DELETE':
      r = req.delete(requestPath);
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

  return r;
}

export function getAs(path: string, role: Role = DEFAULT_ROLE, userId?: string) {
  return dispatch('GET', path, undefined, headersForRole(role, userId) as any);
}

export function get(path: string) {
  return dispatch('GET', path);
}

export function postAs(
  path: string,
  body: any,
  role: Role = DEFAULT_ROLE,
  additionalHeaders?: Record<string, string>,
  userId?: string
) {
  return dispatch('POST', path, body, { ...(headersForRole(role, userId) as any), ...(additionalHeaders || {}) });
}

export function post(path: string, body: any, headers?: Record<string, string>) {
  return dispatch('POST', path, body, headers);
}

export function getRaw(path: string, headers?: Record<string, string>) {
  return dispatch('GET', path, undefined, headers);
}

export function postRaw(path: string, body: any, headers?: Record<string, string>) {
  return dispatch('POST', path, body, headers);
}

export function putWithVersion(
  path: string,
  body: any,
  version: string | number,
  role: Role = DEFAULT_ROLE,
  userId?: string
) {
  return dispatch('PUT', path, body, { ...(headersForRole(role, userId) as any), 'If-Match': String(version) });
}

export function putWithoutVersion(path: string, body: any, role: Role = DEFAULT_ROLE, userId?: string) {
  return dispatch('PUT', path, body, headersForRole(role, userId) as any);
}

export function putRaw(path: string, body: any, headers?: Record<string, string>) {
  return dispatch('PUT', path, body, headers);
}

export function patchWithVersion(
  path: string,
  body: any,
  version: string | number,
  role: Role = DEFAULT_ROLE,
  userId?: string
) {
  return dispatch('PATCH', path, body, { ...(headersForRole(role, userId) as any), 'If-Match': String(version) });
}

export function patchWithoutVersion(path: string, body: any, role: Role = DEFAULT_ROLE, userId?: string) {
  return dispatch('PATCH', path, body, headersForRole(role, userId) as any);
}

export function patchRaw(path: string, body: any, headers?: Record<string, string>) {
  return dispatch('PATCH', path, body, headers);
}

export function putAs(path: string, body: any, role: Role = DEFAULT_ROLE, userId?: string) {
  return dispatch('PUT', path, body, headersForRole(role, userId) as any);
}

export function deleteAs(path: string, role: Role = DEFAULT_ROLE, userId?: string) {
  return dispatch('DELETE', path, undefined, headersForRole(role, userId) as any);
}
