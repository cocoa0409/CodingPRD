"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLANT_MANAGER = "PlantManager"
    PRODUCTION_OPERATOR = "ProductionOperator"
    LAB_ANALYST = "LabAnalyst"
    QUALITY_MANAGER = "QualityManager"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    BILLING_CLERK = "BillingClerk"
    DRIVER = "Driver"


class PlantStatus(str, Enum):
    OPERATING = "OPERATING"
    MAINTENANCE_SHUTDOWN = "MAINTENANCE_SHUTDOWN"


class TankStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    MAINTENANCE = "MAINTENANCE"
    QUARANTINED = "QUARANTINED"


class ProductCode(str, Enum):
    O2 = "O2"
    N2 = "N2"
    AR = "AR"
    CO2 = "CO2"
    H2 = "H2"
    HE = "HE"


class ReadingSource(str, Enum):
    IOT_SENSOR = "IOT_SENSOR"
    MANUAL_DIP = "MANUAL_DIP"
    INITIAL_LOAD = "INITIAL_LOAD"
    SYSTEM_REPLENISHMENT = "SYSTEM_REPLENISHMENT"


class SizeCode(str, Enum):
    SMALL = "SMALL"
    STANDARD = "STANDARD"
    LARGE = "LARGE"


class CylinderStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    RESERVED = "RESERVED"
    FILLED = "FILLED"
    ON_RENT = "ON_RENT"
    QUARANTINED = "QUARANTINED"
    LOST = "LOST"
    RETIRED = "RETIRED"


class HydroStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    DUE_SOON = "DUE_SOON"
    OVERDUE = "OVERDUE"


class FillLotStatus(str, Enum):
    PLANNED = "PLANNED"
    FILLING = "FILLING"
    AWAITING_ANALYSIS = "AWAITING_ANALYSIS"
    RELEASED = "RELEASED"
    ANALYSIS_FAILED = "ANALYSIS_FAILED"
    RECALLED = "RECALLED"
    VENTED = "VENTED"


class SubjectType(str, Enum):
    FILL_LOT = "FILL_LOT"
    BLEND_ORDER = "BLEND_ORDER"


class AnalysisResult(str, Enum):
    PASS = "PASS"
    MARGINAL = "MARGINAL"
    FAIL = "FAIL"
    PASS_OVERRIDE = "PASS_OVERRIDE"


class AnalysisStatus(str, Enum):
    RECORDED = "RECORDED"
    OVERRIDDEN = "OVERRIDDEN"


class BillingVariant(str, Enum):
    CALENDAR_DAY = "CALENDAR_DAY"
    GRACE_PERIOD = "GRACE_PERIOD"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"


class RentalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OVERDUE = "OVERDUE"
    RECALL_HOLD = "RECALL_HOLD"
    RETURNED = "RETURNED"
    LOST_SETTLED = "LOST_SETTLED"


class DriverStatus(str, Enum):
    QUALIFIED = "QUALIFIED"
    SUSPENDED = "SUSPENDED"
    CERT_EXPIRED = "CERT_EXPIRED"


class EndorsementClass(str, Enum):
    FLAMMABLE_GAS = "FLAMMABLE_GAS"
    NONFLAMMABLE_GAS = "NONFLAMMABLE_GAS"
    OXIDIZER = "OXIDIZER"
    POISON_GAS = "POISON_GAS"
    CRYOGENIC = "CRYOGENIC"


class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    DRIVER_ASSIGNED = "DRIVER_ASSIGNED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InstallationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    INSTALLED = "INSTALLED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DECOMMISSIONED = "DECOMMISSIONED"


class ReplenishmentStatus(str, Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class BlendStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    BLENDING = "BLENDING"
    AWAITING_ANALYSIS = "AWAITING_ANALYSIS"
    RELEASED = "RELEASED"
    REWORK = "REWORK"


class BillingRunStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    POSTED = "POSTED"


# --- Entity bodies (PRD §2.5 common fields; telemetry readings are append-only) ---


class Plant(TypedDict, total=False):
    id: str
    plant_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StorageTank(TypedDict, total=False):
    id: str
    plant_id: str
    product_code: str
    capacity_liters: int
    reorder_point_liters: int
    current_level_liters: float
    reserved_liters: float
    drawn_liters: float
    low_level_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class TelemetryReading(TypedDict, total=False):
    # Append-only record: carries only id + created_at; no updated_at, no version.
    id: str
    tank_id: Optional[str]
    installation_id: Optional[str]
    measured_level_liters: float
    measured_at: str
    source: str
    recorded_by_user_id: str
    created_at: str


class CylinderAsset(TypedDict, total=False):
    id: str
    serial_number: str
    size_code: str
    service_gas: str
    water_capacity_liters: int
    last_hydro_date: str
    hydro_due_date: str
    hydro_status: str
    status: str
    current_fill_lot_id: Optional[str]
    last_fill_lot_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FillLot(TypedDict, total=False):
    id: str
    tank_id: str
    product_code: str
    target_fill_pressure_bar: int
    draw_estimate_liters: float
    draw_actual_liters: Optional[float]
    completed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PurityAnalysis(TypedDict, total=False):
    id: str
    subject_type: str
    fill_lot_id: Optional[str]
    blend_order_id: Optional[str]
    readings: list
    result: str
    recorded_by_user_id: str
    overridden_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomerAccount(TypedDict, total=False):
    id: str
    account_name: str
    billing_variant: str
    free_days: int
    credit_limit_cents: int
    outstanding_balance_cents: int
    recall_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CylinderRental(TypedDict, total=False):
    id: str
    customer_id: str
    cylinder_id: str
    daily_rate_cents: int
    planned_days: int
    out_date: str
    due_date: str
    return_date: Optional[str]
    billed_through_date: str
    demurrage_billed_cents: int
    final_charge_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class HazmatEndorsement(TypedDict, total=False):
    endorsement_class: str
    expiry_date: str


class Driver(TypedDict, total=False):
    id: str
    driver_name: str
    cdl_class: str
    hazmat_endorsements: List[HazmatEndorsement]
    medical_card_expiry: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict, total=False):
    stop_name: str
    hazmat_classes: List[str]


class DeliveryRoute(TypedDict, total=False):
    id: str
    route_date: str
    window_start_hour: int
    window_end_hour: int
    stops: List[RouteStop]
    driver_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BulkInstallation(TypedDict, total=False):
    id: str
    customer_id: str
    product_code: str
    capacity_liters: int
    reorder_point_liters: int
    max_order_qty_liters: int
    current_level_liters: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ReplenishmentOrder(TypedDict, total=False):
    id: str
    installation_id: str
    scheduled_delivery_at: str
    requested_qty_liters: float
    delivered_at: Optional[str]
    superseded_by_order_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BlendComponent(TypedDict, total=False):
    product_code: str
    target_pct: float
    tolerance_pct: float
    unit_cost_cents_per_liter: int
    selected_tank_id: Optional[str]


class BlendOrder(TypedDict, total=False):
    id: str
    customer_id: str
    batch_qty_liters: int
    components: List[BlendComponent]
    component_cost_cents: int
    service_fee_cents: int
    total_price_cents: int
    blended_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ChargeLine(TypedDict, total=False):
    rental_id: str
    customer_id: str
    overdue_days: int
    demurrage_cents: int


class BillingRun(TypedDict, total=False):
    id: str
    period_start: str
    period_end: str
    charge_lines: List[ChargeLine]
    total_charges_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
