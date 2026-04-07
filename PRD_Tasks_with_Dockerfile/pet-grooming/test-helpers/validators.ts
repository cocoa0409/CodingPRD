import { AxiosResponse } from 'axios';
import { ApiErrorId, HTTP_STATUS_CODES } from './api-errors';
import {
  ApiResponse,
  ApiSuccessEnvelope,
  ApiErrorEnvelope,
  ErrorResponseData,
  GroomingDay,
  SessionBlock,
  GroomingJob,
  GroomerStation,
  JobAssignment,
  SpecialCapability,
  GroomingDayStatus,
  SessionBlockStatus,
  GroomingJobStatus,
  JobAssignmentStatus,
  SpecialCapabilityName,
  RequiredAllergenType,
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

  if (options.expectPaginated) {
    const meta = successEnvelope.meta;
    if (typeof meta.limit !== 'number' || meta.limit <= 0) {
      throw new Error('Paginated response must have meta.limit as positive number');
    }
    if (typeof meta.offset !== 'number' || meta.offset < 0) {
      throw new Error('Paginated response must have meta.offset as non-negative number');
    }
    if (typeof meta.total_count !== 'number' || meta.total_count < 0) {
      throw new Error('Paginated response must have meta.total_count as non-negative number');
    }
    if (typeof meta.has_more !== 'boolean') {
      throw new Error('Paginated response must have meta.has_more as boolean');
    }
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
  expectedStatus: number | number[],
  options: { expectPaginated?: boolean } = {}
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

  const envelope = validateApiResponseStructure(response, options);
  return envelope.data;
}

function isValidUUID(uuid: string): boolean {
  const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  return uuidRegex.test(uuid);
}

function isValidDate(date: string): boolean {
  const dateRegex = /^\d{4}-\d{2}-\d{2}$/;
  return dateRegex.test(date);
}

export function assertGroomingDay(day: any): asserts day is GroomingDay {
  expect(day).toBeDefined();
  expect(typeof day).toBe('object');

  expect(day.id).toBeDefined();
  expect(typeof day.id).toBe('string');
  expect(isValidUUID(day.id)).toBe(true);

  expect(day.schedule_name).toBeDefined();
  expect(typeof day.schedule_name).toBe('string');
  expect(day.schedule_name.length).toBeGreaterThan(0);

  expect(day.status).toBeDefined();
  expect(Object.values(GroomingDayStatus)).toContain(day.status);

  expect(typeof day.total_supply_budget).toBe('number');
  expect(day.total_supply_budget).toBeGreaterThan(0);

  expect(typeof day.supply_stock_balance).toBe('number');
  expect(day.supply_stock_balance).toBeLessThanOrEqual(day.total_supply_budget);

  expect(typeof day.allergy_exposure_score).toBe('number');
  expect(day.allergy_exposure_score).toBeGreaterThanOrEqual(0);

  expect(isISO8601Timestamp(day.created_at)).toBe(true);
  expect(isISO8601Timestamp(day.updated_at)).toBe(true);
}

export function assertSessionBlock(block: any): asserts block is SessionBlock {
  expect(block).toBeDefined();
  expect(typeof block).toBe('object');

  expect(isValidUUID(block.id)).toBe(true);
  expect(isValidUUID(block.grooming_day_id)).toBe(true);

  expect(block.name).toBeDefined();
  expect(typeof block.name).toBe('string');
  expect(block.name.length).toBeGreaterThan(0);

  expect(Object.values(SessionBlockStatus)).toContain(block.status);

  expect(typeof block.start_time).toBe('number');
  expect(typeof block.end_time).toBe('number');
  expect(block.end_time).toBeGreaterThan(block.start_time);

  expect(isISO8601Timestamp(block.created_at)).toBe(true);
  expect(isISO8601Timestamp(block.updated_at)).toBe(true);
}

export function assertGroomingJob(job: any): asserts job is GroomingJob {
  expect(job).toBeDefined();
  expect(typeof job).toBe('object');

  expect(isValidUUID(job.id)).toBe(true);
  expect(isValidUUID(job.session_block_id)).toBe(true);
  expect(isValidUUID(job.grooming_day_id)).toBe(true);

  expect(job.pet_id).toBeDefined();
  expect(typeof job.pet_id).toBe('string');
  expect(job.pet_id.length).toBeGreaterThan(0);

  expect(job.job_type).toBeDefined();
  expect(typeof job.job_type).toBe('string');
  expect(job.job_type.length).toBeGreaterThan(0);

  expect(Object.values(GroomingJobStatus)).toContain(job.status);

  expect(Object.values(RequiredAllergenType)).toContain(job.required_allergen_type);

  expect(Array.isArray(job.cannot_be_groomed_with_pet_ids)).toBe(true);
  job.cannot_be_groomed_with_pet_ids.forEach((petId: any) => {
    expect(typeof petId).toBe('string');
    expect(isValidUUID(petId)).toBe(true);
  });

  expect(typeof job.start_time).toBe('number');
  expect(typeof job.end_time).toBe('number');
  expect(job.end_time).toBeGreaterThan(job.start_time);

  expect(typeof job.duration_minutes).toBe('number');
  const expectedDuration = (job.end_time - job.start_time) / 60;
  expect(job.duration_minutes).toBeCloseTo(expectedDuration, 2);

  expect(isISO8601Timestamp(job.created_at)).toBe(true);
  expect(isISO8601Timestamp(job.updated_at)).toBe(true);
}

export function assertSpecialCapability(capability: any): asserts capability is SpecialCapability {
  expect(capability).toBeDefined();
  expect(typeof capability).toBe('object');

  expect(isValidUUID(capability.id)).toBe(true);
  expect([SpecialCapabilityName.NUT_ALLERGY_SAFE, SpecialCapabilityName.GRASS_ALLERGY_SAFE]).toContain(capability.name);
  expect(isValidDate(capability.enabled_date)).toBe(true);
}

export function assertGroomerStation(station: any): asserts station is GroomerStation {
  expect(station).toBeDefined();
  expect(typeof station).toBe('object');

  expect(isValidUUID(station.id)).toBe(true);
  expect(isValidUUID(station.grooming_day_id)).toBe(true);

  expect(station.station_name).toBeDefined();
  expect(typeof station.station_name).toBe('string');
  expect(station.station_name.length).toBeGreaterThan(0);

  expect(station.station_type).toBeDefined();
  expect(typeof station.station_type).toBe('string');
  expect(station.station_type.length).toBeGreaterThan(0);

  expect(typeof station.supply_cost_per_hour).toBe('number');
  expect(station.supply_cost_per_hour).toBeGreaterThan(0);

  expect(Array.isArray(station.special_capabilities)).toBe(true);
  station.special_capabilities.forEach(assertSpecialCapability);

  expect(isISO8601Timestamp(station.created_at)).toBe(true);
  expect(isISO8601Timestamp(station.updated_at)).toBe(true);
}

export function assertJobAssignment(assignment: any): asserts assignment is JobAssignment {
  expect(assignment).toBeDefined();
  expect(typeof assignment).toBe('object');

  expect(isValidUUID(assignment.id)).toBe(true);
  expect(isValidUUID(assignment.grooming_day_id)).toBe(true);
  expect(isValidUUID(assignment.job_id)).toBe(true);
  expect(isValidUUID(assignment.station_id)).toBe(true);

  expect(Object.values(JobAssignmentStatus)).toContain(assignment.status);

  expect(typeof assignment.override_allergy_check).toBe('boolean');
  expect(typeof assignment.allergy_override_penalty_applied).toBe('boolean');
  expect(typeof assignment.is_peak_session).toBe('boolean');

  expect(typeof assignment.provisional_supply_cost).toBe('number');
  expect(assignment.provisional_supply_cost).toBeGreaterThanOrEqual(0);

  if (assignment.status === JobAssignmentStatus.COMPLETE) {
    expect(typeof assignment.final_supply_cost).toBe('number');
    expect(assignment.final_supply_cost).toBeGreaterThanOrEqual(0);
  } else {
    expect(assignment.final_supply_cost === undefined || assignment.final_supply_cost === null).toBe(true);
  }

  expect(isISO8601Timestamp(assignment.created_at)).toBe(true);
  expect(isISO8601Timestamp(assignment.updated_at)).toBe(true);
}
