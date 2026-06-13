"""Domain types: entity TypedDicts, status enums, role enum (Bridal Gown Shop API)."""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status enums ──────────────────────────────────────────────────────────

class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class BookingStatus(str, Enum):
    HELD = "HELD"
    RELEASED = "RELEASED"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    ORDERED = "ORDERED"
    RECEIVED = "RECEIVED"
    READY = "READY"
    PICKED_UP = "PICKED_UP"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"
    REFUNDED = "REFUNDED"


class AccessoryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class AlterationStatus(str, Enum):
    QUEUED = "QUEUED"
    FITTING = "FITTING"
    ADJUSTING = "ADJUSTING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CoordinationStatus(str, Enum):
    FORMING = "FORMING"
    LOCKED = "LOCKED"


class PlanStatus(str, Enum):
    DEPOSIT_DUE = "DEPOSIT_DUE"
    ACTIVE = "ACTIVE"
    PAID_IN_FULL = "PAID_IN_FULL"
    CANCELLED = "CANCELLED"


class AccessoryType(str, Enum):
    VEIL = "VEIL"
    TIARA = "TIARA"
    SASH = "SASH"
    SHOES = "SHOES"


class AppointmentType(str, Enum):
    CONSULTATION = "CONSULTATION"
    FITTING = "FITTING"


class PaymentKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    INSTALLMENT = "INSTALLMENT"
    REFUND = "REFUND"


class SettlementStatus(str, Enum):
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class UserRole(str, Enum):
    SHOP_MANAGER = "ShopManager"
    BRIDAL_CONSULTANT = "BridalConsultant"
    SEAMSTRESS = "Seamstress"
    FINANCE_CLERK = "FinanceClerk"


# ─── Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ──

class Stylist(TypedDict):
    id: str
    full_name: str
    turnaround_buffer_minutes: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class FittingRoom(TypedDict):
    id: str
    room_label: str
    capacity: int
    out_of_service: bool
    created_at: str
    updated_at: str
    version: int


class BridalParty(TypedDict):
    id: str
    party_name: str
    event_date: str
    lead_gown_order_id: Optional[str]
    coordination_status: str
    member_order_count: int
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    stylist_id: str
    bridal_party_id: Optional[str]
    appointment_type: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FittingRoomBooking(TypedDict):
    id: str
    appointment_id: str
    fitting_room_id: str
    party_size: int
    slot_start_at: str
    slot_end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GownOrder(TypedDict):
    id: str
    bridal_party_id: Optional[str]
    origin_appointment_id: Optional[str]
    gown_style_code: str
    ordered_size: int
    base_price_cents: int
    standard_lead_days: int
    is_rush: bool
    quoted_total_cents: int
    final_total_cents: Optional[int]
    required_by_date: Optional[str]
    fulfillment_status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class AccessoryAddOn(TypedDict):
    id: str
    gown_order_id: str
    accessory_type: str
    price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AlterationJob(TypedDict):
    id: str
    gown_order_id: str
    fitting_room_id: Optional[str]
    estimated_labor_minutes: int
    actual_labor_minutes: int
    refitting_count: int
    estimated_cost_cents: int
    final_cost_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentPlan(TypedDict):
    id: str
    gown_order_id: str
    plan_total_cents: int
    term_installments: int
    deposit_cents: int
    installment_cents: int
    amount_paid_cents: int
    balance_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — Payment is an immutable ledger record (id + created_at only)
class Payment(TypedDict):
    id: str
    payment_plan_id: str
    amount_cents: int
    kind: str
    settlement_status: str
    created_at: str
