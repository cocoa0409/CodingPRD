export const EVENT_POSTURES = ['DRAFT', 'OPEN', 'LOCKDOWN', 'ARCHIVED'] as const;
export type EventPosture = typeof EVENT_POSTURES[number];

export const PACKAGE_STATUSES = ['ACTIVE', 'RETIRED'] as const;
export type PackageStatus = typeof PACKAGE_STATUSES[number];

export const SPONSOR_STATUSES = ['PROSPECT', 'VETTED', 'WATCHLIST', 'BLOCKED'] as const;
export type SponsorStatus = typeof SPONSOR_STATUSES[number];

export const APPLICATION_STATUSES = ['DRAFT', 'SUBMITTED', 'APPROVED', 'REJECTED', 'WITHDRAWN', 'EXPIRED'] as const;
export type ApplicationStatus = typeof APPLICATION_STATUSES[number];

export const HOLD_STATUSES = ['HELD', 'WAITLISTED'] as const;
export type HoldStatus = typeof HOLD_STATUSES[number];

export const COMMITMENT_STATUSES = ['PENDING_COUNTERSIGN', 'ACTIVE', 'SUSPENDED', 'RESCINDED'] as const;
export type CommitmentStatus = typeof COMMITMENT_STATUSES[number];

export const CLAIM_STATUSES = ['PROPOSED', 'FINALIZED', 'VOIDED'] as const;
export type ClaimStatus = typeof CLAIM_STATUSES[number];

export const BENEFIT_KINDS = ['LEAD_SCANS', 'STAGE_MINUTES', 'SPOTLIGHT'] as const;
export type BenefitKind = typeof BENEFIT_KINDS[number];

export const APPLICATION_ACTIONS = ['SUBMIT', 'APPROVE', 'REJECT', 'WITHDRAW'] as const;
export type ApplicationAction = typeof APPLICATION_ACTIONS[number];

export const PACKAGE_ACTIONS = ['RETIRE', 'REACTIVATE'] as const;
export type PackageAction = typeof PACKAGE_ACTIONS[number];

export const COMMITMENT_ACTIONS = ['COUNTERSIGN', 'RESCIND'] as const;
export type CommitmentAction = typeof COMMITMENT_ACTIONS[number];

export const CLAIM_ACTIONS = ['FINALIZE', 'VOID'] as const;
export type ClaimAction = typeof CLAIM_ACTIONS[number];

export const ERROR_CODES = {
  BAD_REQUEST: 'ERR_BAD_REQUEST',
  NOT_FOUND: 'ERR_NOT_FOUND',
  PRECONDITION_REQUIRED: 'ERR_PRECONDITION_REQUIRED',
  VERSION_CONFLICT: 'ERR_VERSION_CONFLICT',
  EVENT_NOT_OPEN: 'ERR_EVENT_NOT_OPEN',
  EVENT_LOCKDOWN: 'ERR_EVENT_LOCKDOWN',
  INVALID_STATE: 'ERR_INVALID_STATE',
  PACKAGE_RETIRED: 'ERR_PACKAGE_RETIRED',
  DUPLICATE_APPLICATION: 'ERR_DUPLICATE_APPLICATION',
  DUPLICATE_COMMITMENT: 'ERR_DUPLICATE_COMMITMENT',
  NO_ACTIVE_HOLD: 'ERR_NO_ACTIVE_HOLD',
  SPONSOR_BLOCKED: 'ERR_SPONSOR_BLOCKED',
  COMMITMENT_NOT_ACTIVE: 'ERR_COMMITMENT_NOT_ACTIVE',
  BENEFIT_NOT_INCLUDED: 'ERR_BENEFIT_NOT_INCLUDED',
  INSUFFICIENT_BENEFIT: 'ERR_INSUFFICIENT_BENEFIT',
  DUPLICATE_CLAIM: 'ERR_DUPLICATE_CLAIM',
  SPOTLIGHT_FULL: 'ERR_SPOTLIGHT_FULL',
  SPOTLIGHT_IN_USE: 'ERR_SPOTLIGHT_IN_USE',
  HAS_FINALIZED_CLAIMS: 'ERR_HAS_FINALIZED_CLAIMS',
} as const;

export type ErrorCode = typeof ERROR_CODES[keyof typeof ERROR_CODES];

export const CONSTANTS = {
  auth: {
    ROLES: ['Admin'] as readonly string[]
  }
} as const;

export type Role = typeof CONSTANTS.auth.ROLES[number] | string;

export const DEFAULT_ROLE: Role = CONSTANTS.auth.ROLES[0] ?? 'Admin';

export const HOLD_DURATION_OPS = 2;

export const ACTIVATION_DEADLINE_OPS = 3;
