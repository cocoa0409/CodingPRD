import { Response } from 'supertest';

export function expectSuccess(response: Response): void {
  expect(response.status).toBeGreaterThanOrEqual(200);
  expect(response.status).toBeLessThan(300);
}

export function expectClientError(response: Response): void {
  expect(response.status).toBeGreaterThanOrEqual(400);
  expect(response.status).toBeLessThan(500);
}

export function extractErrorCode(body: any): string | undefined {
  if (!body) return undefined;

  if (body.error_code) return body.error_code;

  if (body.data?.error_id) return body.data.error_id;
  if (body.data?.error_code) return body.data.error_code;

  if (body.error_id) return body.error_id;

  if (body.error?.code) return body.error.code;
  if (body.error?.error_code) return body.error.error_code;
  if (body.error?.error_id) return body.error.error_id;

  return undefined;
}

export function expectErrorCode(response: Response, expectedCode: string): void {
  expectClientError(response);
  const actualCode = extractErrorCode(response.body);
  expect(actualCode).toBe(expectedCode);
}

export function expectStatus(response: Response, status: number): void {
  expect(response.status).toBe(status);
}

export function expectStatusOneOf(response: Response, statuses: number[]): void {
  expect(statuses).toContain(response.status);
}

export function extractData<T = any>(response: Response): T {
  const body = response.body;
  if (!body) throw new Error('Response body is empty');

  if ('data' in body) return body.data as T;

  return body as T;
}

export function extractId(response: Response, preferredKey: string = 'id'): string {
  const data = extractData(response);

  if (data[preferredKey]) return data[preferredKey];

  const alternatives = ['id', 'workspace_id', 'event_id', 'pool_id', 'order_id', 'admission_id'];
  for (const key of alternatives) {
    if (data[key]) return data[key];
  }

  throw new Error(`Could not extract ID from response. Body: ${JSON.stringify(response.body)}`);
}

export function extractVersion(response: Response): string {
  const data = extractData(response);

  if (data.version !== undefined) return String(data.version);
  if (data.etag !== undefined) return String(data.etag);

  const etag = response.headers['etag'] || response.headers['ETag'];
  if (etag) return etag;

  throw new Error(`Could not extract version from response. Body: ${JSON.stringify(response.body)}`);
}

export function expectAdmissionCount(response: Response, count: number): string[] {
  expectSuccess(response);
  const data = extractData(response);

  const admissionIds = data.admission_ids || data.admissions?.map((a: any) => a.id) || [];
  expect(Array.isArray(admissionIds)).toBe(true);
  expect(admissionIds.length).toBe(count);

  return admissionIds;
}
