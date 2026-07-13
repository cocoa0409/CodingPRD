"""Domain types: entity TypedDicts, status enums, role enum (from the PRD)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    WAREHOUSE_AGENT = "WarehouseAgent"
    CATALOG_ADMIN = "CatalogAdmin"


class ConditionGrade(str, Enum):
    NEW = "NEW"
    LIKE_NEW = "LIKE_NEW"
    GOOD = "GOOD"
    ACCEPTABLE = "ACCEPTABLE"


class InventoryUnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    RENTED = "RENTED"
    IN_INSPECTION = "IN_INSPECTION"
    RETIRED = "RETIRED"
    SOLD = "SOLD"


class FulfillmentType(str, Enum):
    RENT = "RENT"
    BUY = "BUY"
    EBOOK = "EBOOK"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    DELIVERED = "DELIVERED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RentalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETURN_INITIATED = "RETURN_INITIATED"
    CLOSED_RETURNED = "CLOSED_RETURNED"
    CLOSED_LOST = "CLOSED_LOST"


class ReturnShipmentStatus(str, Enum):
    LABEL_ISSUED = "LABEL_ISSUED"
    CLOSED_GOOD = "CLOSED_GOOD"
    CLOSED_DAMAGED = "CLOSED_DAMAGED"
    CLOSED_LOST = "CLOSED_LOST"


class BuybackQuoteStatus(str, Enum):
    QUOTED = "QUOTED"
    ACCEPTED = "ACCEPTED"
    REVISED = "REVISED"
    PAID = "PAID"
    DECLINED = "DECLINED"
    SUPERSEDED = "SUPERSEDED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class SubscriptionTier(str, Enum):
    STUDY = "STUDY"
    SOLUTIONS = "SOLUTIONS"


class WalletTransactionKind(str, Enum):
    TOP_UP = "TOP_UP"
    ORDER_CHARGE = "ORDER_CHARGE"
    ORDER_REFUND = "ORDER_REFUND"
    EXTENSION_FEE = "EXTENSION_FEE"
    LATE_FEE = "LATE_FEE"
    DAMAGE_FEE = "DAMAGE_FEE"
    REPLACEMENT_CHARGE = "REPLACEMENT_CHARGE"
    BUYBACK_CREDIT = "BUYBACK_CREDIT"
    SUBSCRIPTION_FEE = "SUBSCRIPTION_FEE"
    SUBSCRIPTION_REFUND = "SUBSCRIPTION_REFUND"


# common_fields: true -> id + created_at + updated_at + version
class CatalogItem(TypedDict):
    id: str
    isbn13: str
    edition: int
    title: str
    author: str
    list_price_cents: int
    rental_base_cents: int
    ebook_price_cents: int
    buyback_base_cents: int
    replacement_fee_cents: int
    rentable: bool
    buyable: bool
    ebook_available: bool
    highlighting_allowed: bool
    max_highlight_pct: float
    created_at: str
    updated_at: str
    version: int


class InventoryUnit(TypedDict):
    id: str
    catalog_item_id: str
    condition_grade: str
    status: str
    acquisition_cost_cents: int
    times_rented: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    wallet_credit_cents: int
    active_subscription_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    catalog_item_id: str
    inventory_unit_id: Optional[str]
    fulfillment_type: str
    rental_term_days: Optional[int]
    desired_start_date: Optional[str]
    access_start: Optional[str]
    access_end: Optional[str]
    payment_status: str
    fulfillment_status: str
    quoted_charge_cents: int
    final_charge_cents: Optional[int]
    refunded_cents: int
    created_at: str
    updated_at: str
    version: int


class Rental(TypedDict):
    id: str
    order_id: str
    customer_id: str
    inventory_unit_id: str
    status: str
    start_date: str
    due_date: str
    term_days: int
    extension_count: int
    highlight_pct_used: float
    late_days: int
    late_fee_cents: int
    damage_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class ReturnShipment(TypedDict):
    id: str
    rental_id: str
    status: str
    carrier_label: str
    reported_condition: Optional[str]
    highlight_pct_reported: float
    is_lost: bool
    damage_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class BuybackQuote(TypedDict):
    id: str
    customer_id: str
    catalog_item_id: str
    inventory_unit_id: Optional[str]
    declared_condition: str
    assessed_condition: Optional[str]
    status: str
    quoted_price_cents: int
    revised_price_cents: Optional[int]
    paid_price_cents: Optional[int]
    quote_expires_at: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    customer_id: str
    plan_id: str
    status: str
    period_start: str
    period_end: str
    monthly_fee_cents: int
    rental_discount_pct: float
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> append-only ledger, ONLY id + created_at
class WalletTransaction(TypedDict):
    id: str
    customer_id: str
    amount_cents: int
    kind: str
    reference_id: Optional[str]
    created_at: str
