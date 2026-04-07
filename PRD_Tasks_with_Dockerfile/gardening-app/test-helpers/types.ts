export interface ResponseMetaBase {

  api_request_id: string;

  api_request_timestamp: string;
}

export interface PaginationMeta {
  limit: number;
  offset: number;
  total_count: number;
  has_more: boolean;
}

export type SuccessResponseType = 'object' | 'array';
export type ErrorResponseType = 'error';

export interface ApiSuccessEnvelope<T> {
  meta: ResponseMetaBase & Partial<PaginationMeta>;
  response_type: SuccessResponseType;
  data: T;
}

export interface ErrorResponseData {

  error_id: string;

  message: string;

  details?: Array<{ field: string; issue: string }>;
}

export interface ApiErrorEnvelope {
  meta: ResponseMetaBase;
  response_type: ErrorResponseType;
  data: ErrorResponseData;
}

export type ApiResponse<T> = ApiSuccessEnvelope<T> | ApiErrorEnvelope;

export enum UserRole {
  GardenManager = 'GardenManager',
  Gardener = 'Gardener',
  BillingAdmin = 'BillingAdmin',
}

export enum GardenPlanStatus {
  PLANNING = 'PLANNING',
  ACTIVE = 'ACTIVE',
  HARVESTING_PENDING = 'HARVESTING_PENDING',
  CLOSED = 'CLOSED',
}

export enum PlantingSeasonStatus {
  PLANNING = 'PLANNING',
  READY_FOR_PLANTING = 'READY_FOR_PLANTING',
  CANCELLED = 'CANCELLED',
}

export enum PlantingTaskStatus {
  PENDING = 'PENDING',
  APPROVED = 'APPROVED',
  SCHEDULED = 'SCHEDULED',
  CANCELLED = 'CANCELLED',
}

export enum TaskAssignmentStatus {
  PENDING = 'PENDING',
  APPROVED = 'APPROVED',
  SCHEDULED = 'SCHEDULED',
  BILLED = 'BILLED',
  REJECTED = 'REJECTED',
  CANCELLED = 'CANCELLED',
}

export enum RequiredAmendment {
  ACIDIC_SOIL = 'ACIDIC_SOIL',
  FUNGICIDE_TREATED = 'FUNGICIDE_TREATED',
  NONE = 'NONE',
}

export enum AmendmentName {
  ACIDIC_SOIL = 'ACIDIC_SOIL',
  FUNGICIDE_TREATED = 'FUNGICIDE_TREATED',
}

export interface GardenPlan {
  id: string;
  plan_name: string;
  status: GardenPlanStatus;
  total_water_credits: number;
  water_credits_balance: number;
  pest_risk_score: number;
  created_at: string;
  updated_at: string;
}

export interface PlantingSeason {
  id: string;
  plan_id: string;
  name: string;
  status: PlantingSeasonStatus;
  start_date: number;
  end_date: number;
  created_at: string;
  updated_at: string;
}

export interface PlantingTask {
  id: string;
  season_id: string;
  plant_type: string;
  plant_family: string;
  status: PlantingTaskStatus;
  required_amendment: RequiredAmendment;
  start_date: number;
  end_date: number;
  water_requirement_liters: number;
  created_at: string;
  updated_at: string;
  plan_id: string;
}

export interface Amendment {
  id: string;
  name: AmendmentName;
  applied_date: string;
}

export interface GardenPlot {
  id: string;
  plan_id: string;
  plot_name: string;
  plot_size_sqm: number;
  water_credits_per_liter: number;
  applied_amendments: Amendment[];
  incompatible_plot_ids: string[];
  last_task_family: string | null;
  created_at: string;
  updated_at: string;
}

export interface TaskAssignment {
  id: string;
  plan_id: string;
  task_id: string;
  plot_id: string;
  status: TaskAssignmentStatus;
  override_pest_check: boolean;
  pest_check_override_penalty_applied: boolean;
  is_water_stressed: boolean;
  provisional_credits: number;
  final_credits?: number;
  created_at: string;
  updated_at: string;
}

export interface CreateGardenPlanPayload {
  plan_name: string;
  total_water_credits: number;
}

export interface CreatePlantingSeasonPayload {
  name: string;
  start_date: number;
  end_date: number;
}

export interface UpdatePlantingSeasonStatusPayload {
  status: PlantingSeasonStatus.READY_FOR_PLANTING | PlantingSeasonStatus.CANCELLED;
}

export interface CreatePlantingTaskPayload {
  plant_type: string;
  plant_family: string;
  required_amendment?: RequiredAmendment;
  start_date: number;
  end_date: number;
  water_requirement_liters: number;
}

export interface CreateGardenPlotPayload {
  plot_name: string;
  plot_size_sqm: number;
  water_credits_per_liter: number;
}

export interface AddAmendmentPayload {
  name: AmendmentName.ACIDIC_SOIL | AmendmentName.FUNGICIDE_TREATED;
  applied_date: string;
}

export interface TaskAssignmentPayload {
  task_id: string;
  plot_id: string;
  override_pest_check?: boolean;
}

export interface SetPlotIncompatibilitiesPayload {
  plot_ids: string[];
}

export interface ApiHeaders {
  'X-User-ID': string;
  'X-User-Role': UserRole;
  [key: string]: string;
}
