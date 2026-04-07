export interface ApiMeta {
  api_request_id: string;
  api_request_period_index: number;
  pagination?: {
    total: number;
    page: number;
    per_page: number;
  };
}

export interface ApiResponse<T> {
  meta: ApiMeta;
  response_type: 'object' | 'array' | 'error';
  data: T;
}

export interface ApiError {
  error_id: string;
  message: string;
}

export type ApiErrorResponse = ApiResponse<ApiError>;

export interface ResearchProgram {
  id: string;
  name: string;
  description?: string;
  current_period_index: number;
  governance_overrides?: GovernanceOverrides;
  version: number;
  created_seq: number;
}

export interface ClinicalTrial {
  id: string;
  research_program_id: string;
  treatment_name: string;
  investigator_id: string;
  status: 'DRAFT' | 'ACTIVE' | 'SUSPENDED' | 'COMPLETED' | 'ABANDONED' | 'ETHICAL_REVIEW_LOCK';
  total_ethical_compliance_budget: number;
  effective_ethical_compliance_budget: number;
  ethical_compliance_balance: number;
  patient_safety_risk: number;
  portfolio_id?: string;
  is_under_contagion: boolean;
  deviation_penalty_tier: number;
  irb_id: string;

  total_operational_budget?: number;
  effective_operational_budget?: number;
  operational_balance?: number;
  suspension_reason?: 'FINANCIAL' | 'REGULATORY';

  grant_id?: string;
  overdraft_start_period_index?: number | null;
  version: number;
  created_seq: number;
}

export interface TrialPhase {
  id: string;
  trial_id: string;
  research_program_id: string;
  name: 'PHASE_I' | 'PHASE_II' | 'PHASE_III' | 'PHASE_IV';
  status: 'PENDING' | 'READY_FOR_PROCEDURES' | 'COMPLETED' | 'CANCELLED' | 'REVIEW_REQUIRED';
  version: number;
  created_seq: number;
}

export interface ProtocolProcedure {
  id: string;
  phase_id: string;
  trial_id: string;
  research_program_id: string;
  procedure_type: string;
  status: 'PENDING' | 'AWAITING_EXECUTION' | 'PASSED' | 'FAILED' | 'CANCELLED';
  required_cohort_tag: 'HEALTHY_VOLUNTEERS' | 'HIGH_RISK_PATIENTS' | 'NONE';
  base_risk_cost: number;
  integrity_score_value: number;
  version: number;
  created_seq: number;
}

export interface CohortProperty {
  property_id: string;
  name: 'HEALTHY_VOLUNTEERS' | 'HIGH_RISK_PATIENTS' | 'CONTAINS_PLACEBO';
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
}

export interface ProcedureExecution {
  id: string;
  trial_id: string;
  research_program_id: string;
  procedure_id: string;
  cohort_id: string;
  status: 'PENDING_EXECUTION' | 'EXECUTED' | 'PASSED' | 'REJECTED' | 'CANCELLED';
  protocol_deviation: boolean;
  deviation_penalty_applied: boolean;
  is_expedited_review: boolean;
  provisional_risk_debit: number;
  final_risk_debit: number;
  proposing_user_id: string;
  version: number;
  created_seq: number;
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
}

export interface InvestigatorReputation {
  research_program_id: string;
  investigator_id: string;
  reputation_score: number;
  is_on_probation: boolean;
}

export interface GovernanceOverrides {
  expedited_threshold_points?: number;
  expedited_multiplier?: number;
  audit_lock_threshold?: number;
  probation_threshold_score?: number;
  probation_trial_budget_cap?: number;
  saturation_percent_threshold?: number;
  max_active_deviations_per_user?: number;
  contagion_penalty?: number;
  penalty_ethical_lock?: number;
  penalty_abandoned_trial?: number;
  penalty_dependency_ripple?: number;
  cancel_tier0_penalty?: number;
  cancel_tier1_penalty?: number;
  cancel_tier2plus_penalty?: number;

