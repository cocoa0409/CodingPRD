import { AxiosResponse } from 'axios';
import { ApiErrorId, HTTP_STATUS_CODES } from './api-errors';
import {
  ApiResponse,
  ApiSuccessEnvelope,
  ApiErrorEnvelope,
  ErrorResponseData,
} from './types';

export function isISO8601Timestamp(value: string): boolean {
  const iso8601Pattern = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,3})?Z$/;
  return iso8601Pattern.test(value);
}

export function validateApiResponseStructure<T>(
  response: AxiosResponse<ApiResponse<T>>,
  options: { expectPaginated?: boolean } = {}
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

  if (options.expectPaginated) {
    const { limit, offset, total_count, has_more } = envelope.meta;
    if (typeof limit === 'undefined' || !Number.isInteger(limit) || limit < 1 || limit > 100) {
      throw new Error('meta.limit must be integer between 1 and 100 when paginated');
    }
    if (typeof offset === 'undefined' || !Number.isInteger(offset) || offset < 0) {
      throw new Error('meta.offset must be non-negative integer when paginated');
    }
    if (typeof total_count === 'undefined' || !Number.isInteger(total_count) || total_count < 0) {
      throw new Error('meta.total_count must be non-negative integer when paginated');
    }
    if (typeof has_more !== 'boolean') {
      throw new Error('meta.has_more must be boolean when paginated');
    }
    const expectedHasMore = (offset + limit) < total_count;
    if (has_more !== expectedHasMore) {
      throw new Error('meta.has_more must be true if and only if (offset + limit) < total_count');
    }
  }

  if (!options.expectPaginated) {
    const paginationKeys = ['limit', 'offset', 'total_count', 'has_more'];
    const hasPaginationKey = paginationKeys.some(key => key in envelope.meta);
    if (hasPaginationKey) {
      throw new Error('Pagination keys not allowed when pagination is not expected');
    }
  }

  if (envelope.response_type === 'array' && !Array.isArray(envelope.data)) {
    throw new Error('data must be array when response_type is "array"');
  }

  if (envelope.response_type === 'object' && envelope.data !== null && (typeof envelope.data !== 'object' || Array.isArray(envelope.data))) {
    throw new Error('data must be null or a non-array object when response_type is "object"');
  }

  return envelope as ApiSuccessEnvelope<T>;
}

export function validateErrorEnvelope(
  response: AxiosResponse<ApiResponse<unknown>>,
  options: {
    expectedErrorId?: string;
  } = {}
): ApiErrorEnvelope {
  const { status: actualHttpStatus } = response;
  const { data: envelope } = response;

  if (!envelope || typeof envelope !== 'object') {
    throw new Error('Error response envelope must be an object');
  }

  if (!envelope.meta || typeof envelope.meta !== 'object') {
    throw new Error('Error response envelope must contain meta object');
  }

  if (!envelope.meta.api_request_id || typeof envelope.meta.api_request_id !== 'string' || !envelope.meta.api_request_id.startsWith('req_') || envelope.meta.api_request_id.length <= 'req_'.length) {
    throw new Error('meta.api_request_id must be non-empty string starting with "req_" and contain additional characters');
  }

  if (!envelope.meta.api_request_timestamp || typeof envelope.meta.api_request_timestamp !== 'string' || !isISO8601Timestamp(envelope.meta.api_request_timestamp)) {
    throw new Error('meta.api_request_timestamp must be a valid ISO 8601 UTC timestamp (e.g., "YYYY-MM-DDTHH:mm:ss.sssZ")');
  }

  const paginationKeys = ['limit', 'offset', 'total_count', 'has_more'];
  const hasPaginationKey = paginationKeys.some(key => key in envelope.meta);
  if (hasPaginationKey) {
    throw new Error('Pagination keys not allowed in error responses');
  }

  if (envelope.response_type !== 'error') {
    throw new Error(`Expected response_type "error", got "${envelope.response_type}"`);
  }

  if (!envelope.data || typeof envelope.data !== 'object' || Array.isArray(envelope.data)) {
    throw new Error('Error response must contain a non-array data object');
  }

  const errorData = envelope.data as ErrorResponseData;

  if (!errorData.error_id || typeof errorData.error_id !== 'string' || errorData.error_id.trim() === '') {
    throw new Error('data.error_id must be a non-empty string');
  }
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
  return envelope.data as T;
}

export function handleApiResponse<T>(
  response: AxiosResponse<ApiResponse<T>>,
  expectedStatus: number | number[],
  options: { expectPaginated?: boolean } = {}
): T {
  const statusArray = Array.isArray(expectedStatus) ? expectedStatus : [expectedStatus];

  if (response.status === 204) {
    if (response.data) {
      throw new Error('HTTP 204 response must not have a body');
    }
    const requestId = response.headers['x-api-request-id'];
    const timestamp = response.headers['x-api-request-timestamp'];

    if (!requestId || typeof requestId !== 'string' || !requestId.startsWith('req_') || requestId.length <= 'req_'.length) {
      throw new Error('X-API-Request-ID header must be non-empty string starting with "req_" and contain additional characters');
    }

    if (!timestamp || typeof timestamp !== 'string' || !isISO8601Timestamp(timestamp)) {
      throw new Error('X-API-Request-Timestamp header must be a valid ISO 8601 UTC timestamp (e.g., "YYYY-MM-DDTHH:mm:ss.sssZ")');
    }

    return undefined as T;
  }

  if (!statusArray.includes(response.status)) {
    if (response.data?.response_type === 'error') {
      validateErrorEnvelope(response, {});
      const errorData = response.data.data as ErrorResponseData;
      throw new Error(`API Error: ${errorData.error_id} - ${errorData.message}`);
    }
    throw new Error(`Unexpected status ${response.status}, expected ${statusArray.join(' or ')}`);
  }

  const envelope = validateApiResponseStructure(response, options);
  return envelope.data as T;
}
