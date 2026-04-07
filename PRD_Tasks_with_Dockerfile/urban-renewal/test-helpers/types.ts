export interface ResponseMetaBase {

  api_request_id: string;

  api_request_timestamp: string;

  idempotency_replay?: boolean;
}

export type SuccessResponseType = 'object' | 'array';
export type ErrorResponseType = 'error';

export interface ApiSuccessEnvelope<T> {
  meta: ResponseMetaBase;
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

export enum UrbanRenewalProjectStatus {
  PLANNING = 'PLANNING',
  IN_PROGRESS = 'IN_PROGRESS',
  FINAL_AUDIT_PENDING = 'FINAL_AUDIT_PENDING',
  READY_FOR_LEASING = 'READY_FOR_LEASING',
}

export enum RenovationPhaseStatus {
  PLANNING = 'PLANNING',
  READY_FOR_EXECUTION = 'READY_FOR_EXECUTION',
  COMPLETED = 'COMPLETED',
  CANCELLED = 'CANCELLED',
}

export enum WorkOrderStatus {
  PENDING = 'PENDING',
  AWAITING_CONFIRMATION = 'AWAITING_CONFIRMATION',
  CONTRACTED = 'CONTRACTED',
  COMPLETED = 'COMPLETED',
  CANCELLED = 'CANCELLED',
}

export enum CrewContractStatus {
  PROPOSED = 'PROPOSED',
  SPECIALIZATION_VERIFIED = 'SPECIALIZATION_VERIFIED',
  SCHEDULED = 'SCHEDULED',
  COMPLETED = 'COMPLETED',
  REJECTED = 'REJECTED',
  CANCELLED = 'CANCELLED',
}

export enum Specialization {
  PLUMBING = 'PLUMBING',
  ELECTRICAL = 'ELECTRICAL',
  ASBESTOS_REMOVAL = 'ASBESTOS_REMOVAL',
  GENERAL = 'GENERAL',
}

export interface UrbanRenewalProject {
  id: string;
  project_name: string;
  status: UrbanRenewalProjectStatus;
  renovation_budget: number;
  budget_balance: number;
  community_disruption_index: number;
  version?: number;
  created_at: string;
  updated_at: string;
  committed_costs?: number;
  incurred_costs?: number;
}

export interface RenovationPhase {
  id: string;
  project_id: string;
  name: string;
  status: RenovationPhaseStatus;
  start_hour: number;
  end_hour: number;
  version?: number;
  created_at: string;
  updated_at: string;
}

export interface WorkOrder {
  id: string;
  phase_id: string;
  project_id: string;
  task_type: string;
  status: WorkOrderStatus;
  required_specialization: Specialization;
  required_safety_clearance_level: number;
  start_hour: number;
  end_hour: number;
  duration_hours: number;
  version?: number;
  created_at: string;
  updated_at: string;
}

export interface RenovationCrewCertification {
  id: string;
  specialization_name: Specialization;
  clearance_level: number;
}

export interface RenovationCrew {
  id: string;
  project_id: string;
  crew_name: string;
  company_name: string;
  hourly_rate: number;
  crew_certifications: RenovationCrewCertification[];
  version?: number;
  created_at: string;
  updated_at: string;
}

export interface CrewContract {
  id: string;
  project_id: string;
  work_order_id: string;
  crew_id: string;
  status: CrewContractStatus;
  permit_waiver_used: boolean;
  permit_waiver_penalty_applied: boolean;
  is_hazardous_pay_rate: boolean;
  provisional_cost: number;
  final_cost: number;
  version?: number;
  created_at: string;
  updated_at: string;
}

export interface CrewConflictPairing {
  id: string;
  project_id: string;
  crew_id_1: string;
  crew_id_2: string;
  reason?: string;
  created_at: string;
}

export interface CrewContractPayload {
  work_order_id: string;
  crew_id: string;
  permit_waiver_used?: boolean;
}
