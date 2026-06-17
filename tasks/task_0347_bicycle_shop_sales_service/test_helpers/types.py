"""Domain types: entity TypedDicts, status enums, role enum (PRD §3).

Entities carrying the full id/created_at/updated_at/version set (PRD §2.4) are
modelled with those four system fields. The four ledger-style records that PRD
§2.4 declares carry only `id` and `created_at` — RecallNotice, RecallAck, and
Payment — omit `updated_at` and `version`.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum (PRD §2.1) ───────────────────────────────────────────────────
class UserRole(str, Enum):
    SALES_ASSOCIATE = "SalesAssociate"
    SERVICE_ADVISOR = "ServiceAdvisor"
    SHOP_MANAGER = "ShopManager"
    CUSTOMER = "Customer"


# ─── Status enums (PRD §3) ──────────────────────────────────────────────────
class SkuCategory(str, Enum):
    BIKE = "BIKE"
    PART = "PART"
    ACCESSORY = "ACCESSORY"


class WarrantyClass(str, Enum):
    NONE = "NONE"
    COMPONENT = "COMPONENT"
    FRAME_AND_COMPONENT = "FRAME_AND_COMPONENT"


class TuneUpTierCode(str, Enum):
    BASIC = "BASIC"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class ServiceTicketStatus(str, Enum):
    INTAKE = "INTAKE"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    IN_PROGRESS = "IN_PROGRESS"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class BayBookingStatus(str, Enum):
    BOOKED = "BOOKED"
    RELEASED = "RELEASED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    PENDING = "PENDING"
    RESERVED = "RESERVED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ReservationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


class ReservationHolderType(str, Enum):
    SALES_ORDER = "SALES_ORDER"
    BUILD_JOB = "BUILD_JOB"
    LAYAWAY_PLAN = "LAYAWAY_PLAN"
    SPECIAL_ORDER = "SPECIAL_ORDER"


class LayawayPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FORFEITED = "FORFEITED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class SpecialOrderStatus(str, Enum):
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    ARRIVED = "ARRIVED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class BuildJobStatus(str, Enum):
    DRAFT = "DRAFT"
    PARTS_RESERVED = "PARTS_RESERVED"
    ASSEMBLING = "ASSEMBLING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class WarrantyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED_REPAIR = "APPROVED_REPAIR"
    APPROVED_REPLACE = "APPROVED_REPLACE"
    DENIED = "DENIED"
    RESOLVED = "RESOLVED"


class WarrantyDefectPart(str, Enum):
    FRAME = "FRAME"
    COMPONENT = "COMPONENT"


class WarrantyResolution(str, Enum):
    REPAIR = "REPAIR"
    REPLACE = "REPLACE"


class TradeInGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class TradeInApplyTo(str, Enum):
    STORE_CREDIT = "STORE_CREDIT"
    CASH = "CASH"


class TradeInStatus(str, Enum):
    APPRAISED = "APPRAISED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class RecallSeverity(str, Enum):
    ADVISORY = "ADVISORY"
    MANDATORY = "MANDATORY"


class PaymentTargetType(str, Enum):
    SALES_ORDER = "SALES_ORDER"
    LAYAWAY_PLAN = "LAYAWAY_PLAN"
    SPECIAL_ORDER = "SPECIAL_ORDER"


class PaymentLedgerStatus(str, Enum):
    CAPTURED = "CAPTURED"
    VOIDED = "VOIDED"


# ─── Entity TypedDicts — full system-field set (PRD §2.4) ────────────────────
class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    store_credit_cents: int
    open_recall_count: int
    created_at: str
    updated_at: str
    version: int


class Sku(TypedDict):
    id: str
    name: str
    category: str
    list_price_cents: int
    on_hand: int
    reserved: int
    warranty_class: str
    is_serialized: bool
    created_at: str
    updated_at: str
    version: int


class TuneUpTier(TypedDict):
    id: str
    code: str
    base_labor_cents: int
    turnaround_hours: int
    rush_multiplier_bps: int
    created_at: str
    updated_at: str
    version: int


class ServiceBay(TypedDict):
    id: str
    name: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class BayBooking(TypedDict):
    id: str
    bay_id: str
    ticket_id: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceTicket(TypedDict):
    id: str
    customer_id: str
    tier_id: str
    warranty_claim_id: Optional[str]
    status: str
    is_rush: bool
    promised_ready_at: Optional[str]
    labor_subtotal_cents: int
    revision_count: int
    customer_owes_cents: int
    created_at: str
    updated_at: str
    version: int


class LaborLine(TypedDict):
    id: str
    ticket_id: str
    menu_code: str
    labor_cents: int
    added_after_approval: bool
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict):
    id: str
    customer_id: str
    payment_status: str
    fulfillment_status: str
    subtotal_cents: int
    store_credit_applied_cents: int
    total_due_cents: int
    amount_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    sku_id: str
    qty: int
    unit_price_cents: int
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    sku_id: str
    holder_type: str
    holder_id: str
    qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LayawayPlan(TypedDict):
    id: str
    customer_id: str
    sku_id: str
    qty: int
    price_cents: int
    deposit_cents: int
    status: str
    forfeit_fee_cents: int
    refund_cents: int
    created_at: str
    updated_at: str
    version: int


class SpecialOrder(TypedDict):
    id: str
    customer_id: str
    sku_id: str
    qty: int
    deposit_required_cents: int
    deposit_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BuildJob(TypedDict):
    id: str
    customer_id: str
    frame_sku_id: str
    required_part_count: int
    reserved_part_count: int
    status: str
    build_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    customer_id: str
    sku_id: str
    source_order_line_id: str
    defect_part: str
    status: str
    resolution_sku_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TradeIn(TypedDict):
    id: str
    customer_id: str
    description: str
    condition_grade: str
    appraised_value_cents: int
    offer_cents: int
    apply_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Ledger-style records — id + created_at only (PRD §2.4) ──────────────────
class RecallNotice(TypedDict):
    id: str
    sku_id: str
    severity: str
    remedy: str
    created_at: str


class RecallAck(TypedDict):
    id: str
    recall_id: str
    customer_id: str
    created_at: str


class Payment(TypedDict):
    id: str
    target_type: str
    target_id: str
    amount_cents: int
    status: str
    created_at: str
