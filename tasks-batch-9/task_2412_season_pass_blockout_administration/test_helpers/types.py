"""Typed shapes for the entities and enumerations the PRD declares."""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------- roles -----


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    PASS_OFFICE_CLERK = "PassOfficeClerk"
    GATE_AGENT = "GateAgent"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PASSHOLDER = "Passholder"


# ------------------------------------------------------------ enumerations --


class ProgramStatus(str, Enum):
    DESIGN = "DESIGN"
    SALES_OPEN = "SALES_OPEN"
    SEASON_ACTIVE = "SEASON_ACTIVE"
    RENEWAL_OPEN = "RENEWAL_OPEN"
    CLOSED = "CLOSED"


class TierStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class ParkingBenefit(str, Enum):
    NONE = "NONE"
    DISCOUNT = "DISCOUNT"
    INCLUDED = "INCLUDED"


class DayClass(str, Enum):
    STANDARD = "STANDARD"
    PEAK = "PEAK"
    CAPACITY_LOCKED = "CAPACITY_LOCKED"


class BlockoutStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class BlockoutSource(str, Enum):
    MANUAL = "MANUAL"
    CAPACITY_ADJUSTED = "CAPACITY_ADJUSTED"


class PassholderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BANNED = "BANNED"


class PassStatus(str, Enum):
    """The park-access dimension of a season pass."""

    PENDING_PROCESSING = "PENDING_PROCESSING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class BillingStatus(str, Enum):
    """The billing dimension of a season pass, independent of pass_status."""

    UNBILLED = "UNBILLED"
    PLAN_CURRENT = "PLAN_CURRENT"
    DELINQUENT = "DELINQUENT"
    DEFAULTED = "DEFAULTED"
    PAID_IN_FULL = "PAID_IN_FULL"


class PaymentMode(str, Enum):
    PAY_IN_FULL = "PAY_IN_FULL"
    PAYMENT_PLAN = "PAYMENT_PLAN"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    COMPLETED = "COMPLETED"
    TERMINATED_ON_REVOCATION = "TERMINATED_ON_REVOCATION"


class InstallmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SETTLED = "SETTLED"
    MISSED = "MISSED"
    WAIVED = "WAIVED"
    VOIDED = "VOIDED"


class ReservationStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    CANCELLED_BY_HOLDER = "CANCELLED_BY_HOLDER"
    CANCELLED_BY_SUSPENSION = "CANCELLED_BY_SUSPENSION"
    CANCELLED_BY_BLOCKOUT = "CANCELLED_BY_BLOCKOUT"
    REDEEMED = "REDEEMED"
    NO_SHOW = "NO_SHOW"


class VisitStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class PhotoMatch(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    NOT_CHECKED = "NOT_CHECKED"


class GateCode(str, Enum):
    NORTH = "NORTH"
    SOUTH = "SOUTH"
    EAST = "EAST"
    WEST = "WEST"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUBSTANTIATED = "SUBSTANTIATED"
    APPEAL_PENDING = "APPEAL_PENDING"
    DISMISSED = "DISMISSED"


class CaseDecision(str, Enum):
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"


class UpgradeOrderStatus(str, Enum):
    QUOTED = "QUOTED"
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"
    EXPIRED = "EXPIRED"


class CreditMode(str, Enum):
    PAID_TO_DATE = "PAID_TO_DATE"
    PRORATED_VALUE = "PRORATED_VALUE"


# --------------------------------------------------------------- records ----


class _Record(TypedDict):
    """Fields every persisted record carries."""

    id: str
    created_at: str
    updated_at: str
    version: int


class PassProgram(_Record, total=False):
    season_year: int
    park_name: str
    status: str
    early_bird_deadline: str
    capacity_peak_threshold_pct: float
    capacity_lock_threshold_pct: float
    capacity_lock_blockout_max_rank: int
    delinquency_suspension_threshold: int
    default_threshold: int
    sharing_case_auto_open_score: int
    base_revenue_cents: int
    recognized_revenue_cents: int
    deferred_revenue_cents: int
    forfeited_revenue_cents: int
    active_pass_count: int


class PassTier(_Record, total=False):
    program_id: str
    name: str
    tier_rank: int
    base_price_cents: int
    parking_benefit: str
    in_park_discount_pct: float
    reservation_required_on_peak: bool
    peak_reservation_quota: int
    status: str


class ParkDay(_Record, total=False):
    program_id: str
    calendar_date: str
    capacity_total: int
    forecast_attendance: int
    forecast_utilization_pct: float
    day_class: str
    reservation_slot_capacity: int
    window_slot_capacity: int
    reserved_count: int
    released_count: int
    redeemed_count: int
    no_show_count: int
    remaining_slot_count: int
    grant_count: int


class BlockoutAssignment(_Record, total=False):
    tier_id: str
    park_day_id: str
    status: str
    source: str
    lift_reason: Optional[str]


class Passholder(_Record, total=False):
    full_name: str
    email: str
    date_of_birth: str
    status: str
    sharing_risk_score: int
    photo_mismatch_count: int


class SeasonPass(_Record, total=False):
    program_id: str
    tier_id: str
    passholder_id: str
    media_number: str
    pass_status: str
    billing_status: str
    payment_mode: str
    contract_value_cents: int
    billed_total_cents: int
    paid_to_date_cents: int
    credited_amount_cents: int
    outstanding_balance_cents: int
    photo_captured: bool
    identity_bound: bool
    photo_hash: Optional[str]
    government_id_last4: Optional[str]
    visit_count: int
    in_park_spend_cents: int
    suspension_count: int
    renewed_from_pass_id: Optional[str]


class PaymentPlan(_Record, total=False):
    season_pass_id: str
    plan_status: str
    setup_fee_cents: int
    down_payment_cents: int
    installment_count: int
    financed_amount_cents: int
    monthly_amount_cents: int
    final_installment_cents: int
    first_due_date: str
    settled_count: int
    missed_count: int


class Installment(_Record, total=False):
    payment_plan_id: str
    sequence_no: int
    amount_cents: int
    due_date: str
    status: str
    settled_at: Optional[str]


class Reservation(_Record, total=False):
    season_pass_id: str
    park_day_id: str
    arrival_window_start: str
    arrival_window_end: str
    status: str
    redeemed_visit_id: Optional[str]


class Visit(_Record, total=False):
    season_pass_id: str
    park_day_id: str
    entry_at: str
    gate_code: str
    photo_match: str
    status: str
    reservation_id: Optional[str]
    spend_cents: int
    discount_applied_pct: float


class SharingCase(_Record, total=False):
    season_pass_id: str
    case_status: str
    review_round: int
    evidence_visit_ids: List[str]
    note: str
    opened_by_user_id: str
    opened_by_role: str
    risk_score_at_open: int
    decided_by_user_id: Optional[str]
    decision_rationale: Optional[str]
    revocation_forfeit_cents: Optional[int]


class UpgradeOrder(_Record, total=False):
    season_pass_id: str
    source_tier_id: str
    target_tier_id: str
    credit_mode: str
    status: str
    gross_delta_cents: int
    raw_credit_cents: int
    credit_cents: int
    net_delta_cents: int
    admin_fee_cents: int
    total_due_cents: int
    payment_amount_cents: Optional[int]
    quoted_at: str
    quote_expires_at: str
    reverse_reason: Optional[str]


class RevenueSummary(TypedDict, total=False):
    base_revenue_cents: int
    recognized_revenue_cents: int
    deferred_revenue_cents: int
    forfeited_revenue_cents: int
    active_pass_count: int
    total_visit_count: int
    visits_per_active_pass: float
    total_in_park_spend_cents: int
    spend_per_visit_cents: int


class BillingRunResult(TypedDict, total=False):
    missed_installment_count: int
    delinquent_pass_count: int
    defaulted_pass_count: int
    suspended_pass_count: int
    released_reservation_count: int
    no_show_reservation_count: int
    expired_upgrade_order_count: int


Json = Dict[str, Any]
