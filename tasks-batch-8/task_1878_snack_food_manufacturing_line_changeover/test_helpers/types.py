"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class ProcessType(str, Enum):
    FRYER = "FRYER"
    OVEN = "OVEN"


class Allergen(str, Enum):
    PEANUT = "PEANUT"
    TREE_NUT = "TREE_NUT"
    DAIRY = "DAIRY"
    SOY = "SOY"
    GLUTEN = "GLUTEN"
    SESAME = "SESAME"
    EGG = "EGG"


class FlavorGroup(str, Enum):
    PLAIN = "PLAIN"
    CHEESE = "CHEESE"
    SPICY = "SPICY"
    SWEET = "SWEET"


class LineType(str, Enum):
    FRYER = "FRYER"
    OVEN = "OVEN"
    BOTH = "BOTH"


class LinePosture(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    CLEANING = "CLEANING"
    BLOCKED = "BLOCKED"


class FryerOilState(str, Enum):
    ACTIVE = "ACTIVE"
    QUALITY_HOLD = "QUALITY_HOLD"
    DRAINING = "DRAINING"


class OilMovementType(str, Enum):
    TOP_OFF = "TOP_OFF"
    DISCARD = "DISCARD"
    FILTRATION = "FILTRATION"
    FULL_REPLACE = "FULL_REPLACE"


class ChangeoverLevel(str, Enum):
    NONE = "NONE"
    DRY_CLEAN = "DRY_CLEAN"
    FULL_WASH = "FULL_WASH"


class ChangeoverStatus(str, Enum):
    REQUIRED = "REQUIRED"
    CLEANING = "CLEANING"
    SWAB_PENDING = "SWAB_PENDING"
    VALIDATED = "VALIDATED"
    APPLIED = "APPLIED"
    CANCELLED = "CANCELLED"


class SwabResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class RunExecutionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    HELD = "HELD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RunQualityStatus(str, Enum):
    PENDING = "PENDING"
    QHOLD = "QHOLD"
    PASSED = "PASSED"
    REJECTED = "REJECTED"


class RequestedRoute(str, Enum):
    DSD = "DSD"
    WAREHOUSE = "WAREHOUSE"
    AUTO = "AUTO"


class ShipmentStatus(str, Enum):
    DRAFT = "DRAFT"
    DSD_PLANNED = "DSD_PLANNED"
    WAREHOUSE_PLANNED = "WAREHOUSE_PLANNED"
    DISPATCHED = "DISPATCHED"
    CANCELLED = "CANCELLED"


class PromoWindowStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    CLOSED = "CLOSED"


class DisplayCaseStatus(str, Enum):
    PLANNED = "PLANNED"
    BUILT = "BUILT"
    CANCELLED = "CANCELLED"


class DisplayCaseCancelReason(str, Enum):
    OIL_HOLD = "OIL_HOLD"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    OVER_RESERVED = "OVER_RESERVED"
    RUN_CANCELLED = "RUN_CANCELLED"
    RUN_REJECTED = "RUN_REJECTED"
    MANUAL = "MANUAL"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class SlotStatus(str, Enum):
    BOOKED = "BOOKED"
    CONFIRMED = "CONFIRMED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class Disposition(str, Enum):
    PASS = "PASS"
    REJECT = "REJECT"


class UserRole(str, Enum):
    PLANT_MANAGER = "PlantManager"
    LINE_OPERATOR = "LineOperator"
    QUALITY_TECHNICIAN = "QualityTechnician"
    ROUTE_PLANNER = "RoutePlanner"
    CO_MANUFACTURER = "CoManufacturer"


# --- Entity TypedDicts -------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version.
# OilMovement and WeightCheck are immutable point-in-time records: only
# id + created_at from the common set; updated_at and version are absent.

class Product(TypedDict, total=False):
    id: str
    name: str
    process_type: str
    allergen_profile: List[str]
    flavor_group: str
    declared_net_weight_g: float
    tne_g: float
    giveaway_target_pct: float
    giveaway_max_pct: float
    shelf_life_days: int
    seasoning_target_pct: float
    fry_target_temp_c: Optional[float]
    standard_oil_price_cents_per_gal: int
    case_revenue_cents: int
    min_margin_cents_per_case: int
    bags_per_case: int
    created_at: str
    updated_at: str
    version: int


class ProductionLine(TypedDict, total=False):
    id: str
    name: str
    line_type: str
    oil_capacity_gallons: float
    cleaning_minutes_full_wash: int
    cleaning_minutes_dry: int
    posture: str
    current_allergen_profile: List[str]
    current_flavor_group: str
    created_at: str
    updated_at: str
    version: int


class FryerOil(TypedDict, total=False):
    id: str
    line_id: str
    initial_charge_gallons: float
    current_gallons: float
    tpm_pct: float
    state: str
    total_lbs_since_replace: float
    last_oil_price_cents_per_gal: Optional[int]
    created_at: str
    updated_at: str
    version: int


class OilMovement(TypedDict, total=False):
    # Append-only record: id + created_at only from the common set.
    id: str
    created_at: str
    fryer_oil_id: str
    movement_type: str
    gallons: float
    unit_price_cents_per_gal: Optional[int]
    tpm_after_pct: float
    recorded_at: str
    recorded_by_user_id: str


class Changeover(TypedDict, total=False):
    id: str
    line_id: str
    to_product_id: str
    from_allergen_profile: List[str]
    to_allergen_profile: List[str]
    from_flavor_group: str
    to_flavor_group: str
    required_level: str
    status: str
    cleaned_by_user_id: Optional[str]
    swab_result: Optional[str]
    swab_attempts: int
    validated_by_user_id: Optional[str]
    validated_at: Optional[str]
    consumed_by_run_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict, total=False):
    id: str
    line_id: str
    product_id: str
    scheduled_start: str
    scheduled_end: str
    lbs_planned: float
    cases_planned: int
    execution_status: str
    quality_status: str
    started_at: Optional[str]
    completed_at: Optional[str]
    lbs_produced: Optional[float]
    cases_produced: Optional[int]
    rejected_cases: Optional[int]
    seasoning_actual_pct: Optional[float]
    accepted_cases: int
    cases_unrouted: int
    hold_placed_by_user_id: Optional[str]
    locked_oil_price_cents_per_gal: Optional[int]
    margin_standard_cents: Optional[int]
    margin_actual_cents: Optional[int]
    giveaway_provisional_pct: Optional[float]
    giveaway_final_pct: Optional[float]
    reject_ratio: Optional[float]
    created_at: str
    updated_at: str
    version: int


