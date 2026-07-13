"""Domain types: entity TypedDicts, status enums, role enum for the Event Ticketing API."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Roles ────────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    BUYER = "Buyer"
    BOX_OFFICE = "BoxOffice"
    PROMOTER = "Promoter"
    GATE_SCANNER = "GateScanner"


# ─── Status enums ─────────────────────────────────────────────────────────
class EventStatus(str, Enum):
    DRAFT = "DRAFT"
    ANNOUNCED = "ANNOUNCED"
    PRESALE = "PRESALE"
    ONSALE = "ONSALE"
    POSTPONED = "POSTPONED"
    CANCELED = "CANCELED"
    COMPLETED = "COMPLETED"


class SeatStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    HELD = "HELD"
    SOLD = "SOLD"


class QueueTokenStatus(str, Enum):
    WAITING = "WAITING"
    ADMITTED = "ADMITTED"
    EXPIRED = "EXPIRED"


class HoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONVERTED = "CONVERTED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"
    CANCELED = "CANCELED"


class TicketStatus(str, Enum):
    VALID = "VALID"
    REFUNDED = "REFUNDED"
    VOID = "VOID"


class TicketDeliveryStatus(str, Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"


class TicketScanStatus(str, Enum):
    UNSCANNED = "UNSCANNED"
    SCANNED = "SCANNED"


class DeliveryMethod(str, Enum):
    MOBILE = "MOBILE"
    PRINT = "PRINT"
    WILL_CALL = "WILL_CALL"


class TransferKind(str, Enum):
    GIFT = "GIFT"
    RESALE = "RESALE"


class TransferStatus(str, Enum):
    INITIATED = "INITIATED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class RefundReason(str, Enum):
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"
    POSTPONEMENT = "POSTPONEMENT"
    EVENT_CANCELED = "EVENT_CANCELED"


class RefundDestination(str, Enum):
    ORIGINAL = "ORIGINAL"
    CREDIT = "CREDIT"


class RefundStatus(str, Enum):
    REQUESTED = "REQUESTED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


class SettlementStatus(str, Enum):
    PENDING = "PENDING"
    FINALIZED = "FINALIZED"


# ─── Entity TypedDicts (all carry id/created_at/updated_at/version) ────────
class Buyer(TypedDict):
    id: str
    name: str
    email: str
    credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Event(TypedDict):
    id: str
    promoter_id: str
    name: str
    venue_name: str
    event_datetime: str
    hold_ttl_minutes: int
    purchase_window_minutes: int
    presale_code: Optional[str]
    presale_max_uses: int
    status: str
    total_capacity: int
    seats_available: int
    seats_held: int
    seats_sold: int
    pct_sold: float
    presale_uses_count: int
    created_at: str
    updated_at: str
    version: int


class PriceLevel(TypedDict):
    id: str
    event_id: str
    name: str
    base_face_value_cents: int
    is_platinum: bool
    service_fee_pct: float
    service_fee_flat_cents: int
    dynamic_pricing_enabled: bool
    created_at: str
    updated_at: str
    version: int


class Seat(TypedDict):
    id: str
    event_id: str
    price_level_id: str
    section: str
    row: str
    seat_number: str
    status: str
    current_face_value_cents: int
    created_at: str
    updated_at: str
    version: int


class QueueToken(TypedDict):
    id: str
    event_id: str
    buyer_id: str
    position: int
    status: str
    admitted_at: Optional[str]
    purchase_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Hold(TypedDict):
    id: str
    event_id: str
    buyer_id: str
    seat_ids: List[str]
    presale_code: Optional[str]
    status: str
    face_subtotal_cents: int
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    event_id: str
    buyer_id: str
    hold_id: str
    delivery_method: str
    status: str
    face_total_cents: int
    service_fee_cents: int
    order_total_cents: int
    paid_amount_cents: int
    refunded_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Ticket(TypedDict):
    id: str
    order_id: str
    seat_id: str
    holder_buyer_id: str
    face_value_cents: int
    delivery_method: str
    status: str
    delivery_status: str
    scan_status: str
    created_at: str
    updated_at: str
    version: int


class TicketTransfer(TypedDict):
    id: str
    ticket_id: str
    from_buyer_id: str
    to_buyer_id: str
    kind: str
    list_price_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RefundRequest(TypedDict):
    id: str
    order_id: str
    reason: str
    refund_destination: str
    ticket_ids: Optional[List[str]]
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    event_id: str
    gross_face_cents: int
    service_fees_cents: int
    refunds_cents: int
    net_to_promoter_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
