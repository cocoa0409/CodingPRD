import { Response } from 'supertest';

export function expectSuccess(response: Response, _expectedStatus?: number): void {
  expect(response.status).toBeGreaterThanOrEqual(200);
  expect(response.status).toBeLessThan(300);
  expect(response.body).toBeDefined();
  expect(typeof response.body).toBe('object');
}

export function extractErrorCode(body: any): string | undefined {
  if (!body) return undefined;
  return body?.error?.code;
}

export function expectError(response: Response, status: number, code?: string): void {
  expect(response.status).toBe(status);
  const resolvedCode = extractErrorCode(response.body);
  if (code) {
    expect(resolvedCode).toBe(code);
  } else {
    expect(resolvedCode).toBeDefined();
  }
}

export function expectStatusOneOf(response: Response, statuses: number[]): void {
  expect(statuses).toContain(response.status);
}

export function expectErrorOneOf(response: Response, status: number, codes: string[]): void {
  expect(response.status).toBe(status);
  const resolvedCode = extractErrorCode(response.body);
  expect(resolvedCode).toBeDefined();
  expect(codes).toContain(resolvedCode);
}
