"""Domain types: entity TypedDicts, status enums, role enum.

All entities carry the common system-managed fields described in PRD
"Common Resource Properties": id, created_at, updated_at, version.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PLANT_ADMIN = "PlantAdmin"
    INTAKE_OPERATOR = "IntakeOperator"
    LAB_TECHNICIAN = "LabTechnician"
    PLANT_OPERATOR = "PlantOperator"
    GROWER = "Grower"
    BUYER = "Buyer"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class LotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    SAMPLED = "SAMPLED"
    GRADED = "GRADED"
    ROUTED_IN_SHELL = "ROUTED_IN_SHELL"
    ROUTED_KERNEL = "ROUTED_KERNEL"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    REJECTED = "REJECTED"
    DISPOSED = "DISPOSED"
    SETTLED = "SETTLED"


class LabTestType(str, Enum):
    MOISTURE_KERNEL = "MOISTURE_KERNEL"
    AFLATOXIN = "AFLATOXIN"
    KERNEL_GRADE = "KERNEL_GRADE"


class AflatoxinVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class SizeSpec(str, Enum):
    SPEC_20_22 = "SPEC_20_22"
    SPEC_23_25 = "SPEC_23_25"
    SPEC_25_27 = "SPEC_25_27"
    UNSIZED = "UNSIZED"


class RunStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DRYING = "DRYING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BinStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    FUMIGATING = "FUMIGATING"
    AERATING = "AERATING"


class ProductForm(str, Enum):
    IN_SHELL = "IN_SHELL"
    KERNEL = "KERNEL"
    HULL = "HULL"
    SHELL = "SHELL"


class PlacementStatus(str, Enum):
    STORED = "STORED"
    FUMIGATION_HOLD = "FUMIGATION_HOLD"
    QUARANTINED = "QUARANTINED"
    WITHDRAWN = "WITHDRAWN"
    DISPOSED = "DISPOSED"


class FumigationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    AERATING = "AERATING"
    CLEARED = "CLEARED"
    CANCELLED = "CANCELLED"


class ContractStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    FULFILLED = "FULFILLED"
    CLOSED = "CLOSED"


class ShipmentStatus(str, Enum):
    PLANNED = "PLANNED"
    BLOCKED = "BLOCKED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class RouteChoice(str, Enum):
    IN_SHELL = "IN_SHELL"
    KERNEL = "KERNEL"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all common_fields: id, created_at, updated_at, version)
# ---------------------------------------------------------------------------

class Grower(TypedDict, total=False):
    id: str
    name: str
    ranch_code: str
    base_price_cents_per_lb: int
    premium_rate_pct: float
    payable_outstanding_cents: int
    lifetime_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class Buyer(TypedDict, total=False):
    id: str
    name: str
    buyer_code: str
    created_at: str
    updated_at: str
    version: int


class FieldLot(TypedDict, total=False):
    id: str
    grower_id: str
    variety: str
    gross_weight_lbs: float
    status: str
    intake_moisture_pct: Optional[float]
    intake_kernel_pct: Optional[float]
    intake_fm_pct: Optional[float]
    aflatoxin_ppb: Optional[float]
    edible_kernel_pct: Optional[float]
    size_spec: Optional[str]
    post_dry_moisture_pct: Optional[float]
    requires_drying: Optional[bool]
    kernel_out_lbs: float
    shell_out_lbs: float
    hull_out_lbs: float
    provisional_kernel_lbs: Optional[float]
    graded_kernel_weight_lbs: Optional[float]
    created_at: str
    updated_at: str
    version: int


class LabTest(TypedDict, total=False):
    id: str
    lot_id: str
    test_type: str
    moisture_pct: Optional[float]
    kernel_pct: Optional[float]
    foreign_material_pct: Optional[float]
    aflatoxin_ppb: Optional[float]
    edible_kernel_pct: Optional[float]
    size_spec: Optional[str]
    aflatoxin_verdict: Optional[str]
    recorded_at: str
    created_at: str
    updated_at: str
    version: int


class ProcessingRun(TypedDict, total=False):
    id: str
    lot_id: str
    input_weight_lbs: float
    kernel_out_lbs: Optional[float]
    shell_out_lbs: Optional[float]
    hull_out_lbs: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Dryer(TypedDict, total=False):
    id: str
    dryer_code: str
    capacity_lbs: int
    created_at: str
    updated_at: str
    version: int


class DryingBatch(TypedDict, total=False):
    id: str
    dryer_id: str
    lot_id: str
    start_at: str
    end_at: str
    final_moisture_pct: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class StorageBin(TypedDict, total=False):
    id: str
    bin_code: str
    capacity_lbs: int
    allowed_product_forms: List[str]
    status: str
    occupied_lbs: float
    available_now_lbs: float
    projected_available_lbs: float
    fumigation_cleared_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AllocationEntry(TypedDict, total=False):
    placement_id: str
    lot_id: str
    quantity_lbs: float


class StoragePlacement(TypedDict, total=False):
    id: str
    bin_id: str
    lot_id: str
    product_form: str
    quantity_lbs: float
    remaining_lbs: float
    allocated_planned_lbs: float
    placed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Withdrawal(TypedDict, total=False):
    id: str
    bin_id: str
    product_form: str
    quantity_lbs: float
    allocations: List[AllocationEntry]
    withdrawn_at: str
    created_at: str
    updated_at: str
    version: int


class FumigationEvent(TypedDict, total=False):
    id: str
    bin_id: str
    start_at: str
    aeration_hours: int
    cleared_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BuyerContract(TypedDict, total=False):
    id: str
    buyer_id: str
    product_form: str
    size_spec: str
    max_defects_pct: float
    price_cents_per_lb: int
    required_qty_lbs: float
    reserved_qty_lbs: float
    delivered_qty_lbs: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    contract_id: str
    bin_id: str
    quantity_lbs: float
    allocations: List[AllocationEntry]
    status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict, total=False):
    id: str
    lot_id: str
    grower_id: str
    graded_kernel_weight_lbs: float
    base_cents: int
    premium_cents: int
    moisture_deduction_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ByproductSale(TypedDict, total=False):
    id: str
    product_form: str
    quantity_lbs: float
    price_cents_per_lb: int
    buyer_name: str
    total_cents: int
    created_at: str
    updated_at: str
    version: int
