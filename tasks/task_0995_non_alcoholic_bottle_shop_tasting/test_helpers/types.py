"""Domain types: entity TypedDicts, status enums, role enum.

All resource shapes follow the uniform identity/audit shape from PRD §2.4:
every resource carries id, created_at, updated_at, and version.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums (PRD §3)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    MEMBER = "Member"
    SHOP_STAFF = "ShopStaff"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


class ComplianceClass(str, Enum):
    STANDARD = "STANDARD"
    SENSITIVE_INGREDIENT = "SENSITIVE_INGREDIENT"
    HEMP_DERIVED = "HEMP_DERIVED"
    KAVA = "KAVA"
    FUNCTIONAL_MUSHROOM = "FUNCTIONAL_MUSHROOM"


class AgeNeutralClass(str, Enum):
    OPEN = "OPEN"
    ADULT_ONLY_SUGGESTED = "ADULT_ONLY_SUGGESTED"
    ADULT_ONLY_REQUIRED = "ADULT_ONLY_REQUIRED"
    PROHIBITED_STATE_LIST = "PROHIBITED_STATE_LIST"


class LotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"
    EXPIRED = "EXPIRED"
    QUARANTINED = "QUARANTINED"


class AgeAttestationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    PENDING_REVIEW = "PENDING_REVIEW"
    ATTESTED = "ATTESTED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class LoyaltyTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class ClubCadence(str, Enum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    ANNUAL = "ANNUAL"


class ClubSubscriptionStatus(str, Enum):
    TRIALING = "TRIALING"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class TastingEventStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    LOCKED = "LOCKED"
    IN_SESSION = "IN_SESSION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    RESCHEDULED = "RESCHEDULED"


class TastingSeatStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class SpecialOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    SOURCED = "SOURCED"
    RECEIVED = "RECEIVED"
    FULFILLED = "FULFILLED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"


class OrderChannel(str, Enum):
    RETAIL = "RETAIL"
    DTC = "DTC"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    REFUNDED_PARTIAL = "REFUNDED_PARTIAL"
    REFUNDED_FULL = "REFUNDED_FULL"
    VOIDED = "VOIDED"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    PICKING = "PICKING"
    PACKED = "PACKED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    PICKED_UP = "PICKED_UP"
    CANCELLED = "CANCELLED"


class ShipmentStatus(str, Enum):
    LABEL_CREATED = "LABEL_CREATED"
    IN_TRANSIT = "IN_TRANSIT"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"
    LOST = "LOST"


class AttestationOutcome(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all entities carry the full common audit shape)
# ---------------------------------------------------------------------------

class Category(TypedDict, total=False):
    id: str
    code: str
    display_name: str
    compliance_class: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class SKU(TypedDict, total=False):
    id: str
    category_id: str
    sku_code: str
    title: str
    base_price_cents: int
    abv_basis_points: int
    age_neutral_class: str
    ship_state_overrides: List[Any]
    discontinued: bool
    on_hand_cached: int
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict, total=False):
    id: str
    sku_id: str
    lot_code: str
    qty_received: int
    qty_remaining: int
    unit_cost_cents: int
    expires_on: str
    status: str
    quarantine_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    date_of_birth: str
    home_state_code: str
    age_attestation_status: str
    loyalty_tier: str
    loyalty_points_balance: int
    loyalty_points_lifetime: int
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class ClubPlan(TypedDict, total=False):
    id: str
    code: str
    cadence: str
    bottles_per_shipment: int
    price_cents_per_cycle: int
    allowed_category_ids: List[str]
    discount_bps_on_retail: int
    max_active_subscriptions: int
    active_subscription_count: int
    created_at: str
    updated_at: str
    version: int


class ClubSubscription(TypedDict, total=False):
    id: str
    plan_id: str
    member_id: str
    status: str
    started_on: str
    trial_days: int
    next_billing_on: str
    failed_billing_count: int
    shipments_fulfilled: int
    pause_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TastingEvent(TypedDict, total=False):
    id: str
    title: str
    host_member_id: str
    starts_at: str
    ends_at: str
    capacity: int
    seats_booked: int
    status: str
    flight_price_cents: int
    min_attendee_age_years: int
    compliance_hold: bool
    created_at: str
    updated_at: str
    version: int


class FlightItem(TypedDict, total=False):
    id: str
    tasting_event_id: str
    sku_id: str
    pour_size_ml: int
    sequence_no: int
    estimated_bottle_consumption: float
    created_at: str
    updated_at: str
    version: int


class TastingSeat(TypedDict, total=False):
    id: str
    tasting_event_id: str
    member_id: str
    status: str
    price_paid_cents: int
    booked_at: str
    loyalty_points_awarded: int
    created_at: str
    updated_at: str
    version: int


class SpecialOrder(TypedDict, total=False):
    id: str
    member_id: str
    requested_sku_code: str
    quantity: int
    resolved_sku_id: Optional[str]
    deposit_cents: int
    status: str
    approved_by_user_id: Optional[str]
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    member_id: str
    channel: str
    ship_to_state_code: Optional[str]
    payment_status: str
    fulfillment_status: str
    subtotal_cents: int
    discount_cents: int
    shipping_charge_cents: int
    tax_cents: int
    grand_total_cents: int
    loyalty_points_redeemed: int
    loyalty_points_earned: int
    applied_club_subscription_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    sku_id: str
    qty: int
    unit_price_cents: int
    extended_price_cents: int
    lot_allocation: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    order_id: str
    club_subscription_id: Optional[str]
    carrier: str
    tracking_no: str
    status: str
    shipped_on: str
    delivered_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShippingStateRule(TypedDict, total=False):
    id: str
    state_code: str
    allows_dtc: bool
    min_age_years: int
    abv_cap_basis_points: int
    surcharge_cents_per_order: int
    tax_rate_bps: int
    created_at: str
    updated_at: str
    version: int


class ComplianceAttestation(TypedDict, total=False):
    id: str
    member_id: str
    attested_by_user_id: str
    outcome: str
    attested_on: str
    document_reference: str
    created_at: str
    updated_at: str
    version: int
