export const CONSTANTS = {
  auth: {
    ROLES: ['curator', 'manager', 'legal'] as const
  },

  posture: {
    OPEN: 'OPEN',
    REVIEW: 'REVIEW',
    HALT: 'HALT'
  },

  assetStatus: {
    DRAFT: 'DRAFT',
    ACTIVE: 'ACTIVE',
    QUARANTINED: 'QUARANTINED',
    RETIRED: 'RETIRED'
  },

  clearanceStatus: {
    PENDING: 'PENDING',
    GRANTED: 'GRANTED',
    SUSPENDED: 'SUSPENDED',
    REVOKED: 'REVOKED'
  },

  clearancePolicy: {
    FULL: 'FULL',
    PROMO: 'PROMO'
  },

  mixKind: {
    PUBLIC: 'PUBLIC',
    INTERNAL: 'INTERNAL',
    EVIDENCE: 'EVIDENCE'
  },

  mixStatus: {
    DRAFT: 'DRAFT',
    SUBMITTED: 'SUBMITTED',
    APPROVED: 'APPROVED',
    PUBLISHED: 'PUBLISHED',
    FROZEN: 'FROZEN',
    ARCHIVED: 'ARCHIVED'
  },

  slot: {
    NORMAL: 'NORMAL',
    SPOTLIGHT: 'SPOTLIGHT'
  },

  disputeSeverity: {
    LOW: 'LOW',
    HIGH: 'HIGH'
  },

  disputeStatus: {
    OPEN: 'OPEN',
    ESCALATED: 'ESCALATED',
    RESOLVED: 'RESOLVED',
    VOID: 'VOID'
  },

  disputeResolution: {
    UPHELD: 'UPHELD',
    DISMISSED: 'DISMISSED'
  },

  disputeTargetType: {
    ASSET: 'ASSET',
    MIX: 'MIX'
  },

  duration: {
    MIN: 1,
    MAX: 3600
  },

  entryLimits: {
    GENERAL_MIN: 1,
    GENERAL_MAX: 25,
    EVIDENCE_MIN: 1,
    EVIDENCE_MAX: 10
  },

  spotlightCaps: {
    PUBLIC: 3,
    INTERNAL: 5,
    REVIEW_MAX: 1
  },

  tokenBuckets: {
    BUCKET_1_MAX: 120,
    BUCKET_2_MAX: 240,
    BUCKET_3_MAX: 420,

  },

  errors: {
    BAD_REQUEST: 'ERR_BAD_REQUEST',
    NOT_FOUND: 'ERR_NOT_FOUND',
    MISSING_IDEMPOTENCY_KEY: 'ERR_MISSING_IDEMPOTENCY_KEY',
    MISSING_IF_MATCH: 'ERR_MISSING_IF_MATCH',
    IDEMPOTENCY_REPLAY_MISMATCH: 'ERR_IDEMPOTENCY_REPLAY_MISMATCH',
    VERSION_CONFLICT: 'ERR_VERSION_CONFLICT',
    ROLE_FORBIDDEN: 'ERR_ROLE_FORBIDDEN',
    POSTURE_BLOCKED: 'ERR_POSTURE_BLOCKED',
    INVALID_STATE: 'ERR_INVALID_STATE',
    CYCLE_STALE: 'ERR_CYCLE_STALE',
    TOKEN_BUDGET_EXCEEDED: 'ERR_TOKEN_BUDGET_EXCEEDED',
    ENTRY_LIMIT: 'ERR_ENTRY_LIMIT',
    ENTRY_DUPLICATE_PUBLIC: 'ERR_ENTRY_DUPLICATE_PUBLIC',
    ENTRY_ADJACENT_DUPLICATE: 'ERR_ENTRY_ADJACENT_DUPLICATE',
    SPOTLIGHT_NOT_ALLOWED: 'ERR_SPOTLIGHT_NOT_ALLOWED',
    SPOTLIGHT_CAP_EXCEEDED: 'ERR_SPOTLIGHT_CAP_EXCEEDED',
    ASSET_NOT_ACTIVE: 'ERR_ASSET_NOT_ACTIVE',
    ASSET_QUARANTINED: 'ERR_ASSET_QUARANTINED',
    CLEARANCE_REQUIRED: 'ERR_CLEARANCE_REQUIRED',
    CLEARANCE_SUSPENDED: 'ERR_CLEARANCE_SUSPENDED',
    CLEARANCE_POLICY_MISMATCH: 'ERR_CLEARANCE_POLICY_MISMATCH',
    DISPUTE_BLOCKING: 'ERR_DISPUTE_BLOCKING',
    CLEARANCE_ALREADY_EXISTS: 'ERR_CLEARANCE_ALREADY_EXISTS'
  }
} as const;

export type Role = typeof CONSTANTS.auth.ROLES[number];
export type Posture = typeof CONSTANTS.posture[keyof typeof CONSTANTS.posture];
export type AssetStatus = typeof CONSTANTS.assetStatus[keyof typeof CONSTANTS.assetStatus];
export type ClearanceStatus = typeof CONSTANTS.clearanceStatus[keyof typeof CONSTANTS.clearanceStatus];
export type ClearancePolicy = typeof CONSTANTS.clearancePolicy[keyof typeof CONSTANTS.clearancePolicy];
export type MixKind = typeof CONSTANTS.mixKind[keyof typeof CONSTANTS.mixKind];
export type MixStatus = typeof CONSTANTS.mixStatus[keyof typeof CONSTANTS.mixStatus];
export type Slot = typeof CONSTANTS.slot[keyof typeof CONSTANTS.slot];
export type DisputeSeverity = typeof CONSTANTS.disputeSeverity[keyof typeof CONSTANTS.disputeSeverity];
export type DisputeStatus = typeof CONSTANTS.disputeStatus[keyof typeof CONSTANTS.disputeStatus];
export type DisputeResolution = typeof CONSTANTS.disputeResolution[keyof typeof CONSTANTS.disputeResolution];
export type DisputeTargetType = typeof CONSTANTS.disputeTargetType[keyof typeof CONSTANTS.disputeTargetType];

export const DEFAULT_ROLE: Role = 'curator';
