"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    CUSTOMER_REP = "CustomerRep"
    TEST_ENGINEER = "TestEngineer"
    OPERATIONS_MANAGER = "OperationsManager"
    QUALITY_ENGINEER = "QualityEngineer"


class CustomerTier(str, Enum):
    STANDARD = "STANDARD"
    STRATEGIC = "STRATEGIC"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TestProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    RELEASED = "RELEASED"
    OBSOLETE = "OBSOLETE"


class FixtureStatus(str, Enum):
    COMMISSIONING = "COMMISSIONING"
    AVAILABLE = "AVAILABLE"
    UNDER_MAINTENANCE = "UNDER_MAINTENANCE"
    DECOMMISSIONED = "DECOMMISSIONED"


class ChamberStatus(str, Enum):
    ONLINE = "ONLINE"
    MAINTENANCE = "MAINTENANCE"
    OFFLINE = "OFFLINE"


class ReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class LotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    QUEUED = "QUEUED"
    IN_TEST = "IN_TEST"
    AWAITING_DISPOSITION = "AWAITING_DISPOSITION"
    CONTAINED = "CONTAINED"
    SHIPPED = "SHIPPED"
    SCRAPPED = "SCRAPPED"


class UnitTestStatus(str, Enum):
    UNTESTED = "UNTESTED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class AuthorizationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class EquipmentStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    CALIBRATION_DUE = "CALIBRATION_DUE"
    IN_MAINTENANCE = "IN_MAINTENANCE"
    RETURNED = "RETURNED"


class EquipmentType(str, Enum):
    TESTER = "TESTER"
    HANDLER = "HANDLER"
    PROBER = "PROBER"


class MaintenanceTargetType(str, Enum):
    EQUIPMENT = "EQUIPMENT"
    CHAMBER = "CHAMBER"


class MaintenanceKind(str, Enum):
    CALIBRATION = "CALIBRATION"
    REPAIR = "REPAIR"
    PREVENTIVE = "PREVENTIVE"


class MaintenanceOrderStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class EsdAuditStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class EsdOutcome(str, Enum):
    PASS = "PASS"
    PASS_WITH_MINOR = "PASS_WITH_MINOR"
    FAIL = "FAIL"


class RmaFaStatus(str, Enum):
    INTAKE = "INTAKE"
    FA_IN_PROGRESS = "FA_IN_PROGRESS"
    FA_COMPLETE = "FA_COMPLETE"
    CLOSED = "CLOSED"


class RmaConclusion(str, Enum):
    TEST_ESCAPE = "TEST_ESCAPE"
    CUSTOMER_INDUCED = "CUSTOMER_INDUCED"
    NO_TROUBLE_FOUND = "NO_TROUBLE_FOUND"


class ReviewStatus(str, Enum):
    PENDING = "PENDING"
    DECIDED = "DECIDED"


class Disposition(str, Enum):
    SHIP = "SHIP"
    MRB_REVIEW = "MRB_REVIEW"
    SCRAP_REVIEW = "SCRAP_REVIEW"


class ReviewDecision(str, Enum):
    SHIP = "SHIP"
    SCRAP = "SCRAP"
    REWORK = "REWORK"


class BinClass(str, Enum):
    PASS = "PASS"
    SOFT_FAIL = "SOFT_FAIL"
    HARD_FAIL = "HARD_FAIL"


# --- Entity TypedDicts ---
# Primary resources carry id + created_at + updated_at + version (PRD §2.4).


class Customer(TypedDict, total=False):
    id: str
    name: str
    tier: str
    requires_esd_certification: bool
    account_status: str
    created_at: str
    updated_at: str
    version: int


class TestProgram(TypedDict, total=False):
    id: str
    customer_id: str
    part_number: str
    revision: int
    supersedes_program_id: Optional[str]
    bin_map: Dict[str, str]
    max_retests_per_unit: int
    burn_profile: List[Dict[str, Any]]
    status: str
    created_at: str
    updated_at: str
    version: int


class Fixture(TypedDict, total=False):
    id: str
    program_id: str
    serial_number: str
    site_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Chamber(TypedDict, total=False):
    id: str
    name: str
    area_code: str
    slot_count: int
    supported_profile_classes: List[str]
    status: str
    available_slots: int
    created_at: str
    updated_at: str
    version: int


class ChamberReservation(TypedDict, total=False):
    id: str
    chamber_id: str
    lot_id: str
    fixture_id: str
    profile_class: str
    start_at: str
    end_at: str
    slot_count: int
    planned_duration_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict, total=False):
    id: str
    customer_id: str
    program_id: str
    part_number: str
    quantity: int
    status: str
    units_registered: int
    units_untested: int
    units_passed: int
    units_failed: int
    retested_unit_count: int
    escape_count: int
    suggested_disposition: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict, total=False):
    id: str
    lot_id: str
    serial_number: str
    test_status: str
    current_bin: Optional[int]
    retest_count: int
    created_at: str
    updated_at: str
    version: int


class TestResult(TypedDict, total=False):
    # Append-only event record (PRD §2.4): carries ONLY id + created_at,
    # never updated_at, never version — even after being voided.
    id: str
    unit_id: str
    lot_id: str
    program_id: str
    fixture_id: str
    equipment_id: Optional[str]
    bin_code: int
    passed: bool
    insertion_index: int
    recorded_by_user_id: str
    consumed_authorization_id: Optional[str]
    voided: bool
    void_reason: Optional[str]
    excluded_from_tally: bool
    created_at: str


class RetestAuthorization(TypedDict, total=False):
    id: str
    unit_id: str
    reason: str
    authorized_by_user_id: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomerEquipment(TypedDict, total=False):
    id: str
    customer_id: str
    equipment_type: str
    serial_number: str
    calibration_interval_days: int
    last_calibrated_at: str
    next_calibration_due: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceOrder(TypedDict, total=False):
    id: str
    target_type: str
    target_id: str
    kind: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EsdAudit(TypedDict, total=False):
    id: str
    area_code: str
    findings: List[Dict[str, Any]]
    corrective_actions: List[Dict[str, Any]]
    outcome: Optional[str]
    auditor_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RmaCase(TypedDict, total=False):
    id: str
    lot_id: str
    unit_id: str
    failure_mode: str
    fa_status: str
    fa_conclusion: Optional[str]
    created_by_customer_id: str
    created_at: str
    updated_at: str
    version: int


class LotDispositionReview(TypedDict, total=False):
    id: str
    lot_id: str
    suggested_disposition: Optional[str]
    decision: Optional[str]
    rationale: Optional[str]
    decided_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
