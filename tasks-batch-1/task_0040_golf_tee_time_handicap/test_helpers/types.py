"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PRO_SHOP = "ProShop"
    GOLFER = "Golfer"
    ANONYMOUS = "Anonymous"


class MembershipTier(str, Enum):
    MEMBER = "MEMBER"
    PUBLIC = "PUBLIC"


class ScoreStatus(str, Enum):
    POSTED = "POSTED"
    VOID = "VOID"


class TeeTimeStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    CLOSED = "CLOSED"


class BookingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    STANDBY = "STANDBY"
    CANCELLED = "CANCELLED"


class GroupType(str, Enum):
    TWOSOME = "TWOSOME"
    FOURSOME = "FOURSOME"


class PricingTier(str, Enum):
    PEAK = "PEAK"
    OFF_PEAK = "OFF_PEAK"


# common_fields: true — id + created_at + updated_at + version
class Course(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    course_rating: float
    slope_rating: int
    peak_fee_cents: int
    offpeak_fee_cents: int
    peak_start_hour: int
    peak_end_hour: int
    member_discount_pct: float


# common_fields: true
class Golfer(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    full_name: str
    membership_tier: str
    handicap_index: Optional[float]
    provisional_handicap_index: Optional[float]
    handicap_revision: int
    low_handicap_index: Optional[float]


# common_fields: true
class Score(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    golfer_id: str
    course_id: str
    played_on: str
    adjusted_gross_score: int
    score_differential: float
    status: str
    counted_in_revision: int


# common_fields: true
class TeeTime(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    course_id: str
    start_utc: str
    local_hour: int
    group_type: str
    capacity: int
    confirmed_count: int
    status: str


# common_fields: true
class Booking(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    tee_time_id: str
    golfer_id: str
    status: str
    pricing_tier: str
    green_fee_cents: int
    standby_rank: int


# common_fields: false — append-only audit; ONLY id + created_at as system fields
class HandicapRevision(TypedDict):
    id: str
    created_at: str
    revision_number: int
    effective_utc: str
    golfer_count: int
