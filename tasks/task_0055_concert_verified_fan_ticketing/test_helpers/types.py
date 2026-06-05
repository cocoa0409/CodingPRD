"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class FanVerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    FLAGGED = "FLAGGED"


class EventSalesStatus(str, Enum):
    DRAFT = "DRAFT"
    PRESALE = "PRESALE"
    GENERAL = "GENERAL"
    SOLD_OUT = "SOLD_OUT"
    CLOSED = "CLOSED"


class QueueEntryStatus(str, Enum):
    WAITING = "WAITING"
    OFFERED = "OFFERED"
    PURCHASED = "PURCHASED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    CANCELLED = "CANCELLED"


class TicketEntryStatus(str, Enum):
    VALID = "VALID"
    SCANNED = "SCANNED"
    VOID = "VOID"


class TicketHoldingStatus(str, Enum):
    HELD = "HELD"
    TRANSFER_PENDING = "TRANSFER_PENDING"
    LISTED = "LISTED"


class TransferStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"


class ResaleListingStatus(str, Enum):
    OPEN = "OPEN"
    SOLD = "SOLD"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    FAN = "Fan"
    PROMOTER_ADMIN = "PromoterAdmin"
    GATE_SCANNER = "GateScanner"


# All business entities carry id/created_at/updated_at/version (common_fields: true).

class Fan(TypedDict):
    id: str
    email: str
    full_name: str
    device_fingerprint: str
    risk_score: int
    verification_status: str
    completed_purchase_count: int
    created_at: str
    updated_at: str
    version: int


class Event(TypedDict):
    id: str
    title: str
    venue_capacity: int
    presale_code: str
    face_value_cents: int
    resale_cap_pct: int
    tickets_sold_count: int
    sales_status: str
    created_at: str
    updated_at: str
    version: int


class PriceTier(TypedDict):
    id: str
    event_id: str
    name: str
    allocation: int
    base_multiplier_bps: int
    reserved_count: int
    sold_count: int
    created_at: str
    updated_at: str
    version: int


class QueueEntry(TypedDict):
    id: str
    event_id: str
    fan_id: str
    tier_id: str
    presale_code_used: str
    queue_position: int
    requested_qty: int
    status: str
    offer_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    queue_entry_id: str
    fan_id: str
    tier_id: str
    quantity: int
    unit_price_cents: int
    subtotal_cents: int
    service_fee_cents: int
    total_cents: int
    refund_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Ticket(TypedDict):
    id: str
    order_id: str
    event_id: str
    holder_fan_id: str
    seat_label: str
    entry_status: str
    holding_status: str
    created_at: str
    updated_at: str
    version: int


class Transfer(TypedDict):
    id: str
    ticket_id: str
    sender_fan_id: str
    recipient_fan_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ResaleListing(TypedDict):
    id: str
    ticket_id: str
    seller_fan_id: str
    list_price_cents: int
    buyer_fan_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
