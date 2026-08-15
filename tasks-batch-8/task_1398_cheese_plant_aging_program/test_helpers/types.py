"""Domain types: entity TypedDicts, status enums, role enum.

Every resource carries id, created_at, updated_at, and version (PRD section on
common resource properties).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLANT_ADMIN = "PlantAdmin"
    MILK_RECEIVER = "MilkReceiver"
    MAKE_PLANNER = "MakePlanner"
    CHEESEMAKER = "Cheesemaker"
    QA_GRADER = "QAGrader"
    AGING_ROOM_OPERATOR = "AgingRoomOperator"
    SALES_PLANNER = "SalesPlanner"
    CUT_WRAP_OPERATOR = "CutWrapOperator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


class Variety(str, Enum):
    CHEDDAR = "CHEDDAR"
    COLBY = "COLBY"
    BRICK = "BRICK"
    MUENSTER = "MUENSTER"


class MilkIntakeStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CONSUMED = "CONSUMED"


class VatStatus(str, Enum):
    IDLE = "IDLE"
    BOOKED = "BOOKED"
    IN_MAKE = "IN_MAKE"
    CLEANING = "CLEANING"
    DECOMMISSIONED = "DECOMMISSIONED"


class MakeSheetStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    CURD_READY = "CURD_READY"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AdditiveLotStatus(str, Enum):
    QUARANTINE = "QUARANTINE"
    RELEASED = "RELEASED"
    DEPLETED = "DEPLETED"
    EXPIRED = "EXPIRED"
    RECALLED = "RECALLED"


class CheeseBatchStatus(str, Enum):
    GREEN = "GREEN"
    AGING = "AGING"
    GRADED = "GRADED"
    RELEASED = "RELEASED"
    ALLOCATED = "ALLOCATED"
    CONDEMNED = "CONDEMNED"


class Grade(str, Enum):
    UNGRADED = "UNGRADED"
    GRADE_A = "GRADE_A"
    GRADE_B = "GRADE_B"
    DOWNGRADE = "DOWNGRADE"
    CONDEMNED = "CONDEMNED"


class ReleaseDecision(str, Enum):
    PENDING = "PENDING"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"


class AgingRoomStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECOMMISSIONED = "DECOMMISSIONED"


class RoomPosture(str, Enum):
    AVAILABLE = "AVAILABLE"
    FULL = "FULL"
    DEVIATION = "DEVIATION"


class AgingUnitStatus(str, Enum):
    IN_ROOM = "IN_ROOM"
    MOVED = "MOVED"
    REMOVED = "REMOVED"


class AllocationOrderStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


class CutWrapRunStatus(str, Enum):
    DRAFT = "DRAFT"
    RECONCILED = "RECONCILED"
    VOIDED = "VOIDED"


class ExportCertificateStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ISSUED = "ISSUED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class Channel(str, Enum):
    PRIVATE_LABEL = "PRIVATE_LABEL"
    BRANDED = "BRANDED"


class Plant(TypedDict, total=False):
    id: str
    name: str
    license_number: str
    export_listed: bool
    total_aging_capacity_wheels: int
    created_at: str
    updated_at: str
    version: int


class MilkIntake(TypedDict, total=False):
    id: str
    plant_id: str
    hauler_ticket: str
    received_at: str
    volume_liters: float
    fat_pct: float
    protein_pct: float
    somatic_cell_count: int
    antibiotics_detected: bool
    status: str
    consumed_liters: float
    created_at: str
    updated_at: str
    version: int


class Vat(TypedDict, total=False):
    id: str
    plant_id: str
    code: str
    capacity_liters: int
    cip_clean: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class MakeSheet(TypedDict, total=False):
    id: str
    plant_id: str
    vat_id: str
    milk_intake_id: str
    variety: str
    scheduled_start: str
    scheduled_end: str
    liters_committed: float
    culture_lot_id: str
    coagulant_lot_id: str
    culture_units_planned: float
    coagulant_ml_planned: float
    make_steps_completed: int
    make_steps_required: int
    step_signer_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AdditiveLot(TypedDict, total=False):
    id: str
    plant_id: str
    kind: str
    supplier_lot_no: str
    expires_at: str
    quantity_on_hand: float
    quantity_initial: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CheeseBatch(TypedDict, total=False):
    id: str
    plant_id: str
    make_sheet_id: str
    variety: str
    green_weight_kg: float
    yield_provisional_pct: float
    yield_actual_pct: float
    wheels_produced: int
    wheels_placed: int
    moisture_pct: float
    fat_dry_basis_pct: float
    current_grade: str
    release_decision: str
    min_age_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WheyStream(TypedDict, total=False):
    id: str
    plant_id: str
    make_sheet_id: str
    total_whey_kg: float
    valorized_kg: float
    disposed_kg: float
    valorization_rate_pct: float
    created_at: str
    updated_at: str
    version: int


class AgingRoom(TypedDict, total=False):
    id: str
    plant_id: str
    code: str
    capacity_wheels: int
    wheels_present: int
    temp_c: float
    humidity_pct: float
    posture: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AgingUnit(TypedDict, total=False):
    id: str
    plant_id: str
    cheese_batch_id: str
    aging_room_id: str
    wheel_count: int
    entered_at: str
    age_days: int
    last_turned_at: str
    turns_due: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class GradingEvent(TypedDict, total=False):
    id: str
    plant_id: str
    cheese_batch_id: str
    grader_user_id: str
    moisture_pct: float
    fat_dry_basis_pct: float
    body_score: int
    flavor_score: int
    assigned_grade: str
    graded_at: str
    supersedes_grading_event_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AllocationOrder(TypedDict, total=False):
    id: str
    plant_id: str
    cheese_batch_id: str
    channel: str
    customer_name: str
    wheels_requested: int
    wheels_cut: int
    priority: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CutWrapRun(TypedDict, total=False):
    id: str
    plant_id: str
    allocation_order_id: str
    wheels_in: int
    finished_case_weight_kg: float
    trim_waste_kg: float
    input_weight_kg: float
    reconciliation_gap_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ExportCertificate(TypedDict, total=False):
    id: str
    plant_id: str
    cut_wrap_run_id: str
    destination_country: str
    consignee: str
    certificate_number: str
    issued_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
