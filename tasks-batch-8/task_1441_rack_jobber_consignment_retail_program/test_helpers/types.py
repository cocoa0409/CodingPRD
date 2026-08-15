"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    JOBBER_ADMIN = "JobberAdmin"
    RETAILER_MANAGER = "RetailerManager"
    ROUTE_DRIVER = "RouteDriver"
    FIELD_AUDITOR = "FieldAuditor"
    JOBBER_FINANCE = "JobberFinance"


class ProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class StoreStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_ACCEPTANCE = "PENDING_ACCEPTANCE"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REJECTED = "REJECTED"
    TERMINATED = "TERMINATED"


class SettlementCadence(str, Enum):
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    MONTHLY = "MONTHLY"


class ShrinkValuationMode(str, Enum):
    JOBBER_COST = "JOBBER_COST"
    BLENDED_RETAIL = "BLENDED_RETAIL"


class MarkdownLiability(str, Enum):
    JOBBER = "JOBBER"
    RETAILER = "RETAILER"
    SHARED = "SHARED"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class RackCategory(str, Enum):
    SNACKS = "SNACKS"
    BEVERAGES = "BEVERAGES"
    IMPULSE = "IMPULSE"
    HOUSEWARES = "HOUSEWARES"
    SEASONAL = "SEASONAL"
    PERSONAL_CARE = "PERSONAL_CARE"


class SpaceAllocationStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class PriceDirectiveStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"


class PromotionStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


class StockPosture(str, Enum):
    DEPLETED = "DEPLETED"
    LOW = "LOW"
    NORMAL = "NORMAL"


class RouteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ServiceVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    COUNTS_SUBMITTED = "COUNTS_SUBMITTED"
    CONFIRMED = "CONFIRMED"
    DISPUTED = "DISPUTED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class ScanEventType(str, Enum):
    SALE = "SALE"
    RETURN = "RETURN"
    VOID = "VOID"


class ScanEventStatus(str, Enum):
    MATCHED = "MATCHED"
    UNMATCHED = "UNMATCHED"


class AuditScope(str, Enum):
    FULL = "FULL"
    CATEGORY = "CATEGORY"


class AuditCountStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    DISPUTED = "DISPUTED"
    CERTIFIED = "CERTIFIED"
    LOCKED = "LOCKED"


class MarkdownAuthType(str, Enum):
    MARKDOWN = "MARKDOWN"
    RETURN_TO_VENDOR = "RETURN_TO_VENDOR"


class MarkdownAuthorizationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"
    EXPIRED = "EXPIRED"


class SettlementStatementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    DISPUTED = "DISPUTED"
    APPROVED = "APPROVED"
    PAID = "PAID"


class SettlementVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class SeasonalSetStatus(str, Enum):
    PLANNED = "PLANNED"
    SET_IN_PROGRESS = "SET_IN_PROGRESS"
    SET_COMPLETE = "SET_COMPLETE"
    ACTIVE_SEASON = "ACTIVE_SEASON"
    TEARDOWN_DUE = "TEARDOWN_DUE"
    TORN_DOWN = "TORN_DOWN"
    RECONCILED = "RECONCILED"


