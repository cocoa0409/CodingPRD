"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---- Role enum ------------------------------------------------------------
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    MEMBER = "Member"
    BOOKSELLER = "Bookseller"
    INVENTORY_MANAGER = "InventoryManager"
    STORE_ADMIN = "StoreAdmin"


# ---- Status enums ---------------------------------------------------------
class TitleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class TitleCategory(str, Enum):
    BOOK = "BOOK"
    CAFE = "CAFE"
    SIDELINE = "SIDELINE"


class DemandFlag(str, Enum):
    HIGH = "HIGH"
    NORMAL = "NORMAL"


class StockItemState(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    SOLD = "SOLD"
    RETURNED_TO_PUBLISHER = "RETURNED_TO_PUBLISHER"


class StockItemSource(str, Enum):
    DISTRIBUTOR = "DISTRIBUTOR"
    BUYBACK = "BUYBACK"
    CONSIGNMENT = "CONSIGNMENT"


class MemberTier(str, Enum):
    REGULAR = "REGULAR"
    GOLD = "GOLD"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CreditReason(str, Enum):
    BUYBACK = "BUYBACK"
    REDEMPTION = "REDEMPTION"
    EVENT_REFUND = "EVENT_REFUND"
    ADJUSTMENT = "ADJUSTMENT"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    OPEN = "OPEN"
    RESERVED = "RESERVED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class SpecialOrderState(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class FulfillmentMethod(str, Enum):
    DISTRIBUTOR = "DISTRIBUTOR"
    POD = "POD"


class PublisherReturnState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class AuthorEventState(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class EventTicketState(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    REFUNDED = "REFUNDED"


class BuybackState(str, Enum):
    PENDING = "PENDING"
    OFFERED = "OFFERED"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class ConditionGrade(str, Enum):
    LIKE_NEW = "LIKE_NEW"
    GOOD = "GOOD"
    FAIR = "FAIR"


class ConsignmentAgreementState(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class ConsignmentCopyState(str, Enum):
    ON_SHELF = "ON_SHELF"
    SOLD = "SOLD"
    RETURNED_TO_AUTHOR = "RETURNED_TO_AUTHOR"


# ---- Entity TypedDicts ----------------------------------------------------
# common_fields: true entities carry id + created_at + updated_at + version.
class Title(TypedDict):
    id: str
    isbn13: str
    name: str
    category: str
    list_price_cents: int
    returnable: bool
    demand_flag: str
    pod_eligible: bool
    on_hand_qty: int
    reserved_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StockItem(TypedDict):
    id: str
    title_id: str
    source: str
    cost_cents: int
    state: str
    reserved_order_line_id: Optional[str]
    consignment_copy_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    email: str
    full_name: str
    tier: str
    store_credit_cents: int
    loyalty_points: int
    is_local_author: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only ledger row carrying ONLY id + created_at.
class CreditLedgerEntry(TypedDict):
    id: str
    member_id: str
    delta_cents: int
    reason: str
    ref_id: Optional[str]
    created_at: str


class SalesOrder(TypedDict):
    id: str
    member_id: str
    payment_status: str
    fulfillment_status: str
    credit_redeemed_cents: int
    subtotal_cents: int
    member_discount_cents: int
    net_paid_cents: int
    points_provisional: int
    points_final: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    title_id: str
    quantity: int
    unit_price_cents: int
    line_total_cents: int
    reserved_qty: int
    created_at: str
    updated_at: str
    version: int


class SpecialOrder(TypedDict):
    id: str
    member_id: str
    title_id: str
    quantity: int
    fulfillment_method: str
    state: str
    quoted_unit_cents: Optional[int]
    promised_eta: Optional[str]
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class PublisherReturn(TypedDict):
    id: str
    title_id: str
    quantity: int
    state: str
    credit_unit_cents: int
    credit_total_cents: int
    created_at: str
    updated_at: str
    version: int


class AuthorEvent(TypedDict):
    id: str
    title_id: str
    name: str
    starts_at: str
    capacity: int
    base_price_cents: int
    tickets_sold: int
    state: str
    created_at: str
    updated_at: str
    version: int


class EventTicket(TypedDict):
    id: str
    event_id: str
    member_id: str
    price_paid_cents: int
    state: str
    created_at: str
    updated_at: str
    version: int


class BuybackTransaction(TypedDict):
    id: str
    member_id: str
    state: str
    offer_total_cents: int
    created_at: str
    updated_at: str
    version: int


class BuybackLine(TypedDict):
    id: str
    buyback_id: str
    title_id: str
    condition_grade: str
    quantity: int
    line_offer_cents: int
    created_at: str
    updated_at: str
    version: int


class ConsignmentAgreement(TypedDict):
    id: str
    author_member_id: str
    title_id: str
    units_sold_to_date: int
    total_payout_cents: int
    state: str
    created_at: str
    updated_at: str
    version: int


class ConsignmentCopy(TypedDict):
    id: str
    agreement_id: str
    sale_price_cents: int
    state: str
    payout_cents: int
    created_at: str
    updated_at: str
    version: int
