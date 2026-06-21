"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the Campground & RV Park Reservation API resource model. Entities that
carry the standard system-managed field set expose id/created_at/updated_at/version;
the append-only Payment ledger row carries only id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles ------------------------------------------------------------------
class UserRole(str, Enum):
    OPERATOR = "Operator"
    GUEST = "Guest"


# --- Enums ------------------------------------------------------------------
class SiteType(str, Enum):
    TENT = "TENT"
    RV = "RV"
    CABIN = "CABIN"


class HookupLevel(str, Enum):
    NONE = "NONE"
    PARTIAL = "PARTIAL"
    FULL = "FULL"


class SiteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class MaintenanceHoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLEARED = "CLEARED"


class ReservationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"
    REFUNDED = "REFUNDED"


class StayClass(str, Enum):
    SHORT_TERM = "SHORT_TERM"
    LONG_TERM = "LONG_TERM"


class AddOnKind(str, Enum):
    FIREWOOD = "FIREWOOD"
    EXTRA_VEHICLE = "EXTRA_VEHICLE"
    PET_FEE = "PET_FEE"
    EARLY_CHECKIN = "EARLY_CHECKIN"


class AddOnStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class PaymentType(str, Enum):
    DEPOSIT = "DEPOSIT"
    BALANCE = "BALANCE"
    REFUND = "REFUND"


# --- Entity TypedDicts (common_fields: true) --------------------------------
class Park(TypedDict):
    id: str
    name: str
    timezone: str
    check_in_time: str
    check_out_time: str
    quiet_hours_start: str
    quiet_hours_end: str
    deposit_pct: float
    tax_rate: float
    long_stay_nights_threshold: int
    created_at: str
    updated_at: str
    version: int


class RatePlan(TypedDict):
    id: str
    park_id: str
    site_type: str
    nightly_rate_cents: int
    weekly_rate_cents: int
    monthly_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class Season(TypedDict):
    id: str
    park_id: str
    name: str
    start_date: str
    end_date: str
    surcharge_pct: float
    created_at: str
    updated_at: str
    version: int


class CancellationPolicy(TypedDict):
    id: str
    park_id: str
    full_refund_min_days: int
    half_refund_min_days: int
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict):
    id: str
    park_id: str
    rate_plan_id: str
    label: str
    site_type: str
    hookup_level: str
    max_length_of_stay_nights: int
    turnover_buffer_days: int
    status: str
    booked_night_count: int
    created_at: str
    updated_at: str
    version: int


class MaintenanceHold(TypedDict):
    id: str
    site_id: str
    start_date: str
    end_date: str
    reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Guest(TypedDict):
    id: str
    email: str
    full_name: str
    completed_stays_count: int
    lifetime_spend_cents: int
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    site_id: str
    guest_id: str
    check_in_date: str
    check_out_date: str
    nights: int
    actual_check_out_date: Optional[str]
    stay_class: str
    reservation_status: str
    payment_status: str
    stay_charge_cents: int
    season_surcharge_cents: int
    addon_total_cents: int
    discount_cents: int
    tax_cents: int
    total_due_cents: int
    deposit_due_cents: int
    amount_paid_cents: int
    balance_cents: int
    priced_nights: int
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    reservation_id: str
    kind: str
    amount_cents: int
    taxable: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only ledger row (common_fields: false) --------------------------
class Payment(TypedDict):
    id: str
    reservation_id: str
    type: str
    amount_cents: int
    reason: Optional[str]
    created_at: str
    # No updated_at, no version: immutable ledger entry.
