"""Domain types: entity TypedDicts, status enums, role enum (PRD §3, §2.1)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class BookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    IN_SERVICE = "IN_SERVICE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_HELD = "DEPOSIT_HELD"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"
    FORFEITED = "FORFEITED"


class TechnicianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class GiftCardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"
    VOID = "VOID"


class CommissionStatementStatus(str, Enum):
    DRAFT = "DRAFT"
    SETTLED = "SETTLED"
    VOID = "VOID"


class SanitationStatus(str, Enum):
    CLEAN = "CLEAN"
    DIRTY = "DIRTY"


class PayModel(str, Enum):
    COMMISSION = "COMMISSION"
    BOOTH_RENT = "BOOTH_RENT"


class ServiceCategory(str, Enum):
    MANICURE = "MANICURE"
    PEDICURE = "PEDICURE"
    ENHANCEMENT = "ENHANCEMENT"


class CycleResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class AppointmentOrigin(str, Enum):
    WALK_IN = "WALK_IN"
    APPOINTMENT = "APPOINTMENT"


class UserRole(str, Enum):
    SALON_MANAGER = "SalonManager"
    FRONT_DESK = "FrontDesk"
    TECHNICIAN = "Technician"
    CLIENT = "Client"


# ---------------------------------------------------------------------------
# Entity TypedDicts
#   common_fields: true  -> id, created_at, updated_at, version
#   common_fields: false -> id, created_at only (SanitationLog, AppointmentAddOn)
# ---------------------------------------------------------------------------
class Technician(TypedDict):
    id: str
    full_name: str
    license_number: str
    license_expiry: str
    pay_model: str
    commission_pct: float
    booth_rent_cents: int
    home_station_id: str
    status: str
    accrued_earnings_cents: int
    lifetime_no_show_strikes_attributed: int
    created_at: str
    updated_at: str
    version: int


class Station(TypedDict):
    id: str
    name: str
    requires_autoclave: bool
    sanitation_status: str
    last_pass_sanitation_at: Optional[str]
    in_service_appointment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SanitationLog(TypedDict):
    id: str
    station_id: str
    logged_by_technician_id: str
    cycle_result: str
    cycle_temp_c: float
    hold_minutes: int
    created_at: str


class ServiceMenuItem(TypedDict):
    id: str
    name: str
    category: str
    duration_minutes: int
    base_price_cents: int
    loyalty_points_award: int
    requires_sterile_station: bool
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    name: str
    price_cents: int
    extra_minutes: int
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    full_name: str
    email: str
    loyalty_points_balance: int
    active_no_show_strikes: int
    deposit_required: bool
    last_no_show_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    client_id: str
    technician_id: str
    station_id: str
    service_item_id: str
    origin: str
    start_at: str
    end_at: str
    booking_status: str
    payment_status: str
    deposit_due_cents: int
    deposit_paid_cents: int
    subtotal_cents: int
    loyalty_points_redeemed: int
    gift_card_id: Optional[str]
    total_charged_cents: int
    technician_earning_cents: int
    no_show_strike_charged: bool
    created_at: str
    updated_at: str
    version: int


class AppointmentAddOn(TypedDict):
    id: str
    appointment_id: str
    add_on_id: str
    price_cents_snapshot: int
    extra_minutes_snapshot: int
    created_at: str


class GiftCard(TypedDict):
    id: str
    code: str
    initial_balance_cents: int
    balance_cents: int
    purchaser_client_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CommissionStatement(TypedDict):
    id: str
    technician_id: str
    period_start: str
    period_end: str
    gross_service_cents: int
    technician_payout_cents: int
    salon_retained_cents: int
    swept_appointment_count: int
    status: str
    created_at: str
    updated_at: str
    version: int
