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

export enum TreatmentPlanStatus {
  PLANNING = 'PLANNING',
  ACTIVE = 'ACTIVE',
  FINAL_REVIEW_PENDING = 'FINAL_REVIEW_PENDING',
  COMPLETED = 'COMPLETED'
}

export enum WardRotationStatus {
  PLANNING = 'PLANNING',
  READY_FOR_ASSIGNMENT = 'READY_FOR_ASSIGNMENT',
  COMPLETED = 'COMPLETED',
  CANCELLED = 'CANCELLED'
}

export enum ProcedureStatus {
  PENDING = 'PENDING',
  SCHEDULED = 'SCHEDULED',
  ASSIGNED = 'ASSIGNED',
  COMPLETED = 'COMPLETED',
  CANCELLED = 'CANCELLED'
}

export enum AssignmentStatus {
  PENDING_SCHEDULE = 'PENDING_SCHEDULE',
  PROTOCOL_APPROVED = 'PROTOCOL_APPROVED',
  SCHEDULED = 'SCHEDULED',
  COMPLETED = 'COMPLETED',
  REJECTED = 'REJECTED',
  CANCELLED = 'CANCELLED'
}

export enum UserRole {
  ChargeNurse = 'ChargeNurse',
  AttendingPhysician = 'AttendingPhysician',
  HospitalAdministrator = 'HospitalAdministrator'
}

export enum RequiredCertification {
  BSL_3_CERTIFIED = 'BSL-3_CERTIFIED',
  CARDIAC_CATHETERIZATION_LAB = 'CARDIAC_CATHETERIZATION_LAB',
  NONE = 'NONE'
}

export interface TreatmentPlan {
  id: string;
  plan_name: string;
  status: TreatmentPlanStatus;
  total_budget: number;
  cost_balance: number;
  patient_safety_score: number;
  policies?: {
    require_admin_auth_for_overrides?: boolean;
  };
  created_at: string;
  updated_at: string;
  version: number;
}

export interface WardRotation {
  id: string;
  plan_id: string;
  name: string;
  status: WardRotationStatus;
  start_minute: number;
  end_minute: number;
  created_at: string;
  updated_at: string;
  version: number;
}

export interface Procedure {
  id: string;
  rotation_id: string;
  plan_id: string;
  procedure_type: string;
  status: ProcedureStatus;
  required_certification: RequiredCertification;
  secondary_resource_requirements?: string[];
  start_minute: number;
  end_minute: number;
  duration_minutes: number;
  created_at: string;
  updated_at: string;
  version: number;
}

export enum MedicalResourceStatus {
  AVAILABLE = 'AVAILABLE',
  DECOMMISSIONING_PENDING = 'DECOMMISSIONING_PENDING',
  DECOMMISSIONED = 'DECOMMISSIONED'
}

export interface MedicalResource {
  id: string;
  plan_id: string;
  resource_name: string;
  resource_model: string;
  operating_cost_per_minute: number;
  maintenance_threshold_override?: number | null;
  sterilization_buffer_override?: number | null;
  setup_overhead_minutes?: number;
  teardown_overhead_minutes?: number;
  status?: MedicalResourceStatus;
  resource_certifications: {
    id: string;
    name: 'BSL-3_CERTIFIED' | 'CARDIAC_CATHETERIZATION_LAB';
    applied_date: string;
  }[];
  created_at: string;
  updated_at: string;
  version: number;
}

export interface Assignment {
  id: string;
  plan_id: string;
  procedure_id: string;
  resource_id: string;
  secondary_resource_ids?: string[];
  status: AssignmentStatus;
  override_protocol_check: boolean;
  protocol_override_penalty_applied: boolean;
  is_high_biorisk: boolean;
  provisional_cost: number;
  final_cost: number;
  created_at: string;
  updated_at: string;
  version: number;
}

export interface InfectionRiskPairing {
  id: string;
  plan_id: string;
  resource_id_1: string;
  resource_id_2: string;
  quarantine_until_minute?: number | null;
  reason?: string;
  created_at: string;
}

export interface AssignmentPayload {
  procedure_id: string;
  resource_id: string;
  secondary_resource_ids?: string[];
  override_protocol_check?: boolean;
}

export enum ResourceHoldStatus {
  ACTIVE = 'ACTIVE',
  CANCELLED = 'CANCELLED'
}

export interface MaintenanceEvent {
  id: string;
  plan_id: string;
  resource_id: string;
  at_minute: number;
  created_at: string;
  version: number;
}

export interface ResourceHold {
  id: string;
  plan_id: string;
  resource_id: string;
  start_minute: number;
  end_minute: number;
  reason?: string | null;
  status: ResourceHoldStatus;
  created_at: string;
  updated_at: string;
  version: number;
}

export interface OverrideAuthorization {
  id: string;
  plan_id: string;
  assignment_id: string;
  authorized_by_user_id: string;
  created_at: string;
}
