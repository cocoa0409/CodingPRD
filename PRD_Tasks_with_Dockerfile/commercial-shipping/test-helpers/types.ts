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

export enum VoyageManifestStatus {
  PLANNING = 'PLANNING',
  ACTIVE = 'ACTIVE',
  FINAL_REVIEW_PENDING = 'FINAL_REVIEW_PENDING',
  COMPLETED = 'COMPLETED'
}

export enum PortCallStatus {
  PLANNING = 'PLANNING',
  READY_FOR_STOWAGE = 'READY_FOR_STOWAGE',
  COMPLETED = 'COMPLETED',
  CANCELLED = 'CANCELLED'
}

export enum CargoContractStatus {
  PENDING = 'PENDING',
  STOWAGE_PROPOSED = 'STOWAGE_PROPOSED',
  ASSIGNED = 'ASSIGNED',
  COMPLETED = 'COMPLETED',
  CANCELLED = 'CANCELLED'
}

export enum StowagePlanStatus {
  PENDING_APPROVAL = 'PENDING_APPROVAL',
  COMPLIANCE_APPROVED = 'COMPLIANCE_APPROVED',
  SCHEDULED = 'SCHEDULED',
  COMPLETED = 'COMPLETED',
  REJECTED = 'REJECTED',
  CANCELLED = 'CANCELLED'
}

export enum UserRole {
  LogisticsCoordinator = 'LogisticsCoordinator',
  CargoPlanner = 'CargoPlanner',
  PortAuthority = 'PortAuthority'
}

export enum CargoClass {
  GENERAL = 'GENERAL',
  HAZMAT = 'HAZMAT',
  REEFER = 'REEFER'
}

export enum ImdgClassCode {
  IMDG_CLASS_1_1 = 'IMDG_CLASS_1.1',
  IMDG_CLASS_6_1 = 'IMDG_CLASS_6.1',
  NONE = 'NONE'
}

export interface VoyageManifest {
  id: string;
  voyage_name: string;
  status: VoyageManifestStatus;
  total_revenue_potential: number;
  revenue_balance: number;
  compliance_risk_score: number;
  created_at: string;
  updated_at: string;
}

export interface PortCall {
  id: string;
  manifest_id: string;
  name: string;
  status: PortCallStatus;
  start_hour: number;
  end_hour: number;
  created_at: string;
  updated_at: string;
}

export interface CargoContract {
  id: string;
  port_call_id: string;
  manifest_id: string;
  cargo_type: string;
  cargo_class: CargoClass;
  status: CargoContractStatus;
  required_imdg_class_code: ImdgClassCode;
  start_hour: number;
  end_hour: number;
  duration_hours: number;
  created_at: string;
  updated_at: string;
}

export interface StowageLocation {
  id: string;
  manifest_id: string;
  location_code: string;
  location_model: string;
  stowage_revenue_per_hour: number;
  location_certifications: {
    id: string;
    name: 'IMDG_CLASS_1.1' | 'IMDG_CLASS_6.1';
    applied_date: string;
  }[];
  created_at: string;
  updated_at: string;
}

export interface StowagePlan {
  id: string;
  manifest_id: string;
  contract_id: string;
  location_id: string;
  status: StowagePlanStatus;
  used_special_permit: boolean;
  special_permit_penalty_applied: boolean;
  is_high_stress: boolean;
  provisional_revenue: number;
  final_revenue: number;
  created_at: string;
  updated_at: string;
}

export interface ProximityConflict {
  id: string;
  manifest_id: string;
  location_id_1: string;
  location_id_2: string;
  reason?: string;
  created_at: string;
}

export interface StowagePlanPayload {
  contract_id: string;
  location_id: string;
  use_special_permit?: boolean;
}
