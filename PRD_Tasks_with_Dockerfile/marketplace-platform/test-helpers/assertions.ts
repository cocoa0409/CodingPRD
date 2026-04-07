import { Response } from 'supertest';

export function expectSuccess(response: Response, expectedStatus?: number): void {
  if (expectedStatus !== undefined) {
    expect(response.status).toBe(expectedStatus);
  } else {
    expect(response.status).toBeGreaterThanOrEqual(200);
    expect(response.status).toBeLessThan(300);
  }
  expect(response.body).toBeDefined();
  if ('response_type' in response.body) {
    expect(response.body.response_type === 'object' || response.body.response_type === 'array').toBe(true);
  }
}

export function extractErrorCode(body: any): string | undefined {
  if (!body) return undefined;
  return body.error_code || body?.data?.error_id || body?.data?.error_code || body?.error?.code;
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
