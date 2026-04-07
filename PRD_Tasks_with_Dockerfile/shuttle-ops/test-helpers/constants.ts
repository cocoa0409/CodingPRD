export const RIDE_STATUS = {
  DRAFT: 'DRAFT',
  REQUESTED: 'REQUESTED',
  DISPATCHED: 'DISPATCHED',
  IN_PROGRESS: 'IN_PROGRESS',
  COMPLETED: 'COMPLETED',
  CANCELLED: 'CANCELLED',
  VOIDED: 'VOIDED',
  WAITLISTED: 'WAITLISTED',
  ON_HOLD: 'ON_HOLD',
} as const;

export type RideStatus = typeof RIDE_STATUS[keyof typeof RIDE_STATUS];

export const HOLD_REASON = {
  HUB_SAFETY_HOLD: 'HUB_SAFETY_HOLD',
  PASS_SUSPENDED: 'PASS_SUSPENDED',
  PASS_TRANSFERRED: 'PASS_TRANSFERRED',
} as const;

export type HoldReason = typeof HOLD_REASON[keyof typeof HOLD_REASON];

export const HUB_POSTURE = {
  NORMAL: 'NORMAL',
  SAFETY_HOLD: 'SAFETY_HOLD',
} as const;

export type HubPosture = typeof HUB_POSTURE[keyof typeof HUB_POSTURE];

export const PAYMENT_MODE = {
  WALLET_ONLY: 'WALLET_ONLY',
  PASS_ONLY: 'PASS_ONLY',
  PASS_THEN_WALLET: 'PASS_THEN_WALLET',
} as const;

export type PaymentMode = typeof PAYMENT_MODE[keyof typeof PAYMENT_MODE];

export const RIDE_EVENT_TYPE = {
  SUBMIT: 'SUBMIT',
  DISPATCH: 'DISPATCH',
  START: 'START',
  COMPLETE: 'COMPLETE',
  CANCEL: 'CANCEL',
  ADJUST: 'ADJUST',
  VOID_ADJUSTMENT: 'VOID_ADJUSTMENT',
  VOID: 'VOID',
} as const;

export type RideEventType = typeof RIDE_EVENT_TYPE[keyof typeof RIDE_EVENT_TYPE];

export const ENTITY_STATUS = {
  ACTIVE: 'ACTIVE',
  SUSPENDED: 'SUSPENDED',
} as const;

export type EntityStatus = typeof ENTITY_STATUS[keyof typeof ENTITY_STATUS];

export const DRIVER_EVENT_TYPE = {
  SUSPEND: 'SUSPEND',
  REINSTATE: 'REINSTATE',
} as const;

export type DriverEventType = typeof DRIVER_EVENT_TYPE[keyof typeof DRIVER_EVENT_TYPE];

export const PASS_EVENT_TYPE = {
  TOP_UP: 'TOP_UP',
  SUSPEND: 'SUSPEND',
  REINSTATE: 'REINSTATE',
  TRANSFER: 'TRANSFER',
} as const;

export type PassEventType = typeof PASS_EVENT_TYPE[keyof typeof PASS_EVENT_TYPE];

export const ADJUSTMENT_DIRECTION = {
  CREDIT: 'CREDIT',
  DEBIT: 'DEBIT',
} as const;

export type AdjustmentDirection = typeof ADJUSTMENT_DIRECTION[keyof typeof ADJUSTMENT_DIRECTION];

export const ADJUSTMENT_STATUS = {
  ACTIVE: 'ACTIVE',
  VOIDED: 'VOIDED',
} as const;

export type AdjustmentStatus = typeof ADJUSTMENT_STATUS[keyof typeof ADJUSTMENT_STATUS];

export const CANCEL_BY = {
  RIDER: 'RIDER',
  DRIVER: 'DRIVER',
  OPS: 'OPS',
} as const;

export type CancelBy = typeof CANCEL_BY[keyof typeof CANCEL_BY];

export const CANCEL_REASON = {
  RIDER_CHANGED_MIND: 'RIDER_CHANGED_MIND',
  OPS_STALE: 'OPS_STALE',
  OPS_UNRESOLVED: 'OPS_UNRESOLVED',
} as const;

export type CancelReason = typeof CANCEL_REASON[keyof typeof CANCEL_REASON];

export const ERROR_CODE = {
  ERR_BAD_REQUEST: 'ERR_BAD_REQUEST',
  ERR_NOT_FOUND: 'ERR_NOT_FOUND',
  ERR_MISSING_IF_MATCH: 'ERR_MISSING_IF_MATCH',
  ERR_VERSION_CONFLICT: 'ERR_VERSION_CONFLICT',
  ERR_HUB_POSTURE_RESTRICTED: 'ERR_HUB_POSTURE_RESTRICTED',
  ERR_INVALID_STATE: 'ERR_INVALID_STATE',
  ERR_CONSTRAINT_VIOLATION: 'ERR_CONSTRAINT_VIOLATION',
  ERR_PASS_SUSPENDED: 'ERR_PASS_SUSPENDED',
  ERR_PASS_NOT_OWNED: 'ERR_PASS_NOT_OWNED',
  ERR_WALLET_INSUFFICIENT_FUNDS: 'ERR_WALLET_INSUFFICIENT_FUNDS',
  ERR_DRIVER_SUSPENDED: 'ERR_DRIVER_SUSPENDED',
  ERR_DRIVER_CAPACITY_EXCEEDED: 'ERR_DRIVER_CAPACITY_EXCEEDED',
  ERR_DEPENDENCY_EXISTS: 'ERR_DEPENDENCY_EXISTS',
  ERR_DUPLICATE_ACTIVE_RIDE: 'ERR_DUPLICATE_ACTIVE_RIDE',
} as const;

export type ErrorCode = typeof ERROR_CODE[keyof typeof ERROR_CODE];

export const PRICING = {
  POOL_SEAT_PRICE_CENTS: 800,
} as const;

export const RIDE_KIND = {
  POOL: 'POOL',
} as const;

export type RideKind = typeof RIDE_KIND[keyof typeof RIDE_KIND];

export const CONSTANTS = {
  auth: {
    ROLES: [] as readonly string[]
  }
} as const;

export type Role = string;
export const DEFAULT_ROLE: Role = 'Admin';
