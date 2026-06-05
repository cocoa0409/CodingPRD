"""Domain types: entity TypedDicts, status enums, role enum.

All names are taken verbatim from the PRD's field and enum spellings.
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    OPERATIONS_AGENT = "OperationsAgent"
    MEMBER = "Member"


class Tier(str, Enum):
    BASE = "BASE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class FlightSegmentStatus(str, Enum):
    BOOKED = "BOOKED"
    FLOWN = "FLOWN"
    ACCRUED = "ACCRUED"
    CANCELLED = "CANCELLED"


class AwardBookingStatus(str, Enum):
    QUOTED = "QUOTED"
    ISSUED = "ISSUED"
    CANCELLED = "CANCELLED"
    FLOWN = "FLOWN"


class UpgradeRequestStatus(str, Enum):
    WAITLISTED = "WAITLISTED"
    CLEARED = "CLEARED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class CompanionCertificateStatus(str, Enum):
    ISSUED = "ISSUED"
    RESERVED = "RESERVED"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"


class PointsGiftStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class StatusMatchStatus(str, Enum):
    GRANTED = "GRANTED"
    EXPIRED = "EXPIRED"


# --- common_fields: true entities (carry id, created_at, updated_at, version) ---

class Member(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    home_airport: str
    points_balance: int
    qualifying_segments_ytd: int
    tier: str
    status_match_active: bool
    status_match_used: bool
    last_activity_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FlightSegment(TypedDict, total=False):
    id: str
    member_id: str
    origin: str
    destination: str
    fare_class: str
    distance_miles: int
    base_fare_usd: float
    scheduled_departure: str
    status: str
    is_qualifying: bool
    points_awarded: int
    created_at: str
    updated_at: str
    version: int


class AwardBooking(TypedDict, total=False):
    id: str
    member_id: str
    route_code: str
    cabin: str
    pricing_mode: str
    load_factor: Optional[float]
    points_price: int
    companion_certificate_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class UpgradeRequest(TypedDict, total=False):
    id: str
    member_id: str
    flight_pool_id: str
    requested_at: str
    priority_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FlightPool(TypedDict, total=False):
    id: str
    flight_number: str
    departure_at: str
    premium_capacity: int
    seats_cleared: int
    seats_remaining: int
    cleared: bool
    created_at: str
    updated_at: str
    version: int


class CompanionCertificate(TypedDict, total=False):
    id: str
    member_id: str
    valid_from: str
    valid_until: str
    status: str
    attached_award_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PointsGift(TypedDict, total=False):
    id: str
    sender_id: str
    recipient_id: str
    amount: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StatusMatch(TypedDict, total=False):
    id: str
    member_id: str
    rival_tier: str
    matched_tier: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


# --- common_fields: false entities (carry ONLY id + created_at) ---

class PointsLedger(TypedDict, total=False):
    id: str
    member_id: str
    delta: int
    reason: str
    source_type: str
    source_id: Optional[str]
    expires_at: Optional[str]
    created_at: str


class ClockState(TypedDict, total=False):
    id: str
    current_utc: str
    program_year: int
    created_at: str
