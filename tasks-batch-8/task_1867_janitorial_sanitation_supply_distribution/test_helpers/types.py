"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Every resource carries the four
system-managed fields id + created_at + updated_at + version (PRD section on
resource identity and common fields).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    DISTRIBUTOR_ADMIN = "DistributorAdmin"
    FACILITY_MANAGER = "FacilityManager"
    SALES_REP = "SalesRep"
    FIELD_TECHNICIAN = "FieldTechnician"


class FacilityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SHORTAGE = "SHORTAGE"
    DISCONTINUED = "DISCONTINUED"


class ProductCategory(str, Enum):
    CHEMICAL = "CHEMICAL"
    PAPER = "PAPER"
    EQUIPMENT = "EQUIPMENT"
    DISPENSER_SUPPLY = "DISPENSER_SUPPLY"
    OTHER = "OTHER"


class ChemicalFamily(str, Enum):
    ACID = "ACID"
    ALKALINE = "ALKALINE"
    NEUTRAL = "NEUTRAL"
    OXIDIZER = "OXIDIZER"
    NONE = "NONE"


class UsageRecordStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    POSTED = "POSTED"


class UsageSource(str, Enum):
    MANUAL = "MANUAL"
    AUTO_DISPENSER = "AUTO_DISPENSER"


class ForecastVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class TechnicianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class DispenserStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    INSTALLED = "INSTALLED"
    DECOMMISSIONED = "DECOMMISSIONED"


class TrainingRecordStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CERTIFIED = "CERTIFIED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class StandingOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class PauseReason(str, Enum):
    NONE = "NONE"
    MANUAL = "MANUAL"
    SUSPENSION = "SUSPENSION"


class StandingOrderFrequency(str, Enum):
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    MONTHLY = "MONTHLY"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"
    PARTIALLY_BLOCKED = "PARTIALLY_BLOCKED"
    DELIVERED = "DELIVERED"
    INVOICED = "INVOICED"
    CANCELLED = "CANCELLED"


class OrderSource(str, Enum):
    MANUAL = "MANUAL"
    STANDING_ORDER = "STANDING_ORDER"
    TRIAL_CONVERSION = "TRIAL_CONVERSION"


class FuelSurchargeVariant(str, Enum):
    QUOTED = "QUOTED"
    ACTUAL = "ACTUAL"


class OrderLineStatus(str, Enum):
    PENDING = "PENDING"
    ALLOCATED = "ALLOCATED"
    SUBSTITUTION_PENDING = "SUBSTITUTION_PENDING"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class ContractBidStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    AWARDED = "AWARDED"
    LOST = "LOST"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class SubstitutionProposalStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class TrialProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONVERTED = "CONVERTED"
    EXPIRED = "EXPIRED"


class Facility(TypedDict, total=False):
    id: str
    name: str
    facility_group_code: str
    credit_limit_cents: int
    service_zone: str
    delivery_distance_miles: float
    default_delivery_day: str
    status: str
    committed_cents: int
    outstanding_cents: int
    closed_loop_enrolled: bool
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    sku: str
    name: str
    category: str
    base_price_cents: int
    unit_of_measure: str
    dilution_required: bool
    chemical_family: str
    qty_on_hand: int
    qty_allocated: int
    status: str
    created_at: str
    updated_at: str
    version: int


class UsageRecord(TypedDict, total=False):
    id: str
    facility_id: str
    product_id: str
    period_start: str
    period_end: str
    quantity_used: int
    source: str
    status: str
    posted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ForecastProfile(TypedDict, total=False):
    id: str
    facility_id: str
    product_id: str
    horizon_days: int
    safety_stock: int
    current_on_hand: int
    avg_daily_usage: float
    reorder_point: int
    recommended_qty: int
    replenishment_recommended: bool
    variant_used: Optional[str]
    last_computed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict, total=False):
    id: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispenser(TypedDict, total=False):
    id: str
    facility_id: str
    product_id: str
    zone: str
    technician_id: str
    install_start: str
    install_end: str
    status: str
    installed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrainingRecord(TypedDict, total=False):
    id: str
    facility_id: str
    product_id: str
    employee_name: str
    status: str
    score_pct: Optional[int]
    certified_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StandingOrderItem(TypedDict, total=False):
    product_id: str
    qty: int


class StandingOrder(TypedDict, total=False):
    id: str
    facility_id: str
    items: List[StandingOrderItem]
    frequency: str
    next_run_date: str
    fuel_index: float
    status: str
    pause_reason: str
    price_protected: bool
    next_delivery_total_cents: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    facility_id: str
    standing_order_id: Optional[str]
    source: str
    delivery_date: str
    fuel_index: float
    fuel_index_at_delivery: Optional[float]
    merchandise_subtotal_cents: int
    delivery_fee_cents: int
    fuel_surcharge_cents: int
    fuel_surcharge_variant: str
    trial_credit_cents: int
    total_cents: int
    status: str
    placed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    product_id: str
    qty: int
    discount_pct: float
    unit_price_cents: int
    line_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ContractBidLine(TypedDict, total=False):
    product_id: str
    bid_price_cents: int


class ContractBid(TypedDict, total=False):
    id: str
    bid_reference: str
    facility_group_code: str
    lines: List[ContractBidLine]
    protection_start: str
    protection_end: str
    status: str
    revision_number: int
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubstitutionProposal(TypedDict, total=False):
    id: str
    order_line_id: str
    original_product_id: str
    proposed_product_id: str
    price_delta_cents: int
    status: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class TrialProgram(TypedDict, total=False):
    id: str
    facility_id: str
    product_id: str
    trial_start: str
    trial_end: str
    sample_value_cents: int
    status: str
    conversion_order_id: Optional[str]
    conversion_credit_cents: int
    created_at: str
    updated_at: str
    version: int
