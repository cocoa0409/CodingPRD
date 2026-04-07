import { AxiosResponse } from "axios";
import { ApiErrorId } from "./api-errors";
import { ApiResponse } from "./types";
import { validateErrorEnvelope } from "./validators";

export interface ApiHeaders {
  'X-User-ID': string;
  [key: string]: string;
}

export function buildAuthHeaders(userId: string): ApiHeaders {
  return {
    'X-User-ID': userId,
  };
}

export function createScheduleHour(hoursFromBase: number, baseHour: number = 0): number {
  return baseHour + hoursFromBase;
}

export function addHours(scheduleHour: number, hours: number): number {
  return scheduleHour + hours;
}

export function expectApiError(response: AxiosResponse<ApiResponse<any>>, expectedErrorId: ApiErrorId): void {
  validateErrorEnvelope(response, { expectedErrorId });
}
