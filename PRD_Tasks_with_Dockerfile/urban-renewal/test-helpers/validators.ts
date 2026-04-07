import { AxiosResponse } from 'axios';
import { ApiErrorId, HTTP_STATUS_CODES } from './api-errors';
import {
  ApiResponse,
  ApiSuccessEnvelope,
  ApiErrorEnvelope,
  ErrorResponseData
} from './types';

export function isISO8601Timestamp(value: string): boolean {
  const iso8601Pattern = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,3})?Z$/;
  return iso8601Pattern.test(value);
}

export function validateApiResponseStructure<T>(
  response: AxiosResponse<ApiResponse<T>>
): ApiSuccessEnvelope<T> {
  const { data: envelope } = response;

  if (!envelope || typeof envelope !== 'object') {
    throw new Error('Response envelope must be an object');
  }

  if (!envelope.meta || typeof envelope.meta !== 'object') {
    throw new Error('Response envelope must contain meta object');
  }

  if (!envelope.meta.api_request_id || typeof envelope.meta.api_request_id !== 'string' || !envelope.meta.api_request_id.startsWith('req_') || envelope.meta.api_request_id.length <= 'req_'.length) {
    throw new Error('meta.api_request_id must be non-empty string starting with "req_" and contain additional characters');
  }

  if (!envelope.meta.api_request_timestamp || typeof envelope.meta.api_request_timestamp !== 'string' || !isISO8601Timestamp(envelope.meta.api_request_timestamp)) {
    throw new Error('meta.api_request_timestamp must be a valid ISO 8601 UTC timestamp (e.g., "YYYY-MM-DDTHH:mm:ss.sssZ")');
  }

  if (!envelope.response_type || !['object', 'array', 'error'].includes(envelope.response_type)) {
    throw new Error('response_type must be "object", "array", or "error"');
  }

  if (envelope.response_type === 'error') {
    throw new Error('validateApiResponseStructure called on error response');
  }

  const successEnvelope = envelope as ApiSuccessEnvelope<T>;

  if (!('data' in successEnvelope)) {
    throw new Error('Response envelope must contain data field');
  }

  if (successEnvelope.response_type === 'array' && !Array.isArray(successEnvelope.data)) {
    throw new Error('When response_type is "array", data must be an array');
  }

  if (successEnvelope.response_type === 'object' && (Array.isArray(successEnvelope.data) || (successEnvelope.data !== null && typeof successEnvelope.data !== 'object'))) {
    throw new Error('When response_type is "object", data must be an object or null');
  }

  return successEnvelope;
}

export function validateErrorEnvelope(
  response: AxiosResponse<ApiResponse<any>>,
  options: { expectedErrorId?: ApiErrorId } = {}
): ApiErrorEnvelope {
  const { data: envelope } = response;

  if (!envelope || typeof envelope !== 'object') {
    throw new Error('Response envelope must be an object');
  }

  if (!envelope.meta || typeof envelope.meta !== 'object') {
    throw new Error('Error envelope must contain meta object');
  }

  if (!envelope.meta.api_request_id || typeof envelope.meta.api_request_id !== 'string' || !envelope.meta.api_request_id.startsWith('req_') || envelope.meta.api_request_id.length <= 'req_'.length) {
    throw new Error('meta.api_request_id must be non-empty string starting with "req_" and contain additional characters');
  }

  if (!envelope.meta.api_request_timestamp || typeof envelope.meta.api_request_timestamp !== 'string' || !isISO8601Timestamp(envelope.meta.api_request_timestamp)) {
    throw new Error('meta.api_request_timestamp must be a valid ISO 8601 UTC timestamp');
  }

  if (envelope.response_type !== 'error') {
    throw new Error(`Expected response_type "error", got "${envelope.response_type}"`);
  }

  if (!envelope.data || typeof envelope.data !== 'object' || Array.isArray(envelope.data)) {
    throw new Error('Error envelope must contain data object');
  }

  const errorData = envelope.data as ErrorResponseData;

  if (!errorData.error_id || typeof errorData.error_id !== 'string' || errorData.error_id.trim() === '') {
    throw new Error('data.error_id must be a non-empty string');
  }

  const actualHttpStatus = response.status;
  const actualErrorIdFromResponse = errorData.error_id as ApiErrorId;

  if (options.expectedErrorId && actualErrorIdFromResponse !== options.expectedErrorId) {
    throw new Error(`Expected error_id "${options.expectedErrorId}", but response contained "${actualErrorIdFromResponse}"`);
  }

  const expectedHttpStatusFromMap = HTTP_STATUS_CODES[actualErrorIdFromResponse];

  if (expectedHttpStatusFromMap === undefined) {
    throw new Error(`Unknown error_id "${actualErrorIdFromResponse}" received. Not found in HTTP_STATUS_CODES map.`);
  }

  if (actualHttpStatus !== expectedHttpStatusFromMap) {
    throw new Error(
      `HTTP status mismatch for error_id "${actualErrorIdFromResponse}". ` +
      `Expected status ${expectedHttpStatusFromMap} (based on error_id map), but received ${actualHttpStatus}.`
    );
  }

  if (!errorData.message || typeof errorData.message !== 'string' || errorData.message.trim() === '') {
    throw new Error('data.message must be a non-empty string');
  }

  return envelope as ApiErrorEnvelope;
}

