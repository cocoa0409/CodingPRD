"""Domain types: entity TypedDicts, status enums, role enum for the Moving-Labor Marketplace API."""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    HELPER = "Helper"
    DISPATCHER = "Dispatcher"
    ADMIN = "Admin"


# ---------------------------------------------------------------------------
# Status / enum vocabularies
# ---------------------------------------------------------------------------
class HelperVettingStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class SkillTier(str, Enum):
    STANDARD = "STANDARD"
    PRO = "PRO"


class JobType(str, Enum):
    LOAD = "LOAD"
    UNLOAD = "UNLOAD"
    MOVE = "MOVE"


class JobStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    BOOKED = "BOOKED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class AddOnType(str, Enum):
    PACKING_MATERIALS = "PACKING_MATERIALS"
    HEAVY_ITEM = "HEAVY_ITEM"
    STAIRS = "STAIRS"
    LONG_CARRY = "LONG_CARRY"
    ASSEMBLY = "ASSEMBLY"


class QuoteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    RELEASED = "RELEASED"
    NO_SHOW = "NO_SHOW"


class AssignmentRole(str, Enum):
    LEAD = "LEAD"
    CREW = "CREW"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class PayoutStatus(str, Enum):
    RELEASED = "RELEASED"
    REVERSED = "REVERSED"


class InsuranceTier(str, Enum):
    BASIC = "BASIC"
    FULL = "FULL"


# ---------------------------------------------------------------------------
# Entities carrying the full common-field set: id, created_at, updated_at, version
# ---------------------------------------------------------------------------
class Customer(TypedDict):
    id: str
    display_name: str
    email: str
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Helper(TypedDict):
    id: str
    display_name: str
    email: str
    base_hourly_rate_cents: int
    skill_tier: str
    vetting_status: str
    rating_avg: float
    rating_count: int
    no_show_count: int
    active_assignment_count: int
    lifetime_payout_cents: int
    created_at: str
    updated_at: str
    version: int


class Truck(TypedDict):
    id: str
    name: str
    capacity_cuft: int
    daily_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class Job(TypedDict):
    id: str
    customer_id: str
    rate_card_id: str
    insurance_policy_id: str
    truck_id: Optional[str]
    job_type: str
    crew_size: int
    estimated_hours: float
    actual_hours: Optional[float]
    window_start: str
    window_end: str
    truck_required: bool
    status: str
    estimated_total_cents: Optional[int]
    final_total_cents: Optional[int]
    cancellation_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    job_id: str
    addon_type: str
    quantity: int
    unit_fee_cents: int
    line_total_cents: int
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    job_id: str
    base_labor_cents: int
    truck_fee_cents: int
    addons_total_cents: int
    surge_multiplier: float
    subtotal_cents: int
    service_fee_cents: int
    total_cents: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    job_id: str
    helper_id: str
    role: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    job_id: str
    responsible_helper_id: Optional[str]
    damage_description: str
    claimed_amount_cents: int
    status: str
    approved_amount_cents: Optional[int]
    insurance_covered_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Rating(TypedDict):
    id: str
    job_id: str
    helper_id: str
    stars: int
    tip_cents: int
    comment: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    job_id: str
    helper_id: str
    base_pay_cents: int
    tip_cents: int
    bonus_cents: int
    total_payout_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Immutable reference data: id + created_at ONLY (no updated_at, no version)
# ---------------------------------------------------------------------------
class RateCard(TypedDict):
    id: str
    name: str
    job_type: str
    base_hourly_rate_cents: int
    min_billable_hours: float
    crew_surcharge_pct: float
    peak_surge_multiplier: float
    truck_fee_cents: int
    created_at: str


class InsurancePolicy(TypedDict):
    id: str
    name: str
    tier: str
    coverage_cap_cents: int
    deductible_cents: int
    coverage_pct: float
    created_at: str
