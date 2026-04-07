import axios, { AxiosResponse } from 'axios';

import type {
  CreateContractPayload,
  CreateEventPayload,
  UpdateEventStatusPayload,
  CreateShiftPayload,
  CreateStaffProfilePayload,
  AddCertificationPayload,
  CreateAssignmentPayload,
  CreateConflictPairingPayload
} from './types';

type Headers = Record<string, string>;

const BASE_URL = process.env.API_URL || 'http://localhost:3000';

async function apiRequest(
  method: string,
  path: string,
  headers: Headers,
  body?: any
): Promise<any> {
  const url = `${BASE_URL}${path}`;

  try {
    const response: AxiosResponse = await axios({
      method,
      url,
      headers: {
        'Content-Type': 'application/json',
        ...headers,
      },
      data: body,
      validateStatus: () => true,
    });

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

  createContract: async (payload: CreateContractPayload, headers: Headers) => {
    return apiRequest('POST', '/staffing-contracts', headers, payload);
  },

  getContracts: async (headers: Headers, params?: { limit?: number; offset?: number }) => {
    const queryString = params ? `?${new URLSearchParams(params as any).toString()}` : '';
    return apiRequest('GET', `/staffing-contracts${queryString}`, headers);
  },

  getContract: async (contractId: string, headers: Headers) => {
    return apiRequest('GET', `/staffing-contracts/${contractId}`, headers);
  },

  activateContract: async (contractId: string, headers: Headers) => {
    return apiRequest('POST', `/staffing-contracts/${contractId}/activate`, headers);
  },

  initiatePayroll: async (contractId: string, headers: Headers) => {
    return apiRequest('POST', `/staffing-contracts/${contractId}/initiate-payroll`, headers);
  },

  finalizePayroll: async (contractId: string, headers: Headers) => {
    return apiRequest('POST', `/staffing-contracts/${contractId}/finalize-payroll`, headers);
  },

  createEvent: async (contractId: string, payload: CreateEventPayload, headers: Headers) => {
    return apiRequest('POST', `/staffing-contracts/${contractId}/events`, headers, payload);
  },

  getEvents: async (contractId: string, headers: Headers, params?: { limit?: number; offset?: number }) => {
    const queryString = params ? `?${new URLSearchParams(params as any).toString()}` : '';
    return apiRequest('GET', `/staffing-contracts/${contractId}/events${queryString}`, headers);
  },

  getEvent: async (contractId: string, eventId: string, headers: Headers) => {
    return apiRequest('GET', `/staffing-contracts/${contractId}/events/${eventId}`, headers);
  },

  updateEventStatus: async (contractId: string, eventId: string, payload: UpdateEventStatusPayload, headers: Headers) => {
    return apiRequest('PUT', `/staffing-contracts/${contractId}/events/${eventId}`, headers, payload);
  },

  createShift: async (contractId: string, eventId: string, payload: CreateShiftPayload, headers: Headers) => {
    return apiRequest('POST', `/staffing-contracts/${contractId}/events/${eventId}/shifts`, headers, payload);
  },

  getShifts: async (contractId: string, eventId: string, headers: Headers, params?: { limit?: number; offset?: number }) => {
    const queryString = params ? `?${new URLSearchParams(params as any).toString()}` : '';
    return apiRequest('GET', `/staffing-contracts/${contractId}/events/${eventId}/shifts${queryString}`, headers);
  },

  getShift: async (contractId: string, eventId: string, shiftId: string, headers: Headers) => {
    return apiRequest('GET', `/staffing-contracts/${contractId}/events/${eventId}/shifts/${shiftId}`, headers);
  },

  createStaffProfile: async (contractId: string, payload: CreateStaffProfilePayload, headers: Headers) => {
    return apiRequest('POST', `/staffing-contracts/${contractId}/staff-profiles`, headers, payload);
  },

  getStaffProfiles: async (contractId: string, headers: Headers, params?: { limit?: number; offset?: number }) => {
    const queryString = params ? `?${new URLSearchParams(params as any).toString()}` : '';
    return apiRequest('GET', `/staffing-contracts/${contractId}/staff-profiles${queryString}`, headers);
  },

  getStaffProfile: async (contractId: string, staffProfileId: string, headers: Headers) => {
    return apiRequest('GET', `/staffing-contracts/${contractId}/staff-profiles/${staffProfileId}`, headers);
  },

  addCertification: async (contractId: string, staffProfileId: string, payload: AddCertificationPayload, headers: Headers) => {
    return apiRequest('POST', `/staffing-contracts/${contractId}/staff-profiles/${staffProfileId}/certifications`, headers, payload);
  },

  createAssignment: async (contractId: string, payload: CreateAssignmentPayload, headers: Headers) => {
    return apiRequest('POST', `/staffing-contracts/${contractId}/assignments`, headers, payload);
  },

  getAssignments: async (contractId: string, headers: Headers, params?: { limit?: number; offset?: number }) => {
    const queryString = params ? `?${new URLSearchParams(params as any).toString()}` : '';
    return apiRequest('GET', `/staffing-contracts/${contractId}/assignments${queryString}`, headers);
  },

  getAssignment: async (contractId: string, assignmentId: string, headers: Headers) => {
    return apiRequest('GET', `/staffing-contracts/${contractId}/assignments/${assignmentId}`, headers);
  },

  acceptAssignment: async (contractId: string, assignmentId: string, headers: Headers) => {
    return apiRequest('POST', `/staffing-contracts/${contractId}/assignments/${assignmentId}/accept`, headers);
  },

  declineAssignment: async (contractId: string, assignmentId: string, headers: Headers) => {
    return apiRequest('POST', `/staffing-contracts/${contractId}/assignments/${assignmentId}/decline`, headers);
  },

  confirmAssignment: async (contractId: string, assignmentId: string, headers: Headers) => {
    return apiRequest('POST', `/staffing-contracts/${contractId}/assignments/${assignmentId}/confirm`, headers);
  },

  cancelAssignment: async (contractId: string, assignmentId: string, headers: Headers) => {
    return apiRequest('POST', `/staffing-contracts/${contractId}/assignments/${assignmentId}/cancel`, headers);
  },

  createConflictPairing: async (contractId: string, payload: CreateConflictPairingPayload, headers: Headers) => {
    return apiRequest('POST', `/staffing-contracts/${contractId}/conflict-pairings`, headers, payload);
  },

  getConflictPairings: async (contractId: string, headers: Headers, params?: { limit?: number; offset?: number }) => {
    const queryString = params ? `?${new URLSearchParams(params as any).toString()}` : '';
    return apiRequest('GET', `/staffing-contracts/${contractId}/conflict-pairings${queryString}`, headers);
  },

  getConflictPairing: async (contractId: string, conflictPairingId: string, headers: Headers) => {
    return apiRequest('GET', `/staffing-contracts/${contractId}/conflict-pairings/${conflictPairingId}`, headers);
  },
};
