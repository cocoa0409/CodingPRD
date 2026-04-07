import axios, { AxiosResponse, Method } from 'axios';
import {
  ApiResponse,
  UrbanRenewalProject,
  RenovationPhase,
  WorkOrder,
  RenovationCrew,
  CrewContract,
  CrewConflictPairing,
  CrewContractPayload,
} from './types';
import { ApiHeaders } from './utils';

export const BASE_URL = process.env.API_URL ?? 'http://localhost:3000';

export async function makeRequest<
  TRes,
  TReq = unknown
>(
  method: Method,
  path: string,
  paramsOrData?: TReq | Record<string, unknown>,
  headers: Record<string, string> = {}
): Promise<AxiosResponse<ApiResponse<TRes>>> {
  const config: Record<string, unknown> = {
    method,
    url: `${BASE_URL}${path}`,
    headers,
    validateStatus: () => true,
  };

  if (paramsOrData !== undefined) {
    if (['GET', 'get', 'DELETE', 'delete'].includes(method as string)) {
      (config as any).params = paramsOrData;
    } else {
      (config as any).data = paramsOrData;
    }
  }

  return axios(config);
}

export const apiClient = {
  createProject: (payload: { project_name: string; renovation_budget: number }, headers: ApiHeaders) =>
    makeRequest<UrbanRenewalProject>('POST', '/projects', payload, headers),

  getProjects: (headers: ApiHeaders) =>
    makeRequest<UrbanRenewalProject[]>('GET', '/projects', undefined, headers),

  getProjectsWithParams: (params: Record<string, unknown>, headers: ApiHeaders) =>
    makeRequest<UrbanRenewalProject[]>('GET', '/projects', params, headers),

  getProject: (projId: string, headers: ApiHeaders) =>
    makeRequest<UrbanRenewalProject>('GET', `/projects/${projId}`, undefined, headers),

  beginWork: (projId: string, headers: ApiHeaders) =>
    makeRequest<UrbanRenewalProject>('POST', `/projects/${projId}/begin-work`, undefined, headers),

  initiateFinalAudit: (projId: string, headers: ApiHeaders) =>
    makeRequest<UrbanRenewalProject>('POST', `/projects/${projId}/initiate-final-audit`, undefined, headers),

  finalizeProject: (projId: string, headers: ApiHeaders) =>
    makeRequest<UrbanRenewalProject>('POST', `/projects/${projId}/finalize-project`, undefined, headers),

  createPhase: (projId: string, payload: { name: string; start_hour: number; end_hour: number }, headers: ApiHeaders) =>
    makeRequest<RenovationPhase>('POST', `/projects/${projId}/phases`, payload, headers),

  getPhases: (projId: string, headers: ApiHeaders) =>
    makeRequest<RenovationPhase[]>('GET', `/projects/${projId}/phases`, undefined, headers),

  getPhasesWithParams: (projId: string, params: Record<string, unknown>, headers: ApiHeaders) =>
    makeRequest<RenovationPhase[]>('GET', `/projects/${projId}/phases`, params, headers),

  getPhase: (projId: string, phaseId: string, headers: ApiHeaders) =>
    makeRequest<RenovationPhase>('GET', `/projects/${projId}/phases/${phaseId}`, undefined, headers),

  updatePhaseStatus: (projId: string, phaseId: string, payload: { status: string }, headers: ApiHeaders) =>
    makeRequest<RenovationPhase>('PUT', `/projects/${projId}/phases/${phaseId}`, payload, headers),

  createWorkOrder: (projId: string, phaseId: string, payload: { task_type: string; required_specialization?: string; required_safety_clearance_level?: number; start_hour: number; end_hour: number }, headers: ApiHeaders) =>
    makeRequest<WorkOrder>('POST', `/projects/${projId}/phases/${phaseId}/work-orders`, payload, headers),

  getWorkOrders: (projId: string, phaseId: string, headers: ApiHeaders) =>
    makeRequest<WorkOrder[]>('GET', `/projects/${projId}/phases/${phaseId}/work-orders`, undefined, headers),

  getWorkOrder: (projId: string, phaseId: string, orderId: string, headers: ApiHeaders) =>
    makeRequest<WorkOrder>('GET', `/projects/${projId}/phases/${phaseId}/work-orders/${orderId}`, undefined, headers),

  createContract: (projId: string, payload: CrewContractPayload, headers: ApiHeaders) =>
    makeRequest<CrewContract>('POST', `/projects/${projId}/contracts`, payload, headers),

  getContracts: (projId: string, headers: ApiHeaders) =>
    makeRequest<CrewContract[]>('GET', `/projects/${projId}/contracts`, undefined, headers),

  getContractsWithParams: (projId: string, params: Record<string, unknown>, headers: ApiHeaders) =>
    makeRequest<CrewContract[]>('GET', `/projects/${projId}/contracts`, params, headers),

  getContract: (projId: string, contractId: string, headers: ApiHeaders) =>
    makeRequest<CrewContract>('GET', `/projects/${projId}/contracts/${contractId}`, undefined, headers),

  rejectContract: (projId: string, contractId: string, headers: ApiHeaders) =>
    makeRequest<CrewContract>('POST', `/projects/${projId}/contracts/${contractId}/reject`, undefined, headers),

  cancelContract: (projId: string, contractId: string, headers: ApiHeaders) =>
    makeRequest<CrewContract>('POST', `/projects/${projId}/contracts/${contractId}/cancel`, undefined, headers),

  verifySpecialization: (projId: string, contractId: string, headers: ApiHeaders) =>
    makeRequest<CrewContract>('POST', `/projects/${projId}/contracts/${contractId}/specialization-verify`, undefined, headers),

  scheduleWork: (projId: string, contractId: string, headers: ApiHeaders) =>
    makeRequest<CrewContract>('POST', `/projects/${projId}/contracts/${contractId}/schedule`, undefined, headers),

  createCrew: (projId: string, payload: { crew_name: string; company_name: string; hourly_rate: number }, headers: ApiHeaders) =>
    makeRequest<RenovationCrew>('POST', `/projects/${projId}/crews`, payload, headers),

  getCrews: (projId: string, headers: ApiHeaders) =>
    makeRequest<RenovationCrew[]>('GET', `/projects/${projId}/crews`, undefined, headers),

  getCrew: (projId: string, crewId: string, headers: ApiHeaders) =>
    makeRequest<RenovationCrew>('GET', `/projects/${projId}/crews/${crewId}`, undefined, headers),

  addCrewCertification: (projId: string, crewId: string, payload: { specialization_name: string; clearance_level: number }, headers: ApiHeaders) =>
    makeRequest<RenovationCrew>('POST', `/projects/${projId}/crews/${crewId}/certifications`, payload, headers),

  createCrewConflictPairing: (projId: string, payload: { crew_id_1: string; crew_id_2: string; reason?: string }, headers: ApiHeaders) =>
    makeRequest<CrewConflictPairing>('POST', `/projects/${projId}/crew-conflict-pairings`, payload, headers),

  getCrewConflictPairings: (projId: string, headers: ApiHeaders) =>
    makeRequest<CrewConflictPairing[]>('GET', `/projects/${projId}/crew-conflict-pairings`, undefined, headers),

  getCrewConflictPairing: (projId: string, pairId: string, headers: ApiHeaders) =>
    makeRequest<CrewConflictPairing>('GET', `/projects/${projId}/crew-conflict-pairings/${pairId}`, undefined, headers),

  batchCreateWorkOrders: (
    projId: string,
    phaseId: string,
    payload: { items: Array<{ task_type: string; required_specialization?: string; required_safety_clearance_level?: number; start_hour: number; end_hour: number; idempotency_key?: string }> },
    headers: ApiHeaders
  ) => makeRequest<WorkOrder[]>(
    'POST',
    `/projects/${projId}/phases/${phaseId}/work-orders/batch`,
    payload,
    headers
  ),

  batchCreateContracts: (
    projId: string,
    payload: { items: Array<{ work_order_id: string; crew_id: string; permit_waiver_used?: boolean; idempotency_key?: string }> },
    headers: ApiHeaders
  ) => makeRequest<CrewContract[]>(
    'POST',
    `/projects/${projId}/contracts/batch`,
    payload,
    headers
  ),

} as const;
