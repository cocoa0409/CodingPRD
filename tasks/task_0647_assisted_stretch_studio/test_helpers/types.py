"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resource model in the Assisted Stretch Studio PRD. Entities that
carry the full common field set (id, created_at, updated_at, version) are
distinguished from the leaner append-only resources (AddOn, NoShowEvent,
ClockState) which carry only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Status enums ---------------------------------------------------------

class LocationStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class FlexologistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class TableStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class ServiceKind(str, Enum):
    ASSISTED_STRETCH = "ASSISTED_STRETCH"
    RECOVERY = "RECOVERY"
    INTRO = "INTRO"


class ServiceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class MobilityTier(str, Enum):
    FOUNDATION = "FOUNDATION"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"


class MembershipTier(str, Enum):
    STARTER = "STARTER"
    PLUS = "PLUS"
    PRO = "PRO"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CANCELLED = "CANCELLED"


class CreditPackStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"
    EXPIRED = "EXPIRED"


class FundingSource(str, Enum):
    MEMBERSHIP = "MEMBERSHIP"
    CREDIT_PACK = "CREDIT_PACK"


class ScheduleStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    LATE_CANCELLED = "LATE_CANCELLED"
    NO_SHOW = "NO_SHOW"


class CreditStatus(str, Enum):
    HELD = "HELD"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"
    FORFEITED = "FORFEITED"


class AddOnKind(str, Enum):
    COMPRESSION = "COMPRESSION"
    PERCUSSION = "PERCUSSION"


class NoShowEventKind(str, Enum):
    NO_SHOW = "NO_SHOW"
    LATE_CANCEL = "LATE_CANCEL"


class RecurringSeriesStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class UserRole(str, Enum):
    MEMBER = "Member"
    FLEXOLOGIST = "Flexologist"
    FRONT_DESK = "FrontDesk"
    STUDIO_MANAGER = "StudioManager"


# --- Entity TypedDicts (common_fields: true) ------------------------------

class Location(TypedDict):
    id: str
    name: str
    timezone: str
    open_minute_of_day: int
    close_minute_of_day: int
    flexologist_buffer_minutes: int
    no_show_fee_cents: int
    late_cancel_pct: float
    cancel_window_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Flexologist(TypedDict):
    id: str
    location_id: str
    full_name: str
    certified_intro: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Table(TypedDict):
    id: str
    location_id: str
    label: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Service(TypedDict):
    id: str
    location_id: str
    name: str
    kind: str
    duration_minutes: int
    credit_cost: int
    list_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    home_location_id: str
    full_name: str
    email: str
    intro_completed: bool
    mobility_tier: Optional[str]
    strike_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    member_id: str
    location_id: str
    tier: str
    monthly_fee_cents: int
    included_credits: int
    rollover_cap: int
    granted_credits: int
    held_credits: int
    consumed_credits: int
    available_credits: int
    cycle_anchor_utc: str
    status: str
    freeze_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class CreditPack(TypedDict):
    id: str
    member_id: str
    location_id: str
    pack_credits: int
    base_unit_price_cents: int
    price_cents: int
    held_credits: int
    consumed_credits: int
    available_credits: int
    expires_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    member_id: str
    location_id: str
    service_id: str
    flexologist_id: str
    table_id: str
    series_id: Optional[str]
    rescheduled_from_booking_id: Optional[str]
    session_start_utc: str
    session_end_utc: str
    funding_source: str
    funding_id: str
    credit_cost: int
    list_price_cents: int
    schedule_status: str
    credit_status: str
    fee_charged_cents: int
    is_intro: bool
    created_at: str
    updated_at: str
    version: int


class RecurringSeries(TypedDict):
    id: str
    member_id: str
    location_id: str
    service_id: str
    flexologist_id: str
    table_id: str
    funding_source: str
    funding_id: str
    first_start_utc: str
    interval_days: int
    occurrence_count: int
    generated_count: int
    skipped_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Entity TypedDicts (common_fields: false) -----------------------------
# These append-only resources carry only id + created_at: NO updated_at, NO version.

class AddOn(TypedDict):
    id: str
    booking_id: str
    kind: str
    price_cents: int
    voided: bool
    created_at: str


class NoShowEvent(TypedDict):
    id: str
    member_id: str
    booking_id: str
    event_kind: str
    points: int
    occurred_utc: str
    created_at: str


class ClockState(TypedDict):
    id: str
    current_utc: str
    created_at: str
