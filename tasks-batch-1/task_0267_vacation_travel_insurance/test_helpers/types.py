"""Domain types: entity TypedDicts, status enums, role enum for the Vacation Travel Insurance API."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────────────────────────

class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PlanTier(str, Enum):
    BASIC = "BASIC"
    STANDARD = "STANDARD"
    PREMIER = "PREMIER"


class PolicyPaymentStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class PolicyCoverageStatus(str, Enum):
    QUOTED = "QUOTED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    EXHAUSTED = "EXHAUSTED"


class InsuredTravelerStatus(str, Enum):
    COVERED = "COVERED"
    REMOVED = "REMOVED"


class NamedStormBasin(str, Enum):
    ATLANTIC = "ATLANTIC"
    EAST_PACIFIC = "EAST_PACIFIC"
    WEST_PACIFIC = "WEST_PACIFIC"
    INDIAN = "INDIAN"


class NamedStormStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISSIPATED = "DISSIPATED"


class ClaimPeril(str, Enum):
    CANCELLATION = "CANCELLATION"
    MEDICAL = "MEDICAL"
    DELAY = "DELAY"
    BAGGAGE = "BAGGAGE"


class CancellationReason(str, Enum):
    COVERED_REASON = "COVERED_REASON"
    CFAR = "CFAR"
    NAMED_STORM = "NAMED_STORM"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


class ExpenseCategory(str, Enum):
    PREPAID_TRIP = "PREPAID_TRIP"
    MEDICAL_BILL = "MEDICAL_BILL"
    BAGGAGE_ITEM = "BAGGAGE_ITEM"
    DELAY_EXPENSE = "DELAY_EXPENSE"


class DocumentType(str, Enum):
    RECEIPT = "RECEIPT"
    MEDICAL_REPORT = "MEDICAL_REPORT"
    CARRIER_DELAY_LETTER = "CARRIER_DELAY_LETTER"
    POLICE_REPORT = "POLICE_REPORT"
    OTHER = "OTHER"


class PayoutStatus(str, Enum):
    PENDING = "PENDING"
    DISBURSED = "DISBURSED"
    REVERSED = "REVERSED"


class RefundType(str, Enum):
    FREE_LOOK = "FREE_LOOK"
    SHORT_RATE = "SHORT_RATE"


class RefundStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class UserRole(str, Enum):
    CARRIER_ADMIN = "CarrierAdmin"
    UNDERWRITER = "Underwriter"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    TRAVELER = "Traveler"
    SYSTEM = "System"
    ANY = "Any"


# ─── Entity TypedDicts ────────────────────────────────────────────────────
# Every entity except ClaimDocument carries id + created_at + updated_at + version.
# ClaimDocument is an append-only audit record carrying only id + created_at.

class Plan(TypedDict):
    id: str
    code: str
    tier: str
    base_rate_bps: int
    cancellation_limit_pct: int
    medical_limit_cents: int
    delay_block_cap_cents: int
    delay_limit_cents: int
    baggage_item_sublimit_cents: int
    baggage_limit_cents: int
    baggage_depreciation_bps: int
    waiver_window_days: int
    free_look_days: int
    claim_filing_window_days: int
    cfar_loading_bps: int
    cfar_reimbursement_pct: int
    senior_age_threshold: int
    senior_loading_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Traveler(TypedDict):
    id: str
    email: str
    full_name: str
    date_of_birth: str
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict):
    id: str
    plan_id: str
    owner_traveler_id: str
    trip_cost_cents: int
    initial_deposit_at: str
    trip_start_at: str
    trip_end_at: str
    cfar_opted: bool
    base_premium_cents: int
    premium_cents: int
    aggregate_limit_cents: int
    amount_reimbursed_cents: int
    remaining_aggregate_cents: int
    net_premium_collected_cents: int
    preexisting_waiver_granted: bool
    issued_at: Optional[str]
    free_look_ends_at: Optional[str]
    payment_status: str
    coverage_status: str
    created_at: str
    updated_at: str
    version: int


class InsuredTraveler(TypedDict):
    id: str
    policy_id: str
    traveler_id: str
    age_at_departure: int
    has_preexisting_condition: bool
    covered_trip_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class NamedStorm(TypedDict):
    id: str
    name: str
    basin: str
    named_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    policy_id: str
    insured_traveler_id: str
    named_storm_id: Optional[str]
    peril: str
    cancellation_reason: Optional[str]
    incident_at: str
    delay_hours: int
    involves_preexisting: bool
    provisional_amount_cents: int
    approved_amount_cents: int
    denial_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ClaimExpense(TypedDict):
    id: str
    claim_id: str
    category: str
    description: str
    documented_amount_cents: int
    prepaid_nonrefundable_cents: int
    supplier_refund_received_cents: int
    item_value_cents: int
    created_at: str
    updated_at: str
    version: int


# Append-only audit record: id + created_at only (no updated_at, no version).
class ClaimDocument(TypedDict):
    id: str
    claim_id: str
    doc_type: str
    file_ref: str
    uploaded_by_traveler_id: str
    created_at: str


class Payout(TypedDict):
    id: str
    claim_id: str
    policy_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Refund(TypedDict):
    id: str
    policy_id: str
    refund_type: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
