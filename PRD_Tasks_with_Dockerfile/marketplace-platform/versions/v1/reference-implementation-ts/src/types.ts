export const CONSTANTS = {
  auth: {
    ROLES: ['PlatformAdmin', 'TenantManager', 'Dispatcher', 'WorkerApp', 'FinanceOfficer', 'CustomerSupport'] as const
  },
  worker: {
    MAX_ACTIVE_ASSIGNMENTS: 10,
    SPECIALTY_REQUIRED_THRESHOLD_PRICE: 50000
  },
  budget: {
    MINIMUM_FACTOR: 1.1,
    CRITICAL_THRESHOLD: 0.8,
    EXHAUSTION_BUFFER_PERCENT: 5,
    PRORATION_TRIGGER_PERCENT: 90,
    SURPLUS_RELEASE_THRESHOLD: 1.5
  },
  risk: {
    RISK_HOLD_THRESHOLD: 70,
    AUTO_DEACTIVATE_THRESHOLD: 90,
    WEIGHT_LATE_COMPLETION: 40,
    WEIGHT_CANCELLATION: 30,
    WEIGHT_LOW_RATING: 30,
    DISPUTE_LOST_PENALTY: 25,
    MIN_DATA_POINTS_FOR_STABILITY: 5,
    DEFAULT_CHRONIC_SCORE: 0
  },
  sla: {
    LATE_COMPLETION_MIN_PERIODS: 1
  },
  debt: {
    MAX_SIGNUP_BONUS_CENTS: 100000
  },
  dispute: {
    FILING_WINDOW_PERIODS: 30,
    MAX_DISPUTES_PER_ORDER: 2
  },
  payout: {
    MINIMUM_PAYOUT_CENTS: 100,
    INSTANT_FEE_PERCENT: 3
  },
  clock: {
    MIN_PERIOD_INDEX: 0,
    MAX_ADVANCE_BY: 365,
    SLA_MARGIN_PERIODS: 0
  }
};

export type Role = typeof CONSTANTS.auth.ROLES[number];

export type TenantStatus = 'ACTIVE' | 'SUSPENDED' | 'CLOSED';
export type ListingStatus = 'DRAFT' | 'PUBLISHED' | 'PAUSED' | 'ARCHIVED';
export type ListingCategory = 'DELIVERY' | 'HOME_SERVICE' | 'RIDESHARE' | 'TASK';
export type OrderStatus = 'CREATED' | 'PENDING_MATCHING' | 'ASSIGNED' | 'IN_PROGRESS' | 'COMPLETED' | 'FAILED' | 'CANCELLED_BY_CUSTOMER' | 'CANCELLED_BY_WORKER' | 'DISPUTED' | 'REFUNDED' | 'CLOSED';
export type WorkerStatus = 'ACTIVE' | 'RISK_HOLD' | 'SUSPENDED' | 'DEACTIVATED';
export type AssignmentStatus = 'OFFERED' | 'ACCEPTED' | 'IN_PROGRESS' | 'COMPLETED' | 'CANCELLED_BY_WORKER' | 'CANCELLED_BY_SYSTEM' | 'EXPIRED';
export type PayoutStatus = 'REQUESTED' | 'APPROVED' | 'SENT' | 'CLEARED' | 'FAILED' | 'CANCELLED' | 'HELD';
export type PayoutType = 'NORMAL' | 'INSTANT' | 'ADJUSTMENT' | 'FINAL';
export type DisputeStatus = 'FILED' | 'UNDER_REVIEW' | 'RESOLVED_CUSTOMER' | 'RESOLVED_WORKER' | 'CANCELLED' | 'EXPIRED';
export type DisputeRaisedBy = 'CUSTOMER' | 'WORKER';
export type RatingStatus = 'PENDING_MODERATION' | 'PUBLISHED' | 'HIDDEN' | 'REMOVED';

export interface Certification {
  certification_type: string;
  certified_period_index: number;
  expiry_period_index: number;
}

export interface MarketplaceTenant {
  id: string;
  name: string;
  payout_credit_limit_cents: number;
  current_period_index: number;
  payout_consumed_cents: number;
  payout_reserved_cents: number;
  payout_available_cents: number;
  recovered_clawbacks_cents: number;
  is_payout_critical: boolean;
  is_payout_exhausted: boolean;
  aggregate_risk_score: number;
  status: TenantStatus;
  term_end_period_index: number | null;
  created_seq: number;
}

