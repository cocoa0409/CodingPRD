export type Role = 'curator' | 'manager' | 'legal';

export type StudioPosture = 'OPEN' | 'REVIEW' | 'HALT';

export type AssetStatus = 'DRAFT' | 'ACTIVE' | 'QUARANTINED' | 'RETIRED';

export type ClearancePolicy = 'FULL' | 'PROMO';
export type ClearanceStatus = 'PENDING' | 'GRANTED' | 'SUSPENDED' | 'REVOKED';

export type MixKind = 'PUBLIC' | 'INTERNAL' | 'EVIDENCE';
export type MixStatus = 'DRAFT' | 'SUBMITTED' | 'APPROVED' | 'PUBLISHED' | 'FROZEN' | 'ARCHIVED';
export type SlotType = 'NORMAL' | 'SPOTLIGHT';

export type DisputeSeverity = 'LOW' | 'HIGH';
export type DisputeStatus = 'OPEN' | 'ESCALATED' | 'RESOLVED' | 'VOID';
export type DisputeResolution = 'UPHELD' | 'DISMISSED' | 'VOID';
export type DisputeTargetType = 'ASSET' | 'MIX';

export interface Studio {
  id: string;
  name: string;
  cycle_index: number;
  token_budget: number;
  token_reserved: number;
  token_committed: number;
  token_available: number;
  posture: StudioPosture;
  version: number;
}

export interface StudioRow {
  id: string;
  name: string;
  cycle_index: number;
  token_budget: number;
  version: number;
  created_at: string;
}

export interface Asset {
  id: string;
  studio_id: string;
  title: string;
  duration_sec: number;
  status: AssetStatus;
  version: number;
}

export interface AssetRow {
  id: string;
  studio_id: string;
  title: string;
  duration_sec: number;
  status: AssetStatus;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface Clearance {
  id: string;
  studio_id: string;
  asset_id: string;
  policy: ClearancePolicy;
  status: ClearanceStatus;
  last_granted_in_cycle: number | null;
  version: number;
}

export interface ClearanceRow {
  id: string;
  studio_id: string;
  asset_id: string;
  policy: ClearancePolicy;
  status: ClearanceStatus;
  last_granted_in_cycle: number | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface MixEntry {
  asset_id: string;
  slot: SlotType;
}

export interface MixEntryRow {
  id: string;
  mix_id: string;
  asset_id: string;
  slot: SlotType;
  position: number;
  created_at: string;
}

export interface Mix {
  id: string;
  studio_id: string;
  title: string;
  kind: MixKind;
  status: MixStatus;
  entries: MixEntry[];
  token_cost: number;
  approved_in_cycle: number | null;
  published_in_cycle: number | null;
  version: number;
}

export interface MixRow {
  id: string;
  studio_id: string;
  title: string;
  kind: MixKind;
  status: MixStatus;
  token_cost: number;
  approved_in_cycle: number | null;
  published_in_cycle: number | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface Dispute {
  id: string;
  studio_id: string;
  target_type: DisputeTargetType;
  target_id: string;
  severity: DisputeSeverity;
  status: DisputeStatus;
  resolution: DisputeResolution | null;
  version: number;
}

export interface DisputeRow {
  id: string;
  studio_id: string;
  target_type: DisputeTargetType;
  target_id: string;
  severity: DisputeSeverity;
  status: DisputeStatus;
  resolution: DisputeResolution | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface Effect {
  type: 'studio' | 'asset' | 'clearance' | 'mix' | 'dispute';
  id: string;
  status?: string;
  version: number;
  token_cost?: number;
  token_reserved?: number;
  token_committed?: number;
  token_available?: number;
  posture?: StudioPosture;
  cycle_index?: number;
}

export interface ApiError {
  code: string;
  message: string;
}

export interface ApiResponse<T = unknown> {
  data?: T;
  effects?: Effect[];
  error?: ApiError;
}

export const ERROR_CODES = {
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
  CLEARANCE_ALREADY_EXISTS: 'ERR_CLEARANCE_ALREADY_EXISTS',
} as const;