class WeightCheck(TypedDict, total=False):
    # Append-only record: id + created_at only from the common set.
    id: str
    created_at: str
    run_id: str
    bag_weight_g: float
    lbs_fried_since_last_check: float
    avg_fry_temp_c: Optional[float]
    is_reject: bool
    recorded_at: str
    checked_by_user_id: str


class Shipment(TypedDict, total=False):
    id: str
    run_id: str
    cases: int
    requested_route: str
    transit_days: int
    planned_route: Optional[str]
    status: str
    freshness_days_at_plan: Optional[int]
    dispatched_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PromoWindow(TypedDict, total=False):
    id: str
    product_id: str
    quota_total_cases: int
    window_start_date: str
    window_end_date: str
    case_size_bags: int
    status: str
    quota_consumed_cases: int
    quota_released_cases: int
    quota_remaining_cases: int
    created_at: str
    updated_at: str
    version: int


class DisplayCase(TypedDict, total=False):
    id: str
    promo_window_id: str
    run_id: str
    cases_planned: int
    status: str
    cancelled_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoManufacturer(TypedDict, total=False):
    id: str
    name: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class CoManAgreement(TypedDict, total=False):
    id: str
    co_manufacturer_id: str
    weekly_capacity_lbs: float
    rate_per_lb_cents: int
    budget_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CoManSlot(TypedDict, total=False):
    id: str
    agreement_id: str
    product_id: str
    week_start_date: str
    reserved_lbs: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CostSummary(TypedDict, total=False):
    margin_standard_cents: Optional[int]
    margin_actual_cents: Optional[int]
    margin_actual_per_case_cents: Optional[int]
    giveaway_provisional_pct: Optional[float]
    giveaway_final_pct: Optional[float]
    accepted_cases: int
    reject_ratio: Optional[float]
