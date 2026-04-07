import axios, { AxiosResponse, Method } from 'axios';
import {
  ApiResponse,
  CreateGardenPlanPayload,
  CreatePlantingSeasonPayload,
  UpdatePlantingSeasonStatusPayload,
  CreatePlantingTaskPayload,
  CreateGardenPlotPayload,
  AddAmendmentPayload,
  TaskAssignmentPayload,
  SetPlotIncompatibilitiesPayload,
  GardenPlan,
  PlantingSeason,
  PlantingTask,
  GardenPlot,
  TaskAssignment,
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

  createGardenPlan: (payload: CreateGardenPlanPayload, headers: ApiHeadersBase) =>
    makeRequest<GardenPlan>('POST', '/garden-plans', payload, headers),

  getGardenPlans: (headers: ApiHeadersBase, params?: { limit?: number; offset?: number }) =>
    makeRequest<GardenPlan[]>('GET', '/garden-plans', params, headers),

  getGardenPlan: (planId: string, headers: ApiHeadersBase) =>
    makeRequest<GardenPlan>('GET', `/garden-plans/${planId}`, undefined, headers),

  activateGardenPlan: (planId: string, headers: ApiHeadersBase) =>
    makeRequest<GardenPlan>('POST', `/garden-plans/${planId}/activate`, undefined, headers),

  initiateHarvest: (planId: string, headers: ApiHeadersBase) =>
    makeRequest<GardenPlan>('POST', `/garden-plans/${planId}/initiate-harvest`, undefined, headers),

  generateHarvestReport: (planId: string, headers: ApiHeadersBase) =>
    makeRequest<any>('POST', `/garden-plans/${planId}/generate-harvest-report`, undefined, headers),

  createPlantingSeason: (planId: string, payload: CreatePlantingSeasonPayload, headers: ApiHeadersBase) =>
    makeRequest<PlantingSeason>('POST', `/garden-plans/${planId}/planting-seasons`, payload, headers),

  getPlantingSeasons: (planId: string, headers: ApiHeadersBase, params?: { limit?: number; offset?: number }) =>
    makeRequest<PlantingSeason[]>('GET', `/garden-plans/${planId}/planting-seasons`, params, headers),

  getPlantingSeason: (planId: string, seasonId: string, headers: ApiHeadersBase) =>
    makeRequest<PlantingSeason>('GET', `/garden-plans/${planId}/planting-seasons/${seasonId}`, undefined, headers),

  updatePlantingSeasonStatus: (planId: string, seasonId: string, payload: UpdatePlantingSeasonStatusPayload, headers: ApiHeadersBase) =>
    makeRequest<PlantingSeason>('PUT', `/garden-plans/${planId}/planting-seasons/${seasonId}`, payload, headers),

  createPlantingTask: (planId: string, seasonId: string, payload: CreatePlantingTaskPayload, headers: ApiHeadersBase) =>
    makeRequest<PlantingTask>('POST', `/garden-plans/${planId}/planting-seasons/${seasonId}/planting-tasks`, payload, headers),

  getPlantingTasks: (planId: string, seasonId: string, headers: ApiHeadersBase, params?: { limit?: number; offset?: number }) =>
    makeRequest<PlantingTask[]>('GET', `/garden-plans/${planId}/planting-seasons/${seasonId}/planting-tasks`, params, headers),

  getPlantingTask: (planId: string, seasonId: string, taskId: string, headers: ApiHeadersBase) =>
    makeRequest<PlantingTask>('GET', `/garden-plans/${planId}/planting-seasons/${seasonId}/planting-tasks/${taskId}`, undefined, headers),

  cancelPlantingTask: (planId: string, seasonId: string, taskId: string, headers: ApiHeadersBase) =>
    makeRequest<PlantingTask>('POST', `/garden-plans/${planId}/planting-seasons/${seasonId}/planting-tasks/${taskId}/cancel`, undefined, headers),

  createTaskAssignment: (planId: string, payload: TaskAssignmentPayload, headers: ApiHeadersBase) =>
    makeRequest<TaskAssignment>('POST', `/garden-plans/${planId}/task-assignments`, payload, headers),

  getTaskAssignments: (planId: string, headers: ApiHeadersBase, params?: { limit?: number; offset?: number }) =>
    makeRequest<TaskAssignment[]>('GET', `/garden-plans/${planId}/task-assignments`, params, headers),

  getTaskAssignment: (planId: string, assignmentId: string, headers: ApiHeadersBase) =>
    makeRequest<TaskAssignment>('GET', `/garden-plans/${planId}/task-assignments/${assignmentId}`, undefined, headers),

  rejectTaskAssignment: (planId: string, assignmentId: string, headers: ApiHeadersBase) =>
    makeRequest<TaskAssignment>('POST', `/garden-plans/${planId}/task-assignments/${assignmentId}/reject`, undefined, headers),

  cancelTaskAssignment: (planId: string, assignmentId: string, headers: ApiHeadersBase) =>
    makeRequest<TaskAssignment>('POST', `/garden-plans/${planId}/task-assignments/${assignmentId}/cancel`, undefined, headers),

  approveTaskAssignment: (planId: string, assignmentId: string, headers: ApiHeadersBase) =>
    makeRequest<TaskAssignment>('POST', `/garden-plans/${planId}/task-assignments/${assignmentId}/approve`, undefined, headers),

  scheduleTaskAssignment: (planId: string, assignmentId: string, headers: ApiHeadersBase) =>
    makeRequest<TaskAssignment>('POST', `/garden-plans/${planId}/task-assignments/${assignmentId}/schedule`, undefined, headers),

  createGardenPlot: (planId: string, payload: CreateGardenPlotPayload, headers: ApiHeadersBase) =>
    makeRequest<GardenPlot>('POST', `/garden-plans/${planId}/garden-plots`, payload, headers),

  getGardenPlots: (planId: string, headers: ApiHeadersBase, params?: { limit?: number; offset?: number }) =>
    makeRequest<GardenPlot[]>('GET', `/garden-plans/${planId}/garden-plots`, params, headers),

  getGardenPlot: (planId: string, plotId: string, headers: ApiHeadersBase) =>
    makeRequest<GardenPlot>('GET', `/garden-plans/${planId}/garden-plots/${plotId}`, undefined, headers),

  addAmendment: (planId: string, plotId: string, payload: AddAmendmentPayload, headers: ApiHeadersBase) =>
    makeRequest<GardenPlot>('POST', `/garden-plans/${planId}/garden-plots/${plotId}/amendments`, payload, headers),

  setPlotIncompatibilities: (planId: string, plotId: string, payload: SetPlotIncompatibilitiesPayload, headers: ApiHeadersBase) =>
    makeRequest<GardenPlot>('POST', `/garden-plans/${planId}/garden-plots/${plotId}/incompatibilities`, payload, headers),

} as const;
