"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity model (PRD Sections 2.4 and 3). Entities that
carry the full common field set expose id + created_at + updated_at + version;
the append-only credit ledger entry carries only id + created_at (PRD 2.4).
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CUSTOMER = "Customer"
    AGRONOMIST = "Agronomist"
    FULFILLMENT_OPS = "FulfillmentOps"
    PLATFORM_ADMIN = "PlatformAdmin"


class ClimateZone(str, Enum):
    COOL = "COOL"
    TRANSITION = "TRANSITION"
    WARM = "WARM"


class GrassType(str, Enum):
    COOL_SEASON = "COOL_SEASON"
    WARM_SEASON = "WARM_SEASON"
    MIXED = "MIXED"


class ProductCategory(str, Enum):
    FERTILIZER = "FERTILIZER"
    WEED = "WEED"
    PEST = "PEST"
    SEED = "SEED"
    SOIL_AMENDMENT = "SOIL_AMENDMENT"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CHURNED = "CHURNED"


class LawnStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class SoilTestStatus(str, Enum):
    KIT_SHIPPED = "KIT_SHIPPED"
    SAMPLE_RETURNED = "SAMPLE_RETURNED"
    ANALYZED = "ANALYZED"


class LabOutcome(str, Enum):
    ANALYZED = "ANALYZED"
    REJECTED = "REJECTED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class BillingCycle(str, Enum):
    MONTHLY = "MONTHLY"
    ANNUAL = "ANNUAL"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    PAST_DUE = "PAST_DUE"
    CANCELLED = "CANCELLED"


class BoxKind(str, Enum):
    SEASONAL = "SEASONAL"
    ADDON = "ADDON"
    REPLACEMENT = "REPLACEMENT"


class FulfillmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PICKING = "PICKING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    HELD = "HELD"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    PENDING = "PENDING"
    INVOICED = "INVOICED"
    PAID = "PAID"
    FAILED = "FAILED"
    VOID = "VOID"


class ApplicationStatus(str, Enum):
    AWAITING_DELIVERY = "AWAITING_DELIVERY"
    SCHEDULED = "SCHEDULED"
    FROZEN = "FROZEN"
    APPLIED = "APPLIED"
    CANCELLED = "CANCELLED"


class AddOnStatus(str, Enum):
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ClaimReason(str, Enum):
    INEFFECTIVE = "INEFFECTIVE"
    DAMAGED = "DAMAGED"
    WRONG_PRODUCT = "WRONG_PRODUCT"
    OTHER = "OTHER"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    RESOLVED = "RESOLVED"
    DENIED = "DENIED"


class ResolutionType(str, Enum):
    RESHIP = "RESHIP"
    CREDIT = "CREDIT"
    REFUND = "REFUND"
    DENY = "DENY"


class ReferralStatus(str, Enum):
    PENDING = "PENDING"
    QUALIFIED = "QUALIFIED"
    REVOKED = "REVOKED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    FAILED = "FAILED"
    VOID = "VOID"


class PaymentOutcome(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class LedgerEntryType(str, Enum):
    EARN_REFERRAL = "EARN_REFERRAL"
    REVOKE_REFERRAL = "REVOKE_REFERRAL"
    EARN_SATISFACTION = "EARN_SATISFACTION"
    REDEEM_INVOICE = "REDEEM_INVOICE"
    RESTORE_VOID_INVOICE = "RESTORE_VOID_INVOICE"
    ADJUSTMENT = "ADJUSTMENT"


class PlanLine(TypedDict):
    product_sku: str
    qty_units: int
    target_month: int


class ShipmentLine(TypedDict):
    product_sku: str
    qty_units: int


class InvoiceLine(TypedDict):
    product_sku: str
    qty_units: int
    unit_price_cents: int
    line_discount_pct: float
    line_total_cents: int


# --- Entities with the full common field set (id, created_at, updated_at, version) ---


class Customer(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    climate_zone: str
    referral_code: str
    credit_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LawnProfile(TypedDict, total=False):
    id: str
    customer_id: str
    label: str
    lawn_size_sqm: int
    grass_type: str
    region: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SoilTestKit(TypedDict, total=False):
    id: str
    lawn_id: str
    status: str
    reship_count: int
    rejection_reason: Optional[str]
    ph: Optional[float]
    nitrogen_ppm: Optional[float]
    phosphorus_ppm: Optional[float]
    potassium_ppm: Optional[float]
    organic_matter_pct: Optional[float]
    analyzed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlanVersion(TypedDict, total=False):
    id: str
    lawn_id: str
    soil_test_id: str
    season_year: int
    plan_lines: List[PlanLine]
    status: str
    provisional_value_cents: int
    committed_value_cents: Optional[int]
    discount_pct_locked: Optional[float]
    supersedes_plan_id: Optional[str]
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    customer_id: str
    plan_id: str
    billing_cycle: str
    auto_ship: bool
    status: str
    next_ship_date: Optional[str]
    skips_used_in_window: int
    skip_window_anchor: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShipmentBox(TypedDict, total=False):
    id: str
    subscription_id: str
    box_kind: str
    fulfillment_status: str
    billing_status: str
    ship_date: str
    delivery_window_start: str
    delivery_window_end: str
    lines: List[ShipmentLine]
    provisional_charge_cents: int
    final_charge_cents: Optional[int]
    delivered_at: Optional[str]
    source_claim_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ApplicationTask(TypedDict, total=False):
    id: str
    lawn_id: str
    subscription_id: str
    shipment_id: str
    product_sku: str
    scheduled_date: str
    status: str
    window_start_date: str
    window_end_date: str
    snooze_count: int
    applied_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WeatherAdvisory(TypedDict, total=False):
    id: str
    region: str
    date: str
    rain_probability: float
    wind_kph: int
    temp_high_c: int
    created_at: str
    updated_at: str
    version: int


class AddOnOrder(TypedDict, total=False):
    id: str
    subscription_id: str
    add_on_sku: str
    qty_units: int
    status: str
    quoted_price_cents: int
    quote_expires_at: str
    attached_shipment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SatisfactionClaim(TypedDict, total=False):
    id: str
    subscription_id: str
    shipment_id: str
    claim_reason: str
    evidence_url: Optional[str]
    status: str
    resolution_type: Optional[str]
    credit_amount_cents: Optional[int]
    filed_at: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict, total=False):
    id: str
    referrer_customer_id: str
    referee_customer_id: str
    referral_code_used: str
    status: str
    provisional_credit_cents: int
    qualified_credit_cents: Optional[int]
    referee_first_invoice_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    subscription_id: str
    shipment_id: str
    line_items: List[InvoiceLine]
    subtotal_cents: int
    credit_applied_cents: int
    total_cents: int
    status: str
    issued_at: str
    created_at: str
    updated_at: str
    version: int


class CatalogProduct(TypedDict, total=False):
    id: str
    sku: str
    name: str
    category: str
    list_price_cents: int
    tier_t1_cents: int
    tier_t2_cents: int
    tier_t3_cents: int
    add_on_flat_price_cents: Optional[int]
    window_start_md: str
    window_end_md: str
    conflicting_categories: List[str]
    min_gap_days: int
    active: bool
    created_at: str
    updated_at: str
    version: int


# --- Append-only entity: carries ONLY id + created_at from the common set ---
# PRD 2.4: a CreditLedgerEntry never exposes updated_at or version.


class CreditLedgerEntry(TypedDict, total=False):
    id: str
    customer_id: str
    entry_type: str
    amount_cents: int
    reference_id: Optional[str]
    note: Optional[str]
    created_at: str
