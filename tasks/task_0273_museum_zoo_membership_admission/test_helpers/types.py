"""Domain types: entity TypedDicts, status enums, role enum.

All names mirror the Museum & Zoo Membership & Admission PRD exactly.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum (PRD §2.1) ─────────────────────────────────────────────

class UserRole(str, Enum):
    PATRON = "Patron"
    BOX_OFFICE = "BoxOffice"
    GATE_SCANNER = "GateScanner"
    MEMBERSHIP_ADMIN = "MembershipAdmin"


# ─── Status / enum value sets ─────────────────────────────────────────

class MembershipTier(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    DUAL = "DUAL"
    HOUSEHOLD = "HOUSEHOLD"
    PATRON_CIRCLE = "PATRON_CIRCLE"


class MembershipStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    GRACE = "GRACE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class HouseholdRelationship(str, Enum):
    SPOUSE = "SPOUSE"
    CHILD = "CHILD"
    PARTNER = "PARTNER"
    OTHER = "OTHER"


class GuestPassStatus(str, Enum):
    UNUSED = "UNUSED"
    RESERVED = "RESERVED"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"


class SlotStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class TicketType(str, Enum):
    MEMBER = "MEMBER"
    NON_MEMBER = "NON_MEMBER"
    GUEST = "GUEST"
    RECIPROCAL = "RECIPROCAL"


class TicketState(str, Enum):
    ACTIVE = "ACTIVE"
    SCANNED = "SCANNED"
    VOIDED = "VOIDED"


class ReciprocalBenefitType(str, Enum):
    FREE = "FREE"
    DISCOUNT = "DISCOUNT"


# ─── Entity TypedDicts ────────────────────────────────────────────────
# Entities carrying id + created_at + updated_at + version, except Donation,
# which is an immutable receipt carrying only id + created_at.

class Patron(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    email: str
    full_name: str
    home_partner_id: Optional[str]


class MembershipPlan(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    tier: str
    annual_fee_cents: int
    household_max: int
    guest_passes_granted: int
    member_admission_cents: int
    exhibit_surcharge_waived: bool
    reciprocal_eligible: bool
    term_days: int
    reinstatement_fee_cents: int


class Membership(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    plan_id: str
    primary_patron_id: str
    status: str
    auto_renew: bool
    started_at: Optional[str]
    expires_at: Optional[str]
    grace_until: Optional[str]
    term_count: int
    last_paid_fee_cents: int


class HouseholdMember(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    membership_id: str
    full_name: str
    relationship: str
    active: bool


class GuestPass(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    membership_id: str
    status: str
    reserved_order_id: Optional[str]


class TimedEntrySlot(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    starts_at: str
    ends_at: str
    capacity_total: int
    reserved_count: int
    status: str
    non_member_admission_cents: int


class SpecialExhibit(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    surcharge_cents: int
    member_surcharge_discount_pct: float
    buffer_minutes: int


class ExhibitSession(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    exhibit_id: str
    starts_at: str
    ends_at: str
    capacity_total: int
    reserved_count: int


class AdmissionOrder(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    patron_id: str
    slot_id: str
    membership_id: Optional[str]
    exhibit_session_id: Optional[str]
    party_size: int
    status: str
    donation_cents: int
    quoted_total_cents: int
    final_total_cents: Optional[int]


class AdmissionTicket(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    order_id: str
    ticket_type: str
    person_name: str
    guest_pass_id: Optional[str]
    reciprocal_partner_id: Optional[str]
    price_cents: int
    state: str


class ReciprocalPartner(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    org_name: str
    benefit_type: str
    discount_pct: float


# Donation: immutable receipt — only id + created_at + the join/amount fields.
# No updated_at, no version.
class Donation(TypedDict, total=False):
    id: str
    created_at: str
    order_id: Optional[str]
    membership_id: Optional[str]
    amount_cents: int
