import axios, { AxiosResponse, Method } from 'axios';
import {
  ApiResponse,
  CreateMealOrderPayload,
  CreateRecipePayload,
  UpdateRecipeStatusPayload,
  CreateCookingStepPayload,
  CreateCookingStationPayload,
  AddUtensilCapabilityPayload,
  TaskExecutionPayload,
  CreateFoodSafetyProtocolPayload,
  MealOrder,
  Recipe,
  CookingStep,
  CookingStation,
  TaskExecution,
  FoodSafetyProtocol,
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

  createMealOrder: (payload: CreateMealOrderPayload, headers: ApiHeadersBase) =>
    makeRequest<MealOrder>('POST', '/meal-orders', payload, headers),

  getMealOrders: (headers: ApiHeadersBase, params?: { limit?: number; offset?: number }) => {
    return makeRequest<MealOrder[]>('GET', '/meal-orders', params, headers);
  },

  getMealOrder: (orderId: string, headers: ApiHeadersBase) =>
    makeRequest<MealOrder>('GET', `/meal-orders/${orderId}`, undefined, headers),

  updateMealOrder: (orderId: string, payload: { total_payment: number }, headers: ApiHeadersBase) =>
    makeRequest<MealOrder>('PUT', `/meal-orders/${orderId}`, payload, headers),

  beginCooking: (orderId: string, headers: ApiHeadersBase) =>
    makeRequest<MealOrder>('POST', `/meal-orders/${orderId}/begin-cooking`, undefined, headers),

  finishCooking: (orderId: string, headers: ApiHeadersBase) =>
    makeRequest<MealOrder>('POST', `/meal-orders/${orderId}/finish-cooking`, undefined, headers),

  markOrderComplete: (orderId: string, headers: ApiHeadersBase) =>
    makeRequest<MealOrder>('POST', `/meal-orders/${orderId}/mark-order-complete`, undefined, headers),

  createRecipe: (orderId: string, payload: CreateRecipePayload, headers: ApiHeadersBase) =>
    makeRequest<Recipe>('POST', `/meal-orders/${orderId}/recipes`, payload, headers),

  getRecipes: (orderId: string, headers: ApiHeadersBase, params?: { limit?: number; offset?: number }) => {
    return makeRequest<Recipe[]>('GET', `/meal-orders/${orderId}/recipes`, params, headers);
  },

  getRecipe: (orderId: string, recipeId: string, headers: ApiHeadersBase) =>
    makeRequest<Recipe>('GET', `/meal-orders/${orderId}/recipes/${recipeId}`, undefined, headers),

  updateRecipeStatus: (orderId: string, recipeId: string, payload: UpdateRecipeStatusPayload, headers: ApiHeadersBase) =>
    makeRequest<Recipe>('PUT', `/meal-orders/${orderId}/recipes/${recipeId}`, payload, headers),

  createCookingStep: (orderId: string, recipeId: string, payload: CreateCookingStepPayload, headers: ApiHeadersBase) =>
    makeRequest<CookingStep>('POST', `/meal-orders/${orderId}/recipes/${recipeId}/cooking-steps`, payload, headers),

  getCookingSteps: (orderId: string, recipeId: string, headers: ApiHeadersBase, params?: { limit?: number; offset?: number }) => {
    return makeRequest<CookingStep[]>('GET', `/meal-orders/${orderId}/recipes/${recipeId}/cooking-steps`, params, headers);
  },

  getCookingStep: (orderId: string, recipeId: string, stepId: string, headers: ApiHeadersBase) =>
    makeRequest<CookingStep>('GET', `/meal-orders/${orderId}/recipes/${recipeId}/cooking-steps/${stepId}`, undefined, headers),

  createCookingStation: (orderId: string, payload: CreateCookingStationPayload, headers: ApiHeadersBase) =>
    makeRequest<CookingStation>('POST', `/meal-orders/${orderId}/cooking-stations`, payload, headers),

  getCookingStations: (orderId: string, headers: ApiHeadersBase, params?: { limit?: number; offset?: number }) => {
    return makeRequest<CookingStation[]>('GET', `/meal-orders/${orderId}/cooking-stations`, params, headers);
  },

  getCookingStation: (orderId: string, stationId: string, headers: ApiHeadersBase) =>
    makeRequest<CookingStation>('GET', `/meal-orders/${orderId}/cooking-stations/${stationId}`, undefined, headers),

  addUtensilCapability: (orderId: string, stationId: string, payload: AddUtensilCapabilityPayload, headers: ApiHeadersBase) =>
    makeRequest<CookingStation>('POST', `/meal-orders/${orderId}/cooking-stations/${stationId}/utensil-capabilities`, payload, headers),

  proposeTaskExecution: (orderId: string, payload: TaskExecutionPayload, headers: ApiHeadersBase) =>
    makeRequest<TaskExecution>('POST', `/meal-orders/${orderId}/task-executions`, payload, headers),

  getTaskExecutions: (orderId: string, headers: ApiHeadersBase, params?: { limit?: number; offset?: number }) => {
    return makeRequest<TaskExecution[]>('GET', `/meal-orders/${orderId}/task-executions`, params, headers);
  },

  getTaskExecution: (orderId: string, recordId: string, headers: ApiHeadersBase) =>
    makeRequest<TaskExecution>('GET', `/meal-orders/${orderId}/task-executions/${recordId}`, undefined, headers),

  acknowledgeExecution: (orderId: string, recordId: string, headers: ApiHeadersBase) =>
    makeRequest<TaskExecution>('POST', `/meal-orders/${orderId}/task-executions/${recordId}/acknowledge`, undefined, headers),

  rejectExecution: (orderId: string, recordId: string, headers: ApiHeadersBase) =>
    makeRequest<TaskExecution>('POST', `/meal-orders/${orderId}/task-executions/${recordId}/reject`, undefined, headers),

  bindStep: (orderId: string, recordId: string, headers: ApiHeadersBase) =>
    makeRequest<TaskExecution>('POST', `/meal-orders/${orderId}/task-executions/${recordId}/bind`, undefined, headers),

  cancelExecution: (orderId: string, recordId: string, headers: ApiHeadersBase) =>
    makeRequest<TaskExecution>('POST', `/meal-orders/${orderId}/task-executions/${recordId}/cancel`, undefined, headers),

  createFoodSafetyProtocol: (orderId: string, payload: CreateFoodSafetyProtocolPayload, headers: ApiHeadersBase) =>
    makeRequest<FoodSafetyProtocol>('POST', `/meal-orders/${orderId}/food-safety-protocols`, payload, headers),

  getFoodSafetyProtocols: (orderId: string, headers: ApiHeadersBase, params?: { limit?: number; offset?: number }) => {
    return makeRequest<FoodSafetyProtocol[]>('GET', `/meal-orders/${orderId}/food-safety-protocols`, params, headers);
  },

  getFoodSafetyProtocol: (orderId: string, protocolId: string, headers: ApiHeadersBase) =>
    makeRequest<FoodSafetyProtocol>('GET', `/meal-orders/${orderId}/food-safety-protocols/${protocolId}`, undefined, headers),
} as const;
