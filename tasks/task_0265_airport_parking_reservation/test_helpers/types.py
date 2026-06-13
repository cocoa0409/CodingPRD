"""Domain types: entity TypedDicts, status enums, role enum.

All names and fields follow the Airport Parking Reservation API PRD exactly.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Roles ───────────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    LOT_OPERATOR = "LotOperator"
    FACILITY_ADMIN = "FacilityAdmin"


# ─── Status enums ────────────────────────────────────────────────────────────
class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class VehicleSizeClass(str, Enum):
    STANDARD = "STANDARD"
    OVERSIZED = "OVERSIZED"


class LotKind(str, Enum):
    SURFACE_LOT = "SURFACE_LOT"
    GARAGE = "GARAGE"
    VALET_GARAGE = "VALET_GARAGE"


class RateMode(str, Enum):
    DAILY = "DAILY"
    HOURLY = "HOURLY"
    VALET = "VALET"


class StallClass(str, Enum):
    STANDARD = "STANDARD"
    OVERSIZED = "OVERSIZED"
    EV = "EV"


class OccupancyStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    OUT_TEMP = "OUT_TEMP"
    CHECKED_OUT = "CHECKED_OUT"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class SettlementStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    AUTHORIZED = "AUTHORIZED"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"


class StallHoldStatus(str, Enum):
    HELD = "HELD"
    OCCUPIED = "OCCUPIED"
    RELEASED = "RELEASED"


class ShuttleTripStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    BOARDING = "BOARDING"
    DEPARTED = "DEPARTED"
    CANCELLED = "CANCELLED"


class PaymentTxnKind(str, Enum):
    AUTHORIZATION = "AUTHORIZATION"
    CAPTURE = "CAPTURE"
    REFUND = "REFUND"
    FEE_RETAIN = "FEE_RETAIN"


# ─── Entity TypedDicts (common_fields: true → id, created_at, updated_at, version) ─
class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    no_show_strikes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    customer_id: str
    plate: str
    size_class: str
    is_ev: bool
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict):
    id: str
    name: str
    kind: str
    standard_capacity: int
    oversized_capacity: int
    ev_capacity: int
    available_standard_count: int
    available_oversized_count: int
    available_ev_count: int
    in_out_allowed: bool
    created_at: str
    updated_at: str
    version: int


class RatePlan(TypedDict):
    id: str
    lot_id: str
    rate_mode: str
    hourly_cents: int
    daily_cap_cents: int
    valet_surcharge_cents: int
    oversized_multiplier_bps: int
    ev_surcharge_cents_per_day: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class CancellationPolicy(TypedDict):
    id: str
    lot_id: str
    free_cancel_hours: int
    late_cancel_fee_bps: int
    prepay_discount_bps: int
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    customer_id: str
    lot_id: str
    vehicle_id: str
    rate_plan_id: str
    shuttle_trip_id: Optional[str]
    stall_class: str
    scheduled_start: str
    scheduled_end: str
    actual_in: Optional[str]
    actual_out: Optional[str]
    prepaid: bool
    occupancy_status: str
    settlement_status: str
    rate_snapshot: dict
    provisional_quote_cents: int
    final_charge_cents: Optional[int]
    overstay_cents: int
    created_at: str
    updated_at: str
    version: int


class StallHold(TypedDict):
    id: str
    lot_id: str
    reservation_id: str
    stall_class: str
    hold_start: str
    hold_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ShuttleTrip(TypedDict):
    id: str
    lot_id: str
    depart_at: str
    seat_capacity: int
    seats_taken: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — PaymentTxn is immutable: only id + created_at, NO updated_at/version
class PaymentTxn(TypedDict):
    id: str
    reservation_id: str
    kind: str
    amount_cents: int
    note: str
    created_at: str
