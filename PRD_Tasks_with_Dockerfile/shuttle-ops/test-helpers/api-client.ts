import request from 'supertest';

function getRequest() {
  const apiUrl = process.env.API_URL || 'http://localhost:3000';
  return request(apiUrl);
}

export function headersForRole(role: string = 'Admin', userId?: string): Record<string, string> {
  return {
    'X-User-Role': role,
    'X-User-ID': userId || 'test-user',
  };
}

export function get(path: string) {
  return getRequest().get(path);
}

export function post(path: string, body: any) {
  return getRequest()
    .post(path)
    .set('Content-Type', 'application/json')
    .send(body);
}

export function put(path: string, body: any, ifMatch?: number | string) {
  const req = getRequest()
    .put(path)
    .set('Content-Type', 'application/json');

  if (ifMatch !== undefined) {
    req.set('If-Match', String(ifMatch));
  }

  return req.send(body);
}

export function del(path: string) {
  return getRequest().delete(path);
}

export function getAs(path: string, _role?: string, _userId?: string) {
  return get(path);
}

export function postAs(path: string, body: any, _role?: string, additionalHeaders?: Record<string, string>, _userId?: string) {
  const req = getRequest()
    .post(path)
    .set('Content-Type', 'application/json');

  if (additionalHeaders) {
    Object.entries(additionalHeaders).forEach(([key, value]) => {
      req.set(key, value);
    });
  }

  return req.send(body);
}

export function putAs(path: string, body: any, _role?: string, _userId?: string) {
  return put(path, body);
}

export function deleteAs(path: string, _role?: string, _userId?: string) {
  return del(path);
}

export function putWithVersion(path: string, body: any, version: number | string) {
  return put(path, body, version);
}

export function putWithoutVersion(path: string, body: any) {
  return getRequest()
    .put(path)
    .set('Content-Type', 'application/json')
    .send(body);
}
