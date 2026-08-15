"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    SAILMAKER = "Sailmaker"
    MEASURER = "Measurer"
    RIGGER = "Rigger"
    LOFT_MANAGER = "LoftManager"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class BoatStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    RETIRED = "RETIRED"


class MastStatus(str, Enum):
    STEPPED = "STEPPED"
    UNSTEPPING_SCHEDULED = "UNSTEPPING_SCHEDULED"
    UNSTEPPED = "UNSTEPPED"
    TUNING_IN_PROGRESS = "TUNING_IN_PROGRESS"


class RacingClass(str, Enum):
    NONE = "NONE"
    J70 = "J70"
    J105 = "J105"
    TP52 = "TP52"
    ORC = "ORC"
    PHRF = "PHRF"


class SheetStatus(str, Enum):
    DRAFT = "DRAFT"
    FROZEN = "FROZEN"
    SUPERSEDED = "SUPERSEDED"


class ClothTier(str, Enum):
    CRUISE = "CRUISE"
    PERFORMANCE = "PERFORMANCE"
    RACE = "RACE"
    GRAND_PRIX = "GRAND_PRIX"


class OptionCode(str, Enum):
    BATTENS = "BATTENS"
    REEF_POINTS = "REEF_POINTS"
    UV_STRIP = "UV_STRIP"
    NUMBERS = "NUMBERS"
    LOGO = "LOGO"


class DesignStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class OrderKind(str, Enum):
    NEW_SAIL = "NEW_SAIL"
    RIGGING_SERVICE = "RIGGING_SERVICE"
    MAST_SERVICE = "MAST_SERVICE"
    STORAGE_PROGRAM = "STORAGE_PROGRAM"
    REPAIR = "REPAIR"


class OrderStatus(str, Enum):
    OPEN = "OPEN"
    DESIGN_LOCKED = "DESIGN_LOCKED"
    IN_PRODUCTION = "IN_PRODUCTION"
    READY_FOR_FIT_CHECK = "READY_FOR_FIT_CHECK"
    DELIVERED = "DELIVERED"
    WARRANTY_REVIEW = "WARRANTY_REVIEW"
    WARRANTY_REPAIR = "WARRANTY_REPAIR"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class BayCode(str, Enum):
    BAY_A = "BAY_A"
    BAY_B = "BAY_B"
    BAY_C = "BAY_C"


class JobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CUTTING = "CUTTING"
    SEAMING = "SEAMING"
    FINISHING = "FINISHING"
    QC_PASSED = "QC_PASSED"
    QC_FAILED = "QC_FAILED"
    CANCELLED = "CANCELLED"


class RiggingScope(str, Enum):
    STANDING = "STANDING"
    RUNNING = "RUNNING"
    FULL = "FULL"


class Verdict(str, Enum):
    PASS = "PASS"
    ADVISORY = "ADVISORY"
    FAIL = "FAIL"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    REPORTED = "REPORTED"
    CLOSED = "CLOSED"


class ServiceKind(str, Enum):
    UNSTEP = "UNSTEP"
    STEP = "STEP"
    TUNE = "TUNE"


class MastEventStatus(str, Enum):
    BOOKED = "BOOKED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    RIGGING_HOLD = "RIGGING_HOLD"
    CANCELLED = "CANCELLED"


class WashItem(str, Enum):
    MAIN_WASH = "MAIN_WASH"
    GENOA_WASH = "GENOA_WASH"
    SPINNAKER_WASH = "SPINNAKER_WASH"
    RIG_WASH = "RIG_WASH"


class ContractStatus(str, Enum):
    ENROLLED = "ENROLLED"
    RECEIVED = "RECEIVED"
    WASHED = "WASHED"
    STORED = "STORED"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class CertStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


# All resources carry the four system-managed properties of PRD §2.4:
# id, created_at, updated_at, version.


class Customer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    credit_limit_cents: int
    outstanding_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Boat(TypedDict, total=False):
    id: str
    customer_id: str
    boat_name: str
    hull_length_m: float
    racing_class: str
    mast_status: str
    standing_rigging_install_date: str
    running_rigging_hours_accumulated: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MeasurementSheet(TypedDict, total=False):
    id: str
    boat_id: str
    captured_by_measurer_id: str
    i_height_m: float
    j_base_m: float
    p_main_m: float
    e_main_m: float
    measured_area_sqm: float
    sheet_status: str
    frozen_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SailDesign(TypedDict, total=False):
    id: str
    boat_id: str
    measurement_sheet_id: str
    revision_number: int
    supersedes_design_id: Optional[str]
    cloth_tier: str
    reinforcement_level: int
    option_codes: List[str]
    design_status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LoftWorkOrder(TypedDict, total=False):
    id: str
    customer_id: str
    boat_id: str
    sail_design_id: Optional[str]
    order_kind: str
    quoted_total_cents: int
    invoiced_total_cents: int
    warranty_flag: bool
    order_status: str
    created_at: str
    updated_at: str
    version: int


class ProductionJob(TypedDict, total=False):
    id: str
    work_order_id: str
    bay_code: str
    scheduled_start_date: str
    scheduled_end_date: str
    reserved_cloth_sqm: float
    qc_notes: Optional[str]
    job_status: str
    created_at: str
    updated_at: str
    version: int


class ClothLedgerEntry(TypedDict, total=False):
    id: str
    bolt_code: str
    cloth_tier: str
    total_sqm: float
    available_sqm: float
    price_per_sqm_cents: int
    created_at: str
    updated_at: str
    version: int


class RiggingInspection(TypedDict, total=False):
    id: str
    boat_id: str
    rigging_scope: str
    inspected_at: Optional[str]
    standing_months_at_inspection: int
    standing_replacement_due_date: str
    running_replacement_due_hours: int
    verdict: str
    inspection_status: str
    created_at: str
    updated_at: str
    version: int


class MastServiceEvent(TypedDict, total=False):
    id: str
    boat_id: str
    service_kind: str
    slot_start_utc: str
    slot_end_utc: str
    event_status: str
    created_at: str
    updated_at: str
    version: int


class StorageContract(TypedDict, total=False):
    id: str
    boat_id: str
    season_code: str
    wash_item_codes: List[str]
    quoted_storage_fee_cents: int
    contract_status: str
    created_at: str
    updated_at: str
    version: int


class ClassCertificate(TypedDict, total=False):
    id: str
    boat_id: str
    measurement_sheet_id: str
    racing_class: str
    issued_at: str
    cert_status: str
    created_at: str
    updated_at: str
    version: int
