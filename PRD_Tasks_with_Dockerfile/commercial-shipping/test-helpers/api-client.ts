import axios, { AxiosResponse, Method } from 'axios';
import {
  ApiResponse,
  VoyageManifest,
  PortCall,
  CargoContract,
  StowageLocation,
  StowagePlan,
  ProximityConflict,
  StowagePlanPayload,
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
  createVoyageManifest: (payload: { voyage_name: string; total_revenue_potential: number }, headers: ApiHeadersBase) =>
    makeRequest<VoyageManifest>('POST', '/voyage-manifests', payload, headers),

  getVoyageManifests: (headers: ApiHeadersBase) =>
    makeRequest<VoyageManifest[]>('GET', '/voyage-manifests', undefined, headers),

  getVoyageManifest: (manifestId: string, headers: ApiHeadersBase) =>
    makeRequest<VoyageManifest>('GET', `/voyage-manifests/${manifestId}`, undefined, headers),

  activateVoyageManifest: (manifestId: string, headers: ApiHeadersBase) =>
    makeRequest<VoyageManifest>('POST', `/voyage-manifests/${manifestId}/activate`, undefined, headers),

  createPortCall: (manifestId: string, payload: { name: string; start_hour: number; end_hour: number }, headers: ApiHeadersBase) =>
    makeRequest<PortCall>('POST', `/voyage-manifests/${manifestId}/port-calls`, payload, headers),

  getPortCalls: (manifestId: string, headers: ApiHeadersBase) =>
    makeRequest<PortCall[]>('GET', `/voyage-manifests/${manifestId}/port-calls`, undefined, headers),

  getPortCall: (manifestId: string, portCallId: string, headers: ApiHeadersBase) =>
    makeRequest<PortCall>('GET', `/voyage-manifests/${manifestId}/port-calls/${portCallId}`, undefined, headers),

  updatePortCallStatus: (manifestId: string, portCallId: string, payload: { status: string }, headers: ApiHeadersBase) =>
    makeRequest<PortCall>('PUT', `/voyage-manifests/${manifestId}/port-calls/${portCallId}`, payload, headers),

  createCargoContract: (manifestId: string, portCallId: string, payload: { cargo_type: string; cargo_class: string; required_imdg_class_code: string; start_hour: number; end_hour: number }, headers: ApiHeadersBase) =>
    makeRequest<CargoContract>('POST', `/voyage-manifests/${manifestId}/port-calls/${portCallId}/contracts`, payload, headers),

  getCargoContracts: (manifestId: string, portCallId: string, headers: ApiHeadersBase) =>
    makeRequest<CargoContract[]>('GET', `/voyage-manifests/${manifestId}/port-calls/${portCallId}/contracts`, undefined, headers),

  getCargoContract: (manifestId: string, portCallId: string, contractId: string, headers: ApiHeadersBase) =>
    makeRequest<CargoContract>('GET', `/voyage-manifests/${manifestId}/port-calls/${portCallId}/contracts/${contractId}`, undefined, headers),

  cancelCargoContract: (manifestId: string, portCallId: string, contractId: string, headers: ApiHeadersBase) =>
    makeRequest<CargoContract>('POST', `/voyage-manifests/${manifestId}/port-calls/${portCallId}/contracts/${contractId}/cancel`, undefined, headers),

  createStowagePlan: (manifestId: string, payload: StowagePlanPayload, headers: ApiHeadersBase) =>
    makeRequest<StowagePlan>('POST', `/voyage-manifests/${manifestId}/stowage-plans`, payload, headers),

  getStowagePlans: (manifestId: string, headers: ApiHeadersBase) =>
    makeRequest<StowagePlan[]>('GET', `/voyage-manifests/${manifestId}/stowage-plans`, undefined, headers),

  getStowagePlan: (manifestId: string, planId: string, headers: ApiHeadersBase) =>
    makeRequest<StowagePlan>('GET', `/voyage-manifests/${manifestId}/stowage-plans/${planId}`, undefined, headers),

  rejectStowagePlan: (manifestId: string, planId: string, headers: ApiHeadersBase) =>
    makeRequest<StowagePlan>('POST', `/voyage-manifests/${manifestId}/stowage-plans/${planId}/reject`, undefined, headers),

  cancelStowagePlan: (manifestId: string, planId: string, headers: ApiHeadersBase) =>
    makeRequest<StowagePlan>('POST', `/voyage-manifests/${manifestId}/stowage-plans/${planId}/cancel`, undefined, headers),

  complianceApproveStowagePlan: (manifestId: string, planId: string, headers: ApiHeadersBase) =>
    makeRequest<StowagePlan>('POST', `/voyage-manifests/${manifestId}/stowage-plans/${planId}/compliance-approve`, undefined, headers),

  scheduleStowagePlan: (manifestId: string, planId: string, headers: ApiHeadersBase) =>
    makeRequest<StowagePlan>('POST', `/voyage-manifests/${manifestId}/stowage-plans/${planId}/schedule`, undefined, headers),

  createStowageLocation: (manifestId: string, payload: { location_code: string; location_model: string; stowage_revenue_per_hour: number }, headers: ApiHeadersBase) =>
    makeRequest<StowageLocation>('POST', `/voyage-manifests/${manifestId}/stowage-locations`, payload, headers),

  getStowageLocations: (manifestId: string, headers: ApiHeadersBase) =>
    makeRequest<StowageLocation[]>('GET', `/voyage-manifests/${manifestId}/stowage-locations`, undefined, headers),

  getStowageLocation: (manifestId: string, locationId: string, headers: ApiHeadersBase) =>
    makeRequest<StowageLocation>('GET', `/voyage-manifests/${manifestId}/stowage-locations/${locationId}`, undefined, headers),

  addStowageLocationCertification: (manifestId: string, locationId: string, payload: { name: string; applied_date: string }, headers: ApiHeadersBase) =>
    makeRequest<StowageLocation>('POST', `/voyage-manifests/${manifestId}/stowage-locations/${locationId}/certifications`, payload, headers),

  createProximityConflict: (manifestId: string, payload: { location_id_1: string; location_id_2: string; reason?: string }, headers: ApiHeadersBase) =>
    makeRequest<ProximityConflict>('POST', `/voyage-manifests/${manifestId}/proximity-conflicts`, payload, headers),

  getProximityConflicts: (manifestId: string, headers: ApiHeadersBase) =>
    makeRequest<ProximityConflict[]>('GET', `/voyage-manifests/${manifestId}/proximity-conflicts`, undefined, headers),

  getProximityConflict: (manifestId: string, conflictId: string, headers: ApiHeadersBase) =>
    makeRequest<ProximityConflict>('GET', `/voyage-manifests/${manifestId}/proximity-conflicts/${conflictId}`, undefined, headers),

  initiateFinalReview: (manifestId: string, headers: ApiHeadersBase) =>
    makeRequest<VoyageManifest>('POST', `/voyage-manifests/${manifestId}/initiate-final-review`, undefined, headers),

  finalizeManifest: (manifestId: string, headers: ApiHeadersBase) =>
    makeRequest<VoyageManifest>('POST', `/voyage-manifests/${manifestId}/finalize-manifest`, undefined, headers),
} as const;
