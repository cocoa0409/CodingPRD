import { Response } from 'supertest';

export function expectSuccess(response: Response): void {
  expect(response.status).toBeGreaterThanOrEqual(200);
  expect(response.status).toBeLessThan(300);
  expect(response.body).toBeDefined();
  if ('response_type' in response.body) {
    expect(response.body.response_type).toBe('object');
  }
}

export function extractErrorCode(body: any): string | undefined {
  if (!body) return undefined;

  if (body.response_type === 'error' && body.data?.error_code) {
    return body.data.error_code;
  }

  return body.error_code || body?.data?.error_code || body?.error?.code;
}

export function expectError(response: Response, status: number, code?: string): void {
  expect(response.status).toBe(status);
  if (code) {
    const resolvedCode = extractErrorCode(response.body);
    expect(resolvedCode).toBe(code);
  }
}

export function expectErrorCode(response: Response, code: string): void {
  expect(response.status).toBeGreaterThanOrEqual(400);
  expect(response.status).toBeLessThan(500);
  const resolvedCode = extractErrorCode(response.body);
  expect(resolvedCode).toBe(code);
}

export function expectClientError(response: Response): void {
  expect(response.status).toBeGreaterThanOrEqual(400);
  expect(response.status).toBeLessThan(500);
}

export function expectStatusOneOf(response: Response, statuses: number[]): void {
  expect(statuses).toContain(response.status);
}

export function expectErrorCodeOneOf(response: Response, codes: string[]): void {
  expectClientError(response);
  const resolvedCode = extractErrorCode(response.body);
  expect(codes).toContain(resolvedCode);
}

export function expectErrorResponse(response: Response): void {
  expect(response.body.response_type).toBe('error');
}
