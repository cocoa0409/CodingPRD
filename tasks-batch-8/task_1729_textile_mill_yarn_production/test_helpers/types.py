"""Domain types: entity TypedDicts, status enums, role enum.

Common-field rule (PRD §2.4): every primary resource carries id, created_at,
updated_at and version. A blend component carries only id and created_at —
updated_at and version are absent from that resource entirely.
"""
from enum import Enum
from typing import Optional, TypedDict


class FiberType(str, Enum):
    COTTON = "COTTON"
    POLYESTER = "POLYESTER"
    RAYON = "RAYON"
    WOOL = "WOOL"
    NYLON = "NYLON"


class FiberLotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    BLENDED = "BLENDED"
    EXHAUSTED = "EXHAUSTED"


class BlendRecipeStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class SpinningMachineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DOWN = "DOWN"
    DECOMMISSIONED = "DECOMMISSIONED"


class YarnLotStatus(str, Enum):
    GREIGE = "GREIGE"
    DYEING = "DYEING"
    FINISHED = "FINISHED"
    ALLOCATED = "ALLOCATED"
    REJECTED = "REJECTED"


class MachineAssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DyeLotStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    DYEING = "DYEING"
    SHADE_PENDING = "SHADE_PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ShadeBandStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class LabDipStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class QualityGrade(str, Enum):
    FIRST_QUALITY = "FIRST_QUALITY"
    SECOND_QUALITY = "SECOND_QUALITY"
    REJECTED = "REJECTED"


class FinishedRollStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    CLOSE_OUT = "CLOSE_OUT"


class CustomerOrderStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_ALLOCATED = "PARTIALLY_ALLOCATED"
    FULLY_ALLOCATED = "FULLY_ALLOCATED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    MILL_PLANNER = "MillPlanner"
    SPINNING_SUPERVISOR = "SpinningSupervisor"
    DYE_HOUSE_OPERATOR = "DyeHouseOperator"
    QUALITY_INSPECTOR = "QualityInspector"
    CUSTOMER_SERVICE_REP = "CustomerServiceRep"
    MILL_ADMIN = "MillAdmin"


class FiberLot(TypedDict, total=False):
    id: str
    fiber_type: str
    received_weight_lbs: float
    available_weight_lbs: float
    unit_cost_per_lb: float
    status: str
    created_at: str
    updated_at: str
    version: int


class BlendRecipe(TypedDict, total=False):
    id: str
    recipe_code: str
    target_yarn_count_ne: float
    status: str
    total_component_weight_lbs: float
    projected_cost_per_lb: Optional[float]
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BlendComponent(TypedDict, total=False):
    # Components are detached and re-derived rather than updated in place:
    # only id and created_at exist as system fields (no updated_at, no version).
    id: str
    recipe_id: str
    fiber_lot_id: str
    component_weight_lbs: float
    proportion_pct: float
    created_at: str


class SpinningMachine(TypedDict, total=False):
    id: str
    machine_code: str
    supported_count_min_ne: float
    supported_count_max_ne: float
    status: str
    created_at: str
    updated_at: str
    version: int


class YarnLot(TypedDict, total=False):
    id: str
    recipe_id: str
    spun_weight_lbs: float
    actual_yarn_count_ne: float
    greige_yards_available: float
    actual_cost_per_lb: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class MachineAssignment(TypedDict, total=False):
    id: str
    machine_id: str
    yarn_lot_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DyeLot(TypedDict, total=False):
    id: str
    yarn_lot_id: str
    shade_band_id: str
    vat_id: str
    scheduled_at: str
    requested_yards: float
    status: str
    measured_delta_e: Optional[float]
    created_at: str
    updated_at: str
    version: int


class ShadeBand(TypedDict, total=False):
    id: str
    customer_code: str
    color_code: str
    centroid_l: float
    centroid_a: float
    centroid_b: float
    delta_e_tolerance: float
    status: str
    created_at: str
    updated_at: str
    version: int


class LabDip(TypedDict, total=False):
    id: str
    shade_band_id: str
    submitted_by_operator_id: str
    measured_delta_e: float
    status: str
    created_at: str
    updated_at: str
    version: int


class QualityTest(TypedDict, total=False):
    id: str
    dye_lot_id: str
    shrinkage_pct_provisional: float
    shrinkage_pct_final: Optional[float]
    hand_score: int
    grade: str
    created_at: str
    updated_at: str
    version: int


class FinishedRoll(TypedDict, total=False):
    id: str
    dye_lot_id: str
    put_up_yards: float
    actual_yards: float
    yardage_deviation_pct: float
    is_second_quality: bool
    allocated_order_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomerOrder(TypedDict, total=False):
    id: str
    customer_code: str
    color_code: str
    requested_yards: float
    allocated_yards: float
    yardage_tolerance_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int
