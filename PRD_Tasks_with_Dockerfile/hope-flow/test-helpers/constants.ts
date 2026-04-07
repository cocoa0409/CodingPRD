export const POSTURES = ['OPEN', 'RESTRICTED', 'FROZEN'] as const;
export type Posture = typeof POSTURES[number];

export const PHASES = ['ACTIVE', 'CLOSED'] as const;
export type Phase = typeof PHASES[number];

export const PLEDGE_STATUSES = ['OUTSTANDING', 'FULFILLED', 'LAPSED', 'VOIDED'] as const;
export type PledgeStatus = typeof PLEDGE_STATUSES[number];

export const CONTRIBUTION_STATUSES = ['CLEARED', 'REFUNDED'] as const;
export type ContributionStatus = typeof CONTRIBUTION_STATUSES[number];

export const GRANT_STATUSES = ['ACTIVE', 'SUSPENDED', 'REVOKED', 'EXHAUSTED'] as const;
export type GrantStatus = typeof GRANT_STATUSES[number];

export const CAUSE_STATUSES = ['OPEN', 'THRESHOLD_MET', 'FUNDED', 'CLOSED'] as const;
export type CauseStatus = typeof CAUSE_STATUSES[number];

export const DISBURSEMENT_STATUSES = ['PENDING', 'APPROVED', 'COMPLETED', 'VOIDED'] as const;
export type DisbursementStatus = typeof DISBURSEMENT_STATUSES[number];

export const HOLD_STATUSES = ['ACTIVE', 'RESOLVED'] as const;
export type HoldStatus = typeof HOLD_STATUSES[number];

export const HOLD_SEVERITIES = ['STANDARD', 'CRITICAL'] as const;
export type HoldSeverity = typeof HOLD_SEVERITIES[number];

export const PROCESSING_FEE_PERCENT = 3;

export const ERROR_CODES = {
  INVALID_REQUEST: 'ERR_INVALID_REQUEST',
  NOT_FOUND: 'ERR_NOT_FOUND',
  CAMPAIGN_CLOSED: 'ERR_CAMPAIGN_CLOSED',
  POSTURE_FROZEN: 'ERR_POSTURE_FROZEN',
  POSTURE_RESTRICTED: 'ERR_POSTURE_RESTRICTED',
  INVALID_STATE: 'ERR_INVALID_STATE',
  PLEDGE_MISMATCH: 'ERR_PLEDGE_MISMATCH',
  INSUFFICIENT_FUNDS: 'ERR_INSUFFICIENT_FUNDS',
  ALLOCATION_EXCEEDED: 'ERR_ALLOCATION_EXCEEDED',
  CAUSE_FULL: 'ERR_CAUSE_FULL',
  DISBURSEMENT_BLOCKED: 'ERR_DISBURSEMENT_BLOCKED',
  PLEDGES_OUTSTANDING: 'ERR_PLEDGES_OUTSTANDING',
  PRIORITY_CONFLICT: 'ERR_PRIORITY_CONFLICT',
} as const;

export const CONSTANTS = {
  auth: {
    ROLES: [] as readonly string[]
  }
} as const;

export type Role = typeof CONSTANTS.auth.ROLES[number] | string;
export const DEFAULT_ROLE: Role = CONSTANTS.auth.ROLES[0] ?? 'Admin';
