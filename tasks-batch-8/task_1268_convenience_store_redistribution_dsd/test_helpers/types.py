"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    WholesaleAdmin = "WholesaleAdmin"
    SalesRep = "SalesRep"
    StoreManager = "StoreManager"
    RouteDriver = "RouteDriver"
    CreditManager = "CreditManager"


class JurisdictionCode(str, Enum):
    CA_NORTH = "CA_NORTH"
    CA_SOUTH = "CA_SOUTH"
    NV_CLARK = "NV_CLARK"
    AZ_MARICOPA = "AZ_MARICOPA"


class CreditTerms(str, Enum):
    COD = "COD"
    NET7 = "NET7"
    NET14 = "NET14"


class CreditStatus(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    CREDIT_HOLD = "CREDIT_HOLD"


class DeliveryDay(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"


class OrderGuideStatus(str, Enum):
    ACTIVE = "ACTIVE"


class PromoType(str, Enum):
    OFF_INVOICE = "OFF_INVOICE"
    SCAN_BACK = "SCAN_BACK"


class PromoStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class RetailPriceRecordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class TaxStampSupplyStatus(str, Enum):
    ACTIVE = "ACTIVE"


class ManifestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LOADING = "LOADING"
    CLOSED = "CLOSED"
    COMPLETED = "COMPLETED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ASSIGNED = "ASSIGNED"
    CLOSED = "CLOSED"
    DELIVERED = "DELIVERED"
    INVOICED = "INVOICED"
    CANCELLED = "CANCELLED"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    PAST_DUE = "PAST_DUE"


class PaymentMethod(str, Enum):
    CASH_ON_DELIVERY = "CASH_ON_DELIVERY"
    CHECK = "CHECK"
    ACH = "ACH"


class PaymentStatus(str, Enum):
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"


class CreditMemoOrigin(str, Enum):
    SHORT = "SHORT"
    DAMAGE = "DAMAGE"
    MANUAL = "MANUAL"


class CreditMemoStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class ExceptionType(str, Enum):
    SHORT = "SHORT"
    DAMAGE = "DAMAGE"


class ExceptionStatus(str, Enum):
    RECORDED = "RECORDED"
    CREDITED = "CREDITED"


class NewItemRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    AUTHORIZED = "AUTHORIZED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Entities (common_fields: true) — id + created_at + updated_at + version.
# ---------------------------------------------------------------------------


class Retailer(TypedDict, total=False):
    id: str
    store_name: str
    jurisdiction_code: str
    credit_terms: str
    credit_limit_cents: int
    credit_status: str
    tobacco_license_id: Optional[str]
    ar_balance_cents: int
    exposure_forward_cents: int
    delivery_day: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    sku: str
    description: str
    case_pack_units: int
    case_cost_cents: int
    unit_cost_cents: int
    split_case_allowed: bool
    is_tobacco: bool
    weight_lbs_per_case: float
    status: str
    created_at: str
    updated_at: str
    version: int


class OrderGuideLine(TypedDict, total=False):
    product_id: str
    par_cases: int


class OrderGuide(TypedDict, total=False):
    id: str
    retailer_id: str
    delivery_day: str
    cutoff_hours_before: int
    lines: List[OrderGuideLine]
    status: str
    created_at: str
    updated_at: str
    version: int


class PromoEvent(TypedDict, total=False):
    id: str
    product_id: str
    promo_type: str
    discount_pct_bps: int
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RetailPriceRecord(TypedDict, total=False):
    id: str
    retailer_id: str
    product_id: str
    shelf_price_cents: int
    effective_start: str
    effective_end: Optional[str]
    supersedes_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryWindow(TypedDict, total=False):
    id: str
    route_code: str
    window_start: str
    window_end: str
    turnaround_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class FuelSurchargeRate(TypedDict, total=False):
    id: str
    week_start_date: str
    doe_index_usd: float
    created_at: str
    updated_at: str
    version: int


class TaxStampSupply(TypedDict, total=False):
    id: str
    jurisdiction_code: str
    stamp_rate_cents_per_pack: int
    handling_fee_per_roll_cents: int
    packs_per_roll: int
    min_charge_cents: int
    rolls_on_hand: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryManifest(TypedDict, total=False):
    id: str
    route_code: str
    delivery_date: str
    status: str
    capacity_lbs: float
    total_weight_lbs: float
    overweight_flag: bool
    fuel_rate_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PurchaseOrder(TypedDict, total=False):
    id: str
    retailer_id: str
    order_guide_id: str
    manifest_id: Optional[str]
    status: str
    has_tobacco: bool
    merch_subtotal_cents: int
    promo_allowance_cents: int
    pick_fee_cents: int
    min_drop_fee_cents: int
    fuel_surcharge_cents: int
    tax_stamp_cost_cents: int
    provisional_total_cents: int
    final_total_cents: int
    weight_lbs: float
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# OrderLine (common_fields: false) — ONLY id + created_at; no updated_at/version.
# ---------------------------------------------------------------------------


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    product_id: str
    cases_qty: int
    split_units_qty: int
    line_merch_cents: int
    line_promo_cents: int
    delivered_cases: int
    delivered_split_units: int
    created_at: str


class Invoice(TypedDict, total=False):
    id: str
    order_id: str
    retailer_id: str
    invoiced_total_cents: int
    balance_cents: int
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    invoice_id: str
    amount_cents: int
    method: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CreditMemo(TypedDict, total=False):
    id: str
    invoice_id: str
    exception_id: Optional[str]
    origin: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryException(TypedDict, total=False):
    id: str
    manifest_id: str
    order_id: str
    order_line_id: str
    exception_type: str
    cases_qty: int
    split_units_qty: int
    credit_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class NewItemRequest(TypedDict, total=False):
    id: str
    retailer_id: str
    product_id: str
    proposed_shelf_price_cents: int
    slotting_fee_cents: int
    revision_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
