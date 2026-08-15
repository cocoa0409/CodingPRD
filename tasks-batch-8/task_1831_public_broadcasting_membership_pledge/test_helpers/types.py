"""Domain types: entity TypedDicts, status enums, role enum.

Every entity carries the four common fields (id, created_at, updated_at,
version) per the PRD common-resource-property rules.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    STATION_ADMIN = "StationAdmin"
    MEMBERSHIP_COORDINATOR = "MembershipCoordinator"
    PHONE_VOLUNTEER = "PhoneVolunteer"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    GRACE = "GRACE"
    LAPSED = "LAPSED"
    REINSTATED_PENDING = "REINSTATED_PENDING"


class DriveStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    ON_AIR = "ON_AIR"
    CLOSED = "CLOSED"
    RECONCILED = "RECONCILED"


class BreakStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    AIRED = "AIRED"


class PaymentStatus(str, Enum):
    PLEDGED = "PLEDGED"
    PAID = "PAID"
    PARTIAL = "PARTIAL"
    DECLINED = "DECLINED"
    WRITTEN_OFF = "WRITTEN_OFF"


class FulfillmentStatus(str, Enum):
    NO_PREMIUM = "NO_PREMIUM"
    AWAITING_RESERVATION = "AWAITING_RESERVATION"
    RESERVED = "RESERVED"
    SHIPPED = "SHIPPED"
    WAIVED = "WAIVED"


class PledgeChannel(str, Enum):
    PHONE = "PHONE"
    WEB = "WEB"


class PledgeKind(str, Enum):
    ONE_TIME = "ONE_TIME"
    SUSTAINER = "SUSTAINER"


class ReservationStatus(str, Enum):
    HELD = "HELD"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


class ChallengeStatus(str, Enum):
    OPEN = "OPEN"
    MET = "MET"
    EXPIRED = "EXPIRED"


class NffsVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class NffsStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    AMENDED = "AMENDED"


class MembershipLevel(TypedDict):
    id: str
    code: str
    min_annual_cents: int
    min_monthly_sustainer_cents: int
    premium_eligible: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class Premium(TypedDict):
    id: str
    sku: str
    title: str
    fair_market_value_cents: int
    membership_level_code: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class PremiumInventoryLot(TypedDict):
    id: str
    premium_id: str
    received_at: str
    unit_cost_cents: int
    total_qty: int
    available_qty: int
    reserved_qty: int
    committed_qty: int
    written_off_qty: int
    created_at: str
    updated_at: str
    version: int


class Donor(TypedDict):
    id: str
    email: str
    full_name: str
    postal_code: str
    lifetime_given_cents: int
    lapse_count: int
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    donor_id: str
    level_code: str
    status: str
    current_period_start: str
    current_period_end: str
    sustainer: bool
    created_at: str
    updated_at: str
    version: int


class PledgeDrive(TypedDict):
    id: str
    name: str
    starts_at: str
    ends_at: str
    status: str
    goal_cents: int
    pledged_cents: int
    collected_cents: int
    created_at: str
    updated_at: str
    version: int


class OnAirBreak(TypedDict):
    id: str
    drive_id: str
    starts_at: str
    ends_at: str
    program_title: str
    pitch_level_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Pledge(TypedDict):
    id: str
    donor_id: str
    membership_id: str
    drive_id: str
    on_air_break_id: Optional[str]
    matching_challenge_id: Optional[str]
    channel: str
    kind: str
    amount_cents: int
    payment_status: str
    fulfillment_status: str
    premium_id: Optional[str]
    premium_waived: bool
    net_collected_cents: int
    collected_cents: int
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PremiumReservation(TypedDict):
    id: str
    pledge_id: str
    premium_id: str
    lot_id: str
    quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MatchingChallenge(TypedDict):
    id: str
    drive_id: str
    sponsor_name: str
    goal_cents: int
    match_cents: int
    progress_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class UnderwritingCredit(TypedDict):
    id: str
    drive_id: str
    underwriter_name: str
    amount_cents: int
    aired: bool
    created_at: str
    updated_at: str
    version: int


class NFFSReport(TypedDict):
    id: str
    fiscal_year: int
    variant: str
    status: str
    membership_revenue_cents: int
    underwriting_excluded_cents: int
    matching_revenue_cents: int
    drafted_by_user_id: str
    finalized_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
