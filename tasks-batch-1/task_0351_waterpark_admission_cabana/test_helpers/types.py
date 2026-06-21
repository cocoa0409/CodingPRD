"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Waterpark Admission & Cabana PRD (§3 entity narratives,
§2.4 common resource properties).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles (PRD §2.1) ---
class UserRole(str, Enum):
    GUEST = "Guest"
    GATE_AGENT = "GateAgent"
    PARK_MANAGER = "ParkManager"
    FINANCE_CLERK = "FinanceClerk"


# --- Status enums ---
class WeatherStatus(str, Enum):
    CLEAR = "CLEAR"
    STORM_WATCH = "STORM_WATCH"
    RAINED_OUT = "RAINED_OUT"


class ProductType(str, Enum):
    DAY_TICKET = "DAY_TICKET"
    SEASON_PASS = "SEASON_PASS"


class EntryWindowStatus(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"
    RAINED_OUT = "RAINED_OUT"


class CabanaTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    CABANA_SUITE = "CABANA_SUITE"


class OrderPaymentStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    VOID = "VOID"
    REFUNDED = "REFUNDED"


class OrderFulfillmentStatus(str, Enum):
    UNFULFILLED = "UNFULFILLED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class AdmissionStatus(str, Enum):
    ISSUED = "ISSUED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    FROZEN = "FROZEN"
    RAINED_OUT = "RAINED_OUT"
    CANCELLED = "CANCELLED"


class BandColor(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class CabanaRentalStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    RAINED_OUT = "RAINED_OUT"


class RainCheckStatus(str, Enum):
    ISSUED = "ISSUED"
    SETTLED = "SETTLED"
    EXPIRED = "EXPIRED"


class RainCheckSourceKind(str, Enum):
    ADMISSION = "ADMISSION"
    CABANA_RENTAL = "CABANA_RENTAL"


# --- Entity TypedDicts (common_fields: true → id/created_at/updated_at/version) ---
class Park(TypedDict):
    id: str
    name: str
    timezone: str
    total_gate_capacity: int
    weather_status: str
    resident_zip_prefixes: List[str]
    open_window_count: int
    rain_check_value_cents: int
    created_at: str
    updated_at: str
    version: int


class PricingPolicy(TypedDict):
    id: str
    park_id: str
    product_type: str
    base_price_cents: int
    resident_discount_pct: float
    group_threshold: int
    group_discount_pct: float
    combo_price_cents: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class EntryWindow(TypedDict):
    id: str
    park_id: str
    starts_at: str
    ends_at: str
    window_capacity: int
    reserved_count: int
    admitted_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Cabana(TypedDict):
    id: str
    park_id: str
    label: str
    tier: str
    daily_rate_cents: int
    turnover_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class Locker(TypedDict):
    id: str
    park_id: str
    bank_code: str
    hourly_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class Guest(TypedDict):
    id: str
    full_name: str
    email: str
    zip_code: str
    height_cm: int
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    park_id: str
    guest_id: str
    product_type: str
    party_size: int
    food_beverage_combo: bool
    resident_rate_applied: bool
    group_rate_applied: bool
    subtotal_cents: int
    total_cents: int
    wallet_credit_used_cents: int
    payment_status: str
    fulfillment_status: str
    created_at: str
    updated_at: str
    version: int


class Admission(TypedDict):
    id: str
    order_id: str
    park_id: str
    guest_id: Optional[str]
    entry_window_id: Optional[str]
    product_type: str
    ticket_price_cents: int
    status: str
    freeze_days_used: int
    frozen_at: Optional[str]
    band_color: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CabanaRental(TypedDict):
    id: str
    cabana_id: str
    order_id: str
    park_id: str
    entry_window_id: str
    starts_at: str
    ends_at: str
    price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RainCheck(TypedDict):
    id: str
    park_id: str
    guest_id: str
    source_kind: str
    source_ref_id: str
    value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Lean entities (common_fields: false → only id + created_at) ---
class LockerRental(TypedDict):
    id: str
    locker_id: str
    order_id: str
    starts_at: str
    ends_at: str
    hours_billed: int
    price_cents: int
    created_at: str


class ClockState(TypedDict):
    id: str
    current_utc: str
    created_at: str
