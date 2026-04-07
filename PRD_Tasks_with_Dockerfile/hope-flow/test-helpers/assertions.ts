import { Response } from 'supertest';

export function expectSuccess(response: Response): void {
  expect(response.status).toBeGreaterThanOrEqual(200);
  expect(response.status).toBeLessThan(300);
  expect(response.body).toBeDefined();
  if ('response_type' in response.body) {
    expect(
      response.body.response_type === 'object' || response.body.response_type === 'array'
    ).toBe(true);
  }
}

export function extractErrorCode(body: any): string | undefined {
  if (!body) return undefined;

  if (body?.data?.error_code) return body.data.error_code;

  if (body?.error_code) return body.error_code;

  if (body?.data?.error_id) return body.data.error_id;
  if (body?.error?.code) return body.error.code;
  return undefined;
}

export function expectClientError(response: Response): void {
  expect(response.status).toBeGreaterThanOrEqual(400);
  expect(response.status).toBeLessThan(500);
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

export async function expectErrorCode(response: Response, errorCode: string): Promise<void> {
  expectClientError(response);
  const resolvedCode = extractErrorCode(response.body);
  expect(resolvedCode).toBe(errorCode);
}

export function expectStatusOneOf(response: Response, statuses: number[]): void {
  expect(statuses).toContain(response.status);
}

export function expectFields(body: any, expected: Record<string, any>): void {
  const data = body?.data ?? body;
  for (const [key, value] of Object.entries(expected)) {
    expect(data[key]).toBe(value);
  }
}
