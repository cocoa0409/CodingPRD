export const POSTURE = {
  NORMAL: 'NORMAL',
  RESTRICTED: 'RESTRICTED',
} as const;

export type Posture = typeof POSTURE[keyof typeof POSTURE];

export const EPISODE_STATUS = {
  DRAFT: 'DRAFT',
  SUBMITTED: 'SUBMITTED',
  LIVE: 'LIVE',
  RETRACTED: 'RETRACTED',
} as const;

export type EpisodeStatus = typeof EPISODE_STATUS[keyof typeof EPISODE_STATUS];

export const CLEARANCE = {
  CLEAR: 'CLEAR',
  UNDER_REVIEW: 'UNDER_REVIEW',
} as const;

export type Clearance = typeof CLEARANCE[keyof typeof CLEARANCE];

export const CONTENT_RATING = {
  GENERAL: 'GENERAL',
  MATURE: 'MATURE',
} as const;

export type ContentRating = typeof CONTENT_RATING[keyof typeof CONTENT_RATING];

export const DEAL_STATUS = {
  DRAFT: 'DRAFT',
  ACTIVE: 'ACTIVE',
  PAUSED: 'PAUSED',
  CLOSED: 'CLOSED',
} as const;

export type DealStatus = typeof DEAL_STATUS[keyof typeof DEAL_STATUS];

export const BRAND_TIER = {
  FAMILY_SAFE: 'FAMILY_SAFE',
  STANDARD: 'STANDARD',
} as const;

export type BrandTier = typeof BRAND_TIER[keyof typeof BRAND_TIER];

export const RESERVATION_STATUS = {
  HOLD: 'HOLD',
  APPROVED: 'APPROVED',
  NEEDS_REVIEW: 'NEEDS_REVIEW',
  OVERBOOKED: 'OVERBOOKED',
  SETTLED: 'SETTLED',
  CREDITED: 'CREDITED',
  CANCELED: 'CANCELED',
  EXPIRED: 'EXPIRED',
} as const;

export type ReservationStatus = typeof RESERVATION_STATUS[keyof typeof RESERVATION_STATUS];

export const PLACEMENT = {
  PRE_ROLL: 'PRE_ROLL',
  MID_ROLL: 'MID_ROLL',
  POST_ROLL: 'POST_ROLL',
} as const;

export type Placement = typeof PLACEMENT[keyof typeof PLACEMENT];

export const TERMINAL_RESERVATION_STATUSES: ReservationStatus[] = [
  RESERVATION_STATUS.SETTLED,
  RESERVATION_STATUS.CREDITED,
  RESERVATION_STATUS.CANCELED,
  RESERVATION_STATUS.EXPIRED,
];

export const CLAIM_KIND = {
  RIGHTS: 'RIGHTS',
  BRAND_SAFETY: 'BRAND_SAFETY',
} as const;

export type ClaimKind = typeof CLAIM_KIND[keyof typeof CLAIM_KIND];

export const CLAIM_OUTCOME = {
  ACCEPTED: 'ACCEPTED',
  REJECTED: 'REJECTED',
  WITHDRAWN: 'WITHDRAWN',
} as const;

export type ClaimOutcome = typeof CLAIM_OUTCOME[keyof typeof CLAIM_OUTCOME];

export const ERROR_CODES = {
  ERR_BAD_REQUEST: 'ERR_BAD_REQUEST',
  ERR_NOT_FOUND: 'ERR_NOT_FOUND',
  ERR_MISSING_IF_MATCH: 'ERR_MISSING_IF_MATCH',
  ERR_VERSION_CONFLICT: 'ERR_VERSION_CONFLICT',
  ERR_PODCAST_RESTRICTED: 'ERR_PODCAST_RESTRICTED',
  ERR_INVALID_STATE: 'ERR_INVALID_STATE',
  ERR_CAPACITY_EXCEEDED: 'ERR_CAPACITY_EXCEEDED',
  ERR_DEAL_BUDGET_EXCEEDED: 'ERR_DEAL_BUDGET_EXCEEDED',
  ERR_DEAL_NOT_ACTIVE: 'ERR_DEAL_NOT_ACTIVE',
  ERR_EPISODE_UNDER_REVIEW: 'ERR_EPISODE_UNDER_REVIEW',
  ERR_BRAND_SAFETY_MISMATCH: 'ERR_BRAND_SAFETY_MISMATCH',
  ERR_DUPLICATE_RESERVATION: 'ERR_DUPLICATE_RESERVATION',
  ERR_DUPLICATE_CLAIM: 'ERR_DUPLICATE_CLAIM',
  ERR_EPISODE_HAS_HOLDS: 'ERR_EPISODE_HAS_HOLDS',
  ERR_EPISODE_HAS_UNREVIEWED_RESERVATIONS: 'ERR_EPISODE_HAS_UNREVIEWED_RESERVATIONS',
  ERR_EPISODE_HAS_OVERBOOKED_RESERVATIONS: 'ERR_EPISODE_HAS_OVERBOOKED_RESERVATIONS',
} as const;

export type ErrorCode = typeof ERROR_CODES[keyof typeof ERROR_CODES];

export const CAPACITY_SCOPE = {
  PODCAST: 'PODCAST',
  EPISODE: 'EPISODE',
} as const;

export type CapacityScope = typeof CAPACITY_SCOPE[keyof typeof CAPACITY_SCOPE];

export const RESPONSE_TYPE = {
  OBJECT: 'object',
  ARRAY: 'array',
  ERROR: 'error',
} as const;

export type ResponseType = typeof RESPONSE_TYPE[keyof typeof RESPONSE_TYPE];

export const DEFAULT_AD_CAPACITY_SECONDS = 180;

export const DEFAULT_AD_SLOTS_TOTAL_SECONDS = 60;

export const DEFAULT_BUDGET_TOTAL_CENTS = 5000;
export const DEFAULT_SLOT_PRICE_CENTS = 1000;

export const RESTRICTED_CLAIM_THRESHOLD = 2;

export const HOLD_EXPIRY_OPS_RUNS = 2;

export const CONSTANTS = {
  auth: {
    ROLES: [] as readonly string[]
  }
} as const;

export type Role = typeof CONSTANTS.auth.ROLES[number] | string;

export const DEFAULT_ROLE: Role = 'Admin';