  phase_execution_limit?: Record<string, number>;

  risk_scaling_threshold?: number;

  financial_suspension_grace_period?: number;
}

export interface TreatmentDependency {
  id: string;
  source_trial_id: string;
  dependency_trial_id: string;
  research_program_id: string;
  reason?: string;
  version: number;
  created_seq: number;
}

export interface InstitutionalReviewBoard {
  id: string;
  research_program_id: string;
  name: string;
  description?: string;
  version: number;
  created_seq: number;
}

export interface IRBApproval {
  id: string;
  irb_id: string;
  trial_id: string;
  research_program_id: string;
  status: 'PENDING' | 'APPROVED' | 'REJECTED';
  version: number;
  created_seq: number;
}

export interface IncompatibleCohortPhasePairing {
  id: string;
  research_program_id: string;
  cohort_property: 'CONTAINS_PLACEBO';
  phase_name: 'PHASE_I' | 'PHASE_II' | 'PHASE_III' | 'PHASE_IV';
  reason: string;
  version: number;
  created_seq: number;
}

export interface TrialHistoryEntry {
  id: string;
  trial_id: string;
  research_program_id: string;
  event_type: string;
  description: string;
  user_id: string;
  period_index: number;
  created_at: string;
  created_seq: number;
}

export interface SiteInvestigatorCap {
  id: string;
  site_id: string;
  research_program_id: string;
  investigator_id: string;
  max_active_trials: number;
  version: number;
  created_seq: number;
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
}

export interface CreateResearchProgramRequest {
  name: string;
  description?: string;

  governance_overrides?: GovernanceOverrides;
}

export interface CreateTrialRequest {
  treatment_name: string;
  total_ethical_compliance_budget: number;
  portfolio_id?: string;
  irb_id: string;

  total_operational_budget?: number;
  site_id?: string;

  execution_window_start_period_index?: number;
  execution_window_end_period_index?: number;

  grant_id?: string;
}

export interface CreatePhaseRequest {
  name: 'PHASE_I' | 'PHASE_II' | 'PHASE_III' | 'PHASE_IV';

  max_active_executions?: number;
}

export interface CreateProcedureRequest {
  procedure_type: string;
  required_cohort_tag: 'HEALTHY_VOLUNTEERS' | 'HIGH_RISK_PATIENTS' | 'NONE';
  base_risk_cost: number;
  integrity_score_value: number;

  operational_cost?: number;
  required_certification_id?: string;
  is_integrity_procedure?: boolean;

  sets_flag_on_pass?: string;
  required_flags?: string[];
  excluded_flags?: string[];
}

export interface CreateCohortRequest {
  cohort_name: string;
  cohort_version: string;
  base_risk_points: number;
  properties: CohortProperty[];
}

export interface CreateExecutionRequest {
  procedure_id: string;
  cohort_id: string;
  protocol_deviation: boolean;
}

export interface CreatePortfolioRequest {
  name: string;
  description?: string;
  max_total_ethical_budget: number;
}

export interface ManualRiskAdjustmentRequest {
  adjustment: number;
  justification: string;
}

export interface AdvanceClockRequest {
  by_periods: number;
}

export interface CreateDependencyRequest {
  dependency_trial_id: string;
  reason?: string;
}

export interface UpdatePhaseRequest {
  status: string;
  version: number;
}

export interface UpdatePortfolioRequest {
  name?: string;
  description?: string;
  max_total_ethical_budget?: number;
  version: number;
}

export interface UpdateIRBApprovalRequest {
  status: 'APPROVED' | 'REJECTED';
  version: number;
}

export interface UpdateResearchProgramRequest {
  max_active_trials_per_investigator?: number | null;
  governance_overrides?: GovernanceOverrides;
  version?: number;
}

export interface CreateInvestigatorCapRequest {
  investigator_id: string;
  max_active_trials: number;
}

export interface UpdateInvestigatorCapRequest {
  max_active_trials: number;
  version?: number;
}
