"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.7, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------


class ProductCategory(str, Enum):
    GASOLINE = "GASOLINE"
    DIESEL = "DIESEL"


class OperatingStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class CreditStatus(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    WATCH = "WATCH"
    HOLD = "HOLD"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    CURE_PERIOD = "CURE_PERIOD"
    DEFAULT = "DEFAULT"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    DEFAULT_NOTICE = "DEFAULT_NOTICE"
    BUYOUT_PENDING = "BUYOUT_PENDING"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"
    BOUGHT_OUT = "BOUGHT_OUT"


class BuyoutMethod(str, Enum):
    UNAMORTIZED_DISCOUNT = "UNAMORTIZED_DISCOUNT"
    LOST_MARGIN = "LOST_MARGIN"


class PostingStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    SUPERSEDED = "SUPERSEDED"
    DISCARDED = "DISCARDED"


class DropStatus(str, Enum):
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    DELIVERED = "DELIVERED"
    DELIVERY_FAILED = "DELIVERY_FAILED"
    RECONCILED = "RECONCILED"
    CANCELLED = "CANCELLED"


class LossType(str, Enum):
    DRIVE_OFF = "DRIVE_OFF"
    SHRINKAGE = "SHRINKAGE"
    SPILL = "SPILL"
    THEFT = "THEFT"


class LossStatus(str, Enum):
    REPORTED = "REPORTED"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    WRITTEN_OFF = "WRITTEN_OFF"
    VOIDED = "VOIDED"


class ReconciliationStatus(str, Enum):
    OPEN = "OPEN"
    VARIANCE_FLAGGED = "VARIANCE_FLAGGED"
    RESOLVED = "RESOLVED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    OVERDUE = "OVERDUE"
    PAID = "PAID"
    VOID = "VOID"


class DraftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SETTLED = "SETTLED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class DraftOutcome(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class RemittanceStatus(str, Enum):
    ACCRUING = "ACCRUING"
    FILED = "FILED"
    PAID = "PAID"


class AuditResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class UserRole(str, Enum):
    JOBBER_ADMIN = "JobberAdmin"
    PRICING_DESK = "PricingDesk"
    DISPATCHER = "Dispatcher"
    CREDIT_MANAGER = "CreditManager"
    TAX_ACCOUNTANT = "TaxAccountant"
    BRAND_INSPECTOR = "BrandInspector"
    DEALER_OPERATOR = "DealerOperator"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------


class Product(TypedDict):
    id: str
    product_code: str
    display_name: str
    category: str
    federal_excise_tc_per_gal: int
    temp_coeff: float
    created_at: str
    updated_at: str
    version: int


class DealerStation(TypedDict):
    id: str
    station_name: str
    state_code: str
    home_terminal_code: str
    state_excise_tc_per_gal: int
    local_option_tc_per_gal: int
    credit_limit_cents: int
    credit_terms_days: int
    current_exposure_cents: int
    operating_status: str
    credit_status: str
    compliance_status: str
    cure_started_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupplyAgreement(TypedDict):
    id: str
    station_id: str
    term_start_date: str
    term_end_date: str
    committed_gallons: int
    fulfilled_gallons: int
    imaging_allowance_cents: int
    margin_tc_per_gal: int
    shortfall_penalty_tc_per_gal: int
    buyout_method: str
    renewal_count: int
    renewal_credit_cents: int
    buyout_settlement_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class BuyoutQuote(TypedDict):
    method: str
    base_cents: int
    alternate_base_cents: int
    shortfall_penalty_cents: int
    net_settlement_cents: int


class RackPricePosting(TypedDict):
    id: str
    terminal_code: str
    product_id: str
    effective_date: str
    price_tc_per_gal: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StorageTank(TypedDict):
    id: str
    station_id: str
    product_id: str
    capacity_gallons: int
    safe_fill_pct: float
    opening_physical_gallons: int
    physical_gallons: float
    physical_temp_f: Optional[float]
    book_inventory_gallons: float
    created_at: str
    updated_at: str
    version: int


class Truck(TypedDict):
    id: str
    truck_code: str
    capacity_gallons: int
    created_at: str
    updated_at: str
    version: int


class TransportDrop(TypedDict):
    id: str
    station_id: str
    tank_id: str
    truck_id: str
    product_id: str
    planned_gallons: int
    window_start: str
    window_end: str
    delivered_gallons: Optional[int]
    delivered_at: Optional[str]
    estimated_amount_cents: int
    invoice_id: Optional[str]
    failure_count: int
    failure_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only; only id + created_at + entity fields
class MeterReading(TypedDict):
    id: str
    tank_id: str
    reading_at: str
    totalizer_gallons: int
    metered_gallons: int
    created_at: str


class LossEvent(TypedDict):
    id: str
    station_id: str
    tank_id: Optional[str]
    reconciliation_id: Optional[str]
    loss_type: str
    gallons: int
    occurred_at: str
    auto_generated: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryReconciliation(TypedDict):
    id: str
    station_id: str
    period_start: str
    period_end: str
    threshold_gallons: int
    book_gallons: float
    physical_gross_gallons: float
    variance_gross_gallons: float
    variance_net_gallons: float
    status: str
    opener_user_id: str
    resolver_user_id: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    station_id: str
    drop_id: str
    product_id: str
    gallons_delivered: int
    price_tc_per_gal: int
    fuel_amount_cents: int
    freight_amount_cents: int
    tax_amount_cents: int
    total_cents: int
    invoice_date: str
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EFTDraft(TypedDict):
    id: str
    invoice_id: str
    station_id: str
    scheduled_date: str
    amount_cents: int
    attempts: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxRemittance(TypedDict):
    id: str
    state_code: str
    period_start: str
    period_end: str
    due_date: str
    gasoline_gallons: int
    diesel_gallons: int
    tax_amount_cents: int
    late_penalty_cents: int
    total_due_cents: int
    filed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only; only id + created_at + entity fields
class BrandComplianceAudit(TypedDict):
    id: str
    station_id: str
    audit_date: str
    score: int
    deficiencies: List[str]
    result: str
    created_at: str
