"""Domain types: entity TypedDicts, status enums, and the role enum.

Derived entirely from the PRD contract. Entities exempt from the standard
id/created_at/updated_at/version quartet (the append-only WeatherEvent) carry
only id + created_at, per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Status enums -----------------------------------------------------------

class FarmStatus(str, Enum):
    OPEN = "OPEN"
    WEATHER_HOLD = "WEATHER_HOLD"
    CLOSED = "CLOSED"


class PricingPolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class AdmissionWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SOLD_OUT = "SOLD_OUT"
    CANCELLED = "CANCELLED"


class SeasonPassStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ReservationStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class ActivityPassStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class ActivityKind(str, Enum):
    HAYRIDE = "HAYRIDE"
    MAZE = "MAZE"
    UPICK = "UPICK"


class WaiverStatus(str, Enum):
    SIGNED = "SIGNED"
    VOID = "VOID"


class PumpkinPurchaseStatus(str, Enum):
    ESTIMATED = "ESTIMATED"
    WEIGHED = "WEIGHED"
    VOID = "VOID"


class ConcessionOrderStatus(str, Enum):
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class WeatherKind(str, Enum):
    HOLD = "HOLD"
    CLEARED = "CLEARED"
    CLOSURE = "CLOSURE"


class GroupKind(str, Enum):
    FIELD_TRIP = "FIELD_TRIP"
    SCHOOL = "SCHOOL"
    CORPORATE = "CORPORATE"


class GroupBookingStatus(str, Enum):
    QUOTED = "QUOTED"
    REVISING = "REVISING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    FARM_MANAGER = "FarmManager"
    VISITOR = "Visitor"
    GROUP_LEADER = "GroupLeader"
    GATE_AGENT = "GateAgent"


# --- Entity TypedDicts ------------------------------------------------------

class Farm(TypedDict):
    id: str
    name: str
    timezone: str
    parking_fee_cents: int
    window_buffer_minutes: int
    operational_status: str
    active_weather_event_id: Optional[str]
    refunds_issued_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only log; carries ONLY id + created_at.
class WeatherEvent(TypedDict):
    id: str
    farm_id: str
    kind: str
    affected_span_start: Optional[str]
    affected_span_end: Optional[str]
    note: Optional[str]
    resulting_status: str
    created_at: str


class PricingPolicy(TypedDict):
    id: str
    farm_id: str
    adult_admission_cents: int
    child_admission_cents: int
    hayride_pass_cents: int
    maze_pass_cents: int
    upick_pass_cents: int
    pumpkin_per_lb_cents: int
    pumpkin_flat_each_cents: int
    heavy_pumpkin_lb: float
    group_rate_min_headcount: int
    group_discount_pct: float
    school_discount_pct: float
    season_pass_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AdmissionWindow(TypedDict):
    id: str
    farm_id: str
    starts_at: str
    ends_at: str
    capacity: int
    seats_held: int
    seats_committed: int
    seats_available: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Visitor(TypedDict):
    id: str
    email: str
    full_name: str
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class SeasonPass(TypedDict):
    id: str
    farm_id: str
    visitor_id: str
    purchase_price_cents: int
    valid_from: str
    valid_until: str
    status: str
    visits_used: int
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    window_id: str
    visitor_id: str
    season_pass_id: Optional[str]
    group_booking_id: Optional[str]
    adult_count: int
    child_count: int
    participant_count: int
    admission_charge_cents: int
    settled_charge_cents: int
    expected_window_version: int
    status: str
    checkout_finalized: bool
    waiver_satisfied: bool
    gross_cents: int
    net_due_cents: int
    created_at: str
    updated_at: str
    version: int


class ActivityPass(TypedDict):
    id: str
    reservation_id: str
    activity: str
    quantity: int
    unit_price_cents: int
    line_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Waiver(TypedDict):
    id: str
    reservation_id: str
    participant_name: str
    is_minor: bool
    guardian_name: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PumpkinPurchase(TypedDict):
    id: str
    reservation_id: str
    estimated_weight_lb: float
    scale_weight_lb: Optional[float]
    charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ConcessionOrder(TypedDict):
    id: str
    reservation_id: str
    food_cents: int
    vehicle_count: int
    parking_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GroupBooking(TypedDict):
    id: str
    farm_id: str
    window_id: str
    group_leader_id: str
    parent_group_id: Optional[str]
    kind: str
    adult_count: int
    child_count: int
    headcount: int
    quoted_total_cents: int
    deposit_cents: int
    expected_window_version: int
    status: str
    created_at: str
    updated_at: str
    version: int
