"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this platform carry id + created_at + updated_at + version
(every persisted resource is versioned, PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, List


# --- Role enum (PRD §2.1) ----------------------------------------------------
class UserRole(str, Enum):
    GARDEN_ADMIN = "GardenAdmin"
    GARDEN_STAFF = "GardenStaff"
    RENTAL_COORDINATOR = "RentalCoordinator"
    DEVELOPMENT_OFFICER = "DevelopmentOfficer"
    VISITOR = "Visitor"


# --- Status enums ------------------------------------------------------------
class MembershipTier(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    HOUSEHOLD = "HOUSEHOLD"
    PATRON = "PATRON"


class MembershipStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"


class TimeSlotStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ReservationStatus(str, Enum):
    HELD = "HELD"
    CHECKED_IN = "CHECKED_IN"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class EventTicketStatus(str, Enum):
    PURCHASED = "PURCHASED"
    REFUNDED = "REFUNDED"


class ProgramSessionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RegistrationStatus(str, Enum):
    ENROLLED = "ENROLLED"
    WAITLISTED = "WAITLISTED"
    WITHDRAWN = "WITHDRAWN"


class RentalStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class DonationDesignation(str, Enum):
    GENERAL = "GENERAL"
    CONSERVANCY = "CONSERVANCY"
    CAPITAL = "CAPITAL"


class DonationStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class CampaignStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


# --- Entity TypedDicts (all carry id/created_at/updated_at/version) -----------
class Garden(TypedDict):
    id: str
    name: str
    timezone: str
    reciprocal_network_code: str
    reciprocal_discount_pct: float
    household_member_cap: int
    guest_pass_grant_household: int
    guest_pass_grant_patron: int
    created_at: str
    updated_at: str
    version: int


class MembershipPlan(TypedDict):
    id: str
    garden_id: str
    tier: str
    annual_fee_cents: int
    admission_included: bool
    event_discount_pct: float
    program_discount_pct: float
    active: bool
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    garden_id: str
    plan_id: str
    primary_member_name: str
    household_member_names: List[str]
    status: str
    auto_renew: bool
    term_start: str
    term_end: str
    paid_total_cents: int
    guest_passes_remaining: int
    renewal_count: int
    created_at: str
    updated_at: str
    version: int


class TimeSlot(TypedDict):
    id: str
    garden_id: str
    starts_at: str
    ends_at: str
    capacity: int
    ga_price_cents: int
    held_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    garden_id: str
    time_slot_id: str
    membership_id: str
    member_heads: int
    guest_heads: int
    paid_heads: int
    reciprocal: bool
    party_size: int
    admission_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EventTicket(TypedDict):
    id: str
    garden_id: str
    membership_id: str
    exhibit_name: str
    list_price_cents: int
    quantity: int
    charged_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProgramSession(TypedDict):
    id: str
    garden_id: str
    title: str
    starts_at: str
    capacity: int
    tuition_cents: int
    enrolled_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict):
    id: str
    garden_id: str
    program_session_id: str
    membership_id: str
    participant_name: str
    charged_cents: int
    status: str
    waitlist_rank: int
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict):
    id: str
    garden_id: str
    name: str
    hourly_rate_cents: int
    buffer_minutes: int
    member_rental_discount_pct: float
    created_at: str
    updated_at: str
    version: int


class Rental(TypedDict):
    id: str
    garden_id: str
    venue_id: str
    membership_id: str
    starts_at: str
    ends_at: str
    quoted_cents: int
    final_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Donation(TypedDict):
    id: str
    garden_id: str
    membership_id: str
    amount_cents: int
    designation: str
    tax_deductible_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ConservancyFund(TypedDict):
    id: str
    garden_id: str
    pledged_total_cents: int
    matched_total_cents: int
    match_ratio: float
    match_cap_cents: int
    campaign_status: str
    created_at: str
    updated_at: str
    version: int
