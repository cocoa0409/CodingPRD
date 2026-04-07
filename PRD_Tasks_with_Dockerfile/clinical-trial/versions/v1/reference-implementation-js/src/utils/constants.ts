export const ROLES = {
  RESEARCH_DIRECTOR: 'ResearchDirector',
  CLINICAL_COORDINATOR: 'ClinicalCoordinator',
  ETHICS_AUDITOR: 'EthicsAuditor'
} as const;

export type UserRole = typeof ROLES[keyof typeof ROLES];

export const ALL_ROLES = Object.values(ROLES);

export const MAX_ACTIVE_DEVIATIONS_PER_USER = 3;

export const IDEMPOTENCY_REQUIRED_FOR = [
  'POST /research-programs/:programId/clinical-trials/:trialId/procedure-executions'
];

export const EXPEDITED_THRESHOLD_POINTS = 200;
export const EXPEDITED_MULTIPLIER = 1.5;

export const SAFETY_LOCK_THRESHOLD = 200;
export const AUDIT_LOCK_THRESHOLD = 100;
export const DEVIATION_REJECTION_PENALTY = 5;
export const CANCEL_TIER0_PENALTY = 10;
export const CANCEL_TIER1_PENALTY = 20;
export const CANCEL_TIER2PLUS_PENALTY = 40;

export const PENALTY_ETHICAL_LOCK = 25;
export const PENALTY_ABANDONED_TRIAL = 10;
export const PENALTY_DEPENDENCY_RIPPLE = 5;

export const CONTAGION_PENALTY = 10;
export const SATURATION_PERCENT_THRESHOLD = 90;

export const PROBATION_THRESHOLD_SCORE = 40;
export const PROBATION_TRIAL_BUDGET_CAP = 500;

export const MIN_PERIOD_INDEX = 0;
export const MAX_ADVANCE_BY = 10000;

export const WILDCARDS = ['*', '?'];

export const INITIAL_REPUTATION_SCORE = 100;
export const MIN_REPUTATION_SCORE = 0;
export const MAX_REPUTATION_SCORE = 100;

export const REVIEW_REQUIRED_TIER_THRESHOLD = 3;

export const HIGH_RISK_COMPLETION_THRESHOLD = 75;
