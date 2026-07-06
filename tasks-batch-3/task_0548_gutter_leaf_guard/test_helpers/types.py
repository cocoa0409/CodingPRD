"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this system carry the four common system-managed fields
(id, created_at, updated_at, version), so every TypedDict below includes them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    ADMIN = "Admin"
    SALES_REP = "SalesRep"
    SCHEDULER = "Scheduler"
    WARRANTY_AGENT = "WarrantyAgent"


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #
class ProductCategory(str, Enum):
    GUTTER = "GUTTER"
    LEAF_GUARD = "LEAF_GUARD"
    DOWNSPOUT = "DOWNSPOUT"


class LeadStatus(str, Enum):
    NEW = "NEW"
    CONTACTED = "CONTACTED"
    APPOINTMENT_SET = "APPOINTMENT_SET"
    QUOTED = "QUOTED"
    WON = "WON"
    LOST = "LOST"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"
    NO_SHOW = "NO_SHOW"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    PRESENTED = "PRESENTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    SUPERSEDED = "SUPERSEDED"


class FinancingPlanType(str, Enum):
    DEFERRED_INTEREST = "DEFERRED_INTEREST"
    AMORTIZED = "AMORTIZED"


class FinancingPlanStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    CANCELED = "CANCELED"


class JobStatus(str, Enum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    WEATHER_HOLD = "WEATHER_HOLD"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"


class WarrantyIssueType(str, Enum):
    CLOG = "CLOG"
    OVERFLOW = "OVERFLOW"
    DETACHMENT = "DETACHMENT"


class WarrantyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    RESOLVED = "RESOLVED"


class ReferralStatus(str, Enum):
    PENDING = "PENDING"
    PAYABLE = "PAYABLE"
    PAID = "PAID"
    CLAWED_BACK = "CLAWED_BACK"


class WeatherCondition(str, Enum):
    CLEAR = "CLEAR"
    RAIN = "RAIN"
    SEVERE = "SEVERE"


# --------------------------------------------------------------------------- #
# Entity TypedDicts (all carry id/created_at/updated_at/version)
# --------------------------------------------------------------------------- #
class Product(TypedDict):
    id: str
    name: str
    category: str
    base_rate_cents_per_foot: int
    available_colors: List[str]
    premium_colors: List[str]
    color_surcharge_cents_per_foot: int
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class SalesRep(TypedDict):
    id: str
    full_name: str
    region: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict):
    id: str
    name: str
    region: str
    is_certified_leaf_guard: bool
    booked_days: int
    created_at: str
    updated_at: str
    version: int


class Lead(TypedDict):
    id: str
    full_name: str
    address: str
    phone: str
    region: str
    sales_rep_id: str
    status: str
    no_show_strikes: int
    credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    lead_id: str
    sales_rep_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    measured_linear_feet: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    lead_id: str
    appointment_id: str
    sales_rep_id: str
    product_id: str
    color: str
    estimated_linear_feet: float
    downspout_count: int
    discount_pct: float
    linear_feet: float
    measured_linear_feet: Optional[float]
    subtotal_cents: int
    discount_cents: int
    total_cents: int
    presented_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FinancingPlan(TypedDict):
    id: str
    quote_id: str
    plan_type: str
    apr_bps: int
    term_months: int
    promo_window_days: int
    principal_cents: int
    monthly_payment_cents: int
    total_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Job(TypedDict):
    id: str
    quote_id: str
    lead_id: str
    crew_id: Optional[str]
    install_date: Optional[str]
    install_days: int
    deposit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    job_id: str
    issue_type: str
    estimated_remediation_cents: int
    actual_remediation_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    referrer_lead_id: str
    referee_lead_id: str
    payout_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
