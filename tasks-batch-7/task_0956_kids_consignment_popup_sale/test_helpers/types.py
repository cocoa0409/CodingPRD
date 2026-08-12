"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class SaleEventPhase(str, Enum):
    DRAFT = "DRAFT"
    INTAKE_OPEN = "INTAKE_OPEN"
    INTAKE_CLOSED = "INTAKE_CLOSED"
    PRESALE_DAY = "PRESALE_DAY"
    SALE_ACTIVE = "SALE_ACTIVE"
    SETTLEMENT = "SETTLEMENT"
    CLOSED = "CLOSED"


class ConsignorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class BookingStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class ItemStatus(str, Enum):
    TAGGED = "TAGGED"
    DROPPED_OFF = "DROPPED_OFF"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    ON_FLOOR = "ON_FLOOR"
    IN_CART = "IN_CART"
    SOLD = "SOLD"
    UNSOLD = "UNSOLD"
    PICKED_UP = "PICKED_UP"
    DONATED = "DONATED"


class ItemCategory(str, Enum):
    CLOTHING = "CLOTHING"
    TOYS = "TOYS"
    BOOKS = "BOOKS"
    GEAR = "GEAR"
    MATERNITY = "MATERNITY"
    OTHER = "OTHER"


class InspectionOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class SignupStatus(str, Enum):
    SIGNED_UP = "SIGNED_UP"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class HolderType(str, Enum):
    CONSIGNOR = "CONSIGNOR"
    VOLUNTEER = "VOLUNTEER"


class PassStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class TransactionStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    EVENT_ORGANIZER = "EventOrganizer"
    CONSIGNOR = "Consignor"
    VOLUNTEER = "Volunteer"
    INSPECTOR = "Inspector"
    CASHIER = "Cashier"


# --- Entity TypedDicts (PRD §2.4: primary entities carry id, created_at,
# updated_at, version; InspectionRecord and TransactionLine carry only
# id and created_at) ---


class SaleEvent(TypedDict):
    id: str
    name: str
    intake_start: str
    intake_end: str
    presale_start: str
    presale_end: str
    sale_start: str
    sale_end: str
    pickup_deadline: str
    phase: str
    sold_gross_cents: int
    created_at: str
    updated_at: str
    version: int


class MarkdownRule(TypedDict):
    id: str
    sale_event_id: str
    effective_from: str
    effective_to: str
    discount_pct: int
    created_at: str
    updated_at: str
    version: int


class Consignor(TypedDict):
    id: str
    sale_event_id: str
    full_name: str
    email: str
    consignor_code: str
    status: str
    sold_count: int
    unsold_count: int
    rejected_count: int
    sold_gross_cents: int
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict):
    id: str
    sale_event_id: str
    full_name: str
    email: str
    linked_consignor_id: Optional[str]
    completed_hours: float
    projected_hours: float
    projected_discount_pct: int
    created_at: str
    updated_at: str
    version: int


class DropOffSlot(TypedDict):
    id: str
    sale_event_id: str
    start_time: str
    end_time: str
    capacity: int
    booked_count: int
    created_at: str
    updated_at: str
    version: int


class DropOffBooking(TypedDict):
    id: str
    slot_id: str
    consignor_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Item(TypedDict):
    id: str
    consignor_id: str
    sale_event_id: str
    title: str
    category: str
    size: Optional[str]
    price_cents: int
    discount_eligible: bool
    donate_flag: bool
    barcode: str
    status: str
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only audit row, carries ONLY id + created_at
class InspectionRecord(TypedDict):
    id: str
    item_id: str
    inspector_id: str
    outcome: str
    reasons: Optional[str]
    created_at: str


class VolunteerShift(TypedDict):
    id: str
    sale_event_id: str
    role_name: str
    start_time: str
    end_time: str
    capacity: int
    signed_up_count: int
    created_at: str
    updated_at: str
    version: int


class ShiftSignup(TypedDict):
    id: str
    shift_id: str
    volunteer_id: str
    status: str
    hours_credited: float
    created_at: str
    updated_at: str
    version: int


class PresalePass(TypedDict):
    id: str
    sale_event_id: str
    holder_type: str
    holder_id: str
    discount_pct: int
    status: str
    created_at: str
    updated_at: str
    version: int


class POSTransaction(TypedDict):
    id: str
    sale_event_id: str
    cashier_id: str
    presale_pass_id: Optional[str]
    pass_discount_pct: int
    status: str
    subtotal_cents: int
    discount_cents: int
    total_cents: int
    tendered_cents: Optional[int]
    change_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — audit-light line row, carries ONLY id + created_at
class TransactionLine(TypedDict):
    id: str
    transaction_id: str
    item_id: str
    barcode: str
    tag_price_cents: int
    markdown_pct_applied: int
    line_price_cents: int
    pass_discount_pct_applied: int
    final_line_cents: int
    created_at: str


class Settlement(TypedDict):
    id: str
    sale_event_id: str
    consignor_id: str
    status: str
    provisional_gross_cents: int
    provisional_payout_cents: int
    sold_item_count: int
    gross_cents: Optional[int]
    split_pct: Optional[int]
    commission_cents: Optional[int]
    payout_before_fee_cents: Optional[int]
    supply_fee_cents: Optional[int]
    rejected_fee_cents: Optional[int]
    adjustment_cents: int
    payout_cents: Optional[int]
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
