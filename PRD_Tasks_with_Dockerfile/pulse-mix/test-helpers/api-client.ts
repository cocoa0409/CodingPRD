import { v4 as uuidv4 } from 'uuid';
import { Role, DEFAULT_ROLE } from './constants';
import path from 'node:path';

export type ApiResponse = {
  status: number;
  headers: Record<string, any>;
  body: any;
  text: string;
};

type Transport = 'http' | 'inject';

function getTransport(): Transport {
  return process.env.PULSEMIX_TEST_TRANSPORT === 'inject' ? 'inject' : 'http';
}

function safeJsonParse(payload: string): any {
  if (!payload) return payload;
  try {
    return JSON.parse(payload);
  } catch {
    return payload;
  }
}

type InjectRuntime = {
  app: { inject: (opts: any) => Promise<any>; close: () => Promise<void>; ready: () => Promise<void> };
  store: { close: () => void };
};

let injectRuntimePromise: Promise<InjectRuntime> | null = null;

async function getInjectRuntime(): Promise<InjectRuntime> {
  if (injectRuntimePromise) return injectRuntimePromise;
  injectRuntimePromise = (async () => {
    const implDir = resolveImplementationDir();
    const appModulePath = path.join(implDir, 'src/app');
    const dbModulePath = path.join(implDir, 'src/db/sqlite');

    const { buildApp } = require(appModulePath) as { buildApp: (store: any) => Promise<any> };
    const { openSqliteStore } = require(dbModulePath) as { openSqliteStore: (dbPath: string) => Promise<any> };

    const dbPath = path.join(
      process.cwd(),
      '.inject-db',
      `pulsemix-${uuidv4().slice(0, 8)}.sqlite`
    );

    const store = await openSqliteStore(dbPath);
    const app = await buildApp(store);
    await app.ready();

    return { app, store };
  })();

  return injectRuntimePromise;
}

function resolveImplementationDir(): string {
  const apiStartCommand = process.env.API_START_COMMAND || '';
  const cdMatch = apiStartCommand.match(/cd\s+([^\s&]+)\s*&&/);
  if (!cdMatch) {
    throw new Error(
      'Inject transport requires API_START_COMMAND in the form "cd <implDir> && <command>"'
    );
  }
  return path.resolve(process.cwd(), cdMatch[1]);
}

async function injectRequest(
  method: string,
  url: string,
  headers: Record<string, string>,
  body?: any
): Promise<ApiResponse> {
  const { app } = await getInjectRuntime();

  const payload =
    body === undefined ? undefined : typeof body === 'string' ? body : JSON.stringify(body);

  const res = await app.inject({
    method,
    url,
    headers,
    payload
  });

  const text = typeof res.payload === 'string' ? res.payload : String(res.payload ?? '');
  return {
    status: res.statusCode,
    headers: res.headers || {},
    body: safeJsonParse(text),
    text
  };
}

export const headersForRole = (role: Role = DEFAULT_ROLE) => ({
  'X-Studio-Role': role,
  'Content-Type': 'application/json'
});

export function idempotencyKey(prefix: string = 'idem'): string {
  return `${prefix}-${uuidv4()}`;
}

export async function getAs(path: string, role: Role = DEFAULT_ROLE): Promise<ApiResponse> {
  const headers = headersForRole(role);
  if (getTransport() === 'inject') return injectRequest('GET', path, headers);

  const request = require('supertest') as typeof import('supertest');
  const apiUrl = process.env.API_URL || 'http://localhost:3000';
  const res = await request(apiUrl).get(path).set(headers);
  return { status: res.status, headers: res.headers, body: res.body, text: res.text };
}

export async function postAs(
  path: string,
  body: any,
  role: Role = DEFAULT_ROLE,
  idemKey?: string,
  ifMatch?: number
) : Promise<ApiResponse> {
  const headers: Record<string, string> = {
    ...headersForRole(role),
    'Idempotency-Key': idemKey || idempotencyKey()
  };
  if (ifMatch !== undefined) {
    headers['If-Match'] = String(ifMatch);
  }

  if (getTransport() === 'inject') return injectRequest('POST', path, headers, body);

  const request = require('supertest') as typeof import('supertest');
  const apiUrl = process.env.API_URL || 'http://localhost:3000';
  const res = await request(apiUrl).post(path).set(headers).send(body);
  return { status: res.status, headers: res.headers, body: res.body, text: res.text };
}

export async function postAsNoIdem(path: string, body: any, role: Role = DEFAULT_ROLE): Promise<ApiResponse> {
  const headers = headersForRole(role);
  if (getTransport() === 'inject') return injectRequest('POST', path, headers, body);

  const request = require('supertest') as typeof import('supertest');
  const apiUrl = process.env.API_URL || 'http://localhost:3000';
  const res = await request(apiUrl).post(path).set(headers).send(body);
  return { status: res.status, headers: res.headers, body: res.body, text: res.text };
}

