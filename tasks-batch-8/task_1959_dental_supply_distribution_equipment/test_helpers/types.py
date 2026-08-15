"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class UserRole(str, Enum):
    DISTRIBUTION_ADMIN = "DistributionAdmin"
    SALES_REP = "SalesRep"
    PRACTICE_MANAGER = "PracticeManager"
    SERVICE_DISPATCHER = "ServiceDispatcher"
    FIELD_TECHNICIAN = "FieldTechnician"
    MANUFACTURER_AGENT = "ManufacturerAgent"


class PracticeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PracticeTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIER = "PREMIER"
    ELITE = "ELITE"


class ProductKind(str, Enum):
    CONSUMABLE = "CONSUMABLE"
    EQUIPMENT = "EQUIPMENT"
    PART = "PART"
    REGULATED = "REGULATED"


class OrderKind(str, Enum):
    MANUAL = "MANUAL"
    AUTO = "AUTO"
    STARTUP = "STARTUP"
    BUNDLE = "BUNDLE"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class EquipmentSaleStatus(str, Enum):
    QUOTE = "QUOTE"
    CONFIRMED = "CONFIRMED"
    INSTALL_SCHEDULED = "INSTALL_SCHEDULED"
    INSTALLED = "INSTALLED"
    TRAINED = "TRAINED"
    ACCEPTED = "ACCEPTED"


class TechnicianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class Certification(str, Enum):
    INSTALL = "INSTALL"
    REPAIR = "REPAIR"
    STERILIZATION = "STERILIZATION"


class ServiceTicketStatus(str, Enum):
    OPEN = "OPEN"
    COVERAGE_ASSESSED = "COVERAGE_ASSESSED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    DISPATCHED = "DISPATCHED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class CoverageDetermination(str, Enum):
    WARRANTY = "WARRANTY"
    SERVICE_PLAN = "SERVICE_PLAN"
    BILLABLE = "BILLABLE"


class DispatchJobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class CoverageType(str, Enum):
    WARRANTY = "WARRANTY"
    SERVICE_PLAN = "SERVICE_PLAN"


class CoverageAgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    EXHAUSTED = "EXHAUSTED"


class PromoKind(str, Enum):
    BUNDLE_DISCOUNT = "BUNDLE_DISCOUNT"
    MANUFACTURER_REBATE = "MANUFACTURER_REBATE"


class PromotionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    EXHAUSTED = "EXHAUSTED"


class RebateClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DENIED = "DENIED"
    PAID = "PAID"


class TradeInStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPRAISED = "APPRAISED"
    ACCEPTED = "ACCEPTED"
    CREDITED = "CREDITED"
    DISPOSED = "DISPOSED"


class ValuationMethod(str, Enum):
    MARKET_VALUE = "MARKET_VALUE"
    SCRAP_VALUE = "SCRAP_VALUE"


class TradeInCondition(str, Enum):
    WORKING = "WORKING"
    NEEDS_REPAIR = "NEEDS_REPAIR"
    SCRAP = "SCRAP"


class DisposalMethod(str, Enum):
    RECYCLE = "RECYCLE"
    RESALE_PARTS = "RESALE_PARTS"
    HAZMAT = "HAZMAT"


# All entities carry the PRD §2.4 common fields (id, created_at, updated_at, version).

class Practice(TypedDict, total=False):
    id: str
    name: str
    region: str
    practice_tier: str
    credit_limit_cents: int
    credit_available_cents: int
    regulated_license_expiry: Optional[str]
    sterilization_compliant: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    sku: str
    name: str
    kind: str
    unit_price_cents: int
    manufacturer: str
    max_qty_per_order: Optional[int]
    sterilization_cycle_required: bool
    warranty_months: int
    created_at: str
    updated_at: str
    version: int


class UsageProfile(TypedDict, total=False):
    id: str
    practice_id: str
    product_id: str
    reorder_point: float
    target_stock_level: float
    auto_replenish_enabled: bool
    average_daily_usage: float
    on_hand_estimate: float
    last_evaluated_at: str
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    product_id: str
    quantity: int
    unit_price_cents: int
    line_total_cents: int


class Order(TypedDict, total=False):
    id: str
    practice_id: str
    kind: str
    promotion_id: Optional[str]
    lines: List[OrderLine]
    status: str
    subtotal_cents: int
    volume_discount_cents: int
    bundle_discount_cents: int
    discount_cents: int
    total_cents: int
    submitted_at: Optional[str]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EquipmentSale(TypedDict, total=False):
    id: str
    practice_id: str
    product_id: str
    sale_price_cents: int
    status: str
    installer_technician_id: Optional[str]
    install_window_start: Optional[str]
    install_window_end: Optional[str]
    install_rework_count: int
    training_minutes: Optional[int]
    trade_in_id: Optional[str]
    trade_in_credit_cents: Optional[int]
    warranty_agreement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VanStockEntry(TypedDict, total=False):
    product_id: str
    quantity_on_van: int
    min_quantity: int


class Technician(TypedDict, total=False):
    id: str
    name: str
    region: str
    certifications: List[str]
    status: str
    van_stock: List[VanStockEntry]
    created_at: str
    updated_at: str
    version: int


class PartsUsedEntry(TypedDict, total=False):
    product_id: str
    quantity: int


class ServiceTicket(TypedDict, total=False):
    id: str
    practice_id: str
    equipment_sale_id: str
    issue_description: str
    status: str
    coverage_determination: Optional[str]
    coverage_agreement_id: Optional[str]
    estimate_cents: Optional[int]
    parts_used: Optional[List[PartsUsedEntry]]
    labor_minutes: Optional[int]
    customer_due_cents: Optional[int]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DispatchJob(TypedDict, total=False):
    id: str
    service_ticket_id: str
    technician_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CoverageAgreement(TypedDict, total=False):
    id: str
    practice_id: str
    equipment_sale_id: str
    coverage_type: str
    start_date: str
    end_date: str
    deductible_cents: int
    coverage_cap_cents: Optional[int]
    used_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Promotion(TypedDict, total=False):
    id: str
    name: str
    promo_kind: str
    required_product_ids: Optional[List[str]]
    eligible_product_ids: Optional[List[str]]
    discount_pct: Optional[float]
    max_discount_cents: Optional[int]
    rebate_per_unit_cents: Optional[int]
    stacking_allowed: bool
    fund_total_cents: Optional[int]
    fund_remaining_cents: Optional[int]
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RebateClaim(TypedDict, total=False):
    id: str
    practice_id: str
    order_id: str
    promotion_id: str
    claim_amount_cents: int
    status: str
    submitted_at: Optional[str]
    paid_at: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TradeIn(TypedDict, total=False):
    id: str
    practice_id: str
    description: str
    equipment_age_months: int
    condition: str
    category_base_value_cents: int
    valuation_method: Optional[str]
    appraised_value_cents: Optional[int]
    applied_to_equipment_sale_id: Optional[str]
    disposal_method: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
