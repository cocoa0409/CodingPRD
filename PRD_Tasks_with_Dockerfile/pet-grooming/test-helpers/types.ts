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
  ClinicManager = 'ClinicManager',
  GroomingTechnician = 'GroomingTechnician',
  BillingAdmin = 'BillingAdmin',
}

export enum GroomingDayStatus {
  PLANNING = 'PLANNING',
  ACTIVE = 'ACTIVE',
  INVOICING_PENDING = 'INVOICING_PENDING',
  CLOSED = 'CLOSED',
}

export enum SessionBlockStatus {
  PLANNING = 'PLANNING',
  READY_FOR_GROOMING = 'READY_FOR_GROOMING',
  CANCELLED = 'CANCELLED',
}

export enum GroomingJobStatus {
  PENDING = 'PENDING',
  SCHEDULED = 'SCHEDULED',
  CONFIRMED = 'CONFIRMED',
  CANCELLED = 'CANCELLED',
}

export enum JobAssignmentStatus {
  PROPOSED = 'PROPOSED',
  NEEDS_ALLERGY_REVIEW = 'NEEDS_ALLERGY_REVIEW',
  CONFIRMED = 'CONFIRMED',
  COMPLETE = 'COMPLETE',
  TERMINATED = 'TERMINATED',
  ON_HOLD = 'ON_HOLD',
}

export enum SpecialCapabilityName {
  NUT_ALLERGY_SAFE = 'NUT_ALLERGY_SAFE',
  GRASS_ALLERGY_SAFE = 'GRASS_ALLERGY_SAFE',
}

export enum RequiredAllergenType {
  NUT_ALLERGY = 'NUT_ALLERGY',
  GRASS_ALLERGY = 'GRASS_ALLERGY',
  NONE = 'NONE',
}

export interface GroomingDay {
  id: string;
  schedule_name: string;
  status: GroomingDayStatus;
  total_supply_budget: number;
  supply_stock_balance: number;
  allergy_exposure_score: number;
  created_at: string;
  updated_at: string;
}

export interface SessionBlock {
  id: string;
  grooming_day_id: string;
  name: string;
  status: SessionBlockStatus;
  start_time: number;
  end_time: number;
  created_at: string;
  updated_at: string;
}

export interface GroomingJob {
  id: string;
  session_block_id: string;
  pet_id: string;
  job_type: string;
  status: GroomingJobStatus;
  required_allergen_type: RequiredAllergenType;
  cannot_be_groomed_with_pet_ids: string[];
  start_time: number;
  end_time: number;
  duration_minutes: number;
  created_at: string;
  updated_at: string;
  grooming_day_id: string;
}

export interface SpecialCapability {
  id: string;
  name: SpecialCapabilityName;
  enabled_date: string;
}

export interface GroomerStation {
  id: string;
  grooming_day_id: string;
  station_name: string;
  station_type: string;
  supply_cost_per_hour: number;
  special_capabilities: SpecialCapability[];
  created_at: string;
  updated_at: string;
}

export interface JobAssignment {
  id: string;
  grooming_day_id: string;
  job_id: string;
  station_id: string;
  status: JobAssignmentStatus;
  override_allergy_check: boolean;
  allergy_override_penalty_applied: boolean;
  is_peak_session: boolean;
  provisional_supply_cost: number;
  final_supply_cost?: number;
  created_at: string;
  updated_at: string;
}

export interface CreateGroomingDayPayload {
  schedule_name: string;
  total_supply_budget: number;
}

export interface CreateSessionBlockPayload {
  name: string;
  start_time: number;
  end_time: number;
}

export interface UpdateSessionBlockStatusPayload {
  status: SessionBlockStatus.READY_FOR_GROOMING | SessionBlockStatus.CANCELLED;
}

export interface CreateGroomingJobPayload {
  pet_id: string;
  job_type: string;
  required_allergen_type?: RequiredAllergenType;
  cannot_be_groomed_with_pet_ids?: string[];
  start_time: number;
  end_time: number;
}

export interface CreateGroomerStationPayload {
  station_name: string;
  station_type: string;
  supply_cost_per_hour: number;
}

export interface AddSpecialCapabilityPayload {
  name: SpecialCapabilityName.NUT_ALLERGY_SAFE | SpecialCapabilityName.GRASS_ALLERGY_SAFE;
  enabled_date: string;
}

export interface JobAssignmentPayload {
  job_id: string;
  station_id: string;
  override_allergy_check?: boolean;
}
