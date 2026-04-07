export class ApiError extends Error {
  constructor(
    public statusCode: number,
    public errorId: string,
    message?: string
  ) {
    super(message || errorId);
    this.name = 'ApiError';
    Error.captureStackTrace(this, this.constructor);
  }
}

export const Errors = {
  NOT_FOUND: () => new ApiError(404, 'ERR_NOT_FOUND', 'Resource not found'),
  VERSION_MISMATCH: () => new ApiError(409, 'ERR_VERSION_MISMATCH', 'Version mismatch'),
  INVALID_REQUEST: (msg?: string) => new ApiError(400, 'ERR_INVALID_REQUEST', msg || 'Invalid request'),
  INSUFFICIENT_PERMISSIONS: () => new ApiError(403, 'ERR_INSUFFICIENT_PERMISSIONS', 'Insufficient permissions'),
  MISSING_OR_INVALID_USER_CONTEXT_HEADER: () => new ApiError(400, 'ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER', 'Missing or invalid user context header'),

  TRIAL_NOT_FOUND: () => new ApiError(404, 'ERR_TRIAL_NOT_FOUND', 'Trial not found'),
  PHASE_NOT_FOUND: () => new ApiError(404, 'ERR_PHASE_NOT_FOUND', 'Phase not found'),
  PROCEDURE_NOT_FOUND: () => new ApiError(404, 'ERR_PROCEDURE_NOT_FOUND', 'Procedure not found'),
  COHORT_NOT_FOUND: () => new ApiError(404, 'ERR_COHORT_NOT_FOUND', 'Cohort not found'),
  DEPENDENCY_TRIAL_NOT_FOUND: () => new ApiError(404, 'ERR_DEPENDENCY_TRIAL_NOT_FOUND', 'Dependency trial not found'),
  PORTFOLIO_NOT_FOUND: () => new ApiError(404, 'ERR_PORTFOLIO_NOT_FOUND', 'Portfolio not found'),
  PAIRING_NOT_FOUND: () => new ApiError(404, 'ERR_PAIRING_NOT_FOUND', 'Pairing not found'),
  BLACKOUT_WINDOW_NOT_FOUND: () => new ApiError(404, 'ERR_BLACKOUT_WINDOW_NOT_FOUND', 'Blackout window not found'),
  IRB_NOT_FOUND: () => new ApiError(404, 'ERR_IRB_NOT_FOUND', 'IRB not found'),
  IRB_APPROVAL_NOT_FOUND: () => new ApiError(404, 'ERR_IRB_APPROVAL_NOT_FOUND', 'IRB approval not found'),
  EXECUTION_NOT_FOUND: () => new ApiError(404, 'ERR_EXECUTION_NOT_FOUND', 'Execution not found'),

  TRIAL_NOT_ACTIVE: () => new ApiError(409, 'ERR_TRIAL_NOT_ACTIVE', 'Trial is not active'),
  TRIAL_IN_ETHICAL_REVIEW_LOCK: () => new ApiError(403, 'ERR_TRIAL_IN_ETHICAL_REVIEW_LOCK', 'Trial is in ethical review lock'),
  TRIAL_NOT_IN_ETHICAL_REVIEW_LOCK: () => new ApiError(409, 'ERR_TRIAL_NOT_IN_ETHICAL_REVIEW_LOCK', 'Trial is not in ethical review lock'),
  TRIAL_NOT_IN_DRAFT: () => new ApiError(409, 'ERR_TRIAL_NOT_IN_DRAFT', 'Trial is not in draft state'),
  TRIAL_NOT_ABANDONABLE: () => new ApiError(409, 'ERR_TRIAL_NOT_ABANDONABLE', 'Trial cannot be abandoned'),

  PROCEDURE_NOT_PENDING: () => new ApiError(409, 'ERR_PROCEDURE_NOT_PENDING', 'Procedure is not pending'),
  PROCEDURE_NOT_AWAITING_EXECUTION: () => new ApiError(409, 'ERR_PROCEDURE_NOT_AWAITING_EXECUTION', 'Procedure is not awaiting execution'),
  EXECUTION_NOT_PENDING: () => new ApiError(409, 'ERR_EXECUTION_NOT_PENDING', 'Execution is not pending'),
  EXECUTION_NOT_EXECUTED: () => new ApiError(409, 'ERR_EXECUTION_NOT_EXECUTED', 'Execution is not in executed state'),
  EXECUTION_NOT_REJECTABLE: () => new ApiError(409, 'ERR_EXECUTION_NOT_REJECTABLE', 'Execution cannot be rejected'),
  EXECUTION_NOT_CANCELLABLE: () => new ApiError(409, 'ERR_EXECUTION_NOT_CANCELLABLE', 'Execution cannot be cancelled'),

  ILLEGAL_PHASE_STATE_TRANSITION: () => new ApiError(409, 'ERR_ILLEGAL_PHASE_STATE_TRANSITION', 'Illegal phase state transition'),
  NO_PROCEDURES_DEFINED: () => new ApiError(409, 'ERR_NO_PROCEDURES_DEFINED', 'No procedures defined'),
  PROCEDURES_NOT_PASSED: () => new ApiError(409, 'ERR_PROCEDURES_NOT_PASSED', 'Not all procedures passed'),
  PHASE_IN_REVIEW: () => new ApiError(409, 'ERR_PHASE_IN_REVIEW', 'Phase is in review'),
  PHASE_NOT_IN_REVIEW: () => new ApiError(409, 'ERR_PHASE_NOT_IN_REVIEW', 'Phase is not in review'),

  UNRESOLVED_EXECUTIONS_EXIST: () => new ApiError(409, 'ERR_UNRESOLVED_EXECUTIONS_EXIST', 'Unresolved executions exist'),
  PHASES_NOT_COMPLETED: () => new ApiError(409, 'ERR_PHASES_NOT_COMPLETED', 'Not all phases completed'),
  DEPENDENCIES_NOT_MET: () => new ApiError(409, 'ERR_DEPENDENCIES_NOT_MET', 'Dependencies not met'),
  DEPENDENCY_IN_ETHICAL_REVIEW_LOCK: () => new ApiError(409, 'ERR_DEPENDENCY_IN_ETHICAL_REVIEW_LOCK', 'Dependency is in ethical review lock'),

  SELF_DEPENDENCY: () => new ApiError(400, 'ERR_SELF_DEPENDENCY', 'Cannot create self-dependency'),
  CROSS_PROGRAM_DEPENDENCY: () => new ApiError(400, 'ERR_CROSS_PROGRAM_DEPENDENCY', 'Cannot create cross-program dependency'),

  COHORT_TAG_MISMATCH: () => new ApiError(400, 'ERR_COHORT_TAG_MISMATCH', 'Cohort tag mismatch'),
  INCOMPATIBLE_COHORT_PHASE_PAIRING: () => new ApiError(409, 'ERR_INCOMPATIBLE_COHORT_PHASE_PAIRING', 'Incompatible cohort-phase pairing'),
  INVALID_PROPERTY_NAME: () => new ApiError(400, 'ERR_INVALID_PROPERTY_NAME', 'Invalid property name'),

  MAX_ACTIVE_DEVIATIONS_PER_USER_VIOLATION: () => new ApiError(409, 'ERR_MAX_ACTIVE_DEVIATIONS_PER_USER_VIOLATION', 'Maximum active deviations per user exceeded'),
  INSUFFICIENT_ETHICAL_BUDGET: () => new ApiError(402, 'ERR_INSUFFICIENT_ETHICAL_BUDGET', 'Insufficient ethical budget'),
  PORTFOLIO_RISK_SATURATED: () => new ApiError(403, 'ERR_PORTFOLIO_RISK_SATURATED', 'Portfolio risk is saturated'),

  INVESTIGATOR_ON_PROBATION_BUDGET_EXCEEDED: () => new ApiError(403, 'ERR_INVESTIGATOR_ON_PROBATION_BUDGET_EXCEEDED', 'Investigator on probation: budget cap exceeded'),
  INVESTIGATOR_ON_PROBATION_DEVIATIONS_BLOCKED: () => new ApiError(403, 'ERR_INVESTIGATOR_ON_PROBATION_DEVIATIONS_BLOCKED', 'Investigator on probation: deviations blocked'),

  NO_APPROVED_IRB: () => new ApiError(409, 'ERR_NO_APPROVED_IRB', 'No approved IRB'),
  INVALID_IRB_STATUS: () => new ApiError(400, 'ERR_INVALID_IRB_STATUS', 'Invalid IRB status'),
  IRB_PROGRAM_MISMATCH: () => new ApiError(400, 'ERR_IRB_PROGRAM_MISMATCH', 'IRB and trial are in different programs'),

  INVALID_PHASE_NAME: () => new ApiError(400, 'ERR_INVALID_PHASE_NAME', 'Invalid phase name'),

  ENROLLMENT_BLACKOUT_ACTIVE: () => new ApiError(403, 'ERR_ENROLLMENT_BLACKOUT_ACTIVE', 'Enrollment blackout is active'),

  INVALID_ADJUSTMENT_VALUE: () => new ApiError(400, 'ERR_INVALID_ADJUSTMENT_VALUE', 'Invalid adjustment value'),
  INSUFFICIENT_JUSTIFICATION: () => new ApiError(400, 'ERR_INSUFFICIENT_JUSTIFICATION', 'Insufficient justification'),

  STALE_PERIOD_INDEX: () => new ApiError(409, 'ERR_STALE_PERIOD_INDEX', 'Stale period index'),

  IDEMPOTENCY_CONFLICT: () => new ApiError(409, 'ERR_IDEMPOTENCY_CONFLICT', 'Idempotency conflict'),

  INVALID_STATE: () => new ApiError(409, 'ERR_INVALID_STATE', 'Invalid state transition')
};
