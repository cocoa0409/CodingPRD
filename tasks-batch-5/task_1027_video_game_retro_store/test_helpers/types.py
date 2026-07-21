"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, List, Optional


# --- Role enum -------------------------------------------------------------
class UserRole(str, Enum):
    MEMBER = "Member"
    CLERK = "Clerk"
    MANAGER = "Manager"


# --- Status / value enums --------------------------------------------------
class MemberTier(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"


class ProductKind(str, Enum):
    GAME = "GAME"
    CONSOLE = "CONSOLE"
    ACCESSORY = "ACCESSORY"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class ReleaseState(str, Enum):
    EMBARGOED = "EMBARGOED"
    RELEASED = "RELEASED"


class InventoryItemStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RENTED = "RENTED"
    SOLD = "SOLD"


class PreOrderPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"
    REFUNDED = "REFUNDED"


class PreOrderAllocationStatus(str, Enum):
    PENDING = "PENDING"
    WAITLISTED = "WAITLISTED"
    ALLOCATED = "ALLOCATED"
    FULFILLED = "FULFILLED"
    RELEASED = "RELEASED"


class AllocationStatus(str, Enum):
    HELD = "HELD"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class PayoutMethod(str, Enum):
    CASH = "CASH"
    STORE_CREDIT = "STORE_CREDIT"


class TradeInStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    OFFERED = "OFFERED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class RentalStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_OUT = "CHECKED_OUT"
    RETURNED = "RETURNED"


class StoreCreditReason(str, Enum):
    TRADE_IN_PAYOUT = "TRADE_IN_PAYOUT"
    TRADE_IN_VOID_REVERSAL = "TRADE_IN_VOID_REVERSAL"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"
    SALE_REDEMPTION = "SALE_REDEMPTION"
    PREORDER_REFUND = "PREORDER_REFUND"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version)
class Member(TypedDict):
    id: str
    full_name: str
    email: str
    tier: str
    store_credit_balance_cents: int
    loyalty_points: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    title: str
    kind: str
    base_price_cents: int
    base_trade_value_cents: int
    daily_rental_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class ProductStock(TypedDict):
    id: str
    product_id: str
    unit_price_cents: int
    deposit_cents: int
    total_count: int
    available_count: int
    allocated_count: int
    fulfilled_count: int
    release_state: str
    created_at: str
    updated_at: str
    version: int


class InventoryItem(TypedDict):
    id: str
    product_id: str
    condition_grade: str
    acquisition_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PreOrder(TypedDict):
    id: str
    member_id: str
    product_stock_id: str
    amount_paid_cents: int
    payment_status: str
    allocation_status: str
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict):
    id: str
    pre_order_id: str
    product_stock_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TradeIn(TypedDict):
    id: str
    member_id: str
    product_id: str
    stated_grade: str
    final_grade: Optional[str]
    payout_method: str
    provisional_value_cents: int
    final_value_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Rental(TypedDict):
    id: str
    member_id: str
    inventory_item_id: str
    start_at: str
    due_at: str
    daily_rate_cents: int
    planned_days: int
    returned_at: Optional[str]
    estimated_charge_cents: int
    late_fee_cents: int
    final_charge_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Sale(TypedDict):
    id: str
    member_id: str
    lines: list
    redeem_store_credit_cents: int
    subtotal_cents: int
    tax_total_cents: int
    total_cents: int
    amount_due_cents: int
    loyalty_points_earned: int
    created_at: str
    updated_at: str
    version: int


class Station(TypedDict):
    id: str
    name: str
    seat_capacity: int
    created_at: str
    updated_at: str
    version: int


class Tournament(TypedDict):
    id: str
    station_id: str
    title: str
    starts_at: str
    ends_at: str
    registration_opens_at: str
    registration_closes_at: str
    max_participants: int
    registered_count: int
    registered_member_ids: List[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only ledger event: carries only id + created_at
class StoreCreditEntry(TypedDict):
    id: str
    member_id: str
    amount_cents: int
    reason: str
    related_ref: Optional[str]
    created_at: str
