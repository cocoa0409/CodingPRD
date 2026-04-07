import axios, { AxiosResponse, Method } from 'axios';
import {
  ApiResponse,
  TreatmentPlan,
  WardRotation,
  Procedure,
  MedicalResource,
  Assignment,
  InfectionRiskPairing,
  AssignmentPayload,
  MaintenanceEvent,
  ResourceHold,
  OverrideAuthorization,
} from './types';

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

export interface ApiHeadersBase {
  'X-User-ID': string;
  'X-User-Role': string;
  [key: string]: string;
}

export const apiClient = {
  createTreatmentPlan: (payload: { plan_name: string; total_budget: number; policies?: { require_admin_auth_for_overrides?: boolean } }, headers: ApiHeadersBase) =>
    makeRequest<TreatmentPlan>('POST', '/treatment-plans', payload, headers),

  getTreatmentPlans: (headers: ApiHeadersBase) =>
    makeRequest<TreatmentPlan[]>('GET', '/treatment-plans', undefined, headers),

  getTreatmentPlan: (planId: string, headers: ApiHeadersBase) =>
    makeRequest<TreatmentPlan>('GET', `/treatment-plans/${planId}`, undefined, headers),

  activateTreatmentPlan: (planId: string, headers: ApiHeadersBase) =>
    makeRequest<TreatmentPlan>('POST', `/treatment-plans/${planId}/activate`, undefined, headers),

  createWardRotation: (planId: string, payload: { name: string; start_minute: number; end_minute: number }, headers: ApiHeadersBase) =>
    makeRequest<WardRotation>('POST', `/treatment-plans/${planId}/ward-rotations`, payload, headers),

  getWardRotations: (planId: string, params: { limit?: number; offset?: number }, headers: ApiHeadersBase) =>
    makeRequest<WardRotation[]>('GET', `/treatment-plans/${planId}/ward-rotations`, params, headers),

  getWardRotation: (planId: string, rotationId: string, headers: ApiHeadersBase) =>
    makeRequest<WardRotation>('GET', `/treatment-plans/${planId}/ward-rotations/${rotationId}`, undefined, headers),

  updateWardRotationStatus: (planId: string, rotationId: string, payload: { status: string; version?: number }, headers: ApiHeadersBase) =>
    makeRequest<WardRotation>('PUT', `/treatment-plans/${planId}/ward-rotations/${rotationId}`, payload, headers),

  createProcedure: (planId: string, rotationId: string, payload: { procedure_type: string; required_certification: string; start_minute: number; end_minute: number; secondary_resource_requirements?: string[] }, headers: ApiHeadersBase) =>
    makeRequest<Procedure>('POST', `/treatment-plans/${planId}/ward-rotations/${rotationId}/procedures`, payload, headers),

  getProcedures: (planId: string, rotationId: string, headers: ApiHeadersBase) =>
    makeRequest<Procedure[]>('GET', `/treatment-plans/${planId}/ward-rotations/${rotationId}/procedures`, undefined, headers),

  getProcedure: (planId: string, rotationId: string, procedureId: string, headers: ApiHeadersBase) =>
    makeRequest<Procedure>('GET', `/treatment-plans/${planId}/ward-rotations/${rotationId}/procedures/${procedureId}`, undefined, headers),

  cancelProcedure: (planId: string, rotationId: string, procedureId: string, headers: ApiHeadersBase) =>
    makeRequest<Procedure>('POST', `/treatment-plans/${planId}/ward-rotations/${rotationId}/procedures/${procedureId}/cancel`, undefined, headers),

  createAssignment: (planId: string, payload: AssignmentPayload, headers: ApiHeadersBase) =>
    makeRequest<Assignment>('POST', `/treatment-plans/${planId}/assignments`, payload, headers),

  getAssignments: (planId: string, params: { limit?: number; offset?: number } | undefined, headers: ApiHeadersBase) =>
    makeRequest<Assignment[]>('GET', `/treatment-plans/${planId}/assignments`, params, headers),

  getAssignment: (planId: string, assignmentId: string, headers: ApiHeadersBase) =>
    makeRequest<Assignment>('GET', `/treatment-plans/${planId}/assignments/${assignmentId}`, undefined, headers),

  rejectAssignment: (planId: string, assignmentId: string, headers: ApiHeadersBase) =>
    makeRequest<Assignment>('POST', `/treatment-plans/${planId}/assignments/${assignmentId}/reject`, undefined, headers),

  cancelAssignment: (planId: string, assignmentId: string, headers: ApiHeadersBase) =>
    makeRequest<Assignment>('POST', `/treatment-plans/${planId}/assignments/${assignmentId}/cancel`, undefined, headers),

  protocolApproveAssignment: (planId: string, assignmentId: string, headers: ApiHeadersBase) =>
    makeRequest<Assignment>('POST', `/treatment-plans/${planId}/assignments/${assignmentId}/protocol-approve`, undefined, headers),

  scheduleAssignment: (planId: string, assignmentId: string, headers: ApiHeadersBase) =>
    makeRequest<Assignment>('POST', `/treatment-plans/${planId}/assignments/${assignmentId}/schedule`, undefined, headers),

  createMedicalResource: (planId: string, payload: { resource_name: string; resource_model: string; operating_cost_per_minute: number; maintenance_threshold_override?: number | null; sterilization_buffer_override?: number | null; setup_overhead_minutes?: number; teardown_overhead_minutes?: number }, headers: ApiHeadersBase) =>
    makeRequest<MedicalResource>('POST', `/treatment-plans/${planId}/medical-resources`, payload, headers),

  getMedicalResources: (planId: string, params: { limit?: number; offset?: number } | undefined, headers: ApiHeadersBase) =>
    makeRequest<MedicalResource[]>('GET', `/treatment-plans/${planId}/medical-resources`, params, headers),

  getMedicalResource: (planId: string, resourceId: string, headers: ApiHeadersBase) =>
    makeRequest<MedicalResource>('GET', `/treatment-plans/${planId}/medical-resources/${resourceId}`, undefined, headers),

  addMedicalResourceCertification: (planId: string, resourceId: string, payload: { name: string; applied_date: string }, headers: ApiHeadersBase) =>
    makeRequest<MedicalResource>('POST', `/treatment-plans/${planId}/medical-resources/${resourceId}/certifications`, payload, headers),

  createInfectionRiskPairing: (planId: string, payload: { resource_id_1: string; resource_id_2: string; reason?: string; quarantine_until_minute?: number | null }, headers: ApiHeadersBase) =>
    makeRequest<InfectionRiskPairing>('POST', `/treatment-plans/${planId}/infection-risk-pairings`, payload, headers),

  getInfectionRiskPairings: (planId: string, params: { limit?: number; offset?: number } | undefined, headers: ApiHeadersBase) =>
    makeRequest<InfectionRiskPairing[]>('GET', `/treatment-plans/${planId}/infection-risk-pairings`, params, headers),

  getInfectionRiskPairing: (planId: string, pairingId: string, headers: ApiHeadersBase) =>
    makeRequest<InfectionRiskPairing>('GET', `/treatment-plans/${planId}/infection-risk-pairings/${pairingId}`, undefined, headers),

  initiateFinalReview: (planId: string, headers: ApiHeadersBase) =>
    makeRequest<TreatmentPlan>('POST', `/treatment-plans/${planId}/initiate-final-review`, undefined, headers),

  finalizePlan: (planId: string, headers: ApiHeadersBase) =>
    makeRequest<TreatmentPlan>('POST', `/treatment-plans/${planId}/finalize-plan`, undefined, headers),

  createMaintenanceEvent: (planId: string, payload: { resource_id: string; at_minute: number }, headers: ApiHeadersBase) =>
    makeRequest<MaintenanceEvent>('POST', `/treatment-plans/${planId}/maintenance-events`, payload, headers),

  getMaintenanceEvents: (planId: string, headers: ApiHeadersBase) =>
    makeRequest<MaintenanceEvent[]>('GET', `/treatment-plans/${planId}/maintenance-events`, undefined, headers),

  getMaintenanceEvent: (planId: string, eventId: string, headers: ApiHeadersBase) =>
    makeRequest<MaintenanceEvent>('GET', `/treatment-plans/${planId}/maintenance-events/${eventId}`, undefined, headers),

  createResourceHold: (planId: string, payload: { resource_id: string; start_minute: number; end_minute: number; reason?: string }, headers: ApiHeadersBase) =>
    makeRequest<ResourceHold>('POST', `/treatment-plans/${planId}/resource-holds`, payload, headers),

  getResourceHolds: (planId: string, headers: ApiHeadersBase) =>
    makeRequest<ResourceHold[]>('GET', `/treatment-plans/${planId}/resource-holds`, undefined, headers),

  getResourceHold: (planId: string, holdId: string, headers: ApiHeadersBase) =>
    makeRequest<ResourceHold>('GET', `/treatment-plans/${planId}/resource-holds/${holdId}`, undefined, headers),

  cancelResourceHold: (planId: string, holdId: string, payload: { version?: number }, headers: ApiHeadersBase) =>
    makeRequest<ResourceHold>('POST', `/treatment-plans/${planId}/resource-holds/${holdId}/cancel`, payload, headers),

  authorizeOverride: (planId: string, assignmentId: string, headers: ApiHeadersBase) =>
    makeRequest<OverrideAuthorization>('POST', `/treatment-plans/${planId}/assignments/${assignmentId}/override-authorize`, {}, headers),

  decommissionResource: (planId: string, resourceId: string, payload: { version?: number }, headers: ApiHeadersBase) =>
    makeRequest<MedicalResource>('POST', `/treatment-plans/${planId}/medical-resources/${resourceId}/decommission`, payload, headers),

  cancelDecommissioning: (planId: string, resourceId: string, payload: { version?: number }, headers: ApiHeadersBase) =>
    makeRequest<MedicalResource>('POST', `/treatment-plans/${planId}/medical-resources/${resourceId}/cancel-decommissioning`, payload, headers),

  reallocateAssignment: (planId: string, assignmentId: string, payload: { new_resource_id: string; version?: number }, headers: ApiHeadersBase) =>
    makeRequest<Assignment>('POST', `/treatment-plans/${planId}/assignments/${assignmentId}/reallocate`, payload, headers),
} as const;
