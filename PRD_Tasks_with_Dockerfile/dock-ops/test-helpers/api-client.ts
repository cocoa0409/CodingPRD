import request from 'supertest';
import { v4 as uuidv4 } from 'uuid';
import { Role, DEFAULT_ROLE } from './constants';

export type ApiResponseLike = {
  status: number;
  body: any;
  headers: Record<string, any>;
  text: string;
};

function getRequest() {
  const apiUrl = process.env.API_URL || 'http://localhost:3000';
  return request(apiUrl);
}

async function dispatch(method: string, urlPath: string, body?: any, headers?: Record<string, string>): Promise<ApiResponseLike> {
  const req = getRequest();
  let r: request.Test;

  switch (method.toUpperCase()) {
    case 'GET':
      r = req.get(urlPath);
      break;
    case 'POST':
      r = req.post(urlPath);
      break;
    case 'PUT':
      r = req.put(urlPath);
      break;
    case 'DELETE':
      r = req.delete(urlPath);
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
    text: res.text,
  };
}

export const headersForRole = (role: Role = DEFAULT_ROLE, userId?: string) => ({
  'X-User-Role': role,
  'X-User-ID': userId || uuidv4()
});

export function getRaw(urlPath: string, headers?: Record<string, string>) {
  return dispatch('GET', urlPath, undefined, headers);
}

export function postRaw(urlPath: string, body: any, headers?: Record<string, string>) {
  return dispatch('POST', urlPath, body, headers);
}

export function putRaw(urlPath: string, body: any, headers?: Record<string, string>) {
  return dispatch('PUT', urlPath, body, headers);
}

export function getAs(urlPath: string, role: Role = DEFAULT_ROLE, userId?: string) {
  return dispatch('GET', urlPath, undefined, headersForRole(role, userId));
}

export function postAs(
  urlPath: string,
  body: any,
  role: Role = DEFAULT_ROLE,
  additionalHeaders?: Record<string, string>,
  userId?: string
) {
  return dispatch('POST', urlPath, body, { ...headersForRole(role, userId), ...(additionalHeaders ?? {}) });
}

export function putAs(urlPath: string, body: any, role: Role = DEFAULT_ROLE, userId?: string) {
  return dispatch('PUT', urlPath, body, headersForRole(role, userId));
}

export function deleteAs(urlPath: string, role: Role = DEFAULT_ROLE, userId?: string) {
  return dispatch('DELETE', urlPath, undefined, headersForRole(role, userId));
}

export function postWithEtag(path: string, body: any, etag: string) {
  return dispatch('POST', path, body, { 'If-Match': etag, 'Content-Type': 'application/json' });
}

export function postWithoutEtag(path: string, body: any) {
  return dispatch('POST', path, body, { 'Content-Type': 'application/json' });
}

export function putWithEtag(path: string, body: any, etag: string) {
  return dispatch('PUT', path, body, { 'If-Match': etag, 'Content-Type': 'application/json' });
}

export function putWithoutEtag(path: string, body: any) {
  return dispatch('PUT', path, body, { 'Content-Type': 'application/json' });
}

export function get(path: string) {
  return dispatch('GET', path);
}

export function post(path: string, body: any) {
  return dispatch('POST', path, body, { 'Content-Type': 'application/json' });
}

export function put(path: string, body: any) {
  return dispatch('PUT', path, body, { 'Content-Type': 'application/json' });
}
