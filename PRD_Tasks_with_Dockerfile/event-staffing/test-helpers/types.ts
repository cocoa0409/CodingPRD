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
  StaffingCoordinator = 'StaffingCoordinator',
  StaffMember = 'StaffMember',
  AccountManager = 'AccountManager',
}

export enum ContractStatus {
  PLANNING = 'PLANNING',
  ACTIVE = 'ACTIVE',
  PAYROLL_PENDING = 'PAYROLL_PENDING',
  CLOSED = 'CLOSED',
}

export enum EventStatus {
  PLANNING = 'PLANNING',
  READY_FOR_EXECUTION = 'READY_FOR_EXECUTION',
  CANCELLED = 'CANCELLED',
}

export enum ShiftStatus {
  OPEN = 'OPEN',
  PENDING_CONFIRMATION = 'PENDING_CONFIRMATION',
  FILLED = 'FILLED',
  CANCELLED = 'CANCELLED',
}

export enum AssignmentStatus {
  PROPOSED = 'PROPOSED',
  ACCEPTED = 'ACCEPTED',
  CONFIRMED = 'CONFIRMED',
  PAID = 'PAID',
  DECLINED = 'DECLINED',
  CANCELLED = 'CANCELLED',
}

export enum CertificationType {
  FOOD_HANDLER_PERMIT = 'FOOD_HANDLER_PERMIT',
  ALCOHOL_SERVICE_LICENSE = 'ALCOHOL_SERVICE_LICENSE',
  NONE = 'NONE',
}

export interface StaffingContract {
  id: string;
  client_name: string;
  status: ContractStatus;
  total_budget: number;
  budget_balance: number;
  compliance_risk_score: number;
  created_at: string;
  updated_at: string;
}

export interface Event {
  id: string;
  contract_id: string;
  name: string;
  status: EventStatus;
  start_time: number;
  end_time: number;
  created_at: string;
  updated_at: string;
}

export interface Shift {
  id: string;
  event_id: string;
  contract_id: string;
  role_name: string;
  status: ShiftStatus;
  certification_needed: CertificationType;
  start_time: number;
  end_time: number;
  duration_hours: number;
  created_at: string;
  updated_at: string;
}

export interface Certification {
  id: string;
  name: CertificationType;
  issued_date: string;
  expiry_date: string;
}

export interface StaffProfile {
  id: string;
  contract_id: string;
  first_name: string;
  last_name: string;
  base_pay_rate_per_hour: number;
  certifications: Certification[];
  created_at: string;
  updated_at: string;
}

export interface Assignment {
  id: string;
  contract_id: string;
  shift_id: string;
  staff_profile_id: string;
  status: AssignmentStatus;
  override_risk_check: boolean;
  risk_override_penalty_applied: boolean;
  is_overtime_eligible: boolean;
  provisional_cost: number;
  final_payout?: number;
  created_at: string;
  updated_at: string;
}

export interface ConflictPairing {
  id: string;
  contract_id: string;
  staff_profile_id_1: string;
  staff_profile_id_2: string;
  reason?: string | null;
  created_at: string;
}

export interface CreateContractPayload {
  client_name: string;
  total_budget: number;
}

export interface CreateEventPayload {
  name: string;
  start_time: number;
  end_time: number;
}

export interface UpdateEventStatusPayload {
  status: EventStatus.READY_FOR_EXECUTION | EventStatus.CANCELLED;
}

export interface CreateShiftPayload {
  role_name: string;
  certification_needed?: CertificationType;
  start_time: number;
  end_time: number;
}

export interface CreateStaffProfilePayload {
  first_name: string;
  last_name: string;
  base_pay_rate_per_hour: number;
}

export interface AddCertificationPayload {
  name: CertificationType.FOOD_HANDLER_PERMIT | CertificationType.ALCOHOL_SERVICE_LICENSE;
  issued_date: string;
  expiry_date: string;
}

export interface CreateAssignmentPayload {
  shift_id: string;
  staff_profile_id: string;
  override_risk_check?: boolean;
}

export interface CreateConflictPairingPayload {
  staff_profile_id_1: string;
  staff_profile_id_2: string;
  reason?: string | null;
}
