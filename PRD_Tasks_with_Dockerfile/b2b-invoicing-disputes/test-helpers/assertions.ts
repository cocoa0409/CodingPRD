import { Response } from 'supertest';

export function expectSuccess(response: Response, status?: number): void {
  if (typeof status === 'number') {
    expect(response.status).toBe(status);
    return;
  }
  expect(response.status >= 200 && response.status < 300).toBe(true);
  expect(response.body).toBeDefined();
}

export function extractErrorCode(body: any): string | undefined {
  if (!body) return undefined;
  return (
    body?.error?.code ||
    body?.error_code ||
    body?.data?.error_id ||
    body?.data?.error_code ||
    body?.data?.error?.code ||
    body?.code
  );
}

export function expectError(response: Response, status?: number, code?: string): void {
  if (typeof status === 'number') {
    expect(response.status).toBe(status);
  } else {
    expect(response.status >= 400 && response.status < 500).toBe(true);
  }
  const resolvedCode = extractErrorCode(response.body);
  if (code) {
    expect(resolvedCode).toBe(code);
  } else {
    expect(resolvedCode).toBeDefined();
  }
}

export async function expectErrorCode(response: Response, code: string, status?: number): Promise<void> {
  expectError(response, status, code);
}

export async function expectErrorCodeOneOf(
  response: Response,
  codes: string[],
  status?: number
): Promise<void> {
  expectError(response, status);
  const resolvedCode = extractErrorCode(response.body);
  expect(codes).toContain(resolvedCode);
}

export function expectStatusOneOf(response: Response, statuses: number[]): void {
  expect(statuses).toContain(response.status);
}
