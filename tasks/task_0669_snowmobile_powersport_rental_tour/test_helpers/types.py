"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status / enum value sets ──────────────────────────────────────────

class WaiverStatus(str, Enum):
    UNSIGNED = "UNSIGNED"
    SIGNED = "SIGNED"
    EXPIRED = "EXPIRED"


class TrainingLevel(str, Enum):
    NONE = "NONE"
    BASIC = "BASIC"
    ADVANCED = "ADVANCED"


class MembershipTier(str, Enum):
    NONE = "NONE"
    SEASON = "SEASON"
    PREMIER = "PREMIER"


class GuideStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OFF_DUTY = "OFF_DUTY"


class TrailCondition(str, Enum):
    OPEN = "OPEN"
    CAUTION = "CAUTION"
    CLOSED = "CLOSED"


class UnitClass(str, Enum):
    TRAIL = "TRAIL"
    UTILITY = "UTILITY"
    MOUNTAIN = "MOUNTAIN"


class UnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    OUT = "OUT"
    MAINTENANCE = "MAINTENANCE"


class GearKind(str, Enum):
    HELMET = "HELMET"
    SUIT = "SUIT"


class GearStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    OUT = "OUT"
    RETIRED = "RETIRED"


class DepartureStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LOCKED = "LOCKED"
    DEPARTED = "DEPARTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReservationStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CHECKED_OUT = "CHECKED_OUT"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class SettlementStatus(str, Enum):
    NONE = "NONE"
    HELD = "HELD"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"


class UserRole(str, Enum):
    Anonymous = "Anonymous"
    Member = "Member"
    Guide = "Guide"
    DispatchOperator = "DispatchOperator"
    PlatformAdmin = "PlatformAdmin"


# ─── Entity TypedDicts ─────────────────────────────────────────────────
# Full first-class records carry id + created_at + updated_at + version.
# GuideAssignment and ClosureEvent are lightweight audit records: only
# id + created_at (no updated_at, no version).

class Member(TypedDict):
    id: str
    full_name: str
    email: str
    date_of_birth: str
    membership_tier: str
    membership_expires_at: Optional[str]
    waiver_status: str
    waiver_signed_at: Optional[str]
    training_level: str
    deposit_hold_cents: int
    lifetime_damage_strikes: int
    created_at: str
    updated_at: str
    version: int


class Guide(TypedDict):
    id: str
    full_name: str
    max_class: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Trail(TypedDict):
    id: str
    name: str
    required_class: str
    max_riders: int
    condition: str
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict):
    id: str
    vin_tag: str
    unit_class: str
    daily_rate_cents: int
    deposit_cents: int
    tank_capacity_liters: float
    status: str
    created_at: str
    updated_at: str
    version: int


class GearItem(TypedDict):
    id: str
    kind: str
    size_code: str
    replacement_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TourDeparture(TypedDict):
    id: str
    trail_id: str
    starts_at: str
    ends_at: str
    required_guide_class: str
    capacity_riders: int
    rider_count: int
    guide_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GuideAssignment(TypedDict):
    id: str
    tour_departure_id: str
    guide_id: str
    active: bool
    created_at: str


class Reservation(TypedDict):
    id: str
    member_id: str
    tour_departure_id: str
    unit_id: str
    helmet_gear_id: Optional[str]
    suit_gear_id: Optional[str]
    reservation_status: str
    settlement_status: str
    estimated_total_cents: int
    deposit_hold_cents: int
    checked_out_at: Optional[str]
    returned_at: Optional[str]
    fuel_return_fraction: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    reservation_id: str
    rental_charge_cents: int
    fuel_charge_cents: int
    late_charge_cents: int
    damage_assessed_cents: int
    gear_loss_cents: int
    deposit_applied_cents: int
    refund_cents: int
    net_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class ClosureEvent(TypedDict):
    id: str
    trail_id: str
    new_condition: str
    reason: str
    cancelled_departure_count: int
    created_at: str
