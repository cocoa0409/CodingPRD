export const POSTURES = {
  OPEN: 'OPEN',
  CONGESTED: 'CONGESTED',
  LOCKDOWN: 'LOCKDOWN',
} as const;
export type Posture = typeof POSTURES[keyof typeof POSTURES];

export const CONSIGNMENT_STATUSES = {
  PLANNED: 'PLANNED',
  AT_HUB: 'AT_HUB',
  RELEASED: 'RELEASED',
  CLOSED: 'CLOSED',
  VOIDED: 'VOIDED',
} as const;
export type ConsignmentStatus = typeof CONSIGNMENT_STATUSES[keyof typeof CONSIGNMENT_STATUSES];

export const DOCK_REQUEST_STATUSES = {
  DRAFT: 'DRAFT',
  SUBMITTED: 'SUBMITTED',
  SCHEDULED: 'SCHEDULED',
  ON_HOLD: 'ON_HOLD',
  DONE: 'DONE',
  CANCELLED: 'CANCELLED',
  EXPIRED: 'EXPIRED',
  VOIDED: 'VOIDED',
} as const;
export type DockRequestStatus = typeof DOCK_REQUEST_STATUSES[keyof typeof DOCK_REQUEST_STATUSES];

export const DIRECTIONS = {
  INBOUND: 'INBOUND',
  OUTBOUND: 'OUTBOUND',
} as const;
export type Direction = typeof DIRECTIONS[keyof typeof DIRECTIONS];

export const PRIORITIES = {
  EXPEDITE: 'EXPEDITE',
  STANDARD: 'STANDARD',
  DEFERRED: 'DEFERRED',
} as const;
export type Priority = typeof PRIORITIES[keyof typeof PRIORITIES];

export const COMMODITIES = {
  GENERAL: 'GENERAL',
  COLD_CHAIN: 'COLD_CHAIN',
  HAZMAT: 'HAZMAT',
} as const;
export type Commodity = typeof COMMODITIES[keyof typeof COMMODITIES];

export const HOLD_KINDS = {
  DOCS: 'DOCS',
  DAMAGE: 'DAMAGE',
  TEMPERATURE: 'TEMPERATURE',
  CUSTOMS: 'CUSTOMS',
} as const;
export type HoldKind = typeof HOLD_KINDS[keyof typeof HOLD_KINDS];

export const HOLD_STATUSES = {
  OPEN: 'OPEN',
  CLEARED: 'CLEARED',
  VOIDED: 'VOIDED',
} as const;
export type HoldStatus = typeof HOLD_STATUSES[keyof typeof HOLD_STATUSES];

export const HOLD_SOURCES = {
  MANUAL: 'MANUAL',
  AUTO_VARIANCE: 'AUTO_VARIANCE',
} as const;
export type HoldSource = typeof HOLD_SOURCES[keyof typeof HOLD_SOURCES];

export const ERROR_CODES = {
  ERR_BAD_REQUEST: 'ERR_BAD_REQUEST',
  ERR_NOT_FOUND: 'ERR_NOT_FOUND',
  ERR_MISSING_IF_MATCH: 'ERR_MISSING_IF_MATCH',
  ERR_VERSION_CONFLICT: 'ERR_VERSION_CONFLICT',
  ERR_INVALID_STATE: 'ERR_INVALID_STATE',
  ERR_POSTURE_LOCKDOWN: 'ERR_POSTURE_LOCKDOWN',
  ERR_CONGESTED_INBOUND_LIMIT: 'ERR_CONGESTED_INBOUND_LIMIT',
  ERR_CAPACITY_EXCEEDED: 'ERR_CAPACITY_EXCEEDED',
  ERR_CONSIGNMENT_HAS_OPEN_HOLD: 'ERR_CONSIGNMENT_HAS_OPEN_HOLD',
  ERR_CONSIGNMENT_EMPTY: 'ERR_CONSIGNMENT_EMPTY',
  ERR_CONSIGNMENT_BUSY: 'ERR_CONSIGNMENT_BUSY',
  ERR_CONSTRAINT_VIOLATION: 'ERR_CONSTRAINT_VIOLATION',
} as const;
export type ErrorCode = typeof ERROR_CODES[keyof typeof ERROR_CODES];

export const THRESHOLDS = {

  CONGESTED_THRESHOLD_PERCENT: 0.20,

  CONGESTED_INBOUND_CAP_DIVISOR: 4,
  CONGESTED_INBOUND_MIN: 1,

  VARIANCE_HOLD_THRESHOLD: 3,

  STALE_OPS_RUNS: 2,
} as const;

export const CONSTANTS = {
  auth: {
    ROLES: [] as readonly string[]
  }
} as const;

export type Role = typeof CONSTANTS.auth.ROLES[number] | string;
export const DEFAULT_ROLE: Role = 'Admin';
