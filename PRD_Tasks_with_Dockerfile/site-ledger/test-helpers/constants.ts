export const ROLES = ['FOREMAN', 'INSPECTOR', 'MANAGER'] as const;
export type Role = typeof ROLES[number];
export const DEFAULT_ROLE: Role = 'MANAGER';

export const WORK_ITEM_STATUSES = ['DRAFT', 'READY', 'IN_PROGRESS', 'DONE', 'CANCELLED'] as const;
export type WorkItemStatus = typeof WORK_ITEM_STATUSES[number];

export const TRADES = ['ELECTRICAL', 'PLUMBING', 'STRUCTURAL', 'GENERAL'] as const;
export type Trade = typeof TRADES[number];

export const ZONES = ['ZONE_A', 'ZONE_B', 'ZONE_C'] as const;
export type Zone = typeof ZONES[number];

export const CRITICALITIES = ['STANDARD', 'CRITICAL'] as const;
export type Criticality = typeof CRITICALITIES[number];

export const POSTURES = ['OPEN', 'REVIEW', 'STOP_WORK'] as const;
export type Posture = typeof POSTURES[number];

export const PERMIT_STATUSES = ['REQUESTED', 'GRANTED', 'REVOKED'] as const;
export type PermitStatus = typeof PERMIT_STATUSES[number];

export const PERMIT_DECISIONS = ['GRANT', 'REVOKE'] as const;
export type PermitDecision = typeof PERMIT_DECISIONS[number];

export const INSPECTION_KINDS = ['SAFETY', 'QUALITY'] as const;
export type InspectionKind = typeof INSPECTION_KINDS[number];

export const INSPECTION_STATUSES = ['PLANNED', 'PASSED', 'FAILED', 'VOIDED'] as const;
export type InspectionStatus = typeof INSPECTION_STATUSES[number];

export const INSPECTION_OUTCOMES = ['PASSED', 'FAILED'] as const;
export type InspectionOutcome = typeof INSPECTION_OUTCOMES[number];

export const CHANGE_ORDER_STATUSES = ['PROPOSED', 'APPROVED', 'APPLIED', 'CANCELLED'] as const;
export type ChangeOrderStatus = typeof CHANGE_ORDER_STATUSES[number];

export const START_BLOCKERS = ['POSTURE', 'PERMIT', 'ZONE', 'CHANGE_ORDER', 'SAFETY'] as const;
export type StartBlocker = typeof START_BLOCKERS[number];

export const ERROR_CODES = {
  BAD_REQUEST: 'ERR_BAD_REQUEST',
  UNAUTHENTICATED: 'ERR_UNAUTHENTICATED',
  FORBIDDEN: 'ERR_FORBIDDEN',
  NOT_FOUND: 'ERR_NOT_FOUND',
  MISSING_IDEMPOTENCY_KEY: 'ERR_MISSING_IDEMPOTENCY_KEY',
  IDEMPOTENCY_REPLAY_MISMATCH: 'ERR_IDEMPOTENCY_REPLAY_MISMATCH',
  MISSING_IF_MATCH: 'ERR_MISSING_IF_MATCH',
  ETAG_MISMATCH: 'ERR_ETAG_MISMATCH',
  POSTURE_BLOCKED: 'ERR_POSTURE_BLOCKED',
  INVALID_STATE: 'ERR_INVALID_STATE',
  LABOR_BUDGET_EXCEEDED: 'ERR_LABOR_BUDGET_EXCEEDED',
  PERMIT_ALREADY_EXISTS: 'ERR_PERMIT_ALREADY_EXISTS',
  PERMIT_REPLACEMENT_REQUIRED: 'ERR_PERMIT_REPLACEMENT_REQUIRED',
  PERMIT_REQUIRED: 'ERR_PERMIT_REQUIRED',
  ZONE_OCCUPIED: 'ERR_ZONE_OCCUPIED',
  INSPECTION_ALREADY_PLANNED: 'ERR_INSPECTION_ALREADY_PLANNED',
  WORK_ITEM_FROZEN: 'ERR_WORK_ITEM_FROZEN',
  QUALITY_FAILED_BLOCKING: 'ERR_QUALITY_FAILED_BLOCKING',
  CHANGE_ORDER_CONFLICT: 'ERR_CHANGE_ORDER_CONFLICT',
  CHANGE_ORDER_NOT_APPROVED: 'ERR_CHANGE_ORDER_NOT_APPROVED',
  SCOPE_CHANGE_NOT_ALLOWED: 'ERR_SCOPE_CHANGE_NOT_ALLOWED',
} as const;

export const RESPONSE_TYPES = ['object', 'error'] as const;
export type ResponseType = typeof RESPONSE_TYPES[number];

export const HEADERS = {
  ACTOR_ROLE: 'X-Actor-Role',
  IDEMPOTENCY_KEY: 'Idempotency-Key',
  IF_MATCH: 'If-Match',
} as const;

export const THRESHOLDS = {

  LABOR_REVIEW_THRESHOLD_HOURS: 20,

  QUALITY_FAILURE_REVIEW_THRESHOLD: 2,
} as const;
