"""Domain types: entity TypedDicts, status enums, role enum.

All thirteen resource types carry common fields (id, created_at, updated_at,
version) per PRD §2.4, so every TypedDict lists updated_at and version.
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------
# Role enum (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SELLER = "Seller"
    BUYER = "Buyer"
    TRUST_SAFETY = "TrustSafety"


# --------------------------------------------------------------------------
# Status enums (PRD §3 state machines)
# --------------------------------------------------------------------------
class EventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ON_SALE = "ON_SALE"
    LAST_MINUTE = "LAST_MINUTE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    POSTPONED = "POSTPONED"


class SellerTrustTier(str, Enum):
    NEW = "NEW"
    VERIFIED = "VERIFIED"
    TRUSTED = "TRUSTED"
    RESTRICTED = "RESTRICTED"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SOLD_OUT = "SOLD_OUT"
    DELISTED = "DELISTED"
    FROZEN = "FROZEN"


class PricingMode(str, Enum):
    FIXED = "FIXED"
    DYNAMIC = "DYNAMIC"


class DeliveryMethod(str, Enum):
    MOBILE_TRANSFER = "MOBILE_TRANSFER"
    BARCODE_PDF = "BARCODE_PDF"


class SplitRule(str, Enum):
    ANY = "ANY"
    PAIRS = "PAIRS"
    WHOLE = "WHOLE"


class PriceZone(str, Enum):
    PREMIUM = "PREMIUM"
    STANDARD = "STANDARD"
    VALUE = "VALUE"


class SeatStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    HELD = "HELD"
    SOLD = "SOLD"
    TRANSFERRED = "TRANSFERRED"
    VOID = "VOID"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    CHARGED = "CHARGED"
    REFUNDED = "REFUNDED"
    CREDITED = "CREDITED"


class DeliveryStatus(str, Enum):
    AWAITING = "AWAITING"
    IN_TRANSFER = "IN_TRANSFER"
    DELIVERED = "DELIVERED"
    DELIVERY_FAILED = "DELIVERY_FAILED"
    REPLACED = "REPLACED"


class LifecycleState(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"
    UNWOUND = "UNWOUND"


class TransferStatus(str, Enum):
    INITIATED = "INITIATED"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"
    RECALLED = "RECALLED"


class PayoutStatus(str, Enum):
    PENDING = "PENDING"
    ESCROWED = "ESCROWED"
    RELEASABLE = "RELEASABLE"
    PAID = "PAID"
    CLAWED_BACK = "CLAWED_BACK"
    CANCELLED = "CANCELLED"


class ClaimReason(str, Enum):
    NOT_DELIVERED = "NOT_DELIVERED"
    INVALID_BARCODE = "INVALID_BARCODE"
    DUPLICATE_SEAT = "DUPLICATE_SEAT"
    EVENT_ISSUE = "EVENT_ISSUE"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    INVESTIGATING = "INVESTIGATING"
    REPLACEMENT_OFFERED = "REPLACEMENT_OFFERED"
    RESOLVED_REPLACED = "RESOLVED_REPLACED"
    RESOLVED_REFUNDED = "RESOLVED_REFUNDED"
    DENIED = "DENIED"


class EventCreditStatus(str, Enum):
    ISSUED = "ISSUED"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class FraudSubjectType(str, Enum):
    LISTING = "LISTING"
    ORDER = "ORDER"
    SEAT = "SEAT"


class FraudSignal(str, Enum):
    DUPLICATE_BARCODE = "DUPLICATE_BARCODE"
    PRICE_GOUGE = "PRICE_GOUGE"
    VELOCITY = "VELOCITY"
    CHARGEBACK = "CHARGEBACK"


class FraudSeverity(str, Enum):
    LOW = "LOW"
    HIGH = "HIGH"


class FraudFlagStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


# --------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.4 — all carry id/created_at/updated_at/version)
# --------------------------------------------------------------------------
class Venue(TypedDict):
    id: str
    name: str
    timezone: str
    total_section_count: int
    created_at: str
    updated_at: str
    version: int


class Section(TypedDict):
    id: str
    venue_id: str
    name: str
    price_zone: str
    face_value_cents: int
    row_count: int
    seats_per_row: int
    capacity: int
    created_at: str
    updated_at: str
    version: int


class Event(TypedDict):
    id: str
    venue_id: str
    title: str
    doors_open_at: str
    status: str
    price_cap_multiplier: float
    active_listing_count: int
    last_minute_cutoff_minutes: int
    created_at: str
    updated_at: str
    version: int


class Seller(TypedDict):
    id: str
    display_name: str
    payout_account_ref: str
    trust_tier: str
    escrow_balance_cents: int
    paid_out_balance_cents: int
    open_fraud_flag_count: int
    created_at: str
    updated_at: str
    version: int


class Buyer(TypedDict):
    id: str
    display_name: str
    wallet_credit_cents: int
    lifetime_orders_count: int
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict):
    id: str
    event_id: str
    seller_id: str
    section_id: str
    status: str
    delivery_method: str
    ask_price_cents: int
    pricing_mode: str
    dynamic_floor_cents: Optional[int]
    effective_price_cents: int
    total_seat_count: int
    available_seat_count: int
    split_rule: str
    held_seat_count: int
    created_at: str
    updated_at: str
    version: int


class Seat(TypedDict):
    id: str
    listing_id: str
    section_id: str
    row_label: str
    seat_number: int
    barcode_token: str
    status: str
    order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    listing_id: str
    buyer_id: str
    quantity: int
    payment_status: str
    delivery_status: str
    lifecycle_state: str
    locked_unit_price_cents: int
    estimated_total_cents: int
    final_total_cents: Optional[int]
    buyer_fee_cents: int
    applied_credit_cents: int
    reservation_expires_at: str
    replacement_of_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Transfer(TypedDict):
    id: str
    order_id: str
    method: str
    status: str
    is_last_minute: bool
    deadline_at: str
    attempt_number: int
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    order_id: str
    seller_id: str
    status: str
    gross_sale_cents: int
    seller_fee_rate: float
    seller_fee_cents: int
    net_payout_cents: int
    clawback_cents: int
    created_at: str
    updated_at: str
    version: int


class GuaranteeClaim(TypedDict):
    id: str
    order_id: str
    reason: str
    status: str
    offered_listing_id: Optional[str]
    replacement_order_id: Optional[str]
    round_number: int
    refund_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class EventCredit(TypedDict):
    id: str
    buyer_id: str
    event_id: str
    source_order_id: str
    amount_cents: int
    status: str
    bonus_applied: bool
    created_at: str
    updated_at: str
    version: int


class FraudFlag(TypedDict):
    id: str
    subject_type: str
    listing_id: Optional[str]
    order_id: Optional[str]
    seat_id: Optional[str]
    signal: str
    severity: str
    status: str
    created_at: str
    updated_at: str
    version: int
