"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class ProjectStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIGURED = "CONFIGURED"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    IN_PRODUCTION = "IN_PRODUCTION"
    FINISHING = "FINISHING"
    READY_TO_SHIP = "READY_TO_SHIP"
    SHIPPED = "SHIPPED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class FabStatus(str, Enum):
    QUEUED = "QUEUED"
    MACHINED = "MACHINED"
    FINISHED = "FINISHED"
    LABELED = "LABELED"
    STAGED = "STAGED"
    REWORK = "REWORK"
    CANCELLED = "CANCELLED"


class ShipStatus(str, Enum):
    UNSCHEDULED = "UNSCHEDULED"
    SCHEDULED = "SCHEDULED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    PUNCH_LISTED = "PUNCH_LISTED"
    ACCEPTED = "ACCEPTED"
    CANCELLED = "CANCELLED"


class DrawingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    VOID = "VOID"


class ProgramStatus(str, Enum):
    CREATED = "CREATED"
    SETUP_BOOKED = "SETUP_BOOKED"
    PROVEN = "PROVEN"
    RELEASED = "RELEASED"
    VOIDED = "VOIDED"


class SlotStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BatchStatus(str, Enum):
    MIXED = "MIXED"
    SPRAYED = "SPRAYED"
    CURED = "CURED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class RollStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"
    RETIRED = "RETIRED"


class AllocationStatus(str, Enum):
    ISSUED = "ISSUED"
    APPLIED = "APPLIED"
    VERIFIED = "VERIFIED"
    VOIDED = "VOIDED"


class TripStatus(str, Enum):
    PLANNED = "PLANNED"
    DEPARTED = "DEPARTED"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PunchStatus(str, Enum):
    REPORTED = "REPORTED"
    TRIAGED = "TRIAGED"
    REWORK_AUTHORIZED = "REWORK_AUTHORIZED"
    IN_REWORK = "IN_REWORK"
    RESOLVED = "RESOLVED"
    VERIFIED = "VERIFIED"
    REJECTED_INVALID = "REJECTED_INVALID"


class Species(str, Enum):
    OAK = "OAK"
    MAPLE = "MAPLE"
    CHERRY = "CHERRY"
    WALNUT = "WALNUT"
    PAINT_GRADE = "PAINT_GRADE"


class FinishSystem(str, Enum):
    CLEAR_COAT = "CLEAR_COAT"
    STAIN = "STAIN"
    PAINT = "PAINT"


class SheenTarget(str, Enum):
    MATTE = "MATTE"
    SATIN = "SATIN"
    SEMI_GLOSS = "SEMI_GLOSS"
    HIGH_GLOSS = "HIGH_GLOSS"


class HardwarePrepMode(str, Enum):
    TEMPLATE_PREP = "TEMPLATE_PREP"
    INSTALLER_PREP = "INSTALLER_PREP"


class FireRating(str, Enum):
    NONE = "NONE"
    MIN_20 = "MIN_20"
    MIN_45 = "MIN_45"
    MIN_90 = "MIN_90"


class LabelSeries(str, Enum):
    UL_20MIN = "UL_20MIN"
    UL_45MIN = "UL_45MIN"
    UL_90MIN = "UL_90MIN"


class PunchCategory(str, Enum):
    FINISH_DEFECT = "FINISH_DEFECT"
    HARDWARE_MISALIGNMENT = "HARDWARE_MISALIGNMENT"
    TRANSIT_DAMAGE = "TRANSIT_DAMAGE"
    LABEL_MISSING = "LABEL_MISSING"


class PunchSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class UserRole(str, Enum):
    PLANT_MANAGER = "PlantManager"
    ESTIMATOR = "Estimator"
    ARCHITECT = "Architect"
    PRODUCTION_LEAD = "ProductionLead"
    LABEL_AUTHORITY = "LabelAuthority"
    QA_INSPECTOR = "QAInspector"
    SHIPPING_COORDINATOR = "ShippingCoordinator"
    ANY = "Any"


# All fourteen resources carry id, created_at, updated_at, version (PRD §2.4).

class Project(TypedDict, total=False):
    id: str
    name: str
    site_address: str
    contract_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class HardwareTemplate(TypedDict, total=False):
    id: str
    template_code: str
    manufacturer: str
    fire_rated_compatible: bool
    created_at: str
    updated_at: str
    version: int


class MoulderMachine(TypedDict, total=False):
    id: str
    machine_code: str
    supported_species: List[str]
    active: bool
    created_at: str
    updated_at: str
    version: int


class SprayBooth(TypedDict, total=False):
    id: str
    booth_code: str
    capacity: int
    created_at: str
    updated_at: str
    version: int


class FireLabelRoll(TypedDict, total=False):
    id: str
    label_series: str
    serial_capacity: int
    serials_issued: int
    serials_applied: int
    serials_spoiled: int
    serials_available: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MillworkOrder(TypedDict, total=False):
    id: str
    project_id: str
    order_code: str
    species: str
    profile_code: str
    finish_system: str
    sheen_target: str
    hardware_prep_mode: str
    hardware_template_id: Optional[str]
    fire_rating_required: str
    config_locked: bool
    budget_quote_cents: int
    merchandise_total_cents: int
    freight_fee_cents: int
    contract_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Opening(TypedDict, total=False):
    id: str
    order_id: str
    opening_no: str
    width_in: float
    height_in: float
    leaf_count: int
    fire_rating: str
    required_on_site_date: str
    fab_status: str
    ship_status: str
    assigned_trip_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShopDrawing(TypedDict, total=False):
    id: str
    order_id: str
    revision_no: int
    pinned_species: str
    pinned_profile_code: str
    pinned_sheen_target: str
    pinned_fire_rating_required: str
    pinned_hardware_prep_mode: str
    supersedes_drawing_id: Optional[str]
    submitted_by: Optional[str]
    reviewed_by: Optional[str]
    review_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MachiningProgram(TypedDict, total=False):
    id: str
    drawing_id: str
    order_id: str
    program_code: str
    estimated_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MoulderSetupSlot(TypedDict, total=False):
    id: str
    program_id: str
    machine_id: str
    species: str
    start_hour: int
    end_hour: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FinishingBatch(TypedDict, total=False):
    id: str
    order_id: str
    booth_id: str
    finish_family: str
    cure_start_hour: int
    cure_end_hour: int
    sheen_target_gu: int
    sheen_measured_gu: Optional[float]
    delta_gu: Optional[float]
    is_rework_batch: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class LabelAllocation(TypedDict, total=False):
    id: str
    opening_id: str
    roll_id: str
    serial_count: int
    issued_by: str
    applied_by: Optional[str]
    verified_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryTrip(TypedDict, total=False):
    id: str
    project_id: str
    trip_code: str
    truck_capacity_leaves: int
    departure_date: str
    site_arrival_date: str
    leaves_committed: int
    projected_fill_pct: float
    realized_fill_pct: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class PunchItem(TypedDict, total=False):
    id: str
    opening_id: str
    category: str
    severity: str
    description: str
    reported_by: str
    rework_batch_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