export async function postWithHeaders(
  path: string,
  body: any,
  headers: Record<string, string>
) : Promise<ApiResponse> {
  if (getTransport() === 'inject') return injectRequest('POST', path, headers, body);

  const request = require('supertest') as typeof import('supertest');
  const apiUrl = process.env.API_URL || 'http://localhost:3000';
  const req = request(apiUrl).post(path);
  Object.entries(headers).forEach(([key, value]) => req.set(key, value));
  const res = await req.send(body);
  return { status: res.status, headers: res.headers, body: res.body, text: res.text };
}

export async function getRaw(path: string, headers?: Record<string, string>): Promise<ApiResponse> {
  const resolvedHeaders: Record<string, string> = headers ? { ...headers } : {};
  if (getTransport() === 'inject') return injectRequest('GET', path, resolvedHeaders);

  const request = require('supertest') as typeof import('supertest');
  const apiUrl = process.env.API_URL || 'http://localhost:3000';
  const req = request(apiUrl).get(path);
  if (headers) {
    Object.entries(headers).forEach(([key, value]) => req.set(key, value));
  }
  const res = await req;
  return { status: res.status, headers: res.headers, body: res.body, text: res.text };
}

export async function postRaw(path: string, body: any, headers?: Record<string, string>): Promise<ApiResponse> {
  const resolvedHeaders: Record<string, string> = headers ? { ...headers } : {};
  if (getTransport() === 'inject') return injectRequest('POST', path, resolvedHeaders, body);

  const request = require('supertest') as typeof import('supertest');
  const apiUrl = process.env.API_URL || 'http://localhost:3000';
  const req = request(apiUrl).post(path);
  if (headers) {
    Object.entries(headers).forEach(([key, value]) => req.set(key, value));
  }
  const res = await req.send(body);
  return { status: res.status, headers: res.headers, body: res.body, text: res.text };
}

export async function putAs(
  path: string,
  body: any,
  ifMatch: number,
  role: Role = DEFAULT_ROLE
) : Promise<ApiResponse> {
  const headers: Record<string, string> = {
    ...headersForRole(role),
    'If-Match': String(ifMatch)
  };

  if (getTransport() === 'inject') return injectRequest('PUT', path, headers, body);

  const request = require('supertest') as typeof import('supertest');
  const apiUrl = process.env.API_URL || 'http://localhost:3000';
  const res = await request(apiUrl).put(path).set(headers).send(body);
  return { status: res.status, headers: res.headers, body: res.body, text: res.text };
}

export async function putAsNoIfMatch(path: string, body: any, role: Role = DEFAULT_ROLE): Promise<ApiResponse> {
  const headers = headersForRole(role);
  if (getTransport() === 'inject') return injectRequest('PUT', path, headers, body);

  const request = require('supertest') as typeof import('supertest');
  const apiUrl = process.env.API_URL || 'http://localhost:3000';
  const res = await request(apiUrl).put(path).set(headers).send(body);
  return { status: res.status, headers: res.headers, body: res.body, text: res.text };
}

export async function patchAs(
  path: string,
  body: any,
  ifMatch: number,
  role: Role = DEFAULT_ROLE
) : Promise<ApiResponse> {
  const headers: Record<string, string> = {
    ...headersForRole(role),
    'If-Match': String(ifMatch)
  };

  if (getTransport() === 'inject') return injectRequest('PATCH', path, headers, body);

  const request = require('supertest') as typeof import('supertest');
  const apiUrl = process.env.API_URL || 'http://localhost:3000';
  const res = await request(apiUrl).patch(path).set(headers).send(body);
  return { status: res.status, headers: res.headers, body: res.body, text: res.text };
}

export async function patchAsNoIfMatch(path: string, body: any, role: Role = DEFAULT_ROLE): Promise<ApiResponse> {
  const headers = headersForRole(role);
  if (getTransport() === 'inject') return injectRequest('PATCH', path, headers, body);

  const request = require('supertest') as typeof import('supertest');
  const apiUrl = process.env.API_URL || 'http://localhost:3000';
  const res = await request(apiUrl).patch(path).set(headers).send(body);
  return { status: res.status, headers: res.headers, body: res.body, text: res.text };
}

export async function deleteAs(path: string, role: Role = DEFAULT_ROLE): Promise<ApiResponse> {
  const headers = headersForRole(role);
  if (getTransport() === 'inject') return injectRequest('DELETE', path, headers);

  const request = require('supertest') as typeof import('supertest');
  const apiUrl = process.env.API_URL || 'http://localhost:3000';
  const res = await request(apiUrl).delete(path).set(headers);
  return { status: res.status, headers: res.headers, body: res.body, text: res.text };
}
