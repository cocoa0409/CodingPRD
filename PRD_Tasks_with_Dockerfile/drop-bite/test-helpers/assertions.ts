import { Response } from 'supertest';
import { ErrorCode, ERROR_CODES } from './constants';

export function expectSuccess(response: Response): void {
  expect(response.status).toBeGreaterThanOrEqual(200);
  expect(response.status).toBeLessThan(300);
  expect(response.body).toBeDefined();
  if ('response_type' in response.body) {

    expect(response.body.response_type).not.toBe('error');
  }
}

export function expectSuccessWithStatus(response: Response, status: number): void {
  expect(response.status).toBe(status);
  expect(response.body).toBeDefined();
}

export function extractErrorCode(body: any): string | undefined {
  if (!body) return undefined;
  return (
    body.error_code ||
    body?.data?.error_code ||
    body?.data?.error_id ||
    body?.error?.code
  );
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

export async function expectErrorCode(response: Response, code: ErrorCode | string): Promise<void> {
  expectClientError(response);
  const body = response.body;
  const resolvedCode = extractErrorCode(body);
  expect(resolvedCode).toBe(code);
}

export function expectStatusOneOf(response: Response, statuses: number[]): void {
  expect(statuses).toContain(response.status);
}

export async function expectMissingIfMatch(response: Response): Promise<void> {
  await expectErrorCode(response, ERROR_CODES.MISSING_IF_MATCH);
}

export async function expectVersionConflict(response: Response): Promise<void> {
  await expectErrorCode(response, ERROR_CODES.VERSION_CONFLICT);
}

export async function expectNotFound(response: Response): Promise<void> {
  await expectErrorCode(response, ERROR_CODES.NOT_FOUND);
}

export async function expectInvalidState(response: Response): Promise<void> {
  await expectErrorCode(response, ERROR_CODES.INVALID_STATE);
}

export async function expectStorePaused(response: Response): Promise<void> {
  await expectErrorCode(response, ERROR_CODES.STORE_PAUSED);
}

export async function expectDropNotLive(response: Response): Promise<void> {
  await expectErrorCode(response, ERROR_CODES.DROP_NOT_LIVE);
}

export async function expectDropPaused(response: Response): Promise<void> {
  await expectErrorCode(response, ERROR_CODES.DROP_PAUSED);
}

export async function expectDropClosed(response: Response): Promise<void> {
  await expectErrorCode(response, ERROR_CODES.DROP_CLOSED);
}

export async function expectQuantityLimitExceeded(response: Response): Promise<void> {
  await expectErrorCode(response, ERROR_CODES.QUANTITY_LIMIT_EXCEEDED);
}

export async function expectConstraintViolation(response: Response): Promise<void> {
  await expectErrorCode(response, ERROR_CODES.CONSTRAINT_VIOLATION);
}

export async function expectBundleFull(response: Response): Promise<void> {
  await expectErrorCode(response, ERROR_CODES.BUNDLE_FULL);
}

export async function expectBundleLocked(response: Response): Promise<void> {
  await expectErrorCode(response, ERROR_CODES.BUNDLE_LOCKED);
}

export async function expectBadRequest(response: Response): Promise<void> {
  await expectErrorCode(response, ERROR_CODES.BAD_REQUEST);
}

export function getData<T = any>(response: Response): T {
  const body = response.body;
  if (body && typeof body === 'object' && 'data' in body) {
    return body.data as T;
  }
  return body as T;
}

export function expectMakegoodId(response: Response): string {
  expectSuccess(response);
  const data = getData(response);
  expect(data.makegood_id).toBeDefined();
  return data.makegood_id;
}

export function expectNoMakegoodId(response: Response): void {
  expectSuccess(response);
  const data = getData(response);
  expect(data.makegood_id).toBeUndefined();
}
