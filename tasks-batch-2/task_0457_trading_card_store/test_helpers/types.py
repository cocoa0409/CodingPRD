"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Trading Card Store PRD. Entities carrying the full common-field
set expose id/created_at/updated_at/version; the append-only store-credit ledger
carries only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    STORE_MANAGER = "StoreManager"
    JUDGE_STAFF = "JudgeStaff"


# ─── Status / enum value sets ────────────────────────────────────────────────
class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BANNED = "BANNED"


class LoyaltyTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class ProductKind(str, Enum):
    SINGLE = "SINGLE"
    SEALED = "SEALED"


class Condition(str, Enum):
    MINT = "MINT"
    NEAR_MINT = "NEAR_MINT"
    LIGHTLY_PLAYED = "LIGHTLY_PLAYED"
    MODERATELY_PLAYED = "MODERATELY_PLAYED"
    DAMAGED = "DAMAGED"


class PayoutMethod(str, Enum):
    STORE_CREDIT = "STORE_CREDIT"
    CASH = "CASH"


class BuylistStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class ReleaseProductStatus(str, Enum):
    PRE_ORDER_OPEN = "PRE_ORDER_OPEN"
    RELEASED = "RELEASED"


class PreOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ALLOCATED = "ALLOCATED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    WAITLISTED = "WAITLISTED"


class EventFormat(str, Enum):
    STANDARD = "STANDARD"
    MODERN = "MODERN"
    COMMANDER = "COMMANDER"
    DRAFT = "DRAFT"


class EventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class CheckinStatus(str, Enum):
    PENDING = "PENDING"
    CHECKED_IN = "CHECKED_IN"
    WITHDRAWN = "WITHDRAWN"


class PairingResult(str, Enum):
    PENDING = "PENDING"
    A_WINS = "A_WINS"
    B_WINS = "B_WINS"
    DRAW = "DRAW"
    BYE_A = "BYE_A"


class GradingStatus(str, Enum):
    INTAKE = "INTAKE"
    AT_GRADER = "AT_GRADER"
    GRADED = "GRADED"
    REJECTED = "REJECTED"
    RETURNED = "RETURNED"


class ConsignmentStatus(str, Enum):
    LISTED = "LISTED"
    SOLD = "SOLD"
    WITHDRAWN = "WITHDRAWN"
    SETTLED = "SETTLED"


class ServiceTier(str, Enum):
    ECONOMY = "ECONOMY"
    STANDARD = "STANDARD"
    EXPRESS = "EXPRESS"


class LedgerReason(str, Enum):
    BUYLIST_PAYOUT = "BUYLIST_PAYOUT"
    EVENT_REFUND = "EVENT_REFUND"
    CONSIGNMENT_PAYOUT = "CONSIGNMENT_PAYOUT"
    PREORDER_DEPOSIT = "PREORDER_DEPOSIT"
    EVENT_CHARGE = "EVENT_CHARGE"
    PREORDER_FULFILL = "PREORDER_FULFILL"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"


# ─── Entity TypedDicts (common_fields: true → id/created_at/updated_at/version) ─
class Customer(TypedDict):
    id: str
    display_name: str
    email: str
    loyalty_tier: str
    lifetime_spend_cents: int
    store_credit_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryItem(TypedDict):
    id: str
    title: str
    product_kind: str
    condition: str
    market_price_cents: int
    quantity_on_hand: int
    quantity_reserved: int
    created_at: str
    updated_at: str
    version: int


class BuylistSubmission(TypedDict):
    id: str
    customer_id: str
    payout_method: str
    status: str
    offered_total_cents: int
    created_at: str
    updated_at: str
    version: int


class BuylistLine(TypedDict):
    id: str
    buylist_submission_id: str
    inventory_item_id: str
    quantity: int
    line_payout_cents: int
    created_at: str
    updated_at: str
    version: int


class ReleaseProduct(TypedDict):
    id: str
    title: str
    street_date: str
    allocation_pool: int
    unit_price_cents: int
    deposit_required_cents: int
    quantity_allocated: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PreOrder(TypedDict):
    id: str
    customer_id: str
    release_product_id: str
    requested_quantity: int
    deposit_paid_cents: int
    priority_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Event(TypedDict):
    id: str
    title: str
    format: str
    starts_at: str
    ends_at: str
    capacity: int
    entry_fee_cents: int
    tables_required: int
    seated_count: int
    current_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict):
    id: str
    event_id: str
    customer_id: str
    payment_status: str
    checkin_status: str
    quoted_fee_cents: int
    charged_fee_cents: int
    match_points: int
    created_at: str
    updated_at: str
    version: int


class Pairing(TypedDict):
    id: str
    event_id: str
    round_number: int
    registration_a_id: str
    registration_b_id: Optional[str]
    result: str
    created_at: str
    updated_at: str
    version: int


class GradingSubmission(TypedDict):
    id: str
    customer_id: str
    inventory_item_id: str
    declared_value_cents: int
    service_tier: str
    grading_fee_cents: int
    assigned_grade: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsignmentCase(TypedDict):
    id: str
    customer_id: str
    inventory_item_id: str
    quantity: int
    ask_price_cents: int
    commission_rate_bps: int
    payout_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Append-only ledger (common_fields: false → id + created_at ONLY) ─────────
class StoreCreditLedger(TypedDict):
    id: str
    customer_id: str
    delta_cents: int
    reason: str
    source_entity_id: Optional[str]
    created_at: str
