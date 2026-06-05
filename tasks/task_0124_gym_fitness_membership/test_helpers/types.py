"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resources and status axes defined in the Gym & Fitness Membership PRD.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Roles ---
class UserRole(str, Enum):
    STAFF_MANAGER = "StaffManager"
    MEMBER = "Member"


# --- Status enums ---
class MembershipStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CANCELLED = "CANCELLED"


class DuesStatus(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"
    DELINQUENT = "DELINQUENT"
    SUSPENDED = "SUSPENDED"


class ContractStatus(str, Enum):
    IN_COOLING_OFF = "IN_COOLING_OFF"
    IN_TERM = "IN_TERM"
    FULFILLED = "FULFILLED"
    TERMINATED = "TERMINATED"


class ClassSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class BookingStatus(str, Enum):
    BOOKED = "BOOKED"
    WAITLISTED = "WAITLISTED"
    ATTENDED = "ATTENDED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class PTPackageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    VOID = "VOID"


class PTSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class DuesInvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    VOID = "VOID"


class GuestPassStatus(str, Enum):
    ISSUED = "ISSUED"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class CheckInStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ActorKind(str, Enum):
    MEMBER = "MEMBER"
    GUEST = "GUEST"


class PlanTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    ELITE = "ELITE"


# --- Entity TypedDicts (common_fields: true -> id/created_at/updated_at/version) ---
class MembershipPlan(TypedDict):
    id: str
    tier: str
    monthly_dues_cents: int
    included_class_credits: int
    pt_discount_pct: float
    contract_term_months: int
    early_termination_fee_cents: int
    max_freeze_days_per_term: int
    guest_passes_per_cycle: int
    archived: bool
    created_at: str
    updated_at: str
    version: int


class Location(TypedDict):
    id: str
    name: str
    occupancy_cap: int
    current_occupancy: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    plan_id: str
    home_location_id: str
    full_name: str
    email: str
    membership_status: str
    dues_status: str
    class_credits_remaining: int
    guest_passes_remaining: int
    wallet_credit_cents: int
    cumulative_freeze_days: int
    past_due_since: Optional[str]
    contract_status: str
    contract_term_months: int
    signed_at: str
    cooling_off_ends_at: str
    term_ends_at: str
    created_at: str
    updated_at: str
    version: int


class ClassSession(TypedDict):
    id: str
    location_id: str
    title: str
    starts_at: str
    ends_at: str
    capacity: int
    waitlist_cap: int
    status: str
    booked_count: int
    waitlisted_count: int
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    session_id: str
    member_id: str
    status: str
    waitlist_position: Optional[int]
    credit_charged: bool
    booked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PTPackage(TypedDict):
    id: str
    member_id: str
    sessions_purchased: int
    list_price_cents: int
    price_paid_cents: int
    sessions_remaining: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PTSession(TypedDict):
    id: str
    package_id: str
    trainer_name: str
    starts_at: str
    status: str
    deducted: bool
    created_at: str
    updated_at: str
    version: int


class DuesInvoice(TypedDict):
    id: str
    member_id: str
    period_start: str
    period_end: str
    gross_amount_cents: int
    wallet_applied_cents: int
    amount_due_cents: int
    status: str
    due_date: str
    created_at: str
    updated_at: str
    version: int


class GuestPass(TypedDict):
    id: str
    member_id: str
    guest_name: str
    location_id: str
    status: str
    issued_at: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only event log (common_fields: false -> id/created_at only) ---
class CheckIn(TypedDict):
    id: str
    location_id: str
    member_id: Optional[str]
    guest_pass_id: Optional[str]
    actor_kind: str
    status: str
    created_at: str
