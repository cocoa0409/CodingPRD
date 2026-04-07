import request from 'supertest';
import { v4 as uuidv4 } from 'uuid';
import { Role, DEFAULT_ROLE } from './constants';

export function getRequest() {
  const apiUrl = process.env.API_URL || 'http://localhost:3000';
  return request(apiUrl);
}

export const headersForRole = (role: Role = DEFAULT_ROLE, actorId?: string) => ({
  'X_Actor_Role': role,
  'X_Actor_Id': actorId || uuidv4()
});

export const headersForActor = (role: string, actorId?: string) => ({
  'X_Actor_Role': role,
  'X_Actor_Id': actorId || uuidv4()
});

export function getAs(path: string, role: Role = DEFAULT_ROLE, actorId?: string) {
  return getRequest().get(path).set(headersForRole(role, actorId));
}

export function getRaw(path: string, headers?: Record<string, string>) {
  const req = getRequest().get(path);
  if (headers) {
    Object.entries(headers).forEach(([key, value]) => req.set(key, value));
  }
  return req;
}

export function postAs(
  path: string,
  body: any,
  role: Role = DEFAULT_ROLE,
  additionalHeaders?: Record<string, string>,
  actorId?: string
) {
  const req = getRequest().post(path).set(headersForRole(role, actorId));
  if (additionalHeaders) {
    Object.entries(additionalHeaders).forEach(([key, value]) => {
      req.set(key, value);
    });
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

export function putAs(path: string, body: any, role: Role = DEFAULT_ROLE, actorId?: string) {
  return getRequest().put(path).set(headersForRole(role, actorId)).send(body);
}

export function deleteAs(path: string, role: Role = DEFAULT_ROLE, actorId?: string) {
  return getRequest().delete(path).set(headersForRole(role, actorId));
}
