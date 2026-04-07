import { Response } from 'supertest';
import { ErrorCode } from './constants';

export function expectSuccess(response: Response): void {
  expect(response.status).toBeGreaterThanOrEqual(200);
  expect(response.status).toBeLessThan(300);
  expect(response.body).toBeDefined();
  if ('response_type' in response.body) {

    expect(response.body.response_type).not.toBe('error');
  }
}

export function expectClientError(response: Response): void {
  expect(response.status).toBeGreaterThanOrEqual(400);
  expect(response.status).toBeLessThan(500);
}

export function extractErrorCode(body: any): string | undefined {
  if (!body) return undefined;

  if (body.error_code) return body.error_code;

  if (body.data?.error_code) return body.data.error_code;

  if (body.data?.error_id) return body.data.error_id;
  if (body.error?.code) return body.error.code;
  return undefined;
}

export function expectErrorCode(response: Response, code: ErrorCode | string): void {
  expectClientError(response);
  const resolvedCode = extractErrorCode(response.body);
  expect(resolvedCode).toBe(code);
}

export function expectError(response: Response, status: number, code?: ErrorCode | string): void {
  expect(response.status).toBe(status);
  if (code) {
    const resolvedCode = extractErrorCode(response.body);
    expect(resolvedCode).toBe(code);
  }
}

export function expectErrorResponseType(response: Response): void {
  expect(response.body.response_type).toBe('error');
}

export function expectStatusOneOf(response: Response, statuses: number[]): void {
  expect(statuses).toContain(response.status);
}

export function unwrapData<T = any>(response: Response): T {
  const body = response.body;
  if (body && typeof body === 'object' && 'data' in body) {
    return body.data as T;
  }
  return body as T;
}

export function getResponseType(response: Response): string | undefined {
  return response.body?.response_type;
}