export interface Listing {
  id: string;
  tenant_id: string;
  title: string;
  category: ListingCategory;
  base_price_cents: number;
  surge_multiplier: number;
  customer_sla_periods: number;
  max_parallel_assignments: number;
  status: ListingStatus;
  completed_order_count: number;
  cancellation_rate_percent: number;
  average_rating: number;
  priority_tier: number;
  created_seq: number;
}

export interface Order {
  id: string;
  tenant_id: string;
  listing_id: string;
  external_customer_id: string;
  status: OrderStatus;
  created_period_index: number;
  expected_completion_period_index: number;
  completion_period_index: number | null;
  order_completion_reference_period_index: number | null;
  is_late: boolean;
  is_sla_breached: boolean;
  quoted_price_cents: number;
  final_price_cents: number;
  platform_fee_cents: number;
  worker_earnings_cap_cents: number;
  total_payout_approved_cents: number;
  total_payout_cleared_cents: number;
  active_assignment_count: number;
  has_open_dispute: boolean;
  dispute_count: number;
  can_dispute: boolean;
  rating_count: number;
  average_rating: number;
  created_seq: number;
}

export interface Worker {
  id: string;
  tenant_id: string;
  name: string;
  status: WorkerStatus;
  skills: ListingCategory[];
  certifications: Certification[];
  max_active_assignments: number;
  active_assignment_count: number;
  is_at_capacity: boolean;
  risk_score: number;
  lifetime_orders_completed: number;
  late_order_count: number;
  cancellation_count: number;
  signup_bonus_debt_cents: number;
  debt_repaid_cents: number;
  debt_remaining_cents: number;
  debt_satisfied: boolean;
  created_seq: number;
}

export interface Assignment {
  id: string;
  tenant_id: string;
  order_id: string;
  worker_id: string;
  status: AssignmentStatus;
  share_percentage: number | null;
  expected_earnings_cents: number;
  reserved_earnings_initial_cents: number;
  reserved_earnings_current_cents: number;
  released_earnings_cents: number;
  earnings_adequacy_ratio: number;
  requires_adjustment: boolean;
  is_surplus_release_eligible: boolean;
  suggested_release_amount_cents: number;
  payout_requested_cents: number;
  payout_cleared_cents: number;
  created_seq: number;
}

export interface Payout {
  id: string;
  tenant_id: string;
  worker_id: string;
  assignment_id: string;
  status: PayoutStatus;
  payout_type: PayoutType;
  requested_amount_cents: number;
  unprorated_amount_cents: number;
  approved_amount_cents: number;
  debt_repayment_portion_cents: number;
  cash_portion_cents: number;
  instant_payout_fee_cents: number;
  net_payout_cents: number;
  budget_draw_amount_cents: number;
  proration_factor: number;
  is_prorated: boolean;
  created_seq: number;
}

export interface Dispute {
  id: string;
  tenant_id: string;
  order_id: string;
  assignment_id: string | null;
  raised_by: DisputeRaisedBy;
  reason: string;
  status: DisputeStatus;
  filed_period_index: number;
  resolution_period_index: number | null;
  original_order_status: OrderStatus;
  dispute_sequence: number;
  refund_amount_cents: number;
  worker_penalty_cents: number;
  created_seq: number;
}

export interface Rating {
  id: string;
  tenant_id: string;
  order_id: string;
  worker_id: string;
  rating_value: number;
  comment: string | null;
  status: RatingStatus;
  variance_from_order_average: number;
  is_low_rating: boolean;
  created_seq: number;
}

export interface PayoutBudgetLedger {
  tenant_id: string;
  provisional_reserved_cents: number;
  finalized_paid_cents: number;
  recovered_clawbacks_cents: number;
}

export interface WorkerDebtLedger {
  worker_id: string;
  applied_amount_cents: number;
}

export interface WorkerPerformanceLedger {
  worker_id: string;
  total_assignments_completed: number;
  total_assignments_late: number;
  total_assignments_cancelled: number;
  cumulative_rating_deficit: number;
  rating_count: number;
  dispute_loss_count: number;
}

export interface WorkerCapacityLedger {
  worker_id: string;
  active_assignments: number;
  pending_reassignments: number;
}

export interface ApiMeta {
  api_request_id: string;
  api_request_period_index: number;
  total?: number;
  limit?: number;
  offset?: number;
}

export interface ApiResponse<T> {
  meta: ApiMeta;
  response_type: 'object' | 'array' | 'error';
  data: T;
}

export interface ApiError {
  error_id: string;
  message: string;
}

export interface IdempotencyRecord {
  key: string;
  tenant_id: string;
  worker_id: string;
  assignment_id: string;
  endpoint: string;
  request_body: string;
  response: Payout;
}
