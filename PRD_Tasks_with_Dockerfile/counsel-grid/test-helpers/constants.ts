export const MATTER_TYPES = ['LITIGATION', 'INVESTIGATION'] as const;
export type MatterType = typeof MATTER_TYPES[number];

export const MATTER_STATUSES = ['DRAFT', 'ACTIVE', 'CLOSED'] as const;
export type MatterStatus = typeof MATTER_STATUSES[number];

export const MATTER_POSTURES = ['OPEN', 'REVIEW', 'FROZEN'] as const;
export type MatterPosture = typeof MATTER_POSTURES[number];

export const WORKSPACE_POSTURES = ['NORMAL', 'REVIEW', 'LOCKDOWN'] as const;
export type WorkspacePosture = typeof WORKSPACE_POSTURES[number];

export const CUSTODIAN_STATUSES = ['ACTIVE', 'DEPARTED', 'PURGED'] as const;
export type CustodianStatus = typeof CUSTODIAN_STATUSES[number];

export const HOLD_STATUSES = ['DRAFT', 'ISSUED', 'ACTIVE', 'SUSPENDED', 'RELEASED', 'VOID'] as const;
export type HoldStatus = typeof HOLD_STATUSES[number];

export const LEGAL_BASES = ['LITIGATION', 'REGULATORY', 'CONTRACT'] as const;
export type LegalBasis = typeof LEGAL_BASES[number];

export const HOLD_SCOPES = ['ALL_DATA', 'EMAIL_ONLY', 'CHAT_ONLY', 'DRIVE_ONLY'] as const;
export type HoldScope = typeof HOLD_SCOPES[number];

export const COLLECTION_STATUSES = ['DRAFT', 'SUBMITTED', 'APPROVED', 'IN_PROGRESS', 'DELIVERED', 'WITHDRAWN', 'REJECTED'] as const;
export type CollectionStatus = typeof COLLECTION_STATUSES[number];

export const DATA_SOURCES = ['EMAIL', 'CHAT', 'DRIVE'] as const;
export type DataSource = typeof DATA_SOURCES[number];

export const ERROR_CODES = {
  BAD_REQUEST: 'ERR_BAD_REQUEST',
  NOT_FOUND: 'ERR_NOT_FOUND',
  MISSING_IDEMPOTENCY_KEY: 'ERR_MISSING_IDEMPOTENCY_KEY',
  MISSING_IF_MATCH: 'ERR_MISSING_IF_MATCH',
  IDEMPOTENCY_REPLAY_MISMATCH: 'ERR_IDEMPOTENCY_REPLAY_MISMATCH',
  ETAG_MISMATCH: 'ERR_ETAG_MISMATCH',
  POSTURE_BLOCKED: 'ERR_POSTURE_BLOCKED',
  INVALID_STATE: 'ERR_INVALID_STATE',
  QUOTA_EXCEEDED: 'ERR_QUOTA_EXCEEDED',
  HOLD_SCOPE_MISMATCH: 'ERR_HOLD_SCOPE_MISMATCH',
  HOLD_NOT_ACTIVE: 'ERR_HOLD_NOT_ACTIVE',
  CUSTODIAN_NOT_IN_HOLD: 'ERR_CUSTODIAN_NOT_IN_HOLD',
  CUSTODIAN_DEPARTED: 'ERR_CUSTODIAN_DEPARTED',
  CUSTODIAN_PURGED: 'ERR_CUSTODIAN_PURGED',
  COURT_ORDERED_RESTRICTION: 'ERR_COURT_ORDERED_RESTRICTION',
  MATTER_HAS_ACTIVE_HOLDS: 'ERR_MATTER_HAS_ACTIVE_HOLDS',
  MATTER_HAS_PENDING_COLLECTIONS: 'ERR_MATTER_HAS_PENDING_COLLECTIONS',
} as const;

export type ErrorCode = typeof ERROR_CODES[keyof typeof ERROR_CODES];

export const RESPONSE_TYPES = ['object', 'array', 'error'] as const;
export type ResponseType = typeof RESPONSE_TYPES[number];

export const REVIEW_THRESHOLD_PERCENT = 0.10;

export const CONSTANTS = {
  auth: {
    ROLES: [] as readonly string[]
  }
} as const;

export type Role = typeof CONSTANTS.auth.ROLES[number] | string;
export const DEFAULT_ROLE: Role = 'Admin';
