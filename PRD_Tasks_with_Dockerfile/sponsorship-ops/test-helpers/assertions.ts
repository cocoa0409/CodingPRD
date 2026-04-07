import { Response } from 'supertest';
import { ErrorCode, ERROR_CODES } from './constants';

export function expectSuccess(response: Response): void {
  expect(response.status).toBeGreaterThanOrEqual(200);
  expect(response.status).toBeLessThan(300);
  expect(response.body).toBeDefined();

}

export function expectClientError(response: Response): void {
  expect(response.status).toBeGreaterThanOrEqual(400);
  expect(response.status).toBeLessThan(500);
}

export function extractErrorCode(body: any): string | undefined {
  if (!body) return undefined;

  if (body?.data?.error_code) return body.data.error_code;

  if (body?.error_code) return body.error_code;
  if (body?.data?.error_id) return body.data.error_id;
  if (body?.error?.code) return body.error.code;
  return undefined;
}

export function expectError(response: Response, status?: number, code?: string): void {
  if (status !== undefined) {
    expect(response.status).toBe(status);
  } else {
    expectClientError(response);
  }

  if (code) {
    const resolvedCode = extractErrorCode(response.body);
    expect(resolvedCode).toBe(code);
  }
}

export async function expectErrorCode(response: Response, expectedCode: ErrorCode | string): Promise<void> {
  expectClientError(response);
  const actualCode = extractErrorCode(response.body);
  expect(actualCode).toBe(expectedCode);
}

export function expectStatusOneOf(response: Response, statuses: number[]): void {
  expect(statuses).toContain(response.status);
}

export async function expectErrorCodeOneOf(
  response: Response,
  expectedCodes: (ErrorCode | string)[]
): Promise<void> {
  expectClientError(response);
  const actualCode = extractErrorCode(response.body);
  expect(expectedCodes).toContain(actualCode);
}

export function expectVersionConflict(response: Response): void {
  expectClientError(response);
  const code = extractErrorCode(response.body);
  expect(code).toBe(ERROR_CODES.VERSION_CONFLICT);
}

export function expectPreconditionRequired(response: Response): void {
  expectClientError(response);
  const code = extractErrorCode(response.body);
  expect(code).toBe(ERROR_CODES.PRECONDITION_REQUIRED);
}

export function expectNotFound(response: Response): void {
  expectClientError(response);
  const code = extractErrorCode(response.body);
  expect(code).toBe(ERROR_CODES.NOT_FOUND);
}

export function expectInvalidState(response: Response): void {
  expectClientError(response);
  const code = extractErrorCode(response.body);
  expect(code).toBe(ERROR_CODES.INVALID_STATE);
}

export function expectEventLockdown(response: Response): void {
  expectClientError(response);
  const code = extractErrorCode(response.body);
  expect(code).toBe(ERROR_CODES.EVENT_LOCKDOWN);
}

export function expectEventNotOpen(response: Response): void {
  expectClientError(response);
  const code = extractErrorCode(response.body);
  expect(code).toBe(ERROR_CODES.EVENT_NOT_OPEN);
}
