import type { ApiResponse } from './api-client';

export function expectSuccess(response: ApiResponse): void {
  expect(response.status).toBeGreaterThanOrEqual(200);
  expect(response.status).toBeLessThan(300);
  expect(response.body).toBeDefined();
}

export function extractErrorCode(body: any): string | undefined {
  if (!body) return undefined;

  if (body?.error?.code) return body.error.code;

  if (body?.error_code) return body.error_code;
  if (body?.data?.error_id) return body.data.error_id;
  if (body?.data?.error_code) return body.data.error_code;
  return undefined;
}

export function expectClientError(response: ApiResponse): void {
  expect(response.status).toBeGreaterThanOrEqual(400);
  expect(response.status).toBeLessThan(500);
}

export function expectErrorCode(response: ApiResponse, code: string): void {
  expectClientError(response);
  const resolvedCode = extractErrorCode(response.body);
  expect(resolvedCode).toBe(code);
}

export function expectErrorWithStatus(response: ApiResponse, status: number, code: string): void {
  expect(response.status).toBe(status);
  const resolvedCode = extractErrorCode(response.body);
  expect(resolvedCode).toBe(code);
}

export function expectStatusOneOf(response: ApiResponse, statuses: number[]): void {
  expect(statuses).toContain(response.status);
}

export function expectErrorCodeOneOf(response: ApiResponse, codes: string[]): void {
  expectClientError(response);
  const resolvedCode = extractErrorCode(response.body);
  expect(codes).toContain(resolvedCode);
}
