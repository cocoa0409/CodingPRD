"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import Any, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    SHOP_ADMIN = "ShopAdmin"
    ESTIMATOR = "Estimator"
    SHOP_FOREMAN = "ShopForeman"
    STAFF_ENGINEER = "StaffEngineer"
    PAINT_CHARGE = "PaintCharge"
    CLIENT_PM = "ClientPM"
    TRANSPORT_COORDINATOR = "TransportCoordinator"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------
class ShopPosture(str, Enum):
    OPEN = "OPEN"
    TIGHT = "TIGHT"
    SATURATED = "SATURATED"


class DesignPackageStatus(str, Enum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"


class TakeoffStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"


class TakeoffLineSource(str, Enum):
    PURCHASE = "PURCHASE"
    STOCK = "STOCK"


class PricingVariant(str, Enum):
    DETAILED = "DETAILED"
    ROM = "ROM"


class ComplexityClass(str, Enum):
    A_SIMPLE = "A_SIMPLE"
    B_STANDARD = "B_STANDARD"
    C_COMPLEX = "C_COMPLEX"


class BidStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    COUNTERED = "COUNTERED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class ProductionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_BUILD = "IN_BUILD"
    ON_HOLD = "ON_HOLD"
    BUILT = "BUILT"
    LOADED_IN = "LOADED_IN"
    STRUCK = "STRUCK"
    CLOSED = "CLOSED"


class ReviewScope(str, Enum):
    STRUCTURAL = "STRUCTURAL"
    AUTOMATION = "AUTOMATION"


class EngineeringReviewStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REVISION_REQUIRED = "REVISION_REQUIRED"


class FinishSampleStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ChangeOrderStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class BayReservationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class StockItemOrigin(str, Enum):
    PURCHASED = "PURCHASED"
    RECLAIMED = "RECLAIMED"


class StockItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"


class TransportPlanStatus(str, Enum):
    PLANNED = "PLANNED"
    CONFIRMED = "CONFIRMED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all entities here use common_fields: true per PRD §2.5)
# ---------------------------------------------------------------------------
class Shop(TypedDict, total=False):
    id: str
    name: str
    weekly_crew_hours_capacity: int
    horizon_weeks: int
    bay_count: int
    truck_fleet_size: int
    labor_rate_cents_per_hour: int
    overtime_multiplier_bp: int
    overhead_pct_bp: int
    margin_pct_bp: int
    committed_crew_hours: int
    capacity_ratio_bp: int
    posture: str
    inventory_value_cents: int
    epoch_index: int
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict, total=False):
    id: str
    shop_id: str
    company_name: str
    contact_email: str
    credit_limit_cents: int
    outstanding_cents: int
    created_at: str
    updated_at: str
    version: int


class DesignPackage(TypedDict, total=False):
    id: str
    client_id: str
    show_title: str
    venue: str
    load_in_at: str
    strike_at: str
    drawing_revision: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Takeoff(TypedDict, total=False):
    id: str
    design_package_id: str
    estimator_user_id: str
    labor_hours_est: int
    pinned_package_revision: int
    materials_subtotal_cents: int
    status: str
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TakeoffLine(TypedDict, total=False):
    id: str
    takeoff_id: str
    material_code: str
    quantity: int
    source: str
    unit_cost_cents: Optional[int]
    stock_item_id: Optional[str]
    waste_pct_bp: int
    applied_unit_cost_cents: int
    line_total_cents: int
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict, total=False):
    id: str
    client_id: str
    design_package_id: str
    pricing_variant: str
    takeoff_id: Optional[str]
    floor_area_sqft: Optional[int]
    complexity_class: Optional[str]
    has_automation_scope: bool
    bays_required: int
    build_start_at: str
    estimated_crew_hours: Optional[int]
    validity_days: int
    pinned_drawing_revision: int
    price_cents: int
    valid_until: Optional[str]
    round_no: int
    production_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Production(TypedDict, total=False):
    id: str
    shop_id: str
    bid_id: str
    client_id: str
    show_title: str
    build_start_at: str
    load_in_deadline_at: str
    strike_at: str
    committed_crew_hours: int
    bays_required: int
    required_review_scopes: List[str]
    applied_drawing_revision: int
    current_price_cents: int
    built_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EngineeringReview(TypedDict, total=False):
    id: str
    production_id: str
    scope: str
    design_load_lb: float
    member_capacity_lb: float
    impact_factor_bp: Optional[int]
    prepared_by_user_id: str
    sf_static: float
    sf_dynamic: Optional[float]
    round_no: int
    revision_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FinishSample(TypedDict, total=False):
    id: str
    production_id: str
    finish_code: str
    texture_ref: str
    round_no: int
    rejection_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict, total=False):
    id: str
    production_id: str
    new_drawing_revision: int
    delta_materials_cents: int
    delta_labor_hours: int
    delta_load_in_days: int
    priced_posture: str
    priced_production_status: str
    delta_price_cents: int
    co_no: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BayReservation(TypedDict, total=False):
    id: str
    production_id: str
    bay_slot: int
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StockItem(TypedDict, total=False):
    id: str
    shop_id: str
    material_code: str
    condition_grade: str
    quantity_on_hand: int
    origin: str
    replacement_cost_cents: int
    reuse_unit_cost_cents: int
    reuse_value_cents: int
    replacement_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TransportPlan(TypedDict, total=False):
    id: str
    production_id: str
    truck_count: int
    install_crew_hours: int
    depart_at: str
    arrive_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
