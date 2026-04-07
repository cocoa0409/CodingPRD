export interface ResearchProgram {
  id: string;
  name: string;
  description?: string;
  current_period_index: number;
  version: number;
  created_seq: number;
  created_at: string;
  updated_at: string;
}

export type TrialStatus =
  | 'DRAFT'
  | 'ACTIVE'
  | 'COMPLETED'
  | 'ABANDONED'
  | 'ETHICAL_REVIEW_LOCK';

export interface ClinicalTrial {
  id: string;
  research_program_id: string;
  treatment_name: string;
  investigator_id: string;
  status: TrialStatus;
  total_ethical_compliance_budget: number;
  effective_ethical_compliance_budget: number;
  ethical_compliance_balance: number;
  patient_safety_risk: number;
  portfolio_id?: string;
  is_under_contagion: boolean;
  deviation_penalty_tier: number;
  irb_id: string;
  version: number;
  created_seq: number;
  created_at: string;
  updated_at: string;
}

export type PhaseStatus =
  | 'PENDING'
  | 'READY_FOR_PROCEDURES'
  | 'COMPLETED'
  | 'CANCELLED'
  | 'REVIEW_REQUIRED';

export type PhaseName = 'PHASE_I' | 'PHASE_II' | 'PHASE_III' | 'PHASE_IV';

export interface TrialPhase {
  id: string;
  trial_id: string;
  research_program_id: string;
  name: PhaseName;
  status: PhaseStatus;
  version: number;
  created_seq: number;
  created_at: string;
  updated_at: string;
}

export type ProcedureStatus =
  | 'PENDING'
  | 'AWAITING_EXECUTION'
  | 'PASSED'
  | 'FAILED'
  | 'CANCELLED';

export type CohortTag = 'HEALTHY_VOLUNTEERS' | 'HIGH_RISK_PATIENTS' | 'NONE';

export interface ProtocolProcedure {
  id: string;
  phase_id: string;
  trial_id: string;
  research_program_id: string;
  procedure_type: string;
  status: ProcedureStatus;
  required_cohort_tag: CohortTag;
  base_risk_cost: number;
  integrity_score_value: number;
  version: number;
  created_seq: number;
  created_at: string;
  updated_at: string;
}

export type CohortPropertyName =
  | 'HEALTHY_VOLUNTEERS'
  | 'HIGH_RISK_PATIENTS'
  | 'CONTAINS_PLACEBO';

export interface CohortProperty {
  property_id: string;
  name: CohortPropertyName;
  certified_period_index: number;
}

export interface PatientCohort {
  id: string;
  trial_id: string;
  research_program_id: string;
  cohort_name: string;
  cohort_version: string;
  base_risk_points: number;
  properties: CohortProperty[];
  version: number;
  created_seq: number;
  created_at: string;
  updated_at: string;
}

export type ExecutionStatus =
  | 'PENDING_EXECUTION'
  | 'EXECUTED'
  | 'PASSED'
  | 'REJECTED'
  | 'CANCELLED';

export interface ProcedureExecution {
  id: string;
  trial_id: string;
  research_program_id: string;
  procedure_id: string;
  cohort_id: string;
  status: ExecutionStatus;
  protocol_deviation: boolean;
  deviation_penalty_applied: boolean;
  is_expedited_review: boolean;
  provisional_risk_debit: number;
  final_risk_debit: number;
  proposing_user_id: string;
  version: number;
  created_seq: number;
  created_at: string;
  updated_at: string;
}

export interface TreatmentDependency {
  id: string;
  source_trial_id: string;
  dependency_trial_id: string;
  research_program_id: string;
  reason?: string;
  version: number;
  created_seq: number;
  created_at: string;
  updated_at: string;
}

export interface TrialPortfolio {
  id: string;
  research_program_id: string;
  name: string;
  description?: string;
  max_total_ethical_budget: number;
  is_risk_saturated: boolean;
  version: number;
  created_seq: number;
  created_at: string;
  updated_at: string;
}

