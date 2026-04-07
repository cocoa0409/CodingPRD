import type { ApiResponseLike } from './inprocess-http';

export function expectSuccess(response: ApiResponseLike): void {
  expect(response.status).toBeGreaterThanOrEqual(200);
  expect(response.status).toBeLessThan(300);
  expect(response.body).toBeDefined();
}

export function expectStatus(response: ApiResponseLike, status: number): void {
  expect(response.status).toBe(status);
}

export function extractErrorCode(body: any): string | undefined {
  if (!body) return undefined;

  return body.error_code || body?.data?.error_id || body?.data?.error_code || body?.error?.code;
}

export function expectClientError(response: ApiResponseLike): void {
  expect(response.status).toBeGreaterThanOrEqual(400);
  expect(response.status).toBeLessThan(500);
}

export function expectError(response: ApiResponseLike, status: number, code?: string): void {
  expect(response.status).toBe(status);
  const resolvedCode = extractErrorCode(response.body);
  if (code) {
    expect(resolvedCode).toBe(code);
  } else {
    expect(resolvedCode).toBeDefined();
  }
}

export async function expectErrorCode(response: ApiResponseLike, errorCode: string): Promise<void> {
  expectClientError(response);
  const resolvedCode = extractErrorCode(response.body);
  expect(resolvedCode).toBe(errorCode);
}

export function expectStatusOneOf(response: ApiResponseLike, statuses: number[]): void {
  expect(statuses).toContain(response.status);
}

export function expectData(response: ApiResponseLike, expected: Record<string, any>): void {
  const data = response.body?.data ?? response.body;
  for (const [key, value] of Object.entries(expected)) {
    expect(data[key]).toBe(value);
  }
}

export function expectDataContains(response: ApiResponseLike, expected: Record<string, any>): void {
  const data = response.body?.data ?? response.body;
  expect(data).toMatchObject(expected);
}

export function expectFieldDefined(response: ApiResponseLike, field: string): void {
  const data = response.body?.data ?? response.body;
  expect(data[field]).toBeDefined();
  expect(data[field]).not.toBeNull();
}

export function getEtag(response: ApiResponseLike): string {
  const data = response.body?.data ?? response.body;
  const etag = data?.etag;
  if (!etag) {
    throw new Error(`Expected etag in response but got: ${JSON.stringify(response.body)}`);
  }
  return etag;
}

export function getData<T = any>(response: ApiResponseLike): T {
  return response.body?.data ?? response.body;
}

export function getField<T = any>(response: ApiResponseLike, field: string): T {
  const data = getData(response);
  return data[field];
}
