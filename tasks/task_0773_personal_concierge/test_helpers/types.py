"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status / value enums ──────────────────────────────────────────────
class MemberStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class VipTier(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class BillingCycleStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ServiceRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    IN_PROGRESS = "IN_PROGRESS"
    ON_HOLD = "ON_HOLD"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class Category(str, Enum):
    ERRAND = "ERRAND"
    BOOKING = "BOOKING"
    TRAVEL = "TRAVEL"
    GIFT = "GIFT"


class Cadence(str, Enum):
    NONE = "NONE"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class VendorEngagementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    RECONCILED = "RECONCILED"
    VOID = "VOID"


class BillingMode(str, Enum):
    MARKUP = "MARKUP"
    PASS_THROUGH = "PASS_THROUGH"


class ChargeBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class TimeEntryStatus(str, Enum):
    FINALIZED = "FINALIZED"
    REVERSED = "REVERSED"


class ExpenseStatus(str, Enum):
    RECONCILED = "RECONCILED"
    DISPUTED = "DISPUTED"


class UserRole(str, Enum):
    MEMBER = "Member"
    CONCIERGE_AGENT = "ConciergeAgent"
    ACCOUNT_MANAGER = "AccountManager"
    FINANCE_OPS = "FinanceOps"


# ─── Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ──
class Member(TypedDict):
    id: str
    full_name: str
    email: str
    status: str
    lifetime_billed_cents: int
    created_at: str
    updated_at: str
    version: int


class RetainerPlan(TypedDict):
    id: str
    name: str
    monthly_retainer_cents: int
    included_hours: int
    overage_rate_cents_per_hour: int
    default_markup_pct: float
    max_pass_through_cents: int
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    member_id: str
    plan_id: str
    vip_tier: str
    status: str
    current_cycle_index: int
    hour_bank_remaining_minutes: int
    outstanding_balance_cents: int
    satisfaction_score: Optional[float]
    created_at: str
    updated_at: str
    version: int


class BillingCycle(TypedDict):
    id: str
    membership_id: str
    cycle_index: int
    included_minutes: int
    consumed_minutes: int
    overage_minutes: int
    overage_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceRequest(TypedDict):
    id: str
    membership_id: str
    recurrence_parent_id: Optional[str]
    category: str
    title: str
    is_standing: bool
    cadence: str
    rush: bool
    estimated_minutes: int
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    actual_minutes: int
    priority_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    name: str
    category: str
    status: str
    created_at: str
    updated_at: str
    version: int


class VendorEngagement(TypedDict):
    id: str
    service_request_id: str
    vendor_id: str
    billing_mode: str
    markup_pct: float
    estimated_cost_lines: List[int]
    actual_cost_lines: Optional[List[int]]
    service_start: str
    service_end: str
    client_charge_cents: int
    charge_basis: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TimeEntry(TypedDict):
    id: str
    service_request_id: str
    billing_cycle_id: str
    minutes: int
    note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Expense(TypedDict):
    id: str
    vendor_engagement_id: str
    membership_id: str
    estimated_cents: int
    actual_cents: int
    variance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable event, carries ONLY id + created_at
class SatisfactionRating(TypedDict):
    id: str
    service_request_id: str
    membership_id: str
    score: int
    comment: Optional[str]
    sequence_no: int
    created_at: str