export interface IncompatibleCohortPhasePairing {
  id: string;
  research_program_id: string;
  cohort_property: CohortPropertyName;
  phase_name: PhaseName;
  reason: string;
  version: number;
  created_seq: number;
  created_at: string;
  updated_at: string;
}

export interface EnrollmentBlackoutWindow {
  id: string;
  research_program_id: string;
  treatment_name_pattern: string;
  start_period_index: number;
  end_period_index: number;
  reason: string;
  version: number;
  created_seq: number;
  created_at: string;
  updated_at: string;
}

export interface InstitutionalReviewBoard {
  id: string;
  research_program_id: string;
  name: string;
  description?: string;
  version: number;
  created_seq: number;
  created_at: string;
  updated_at: string;
}

export type IRBApprovalStatus = 'PENDING' | 'APPROVED' | 'REJECTED';

export interface IRBApproval {
  id: string;
  irb_id: string;
  trial_id: string;
  research_program_id: string;
  status: IRBApprovalStatus;
  version: number;
  created_seq: number;
  created_at: string;
  updated_at: string;
}

export interface EthicalComplianceBudget {
  provisional_debits: number;
  finalized_debits: number;
}

export interface PatientSafetyRisk {
  risk_score: number;
}

export interface InvestigatorReputation {
  reputation_score: number;
  is_on_probation: boolean;
}

export interface CreateProgramRequest {
  name: string;
  description?: string;
}

export interface AdvanceClockRequest {
  by_periods: number;
}

export interface CreatePortfolioRequest {
  name: string;
  description?: string;
  max_total_ethical_budget: number;
}

export interface UpdatePortfolioRequest {
  name?: string;
  description?: string;
  max_total_ethical_budget?: number;
  version?: number;
}

export interface CreateTrialRequest {
  treatment_name: string;
  total_ethical_compliance_budget: number;
  portfolio_id?: string;
  irb_id: string;
}

export interface CreatePhaseRequest {
  name: PhaseName;
}

export interface UpdatePhaseRequest {
  status: PhaseStatus;
  version?: number;
}

export interface CreateProcedureRequest {
  procedure_type: string;
  required_cohort_tag: CohortTag;
  base_risk_cost: number;
  integrity_score_value: number;
}

export interface CreateCohortRequest {
  cohort_name: string;
  cohort_version: string;
  base_risk_points: number;
  properties: Omit<CohortProperty, 'property_id'>[];
}

export interface CreateExecutionRequest {
  procedure_id: string;
  cohort_id: string;
  protocol_deviation: boolean;
}

export interface CreateDependencyRequest {
  dependency_trial_id: string;
  reason?: string;
}

export interface CreateIRBRequest {
  name: string;
  description?: string;
}

export interface CreateIRBApprovalRequest {
  trial_id: string;
}

export interface UpdateIRBApprovalRequest {
  status: IRBApprovalStatus;
  version?: number;
}

export interface CreateIncompatiblePairingRequest {
  cohort_property: CohortPropertyName;
  phase_name: PhaseName;
  reason: string;
}

export interface CreateBlackoutWindowRequest {
  treatment_name_pattern: string;
  start_period_index: number;
  end_period_index: number;
  reason: string;
}

export interface ManualRiskAdjustmentRequest {
  adjustment: number;
  justification: string;
}

export interface ResponseMeta {
  api_request_id: string;
  api_request_period_index: number;
  limit?: number;
  offset?: number;
  total_count?: number;
  has_more?: boolean;
}

export interface SuccessResponse<T> {
  meta: ResponseMeta;
  response_type: 'object' | 'array';
  data: T;
}

export interface ErrorData {
  error_id: string;
  message: string;
}

export interface ErrorResponse {
  meta: ResponseMeta;
  response_type: 'error';
  data: ErrorData;
}

export type UserRole = 'ResearchDirector' | 'ClinicalCoordinator' | 'EthicsAuditor';

export interface AuthContext {
  userId: string;
  userRole: UserRole;
}