class Program(TypedDict, total=False):
    id: str
    name: str
    promo_min_gap_days: int
    min_payout_cents: int
    default_settlement_cadence: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Store(TypedDict, total=False):
    id: str
    name: str
    store_code: str
    total_facings: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StoreAgreement(TypedDict, total=False):
    id: str
    program_id: str
    store_id: str
    base_margin_pct: float
    tier1_threshold_cents: int
    tier1_uplift_pct: float
    tier2_threshold_cents: int
    tier2_uplift_pct: float
    min_margin_pct: float
    max_margin_pct: float
    shrink_retailer_share_pct: float
    free_allowance_pct: float
    shrink_suspend_ratio: float
    shrink_valuation_mode: str
    estimated_shrink_rate: float
    restock_value_cap_cents: int
    markdown_liability: str
    markdown_jobber_share_pct: float
    markdown_cap_pct_of_gross: float
    settlement_cadence: str
    service_frequency_days: int
    status: str
    activated_at: Optional[str]
    created_by_user_id: str
    cumulative_delivered_units: int
    cumulative_shrink_units: int
    cumulative_shrink_ratio: float
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    program_id: str
    sku: str
    name: str
    jobber_cost_cents: int
    min_retail_cents: int
    units_per_facing: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SpaceAllocation(TypedDict, total=False):
    id: str
    store_agreement_id: str
    store_id: str
    category: str
    facings: int
    window_start_date: str
    window_end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PriceDirective(TypedDict, total=False):
    id: str
    store_agreement_id: str
    product_id: str
    price_cents: int
    effective_from: str
    status: str
    superseded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Promotion(TypedDict, total=False):
    id: str
    program_id: str
    product_id: str
    name: str
    depth_pct: float
    jobber_funding_pct: float
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryBalance(TypedDict, total=False):
    id: str
    store_agreement_id: str
    product_id: str
    on_hand_units: int
    lifetime_delivered_units: int
    lifetime_scanned_units: int
    lifetime_customer_return_units: int
    lifetime_shrink_units: int
    lifetime_rma_units: int
    reorder_point_units: int
    stock_posture: str
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict, total=False):
    id: str
    program_id: str
    name: str
    assigned_driver_id: str
    service_frequency_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VisitCountLine(TypedDict, total=False):
    product_id: str
    counted_units: int
    restock_units: int


class ServiceVisit(TypedDict, total=False):
    id: str
    route_id: str
    store_agreement_id: str
    scheduled_date: str
    status: str
    submitted_lines: List[VisitCountLine]
    total_counted_units: int
    total_restock_units: int
    total_variance_units: int
    applied_restock_value_cents: int
    auto_restock_flag: bool
    suggested_restock_units: int
    created_at: str
    updated_at: str
    version: int


# ScanEvent is an append-only ledger entry: it carries id and created_at only;
# both updated_at and version are absent (PRD section 2.4).
class ScanEvent(TypedDict, total=False):
    id: str
    store_agreement_id: str
    product_id: str
    client_event_id: str
    event_type: str
    quantity: int
    scanned_at: str
    void_of_event_id: Optional[str]
    status: str
    unit_price_cents: Optional[int]
    line_value_cents: Optional[int]
    jobber_funding_cents: Optional[int]
    is_promo_priced: bool
    settled_in_statement_id: Optional[str]
    created_at: str


class AuditCountedLine(TypedDict, total=False):
    product_id: str
    counted_units: int


class AuditCount(TypedDict, total=False):
    id: str
    store_agreement_id: str
    scope: str
    category: Optional[str]
    status: str
    counted_lines: List[AuditCountedLine]
    counted_by_user_id: Optional[str]
    scanned_units_since_last_audit: int
    variance_units: int
    free_allowance_units: int
    chargeable_units: int
    valuation_unit_cents: Optional[int]
    variance_value_cents: int
    retailer_charge_cents: int
    submitted_at: Optional[str]
    certified_at: Optional[str]
    certified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MarkdownAuthorization(TypedDict, total=False):
    id: str
    store_agreement_id: str
    product_id: str
    auth_type: str
    units: int
    markdown_price_cents: Optional[int]
    status: str
    credit_cents: int
    approved_at: Optional[str]
    applied_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SettlementStatement(TypedDict, total=False):
    id: str
    store_agreement_id: str
    period_index: int
    period_start: str
    period_end: str
    status: str
    variant_used: str
    gross_scanned_sales_cents: int
    scanned_units: int
    promo_scan_units: int
    promo_jobber_funding_cents: int
    markdown_credit_cents: int
    net_sales_cents: int
    margin_pct: float
    retailer_margin_cents: int
    shrink_retailer_charge_cents: int
    teardown_penalty_cents: int
    net_payable_to_jobber_cents: int
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SeasonalSet(TypedDict, total=False):
    id: str
    store_agreement_id: str
    theme: str
    category: str
    allocated_facings: int
    set_window_start: str
    set_window_end: str
    teardown_deadline: str
    status: str
    actual_teardown_date: Optional[str]
    penalty_cents: int
    created_at: str
    updated_at: str
    version: int
