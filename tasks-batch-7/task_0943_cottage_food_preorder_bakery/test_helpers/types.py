"""Domain types for the cottage-food pre-order bakery API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD §2.1) ────────────────────────────────────────────────────────

class UserRole(str, Enum):
    BAKER = "Baker"
    CUSTOMER = "Customer"
    PLATFORM_ADMIN = "PlatformAdmin"
    HEALTH_INSPECTOR = "HealthInspector"


# ─── The eighteen status axes (PRD §2.12) ────────────────────────────────────

class PermitStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CAP_REACHED = "CAP_REACHED"


class RecipeStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    REVISING = "REVISING"
    RETIRED = "RETIRED"


class LotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    RELEASED = "RELEASED"
    CONSUMED = "CONSUMED"
    RECALLED = "RECALLED"
    EXPIRED = "EXPIRED"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    LISTED = "LISTED"
    PAUSED = "PAUSED"
    DELISTED = "DELISTED"


class WindowStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    IN_PRODUCTION = "IN_PRODUCTION"
    HANDOFF_OPEN = "HANDOFF_OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PlanStatus(str, Enum):
    UNPLANNED = "UNPLANNED"
    PLANNED = "PLANNED"
    RECONCILED = "RECONCILED"


class CapacityPosture(str, Enum):
    OPEN_CAPACITY = "OPEN_CAPACITY"
    CONSTRAINED = "CONSTRAINED"
    EXHAUSTED = "EXHAUSTED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_HOLD = "PENDING_HOLD"
    EXPIRED_HOLD = "EXPIRED_HOLD"
    CONFIRMED = "CONFIRMED"
    IN_PRODUCTION = "IN_PRODUCTION"
    READY = "READY"
    FULFILLED = "FULFILLED"
    FORFEITED = "FORFEITED"
    CANCELLED = "CANCELLED"
    VOIDED_RECALL = "VOIDED_RECALL"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"
    VOIDED = "VOIDED"


class HandoffStatus(str, Enum):
    NOT_SCHEDULED = "NOT_SCHEDULED"
    SCHEDULED = "SCHEDULED"
    PICKUP_READY = "PICKUP_READY"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    HANDED_OFF = "HANDED_OFF"
    MISSED = "MISSED"
    FORFEITED = "FORFEITED"


class LineStatus(str, Enum):
    PENDING = "PENDING"
    RELEASED = "RELEASED"
    ALLOCATED = "ALLOCATED"
    FULFILLED = "FULFILLED"
    SHORTED = "SHORTED"
    CREDITED = "CREDITED"
    RECALL_VOID = "RECALL_VOID"


class BatchStatus(str, Enum):
    PLANNED = "PLANNED"
    MIXED = "MIXED"
    BAKED = "BAKED"
    YIELD_CONFIRMED = "YIELD_CONFIRMED"
    UNDER_YIELD = "UNDER_YIELD"
    ALLOCATED = "ALLOCATED"
    CLOSED = "CLOSED"
    SCRAPPED_RECALL = "SCRAPPED_RECALL"


class LabelStatus(str, Enum):
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"
    VOID = "VOID"
    CONSUMED = "CONSUMED"


class SubStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    PAST_DUE = "PAST_DUE"
    CANCELLED = "CANCELLED"


class CycleStatus(str, Enum):
    GENERATED = "GENERATED"
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    SKIPPED = "SKIPPED"
    RELEASED = "RELEASED"
    ORDER_PLACED = "ORDER_PLACED"


class PaymentState(str, Enum):
    INITIATED = "INITIATED"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    SETTLED = "SETTLED"
    DECLINED = "DECLINED"
    VOIDED = "VOIDED"


class RouteStatus(str, Enum):
    DRAFT = "DRAFT"
    SEQUENCED = "SEQUENCED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"


class ReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RESPONDED = "RESPONDED"
    HIDDEN = "HIDDEN"


# ─── Other enumerated fields, not lifecycle axes (PRD §2.12) ─────────────────

class Channel(str, Enum):
    DTC = "DTC"
    WHOLESALE = "WHOLESALE"


class HandoffMode(str, Enum):
    PICKUP_COUNTER = "PICKUP_COUNTER"
    PORCH_SELF_SERVE = "PORCH_SELF_SERVE"
    DELIVERY = "DELIVERY"


class OrderSource(str, Enum):
    WALKUP = "WALKUP"
    SUBSCRIPTION_CLUB = "SUBSCRIPTION_CLUB"


class Disposition(str, Enum):
    WHOLE_UNHEATED = "WHOLE_UNHEATED"
    WITH_UTENSILS = "WITH_UTENSILS"
    BY_THE_SLICE = "BY_THE_SLICE"
    HEATED = "HEATED"


class ProductClass(str, Enum):
    SHELF_STABLE = "SHELF_STABLE"
    REFRIGERATION_REQUIRED = "REFRIGERATION_REQUIRED"


class PricingBasis(str, Enum):
    PER_UNIT = "PER_UNIT"
    PER_DOZEN_BAKERS = "PER_DOZEN_BAKERS"


class OvenProfile(str, Enum):
    STANDARD = "STANDARD"
    LONG_BAKE = "LONG_BAKE"


class Cadence(str, Enum):
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    MONTHLY = "MONTHLY"


class BillingMode(str, Enum):
    PREPAID = "PREPAID"
    PAY_PER_CYCLE = "PAY_PER_CYCLE"


class TipMode(str, Enum):
    PERCENT = "PERCENT"
    FIXED = "FIXED"


class PaymentOutcome(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    DECLINED = "DECLINED"


class LedgerScope(str, Enum):
    CUSTOMER_CREDIT = "CUSTOMER_CREDIT"
    SUBSCRIPTION_PREPAID = "SUBSCRIPTION_PREPAID"
    SETTLEMENT = "SETTLEMENT"


class MovementKind(str, Enum):
    REFUND = "REFUND"
    SHORTFALL_CREDIT = "SHORTFALL_CREDIT"
    PREPAY_DEPOSIT = "PREPAY_DEPOSIT"
    CREDIT_REDEEM = "CREDIT_REDEEM"


class MovementReason(str, Enum):
    SHORTFALL = "SHORTFALL"
    RECALL_VOID = "RECALL_VOID"
    CUSTOMER_CANCEL = "CUSTOMER_CANCEL"
    SUBSCRIPTION_PREPAY = "SUBSCRIPTION_PREPAY"
    ORDER_APPLY = "ORDER_APPLY"


class AllergenSeverity(str, Enum):
    ANAPHYLACTIC = "ANAPHYLACTIC"
    INTOLERANCE = "INTOLERANCE"


# ─── Entity shapes (PRD §2.4: every resource carries id + created_at; almost
#     every one additionally carries updated_at and version. MoneyMovement is
#     the one exception — it carries only id and created_at.) ────────────────

class Baker(TypedDict):
    id: str
    display_name: str
    jurisdiction_code: str
    permit_status: str
    shared_kitchen: bool
    annual_cap_cents: int
    cap_year: int
    annual_gross_sales_cents: int
    permitted_radius_km: float
    payout_period_start: str
    payout_net_cents: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    baker_id: str
    display_name: str
    email: str
    delivery_distance_km: float
    allergen_avoidances: List[dict]
    unattended_consent: bool
    cooler_provided: bool
    credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Recipe(TypedDict):
    id: str
    baker_id: str
    name: str
    recipe_status: str
    published_version: int
    allergen_union: List[str]
    tree_depth: int
    cross_contact_advisory: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecipeComponent(TypedDict):
    id: str
    recipe_id: str
    sub_recipe_id: Optional[str]
    ingredient_lot_id: Optional[str]
    component_name: str
    declared_allergens: List[str]
    quantity_grams: float
    recalled_component: bool
    created_at: str
    updated_at: str
    version: int


class IngredientLot(TypedDict):
    id: str
    baker_id: str
    lot_code: str
    allergens: List[str]
    cross_contact_allergens: List[str]
    lot_status: str
    received_at: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class MenuItem(TypedDict):
    id: str
    baker_id: str
    recipe_id: str
    name: str
    product_class: str
    pricing_basis: str
    unit_price_cents: int
    dozen_price_cents: int
    temp_sensitive: bool
    oven_profile: str
    oven_hours_per_batch: float
    yield_units_per_slot: int
    listing_status: str
    rating_avg: Optional[float]
    rating_count: int
    allergen_summary: List[str]
    created_at: str
    updated_at: str
    version: int


class OfferWindow(TypedDict):
    id: str
    baker_id: str
    label: str
    opens_at: str
    order_cutoff_at: str
    production_date: str
    handoff_date: str
    handoff_window_end_at: str
    window_status: str
    plan_status: str
    capacity_posture: str
    capacity_units: int
    capacity_batch_slots: int
    capacity_oven_hours: float
    confirmed_units: int
    held_units: int
    reserved_units: int
    cutoff_extension_count: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    offer_window_id: str
    subscription_cycle_id: Optional[str]
    delivery_route_id: Optional[str]
    channel: str
    handoff_mode: str
    source: str
    prepaid: bool
    order_status: str
    payment_status: str
    handoff_status: str
    placed_at: Optional[str]
    hold_expires_at: Optional[str]
    allergen_ack: bool
    unattended_consent: bool
    cooler_provided: bool
    delivery_distance_km: Optional[float]
    stop_sequence: Optional[int]
    subtotal_cents: int
    tax_total_cents: int
    delivery_fee_cents: int
    tip_cents: int
    credit_applied_cents: int
    grand_total_cents: int
    shortfall_flag: bool
    rebook_count: int
    pickup_forfeit_at: Optional[str]
    forfeit_latched: bool
    fulfilled_at: Optional[str]
    review_window_closes_at: Optional[str]
    review_window_closed_latch: bool
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    menu_item_id: str
    batch_id: Optional[str]
    quantity: int
    disposition: str
    line_status: str
    pricing_basis_applied: str
    taxable: bool
    line_total_cents: int
    line_tax_cents: int
    allocated_units: int
    shorted_units: int
    allergen_union: List[str]
    hold_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Batch(TypedDict):
    id: str
    offer_window_id: str
    menu_item_id: str
    recipe_id: str
    batch_status: str
    slot_count: int
    planned_yield_units: int
    actual_yield_units: Optional[int]
    surplus_units: int
    oven_hours: float
    recipe_version_pinned: int
    created_at: str
    updated_at: str
    version: int


class Label(TypedDict):
    id: str
    order_line_id: str
    recipe_id: str
    recipe_version_pinned: int
    label_status: str
    net_weight_grams: float
    allergen_union: List[str]
    cross_contact_advisory: Optional[str]
    statement_text: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    customer_id: str
    menu_item_id: str
    cadence: str
    units_per_cycle: int
    billing_mode: str
    handoff_mode: str
    sub_status: str
    pause_count: int
    past_due_since: Optional[str]
    prepaid_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class SubscriptionCycle(TypedDict):
    id: str
    subscription_id: str
    offer_window_id: str
    sequence_number: int
    cycle_status: str
    reserved_units: int
    skip_deadline_at: Optional[str]
    cycle_price_cents: int
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    order_id: str
    payment_state: str
    outcome: str
    tip_mode: str
    tip_pct: Optional[float]
    tip_fixed_cents: Optional[int]
    tip_cents: int
    authorized_cents: int
    captured_cents: int
    refunded_cents: int
    created_at: str
    updated_at: str
    version: int


class MoneyMovement(TypedDict):
    """Append-only ledger entry: id and created_at only, no updated_at, no version."""
    id: str
    customer_id: str
    order_id: Optional[str]
    payment_id: Optional[str]
    subscription_id: Optional[str]
    ledger_scope: str
    movement_kind: str
    reason: str
    amount_cents: int
    leg_tip_cents: int
    leg_delivery_fee_cents: int
    leg_subtotal_cents: int
    leg_credit_cents: int
    expires_at: Optional[str]
    created_at: str


class DeliveryRoute(TypedDict):
    id: str
    baker_id: str
    offer_window_id: str
    route_status: str
    stop_count: int
    total_distance_km: float
    dispatched_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Review(TypedDict):
    id: str
    order_id: str
    menu_item_id: str
    customer_id: str
    rating: int
    body: str
    review_status: str
    baker_response: Optional[str]
    responded_at: Optional[str]
    shortfall_affected: bool
    counts_toward_rollup: bool
    created_at: str
    updated_at: str
    version: int
