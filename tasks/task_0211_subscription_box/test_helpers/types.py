"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's resource model. Every primary resource carries the
common audit set (id, created_at, updated_at, version); the append-only
WalletEntry carries only id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Enums ────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    SUBSCRIBER = "Subscriber"
    CURATION_ADMIN = "CurationAdmin"
    BILLING_OPERATOR = "BillingOperator"


class Cadence(str, Enum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ProductStatus(str, Enum):
    SELLABLE = "SELLABLE"
    DISCONTINUED = "DISCONTINUED"


class SubscriptionLifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCEL_SCHEDULED = "CANCEL_SCHEDULED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class SubscriptionBillingStatus(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"
    PREPAID = "PREPAID"


class GiftGrantStatus(str, Enum):
    ISSUED = "ISSUED"
    REDEEMED = "REDEEMED"
    REVOKED = "REVOKED"


class BillingCycleStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    FAILED = "FAILED"
    REVERSED = "REVERSED"


class FundingSource(str, Enum):
    CHARGE = "CHARGE"
    PREPAID_DRAW = "PREPAID_DRAW"
    GIFT = "GIFT"
    WALLET = "WALLET"


class BoxSelectionDecision(str, Enum):
    PENDING = "PENDING"
    CURATED = "CURATED"
    SKIPPED = "SKIPPED"
    FINALIZED = "FINALIZED"


class WaveStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class AllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    RELEASED = "RELEASED"
    COMMITTED = "COMMITTED"


class ShipmentStatus(str, Enum):
    PACKED = "PACKED"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"


class WalletEntryKind(str, Enum):
    REFUND_CREDIT = "REFUND_CREDIT"
    WINBACK_CREDIT = "WINBACK_CREDIT"
    PERIOD_DEBIT = "PERIOD_DEBIT"
    ADJUSTMENT = "ADJUSTMENT"


class InvoiceKind(str, Enum):
    PERIOD_CHARGE = "PERIOD_CHARGE"
    PREPAID_CHARGE = "PREPAID_CHARGE"
    GIFT_CHARGE = "GIFT_CHARGE"
    CANCEL_REFUND = "CANCEL_REFUND"


class InvoiceStatus(str, Enum):
    SETTLED = "SETTLED"
    VOID = "VOID"


# ─── Entity TypedDicts (common_fields: true → id+created_at+updated_at+version) ─

class SubscriptionPlan(TypedDict):
    id: str
    name: str
    cadence: str
    period_price_cents: int
    box_item_count: int
    prepaid_terms_offered: List[int]
    prepaid_discount_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    name: str
    on_hand_qty: int
    allocated_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscriber(TypedDict):
    id: str
    email: str
    full_name: str
    wallet_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    subscriber_id: str
    plan_id: str
    lifecycle_status: str
    billing_status: str
    is_gift: bool
    prepaid_periods_remaining: int
    prepaid_unit_value_cents: int
    current_period_index: int
    next_renewal_at: Optional[str]
    paused_until: Optional[str]
    pause_count_in_term: int
    cancelled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GiftGrant(TypedDict):
    id: str
    plan_id: str
    gifter_subscriber_id: str
    term_periods: int
    recipient_email: str
    redemption_code: str
    amount_paid_cents: int
    status: str
    redeemed_subscription_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BillingCycle(TypedDict):
    id: str
    subscription_id: str
    period_index: int
    amount_charged_cents: int
    funding_source: str
    status: str
    charged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BoxSelection(TypedDict):
    id: str
    subscription_id: str
    period_index: int
    product_ids: List[str]
    decision: str
    allocation_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShippingWave(TypedDict):
    id: str
    cadence: str
    cutoff_at: str
    ship_date: str
    capacity: int
    reserved_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict):
    id: str
    subscription_id: str
    wave_id: str
    box_selection_id: str
    line_items: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    allocation_id: str
    wave_id: str
    subscription_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    subscriber_id: str
    subscription_id: Optional[str]
    gross_amount_cents: int
    kind: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only ledger line: ONLY id + created_at
class WalletEntry(TypedDict):
    id: str
    subscriber_id: str
    amount_cents: int
    kind: str
    source_ref_id: Optional[str]
    created_at: str
