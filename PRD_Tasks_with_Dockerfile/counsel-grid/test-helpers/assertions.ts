import type { ApiResponse } from './api-client';

export function expectSuccess(response: ApiResponse): void {
  expect(response.status).toBeGreaterThanOrEqual(200);
  expect(response.status).toBeLessThan(300);
  expect(response.body).toBeDefined();
  if ('response_type' in response.body) {
    expect(['object', 'array']).toContain(response.body.response_type);
  }
}

export function expectError(response: ApiResponse): void {
  expect(response.status).toBeGreaterThanOrEqual(400);
  expect(response.status).toBeLessThan(500);
}

export function extractErrorCode(body: any): string | undefined {
  if (!body) return undefined;

  if (body.data?.error_code) {
    return body.data.error_code;
  }

  return body.error_code || body.data?.error_id || body.error?.code;
}

export function expectErrorCode(response: ApiResponse, errorCode: string): void {
  expectError(response);
  const body = response.body;
  const resolvedCode = extractErrorCode(body);
  expect(resolvedCode).toBe(errorCode);
}

export function expectErrorWithStatus(response: ApiResponse, status: number, errorCode: string): void {
  expect(response.status).toBe(status);
  const resolvedCode = extractErrorCode(response.body);
  expect(resolvedCode).toBe(errorCode);
}

export function expectStatusOneOf(response: ApiResponse, statuses: number[]): void {
  expect(statuses).toContain(response.status);
}

export function unwrapData<T = any>(response: ApiResponse): T {
  expectSuccess(response);
  return response.body.data as T;
}

export function getEtag(response: ApiResponse): string {
  const etag = response.body.data?.etag;
  if (!etag) {
    throw new Error('Expected etag in response.body.data.etag but found none');
  }
  return etag;
}

export function getId(response: ApiResponse): string {
  const data = response.body.data;
  const id = data?.id || data?.workspace_id || data?.matter_id ||
             data?.custodian_id || data?.hold_id || data?.collection_id;
  if (!id) {
    throw new Error('Expected id in response.body.data but found none');
  }
  return id;
}
