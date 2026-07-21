"""Domain types for the event ticketing platform: entity shapes, status enums, roles."""
from enum import Enum
from typing import TypedDict, List, Optional


class UserRole(str, Enum):
    ORGANIZER = "Organizer"
    BUYER = "Buyer"
    GATE_STAFF = "GateStaff"
    FINANCE_OFFICER = "FinanceOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"
    ANONYMOUS = "Anonymous"


class EventStatus(str, Enum):
    DRAFT = "DRAFT"
    ONSALE = "ONSALE"
    PAUSED = "PAUSED"
    SALES_CLOSED = "SALES_CLOSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class FeeMode(str, Enum):
    PASS_ON = "PASS_ON"
    ABSORB = "ABSORB"


class RefundPolicy(str, Enum):
    FEE_RETAINED = "FEE_RETAINED"
    FEE_INCLUDED = "FEE_INCLUDED"


class SeatingMode(str, Enum):
    GA = "GA"
    RESERVED = "RESERVED"


class PromoKind(str, Enum):
    PERCENT = "PERCENT"
    FIXED = "FIXED"


class OrderPaymentStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    REFUND_PENDING = "REFUND_PENDING"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"


class OrderFulfillmentStatus(str, Enum):
    HELD = "HELD"
    ISSUED = "ISSUED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"
    CHECKED_IN_PARTIAL = "CHECKED_IN_PARTIAL"
    CHECKED_IN_FULL = "CHECKED_IN_FULL"


class AttendeeStatus(str, Enum):
    ISSUED = "ISSUED"
    CHECKED_IN = "CHECKED_IN"
    TRANSFERRED = "TRANSFERRED"
    VOIDED = "VOIDED"


class RefundRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SETTLED = "SETTLED"


class TransferRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class WaitlistEntryStatus(str, Enum):
    WAITING = "WAITING"
    OFFERED = "OFFERED"
    CLAIMED = "CLAIMED"
    EXPIRED = "EXPIRED"


class PayoutStatus(str, Enum):
    ACCRUING = "ACCRUING"
    ELIGIBLE = "ELIGIBLE"
    ON_HOLD = "ON_HOLD"
    APPROVED = "APPROVED"
    RELEASED = "RELEASED"


# --------------------------------------------------------------------------
# Entity shapes. Every resource carries id + created_at; most also carry
# updated_at and version. The scan record is the single append-only audit
# fact and therefore carries neither.
# --------------------------------------------------------------------------


class Organizer(TypedDict):
    id: str
    display_name: str
    contact_email: str
    lifetime_gross_cents: int
    lifetime_refunds_cents: int
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict):
    id: str
    name: str
    city: str
    seated_capacity: int
    created_at: str
    updated_at: str
    version: int


class Buyer(TypedDict):
    id: str
    email: str
    display_name: str
    created_at: str
    updated_at: str
    version: int


class Event(TypedDict):
    id: str
    organizer_id: str
    venue_id: str
    title: str
    starts_at: str
    ends_at: str
    status: str
    fee_mode: str
    refund_policy: str
    gross_cents: int
    refunds_cents: int
    issued_count: int
    checked_in_count: int
    created_at: str
    updated_at: str
    version: int


class TicketType(TypedDict):
    id: str
    event_id: str
    name: str
    tier_rank: int
    price_cents: int
    quantity_total: int
    seating_mode: str
    sold_count: int
    held_count: int
    created_at: str
    updated_at: str
    version: int


class SeatBlock(TypedDict):
    id: str
    ticket_type_id: str
    row_label: str
    seat_from: int
    seat_to: int
    seats_total: int
    seats_taken: int
    created_at: str
    updated_at: str
    version: int


class PromoCode(TypedDict):
    id: str
    event_id: str
    code: str
    kind: str
    percent_bp: int
    amount_cents: int
    max_uses: int
    uses_count: int
    valid_from: str
    valid_until: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    event_id: str
    buyer_id: str
    promo_code_id: Optional[str]
    payment_status: str
    fulfillment_status: str
    subtotal_cents: int
    discount_cents: int
    fee_total_cents: int
    buyer_total_cents: int
    organizer_gross_cents: int
    refunded_cents: int
    hold_expires_at: str
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderItem(TypedDict):
    id: str
    order_id: str
    ticket_type_id: str
    seat_block_id: Optional[str]
    quantity: int
    seat_numbers: List[int]
    unit_price_cents: int
    per_ticket_fee_cents: int
    line_face_cents: int
    line_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Attendee(TypedDict):
    id: str
    order_id: str
    order_item_id: str
    ticket_type_id: str
    event_id: str
    buyer_id: str
    seat_block_id: Optional[str]
    seat_number: Optional[int]
    holder_email: str
    status: str
    checked_in_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScanRecord(TypedDict):
    """Append-only audit fact: id and created_at only, no updated_at, no version."""
    id: str
    attendee_id: str
    event_id: str
    gate_code: str
    scanned_at: str
    scanned_by_user_id: str
    created_at: str


class RefundRequest(TypedDict):
    id: str
    order_id: str
    policy: str
    status: str
    item_refunds: List[dict]
    refund_amount_cents: int
    platform_retained_cents: int
    organizer_charged_cents: int
    reason: str
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransferRequest(TypedDict):
    id: str
    attendee_id: str
    from_buyer_id: str
    to_buyer_id: Optional[str]
    to_email: str
    status: str
    offer_expires_at: Optional[str]
    resend_count: int
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict):
    id: str
    ticket_type_id: str
    buyer_id: str
    claimed_order_id: Optional[str]
    requested_quantity: int
    status: str
    offered_at: Optional[str]
    offer_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    organizer_id: str
    event_id: str
    status: str
    gross_cents: int
    refunds_cents: int
    platform_fee_cents: int
    reserve_basis_cents: int
    reserve_rate: float
    reserve_cents: int
    net_amount_cents: int
    reliability_score_snapshot: int
    reserve_release_at: str
    reserve_released_cents: int
    approved_by_user_id: Optional[str]
    released_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
