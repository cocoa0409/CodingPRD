import axios, { AxiosResponse } from 'axios';

import type {
  CreateGroomingDayPayload,
  CreateSessionBlockPayload,
  UpdateSessionBlockStatusPayload,
  CreateGroomingJobPayload,
  CreateGroomerStationPayload,
  AddSpecialCapabilityPayload,
  JobAssignmentPayload,
} from './types';

type Headers = Record<string, string>;

const BASE_URL = process.env.API_URL || 'http://localhost:3000';

async function apiRequest(
  method: string,
  path: string,
  headers: Headers,
  body?: any,
): Promise<any> {
  const url = `${BASE_URL}${path}`;

  try {
    const config: any = {
      method,
      url,
      headers: {
        'Content-Type': 'application/json',
        ...headers,
      },
      validateStatus: () => true,
    };

    if (method === 'GET' && body) {
      config.params = body;
    } else {
      config.data = body;
    }

    const response: AxiosResponse = await axios(config);

    return {
      status: response.status,
      data: response.data,
      headers: response.headers,
    } as Pick<AxiosResponse, 'status' | 'data' | 'headers'>;
  } catch (error) {
    throw error;
  }
}

export const apiClient = {
  createGroomingDay: (payload: CreateGroomingDayPayload, headers: Headers) =>
    apiRequest('POST', '/grooming-days', headers, payload),

  getGroomingDays: (headers: Headers, params?: { limit?: number; offset?: number }) =>
    apiRequest('GET', '/grooming-days', headers, params),

  getGroomingDay: (dayId: string, headers: Headers) =>
    apiRequest('GET', `/grooming-days/${dayId}`, headers),

  activateGroomingDay: (dayId: string, headers: Headers) =>
    apiRequest('POST', `/grooming-days/${dayId}/activate`, headers),

  initiateInvoicing: (dayId: string, headers: Headers) =>
    apiRequest('POST', `/grooming-days/${dayId}/initiate-invoicing`, headers),

  generateInvoiceReport: (dayId: string, headers: Headers) =>
    apiRequest('POST', `/grooming-days/${dayId}/generate-invoice-report`, headers),

  createSessionBlock: (dayId: string, payload: CreateSessionBlockPayload, headers: Headers) =>
    apiRequest('POST', `/grooming-days/${dayId}/session-blocks`, headers, payload),

  getSessionBlocks: (dayId: string, headers: Headers, params?: { limit?: number; offset?: number }) =>
    apiRequest('GET', `/grooming-days/${dayId}/session-blocks`, headers, params),

  getSessionBlock: (dayId: string, blockId: string, headers: Headers) =>
    apiRequest('GET', `/grooming-days/${dayId}/session-blocks/${blockId}`, headers),

  updateSessionBlockStatus: (dayId: string, blockId: string, payload: UpdateSessionBlockStatusPayload, headers: Headers) =>
    apiRequest('PUT', `/grooming-days/${dayId}/session-blocks/${blockId}`, headers, payload),

  createGroomingJob: (dayId: string, blockId: string, payload: CreateGroomingJobPayload, headers: Headers) =>
    apiRequest('POST', `/grooming-days/${dayId}/session-blocks/${blockId}/grooming-jobs`, headers, payload),

  getGroomingJobs: (dayId: string, blockId: string, headers: Headers, params?: { limit?: number; offset?: number }) =>
    apiRequest('GET', `/grooming-days/${dayId}/session-blocks/${blockId}/grooming-jobs`, headers, params),

  getGroomingJob: (dayId: string, blockId: string, jobId: string, headers: Headers) =>
    apiRequest('GET', `/grooming-days/${dayId}/session-blocks/${blockId}/grooming-jobs/${jobId}`, headers),

  cancelGroomingJob: (dayId: string, blockId: string, jobId: string, headers: Headers) =>
    apiRequest('POST', `/grooming-days/${dayId}/session-blocks/${blockId}/grooming-jobs/${jobId}/cancel`, headers),

  createJobAssignment: (dayId: string, payload: JobAssignmentPayload, headers: Headers) =>
    apiRequest('POST', `/grooming-days/${dayId}/job-assignments`, headers, payload),

  getJobAssignments: (dayId: string, headers: Headers, params?: { limit?: number; offset?: number }) =>
    apiRequest('GET', `/grooming-days/${dayId}/job-assignments`, headers, params),

  getJobAssignment: (dayId: string, assignmentId: string, headers: Headers) =>
    apiRequest('GET', `/grooming-days/${dayId}/job-assignments/${assignmentId}`, headers),

  terminateJobAssignment: (dayId: string, assignmentId: string, headers: Headers) =>
    apiRequest('POST', `/grooming-days/${dayId}/job-assignments/${assignmentId}/terminate`, headers),

  confirmJobAssignment: (dayId: string, assignmentId: string, headers: Headers) =>
    apiRequest('POST', `/grooming-days/${dayId}/job-assignments/${assignmentId}/confirm`, headers),

  createGroomerStation: (dayId: string, payload: CreateGroomerStationPayload, headers: Headers) =>
    apiRequest('POST', `/grooming-days/${dayId}/groomer-stations`, headers, payload),

  getGroomerStations: (dayId: string, headers: Headers, params?: { limit?: number; offset?: number }) =>
    apiRequest('GET', `/grooming-days/${dayId}/groomer-stations`, headers, params),

  getGroomerStation: (dayId: string, stationId: string, headers: Headers) =>
    apiRequest('GET', `/grooming-days/${dayId}/groomer-stations/${stationId}`, headers),

  addSpecialCapability: (dayId: string, stationId: string, payload: AddSpecialCapabilityPayload, headers: Headers) =>
    apiRequest('POST', `/grooming-days/${dayId}/groomer-stations/${stationId}/special-capabilities`, headers, payload),
} as const;