export function getSuccessData<T>(response: AxiosResponse<ApiResponse<T>>): T {
  if (response.status < 200 || response.status >= 300) {
    if (response.data?.response_type === 'error') {
      validateErrorEnvelope(response, {});
      const errorData = response.data.data as ErrorResponseData;
      throw new Error(
        `API call in test setup failed unexpectedly with error: ${errorData.error_id} - ${errorData.message}`
      );
    }
    throw new Error(
      `API call in test setup failed unexpectedly with status ${response.status}`
    );
  }

  const envelope = validateApiResponseStructure(response);
  return envelope.data;
}

export function handleApiResponse<T>(
  response: AxiosResponse<ApiResponse<T>>,
  expectedStatus: number | number[]
): T {
  const statusArray = Array.isArray(expectedStatus) ? expectedStatus : [expectedStatus];

  if (!statusArray.includes(response.status)) {
    if (response.data?.response_type === 'error') {
      validateErrorEnvelope(response, {});
      const errorData = response.data.data as ErrorResponseData;
      throw new Error(
        `Expected status ${statusArray.join(' or ')}, got ${response.status} with error: ${errorData.error_id} - ${errorData.message}`
      );
    }
    throw new Error(
      `Expected status ${statusArray.join(' or ')}, got ${response.status}`
    );
  }

  const envelope = validateApiResponseStructure(response);
  return envelope.data;
}

export function assertProject(project: any): void {
  expect(project).toBeDefined();
  expect(project.id).toBeDefined();
  expect(typeof project.id).toBe('string');
  expect(project.project_name).toBeDefined();
  expect(typeof project.project_name).toBe('string');
  expect(project.status).toBeDefined();
  expect(['PLANNING', 'IN_PROGRESS', 'FINAL_AUDIT_PENDING', 'READY_FOR_LEASING']).toContain(project.status);
  expect(typeof project.renovation_budget).toBe('number');
  expect(typeof project.budget_balance).toBe('number');
  expect(typeof project.community_disruption_index).toBe('number');
  expect(project.created_at).toBeDefined();
  expect(project.updated_at).toBeDefined();
}

export function assertPhase(phase: any): void {
  expect(phase).toBeDefined();
  expect(phase.id).toBeDefined();
  expect(typeof phase.id).toBe('string');
  expect(phase.project_id).toBeDefined();
  expect(typeof phase.project_id).toBe('string');
  expect(phase.name).toBeDefined();
  expect(typeof phase.name).toBe('string');
  expect(phase.status).toBeDefined();
  expect(['PLANNING', 'READY_FOR_EXECUTION', 'COMPLETED', 'CANCELLED']).toContain(phase.status);
  expect(typeof phase.start_hour).toBe('number');
  expect(typeof phase.end_hour).toBe('number');
  expect(phase.created_at).toBeDefined();
  expect(phase.updated_at).toBeDefined();
}

export function assertContract(contract: any): void {
  expect(contract).toBeDefined();
  expect(contract.id).toBeDefined();
  expect(typeof contract.id).toBe('string');
  expect(contract.project_id).toBeDefined();
  expect(typeof contract.project_id).toBe('string');
  expect(contract.work_order_id).toBeDefined();
  expect(typeof contract.work_order_id).toBe('string');
  expect(contract.crew_id).toBeDefined();
  expect(typeof contract.crew_id).toBe('string');
  expect(contract.status).toBeDefined();
  expect(['PROPOSED', 'SPECIALIZATION_VERIFIED', 'SCHEDULED', 'COMPLETED', 'REJECTED', 'CANCELLED']).toContain(contract.status);
  expect(typeof contract.provisional_cost).toBe('number');
  if (contract.status === 'COMPLETED') {
    expect(typeof contract.final_cost).toBe('number');
  }
  expect(contract.created_at).toBeDefined();
  expect(contract.updated_at).toBeDefined();
}
