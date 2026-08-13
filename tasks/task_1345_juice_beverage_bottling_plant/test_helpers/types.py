"""Domain types: entity TypedDicts, status enums, role enum for the bottling plant API."""
from enum import Enum
from typing import TypedDict, Optional, List


class CustomerStatus(str, Enum):
    PENDING_CREDIT = "PENDING_CREDIT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class FormulaStatus(str, Enum):
    DRAFT = "DRAFT"
    LABEL_REVIEW = "LABEL_REVIEW"
    APPROVED = "APPROVED"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    RETIRED = "RETIRED"


class LabelReviewStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class TankPosture(str, Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    AWAITING_CIP = "AWAITING_CIP"
    IN_CIP = "IN_CIP"


class BatchStatus(str, Enum):
    PLANNED = "PLANNED"
    BLENDING = "BLENDING"
    AWAITING_QA = "AWAITING_QA"
    QA_PASSED = "QA_PASSED"
    QA_FAILED = "QA_FAILED"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    RELEASED = "RELEASED"
    CONDEMNED = "CONDEMNED"
    CONSUMED = "CONSUMED"


class ProcessRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    VALIDATED = "VALIDATED"
    DEVIATED = "DEVIATED"
    ABORTED = "ABORTED"
    DISPOSITION_RELEASED = "DISPOSITION_RELEASED"
    DISPOSITION_REJECTED = "DISPOSITION_REJECTED"


class DeviationClass(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class ContainerLotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    QC_PASSED = "QC_PASSED"
    QC_FAILED = "QC_FAILED"
    RETURNED = "RETURNED"
    DEPLETED = "DEPLETED"


class LineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"


class ProductionStatus(str, Enum):
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    SCHEDULED = "SCHEDULED"
    IN_PRODUCTION = "IN_PRODUCTION"
    COMPLETED = "COMPLETED"
    BLOCKED_SUPPLY = "BLOCKED_SUPPLY"
    BLOCKED_LABEL = "BLOCKED_LABEL"
    CANCELLED = "CANCELLED"


class InvoiceStatus(str, Enum):
    NOT_INVOICED = "NOT_INVOICED"
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class LotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"
    EXPIRED = "EXPIRED"
    RECALLED = "RECALLED"


class OrderStatus(str, Enum):
    PLACED = "PLACED"
    ALLOCATED = "ALLOCATED"
    PICKED = "PICKED"
    SHIPPED = "SHIPPED"
    BACKORDERED = "BACKORDERED"
    CANCELLED = "CANCELLED"


class ProcessType(str, Enum):
    PASTEURIZATION = "PASTEURIZATION"
    HPP = "HPP"


class ContainerType(str, Enum):
    GLASS_355 = "GLASS_355"
    PET_473 = "PET_473"
    PET_1000 = "PET_1000"
    CAN_330 = "CAN_330"


class AllergenGroup(str, Enum):
    NONE = "NONE"
    SULFITE = "SULFITE"
    TREE_NUT = "TREE_NUT"
    MILK = "MILK"


class Channel(str, Enum):
    DIRECT_RETAIL = "DIRECT_RETAIL"
    CLUB = "CLUB"
    FOODSERVICE = "FOODSERVICE"
    EXPORT = "EXPORT"


class TemperatureClass(str, Enum):
    AMBIENT = "AMBIENT"
    CHILLED = "CHILLED"
    FROZEN = "FROZEN"


class PalletEntryType(str, Enum):
    SHIP = "SHIP"
    RETURN = "RETURN"
    CONVERSION = "CONVERSION"


class UserRole(str, Enum):
    PLANT_MANAGER = "PlantManager"
    FINANCE_CLERK = "FinanceClerk"
    PRODUCT_DEVELOPER = "ProductDeveloper"
    LABEL_COMPLIANCE_REVIEWER = "LabelComplianceReviewer"
    BLEND_OPERATOR = "BlendOperator"
    QA_INSPECTOR = "QAInspector"
    PRODUCTION_PLANNER = "ProductionPlanner"
    WAREHOUSE_LEAD = "WarehouseLead"
    CUSTOMER_SERVICE_REP = "CustomerServiceRep"
    CUSTOMER_CONTACT = "CustomerContact"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---

class CustomerAccount(TypedDict, total=False):
    id: str
    name: str
    credit_limit_cents: int
    minimum_run_units: int
    pallet_deposit_cents: int
    outstanding_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Formula(TypedDict, total=False):
    id: str
    customer_id: str
    formula_code: str
    name: str
    target_brix: float
    brix_tolerance: float
    process_type: str
    container_fill_ml: int
    concentrate_brix: float
    allergen_group: str
    shelf_life_days: int
    claims: List[str]
    label_version: int
    submitted_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LabelClaimReview(TypedDict, total=False):
    id: str
    formula_id: str
    claims_snapshot: List[str]
    review_note: Optional[str]
    reviewer_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BlendingTank(TypedDict, total=False):
    id: str
    tank_code: str
    capacity_liters: int
    allergen_group: str
    posture: str
    occupying_batch_id: Optional[str]
    cip_started_at: Optional[str]
    cip_required_hours: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Batch(TypedDict, total=False):
    id: str
    formula_id: str
    tank_id: str
    planned_start_at: str
    planned_end_at: str
    quantity_liters: float
    initial_quantity_liters: float
    measured_brix: Optional[float]
    added_water_liters: float
    added_concentrate_liters: float
    adjustment_count: int
    blended_by_user_id: Optional[str]
    linked_run_id: Optional[str]
    loss_liters: Optional[float]
    processed_liters: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProcessRun(TypedDict, total=False):
    id: str
    batch_id: str
    process_type: str
    setpoint_temp_c: Optional[float]
    setpoint_hold_seconds: Optional[int]
    setpoint_pressure_mpa: Optional[float]
    setpoint_pressure_hold_seconds: Optional[int]
    min_temp_c: Optional[float]
    time_below_setpoint_seconds: Optional[int]
    min_pressure_mpa: Optional[float]
    pressure_hold_shortfall_seconds: Optional[int]
    deviation_class: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ContainerLot(TypedDict, total=False):
    id: str
    container_type: str
    quantity_received: int
    supplier_lot_code: str
    quantity_available: int
    quantity_reserved: int
    quantity_consumed: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BottlingLine(TypedDict, total=False):
    id: str
    line_code: str
    supported_container_types: List[str]
    nominal_cpm: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict, total=False):
    id: str
    customer_id: str
    formula_id: str
    container_type: str
    planned_units: int
    unit_price_cents: int
    batch_id: Optional[str]
    line_id: Optional[str]
    scheduled_start_at: Optional[str]
    scheduled_end_at: Optional[str]
    label_version_pinned: Optional[int]
    theoretical_units: Optional[int]
    actual_units_filled: Optional[int]
    avg_fill_ml: Optional[float]
    giveaway_liters: Optional[float]
    billable_units: Optional[int]
    pallet_count: Optional[int]
    provisional_invoice_cents: Optional[int]
    final_invoice_cents: Optional[int]
    production_status: str
    invoice_status: str
    created_at: str
    updated_at: str
    version: int


class FinishedGoodLot(TypedDict, total=False):
    id: str
    production_run_id: str
    formula_id: str
    customer_id: str
    warehouse_zone_id: str
    lot_code: str
    units_total: int
    units_available: int
    units_allocated: int
    units_shipped: int
    pallet_count: int
    production_date: str
    expiry_label_date: str
    expiry_stability_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WarehouseZone(TypedDict, total=False):
    id: str
    zone_code: str
    temperature_class: str
    pallet_capacity: int
    pallets_stored: int
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict, total=False):
    lot_id: str
    units: int


class ShipmentOrder(TypedDict, total=False):
    id: str
    customer_id: str
    formula_id: str
    channel: str
    requested_delivery_date: str
    units_requested: int
    min_shelf_life_days: int
    allocations: List[Allocation]
    allocated_units: int
    pallet_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PalletAccount(TypedDict, total=False):
    id: str
    customer_id: str
    pallets_out_total: int
    pallets_returned_total: int
    pallets_converted_total: int
    pallets_outstanding: int
    escrow_balance_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only ledger entry: NO updated_at, NO version
class PalletEntry(TypedDict, total=False):
    id: str
    pallet_account_id: str
    entry_type: str
    pallet_count: int
    shipment_order_id: Optional[str]
    entry_date: str
    running_balance: int
    created_at: str


# common_fields: false — append-only epoch record: NO updated_at, NO version
class OpsRun(TypedDict, total=False):
    id: str
    ran_at: str
    lots_expired_count: int
    orders_backordered_count: int
    orders_cancelled_count: int
    customers_suspended_count: int
    pallets_converted_count: int
    created_at: str
