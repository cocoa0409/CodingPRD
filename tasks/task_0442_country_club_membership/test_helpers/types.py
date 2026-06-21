"""Domain types: entity TypedDicts, status enums, role enum (Country Club Membership API)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CLUB_MANAGER = "ClubManager"
    BILLING_CLERK = "BillingClerk"
    MEMBER = "Member"


# ---------------------------------------------------------------------------
# Status enums (PRD §2.7, §3)
# ---------------------------------------------------------------------------
class AccountStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RESIGNED_PENDING = "RESIGNED_PENDING"
    RESIGNED = "RESIGNED"


class BillingStatus(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"
    DELINQUENT = "DELINQUENT"


class CategoryCode(str, Enum):
    GOLF = "GOLF"
    SOCIAL = "SOCIAL"
    CORPORATE = "CORPORATE"


class ResourceKind(str, Enum):
    TEE_TIME = "TEE_TIME"
    COURT = "COURT"
    DINING_TABLE = "DINING_TABLE"


class ReservationStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    AMEND_PENDING = "AMEND_PENDING"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class ChitKind(str, Enum):
    DINING = "DINING"
    PRO_SHOP = "PRO_SHOP"
    GUEST_FEE = "GUEST_FEE"
    EVENT = "EVENT"


class ChitStatus(str, Enum):
    POSTED = "POSTED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class GuestPassStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CHECKED_IN = "CHECKED_IN"
    CANCELLED = "CANCELLED"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    LEVIED = "LEVIED"
    CANCELLED = "CANCELLED"


class AllocationBasis(str, Enum):
    EQUAL = "EQUAL"
    DUES_WEIGHTED = "DUES_WEIGHTED"


class WaitlistStatus(str, Enum):
    WAITING = "WAITING"
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class StatementStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    PAID = "PAID"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# Entities with the full audit set carry id/created_at/updated_at/version.
# AssessmentCharge is the lone append-only record: id + created_at only (PRD §2.4).
# ---------------------------------------------------------------------------
class Club(TypedDict):
    id: str
    name: str
    billing_period_index: int
    closed_through_period_index: int
    fb_minimum_carryover_allowed: bool
    resignation_refund_pct: int
    guest_visits_cap_per_period: int
    created_at: str
    updated_at: str
    version: int


class MembershipCategory(TypedDict):
    id: str
    club_id: str
    code: str
    initiation_fee_cents: int
    refundable_equity_cents: int
    monthly_dues_cents: int
    fb_minimum_cents: int
    capacity: int
    guest_fee_cents: int
    allows_golf: bool
    active_member_count: int
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    club_id: str
    category_id: str
    primary_member_id: Optional[str]
    holder_name: str
    account_status: str
    billing_status: str
    charge_balance_cents: int
    fb_spend_period_cents: int
    fb_credit_carried_cents: int
    refund_owed_cents: int
    activated_period_index: Optional[int]
    guest_visits_used_period: int
    created_at: str
    updated_at: str
    version: int


class Resource(TypedDict):
    id: str
    club_id: str
    kind: str
    label: str
    turnaround_minutes: int
    seat_capacity: int
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    club_id: str
    resource_id: str
    membership_id: str
    starts_at: str
    ends_at: str
    party_size: int
    status: str
    proposed_starts_at: Optional[str]
    proposed_ends_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Chit(TypedDict):
    id: str
    club_id: str
    membership_id: str
    amount_cents: int
    kind: str
    counts_toward_fb: bool
    period_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GuestPass(TypedDict):
    id: str
    club_id: str
    sponsor_membership_id: str
    guest_name: str
    visit_date: str
    status: str
    fee_chit_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CapitalAssessment(TypedDict):
    id: str
    club_id: str
    description: str
    total_target_cents: int
    allocation_basis: str
    status: str
    levied_amount_cents: int
    levied_period_index: Optional[int]
    created_at: str
    updated_at: str
    version: int


# Append-only immutable record (PRD §2.4): id + created_at only.
class AssessmentCharge(TypedDict):
    id: str
    assessment_id: str
    membership_id: str
    amount_cents: int
    created_at: str


class WaitlistEntry(TypedDict):
    id: str
    club_id: str
    category_id: str
    applicant_name: str
    status: str
    offered_period_index: Optional[int]
    created_membership_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Statement(TypedDict):
    id: str
    club_id: str
    membership_id: str
    period_index: int
    dues_cents: int
    fb_minimum_cents: int
    fb_spend_cents: int
    fb_shortfall_cents: int
    chit_charges_cents: int
    assessment_cents: int
    total_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
