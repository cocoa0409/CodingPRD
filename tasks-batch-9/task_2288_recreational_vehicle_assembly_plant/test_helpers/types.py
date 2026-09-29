"""Closed enumerations of PRD §2.10 and the shape of the main resources."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLANT_ADMIN = "PlantAdmin"
    DEALER_PRINCIPAL = "DealerPrincipal"
    PRODUCTION_SCHEDULER = "ProductionScheduler"
    LINE_SUPERVISOR = "LineSupervisor"
    QUALITY_INSPECTOR = "QualityInspector"
    WARRANTY_ADMINISTRATOR = "WarrantyAdministrator"
    RECALL_COORDINATOR = "RecallCoordinator"


CHASSIS_CLASSES = ["CLASS_A", "CLASS_C", "TOWABLE"]
COMPONENT_CATEGORIES = ["CHASSIS", "APPLIANCE", "PLUMBING", "ELECTRICAL"]
OPTION_CATEGORIES = [
    "APPLIANCE",
    "PLUMBING",
    "ELECTRICAL",
    "EXTERIOR",
    "INTERIOR",
    "CHASSIS_UPGRADE",
]
INSTALL_STATIONS = ["SIDEWALL_LAM", "ROOF_SET", "ROUGH_IN", "APPLIANCE_INSTALL", "FINISH"]
BUILD_STATIONS = [
    "CHASSIS_PREP",
    "SIDEWALL_LAM",
    "ROOF_SET",
    "ROUGH_IN",
    "APPLIANCE_INSTALL",
    "FINISH",
    "WATER_TEST",
    "PDI",
    "READY_TO_SHIP",
    "SHIPPED",
    "SCRAPPED",
]
DEALER_REGIONS = ["WEST", "CENTRAL", "EAST", "SOUTH"]
ORDER_TYPES = ["STOCK", "SOLD", "DEMO"]
INSPECTION_TYPES = ["WATER_TEST", "FUNCTIONAL", "PDI"]
BOOTH_TYPES = ["WATER_TEST", "FUNCTIONAL"]
INSPECTION_GRADES = ["PASS", "CONDITIONAL", "FAIL"]
CLAIM_TYPES = ["APPLIANCE", "PLUMBING", "ELECTRICAL", "STRUCTURAL", "WATER_INTRUSION"]
GOODWILL_TIERS = ["TIER_A", "TIER_B", "TIER_C"]
RECALL_SEVERITIES = ["SAFETY", "COMPLIANCE", "ADVISORY"]
SHIP_HOLD_REASONS = ["NONE", "RECALL_HOLD", "QUALITY_HOLD"]

ORDER_STATUSES = [
    "DRAFT",
    "CONFIG_VALIDATED",
    "SLOTTED",
    "IN_PRODUCTION",
    "BUILT",
    "SHIPPED",
    "CANCELLED",
]
FINANCING_STATUSES = [
    "NOT_FINANCED",
    "FUNDING_REQUESTED",
    "FLOOR_PLAN_FUNDED",
    "CURTAILED",
    "PAID_OFF",
]
SUPPLIER_STATUSES = ["ACTIVE", "PROBATION", "SUSPENDED"]
CREDIT_STATUSES = ["GOOD_STANDING", "WATCH", "CREDIT_HOLD"]
DEALER_STATUSES = ["ACTIVE", "SUSPENDED"]
FLOOR_PLAN_STATUSES = ["ACTIVE", "RETIRED"]
OPTION_STATUSES = ["ACTIVE", "DISCONTINUED"]
LINE_STATUSES = ["RUNNING", "PAUSED"]
BOOTH_STATUSES = ["OPEN", "DOWN"]
SLOT_STATUSES = ["RESERVED", "CONSUMED", "RELEASED"]
CHASSIS_STATUSES = ["RECEIVED", "MATCHED", "INSTALLED"]
LOT_STATUSES = ["AVAILABLE", "DEPLETED", "QUARANTINED"]
INSTALLATION_STATUSES = ["INSTALLED", "REVERSED", "RECALL_AFFECTED", "REMEDIED"]
INSPECTION_STATUSES = ["SCHEDULED", "COMPLETED"]
CLAIM_STATUSES = ["SUBMITTED", "INFO_REQUESTED", "APPROVED", "DENIED", "PAID"]
CAMPAIGN_STATUSES = ["DRAFT", "OPEN", "CLOSED"]


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Supplier(CommonFields):
    supplier_code: str
    name: str
    component_categories: List[str]
    quality_score: float
    supplier_status: str
    open_recall_count: int
    penalty_event_count: int


class FloorPlan(CommonFields):
    model_code: str
    chassis_class: str
    length_ft: int
    base_msrp_cents: int
    base_station_hours: float
    base_dry_weight_lbs: int
    gvwr_lbs: int
    required_wheelbase_in: int
    electrical_service_amps: int
    fresh_water_capacity_gal: int
    max_payload_lbs: int
    status: str


class OptionItem(CommonFields):
    option_code: str
    category: str
    install_station: str
    price_cents: int
    weight_lbs: int
    added_station_hours: float
    amp_draw: int
    water_demand_gal: int
    requires_option_codes: List[str]
    excludes_option_codes: List[str]
    status: str


class Dealer(CommonFields):
    dealer_code: str
    region: str
    allocation_share_bp: int
    floor_plan_credit_limit_cents: int
    goodwill_budget_cents: int
    status: str
    financed_exposure_cents: int
    credit_utilization_bp: int
    credit_status: str
    goodwill_used_cents: int
    entitlement_hours: float
    allocation_hours_consumed: float
    allocation_slots_reserved: int


class UnitOrder(CommonFields):
    dealer_id: str
    floor_plan_id: str
    order_type: str
    selected_option_ids: List[str]
    status: str
    financing_status: str
    required_station_hours: float
    config_weight_lbs: int
    payload_remaining_lbs: int
    total_amp_draw: int
    total_water_demand_gal: int
    option_price_total_cents: int
    provisional_invoice_cents: Optional[int]
    final_invoice_cents: Optional[int]
    financed_principal_cents: Optional[int]
    curtailment_paid_cents: int
    curtailment_due_cents: int
    ship_hold_reason: str
    locked_floor_plan_version: Optional[int]
    matched_chassis_receipt_id: Optional[str]


class UnitBuild(CommonFields):
    unit_order_id: str
    production_line_id: str
    chassis_receipt_id: str
    vin: str
    build_sequence: int
    current_station: str
    actual_station_hours: float
    defect_points_total: int
    rework_count: int
    water_test_passed: bool
    pdi_passed: bool
    recall_hold: bool


class WarrantyClaim(CommonFields):
    dealer_id: str
    unit_build_id: str
    component_lot_id: Optional[str]
    claim_type: str
    labor_hours: float
    parts_cost_cents: int
    status: str
    in_warranty: bool
    authority_tier: Optional[str]
    labor_reimbursement_cents: int
    parts_reimbursement_cents: int
    goodwill_authorized_cents: int
    total_reimbursement_cents: int
    supplier_chargeback_cents: int
    info_request_count: int
    resubmission_count: int
    denial_reason: Optional[str]
    approved_by_user_id: Optional[str]
    paid_by_user_id: Optional[str]
