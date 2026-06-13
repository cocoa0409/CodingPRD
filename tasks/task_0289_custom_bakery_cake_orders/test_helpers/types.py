"""Domain types: entity TypedDicts, status enums, role enum.

All types reflect the Custom Bakery & Cake Orders contract. Field names are
PRD-exact. The Payment resource is an immutable ledger entry that carries only
id and created_at (no updated_at, no version); every other resource carries the
full common-field set (id, created_at, updated_at, version).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---- Roles -----------------------------------------------------------------
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CUSTOMER = "Customer"
    BAKERY_STAFF = "BakeryStaff"
    DELIVERY_DISPATCHER = "DeliveryDispatcher"
    BAKERY_MANAGER = "BakeryManager"


# ---- Status enums ----------------------------------------------------------
class OrderProductionStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    PROOF_PENDING = "PROOF_PENDING"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    PROOF_APPROVED = "PROOF_APPROVED"
    IN_PRODUCTION = "IN_PRODUCTION"
    READY = "READY"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class OrderPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"
    REFUNDED = "REFUNDED"


class ProofStatus(str, Enum):
    AWAITING_REVIEW = "AWAITING_REVIEW"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class ReservationStatus(str, Enum):
    HELD = "HELD"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class LoyaltyTier(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"


class PaymentKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    BALANCE = "BALANCE"
    REFUND = "REFUND"


class FulfillmentMode(str, Enum):
    PICKUP = "PICKUP"
    DELIVERY = "DELIVERY"


# ---- Entities (common_fields: true) ----------------------------------------
class ProductCatalogItem(TypedDict, total=False):
    id: str
    name: str
    base_price_cents: int
    base_lead_days: int
    tier_levels: int
    allowed_option_codes: List[str]
    declared_allergen_codes: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomizationOption(TypedDict, total=False):
    id: str
    option_code: str
    surcharge_cents: int
    introduces_allergen_codes: List[str]
    dietary_exclusion_codes: List[str]
    created_at: str
    updated_at: str
    version: int


class ProductionDay(TypedDict, total=False):
    id: str
    production_date: str
    unit_capacity: int
    units_committed: int
    is_peak: bool
    order_cutoff_at: str
    created_at: str
    updated_at: str
    version: int


class DeliveryRoute(TypedDict, total=False):
    id: str
    route_name: str
    service_date: str
    stop_minutes: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    store_credit_cents: int
    lifetime_spend_cents: int
    loyalty_tier: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    customer_id: str
    product_id: str
    production_day_id: str
    placed_at: str
    production_status: str
    payment_status: str
    estimate_total_cents: int
    final_total_cents: int
    deposit_due_cents: int
    balance_due_cents: int
    applied_credit_cents: int
    peak_surcharge_cents: int
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLineCustomization(TypedDict, total=False):
    id: str
    order_id: str
    units: int
    selected_option_codes: List[str]
    requested_dietary_codes: List[str]
    line_surcharge_cents: int
    effective_allergen_codes: List[str]
    created_at: str
    updated_at: str
    version: int


class DesignProof(TypedDict, total=False):
    id: str
    order_id: str
    revision_number: int
    image_ref: str
    proof_status: str
    change_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SlotReservation(TypedDict, total=False):
    id: str
    order_id: str
    fulfillment_mode: str
    route_id: Optional[str]
    window_start_min: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


# ---- Entity (common_fields: false) — append-only ledger entry --------------
class Payment(TypedDict, total=False):
    id: str
    order_id: str
    kind: str
    amount_cents: int
    credit_applied_cents: int
    settled_at: str
    created_at: str
    # NOTE: Payment is immutable — no updated_at, no version.
