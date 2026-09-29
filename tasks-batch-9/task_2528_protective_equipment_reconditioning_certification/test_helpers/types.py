"""Domain types for the protective-equipment reconditioning API.

Status enums, role enum and entity TypedDicts, all named exactly as the PRD
names them. Entities that the PRD gives the common system fields carry
``id``/``created_at``/``updated_at``/``version``; ``ComponentInspection`` is
append-only and carries only ``id`` and ``created_at``.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Role enum (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PLANT_MANAGER = "PlantManager"
    INTAKE_CLERK = "IntakeClerk"
    TECHNICIAN = "Technician"
    CERTIFYING_INSPECTOR = "CertifyingInspector"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CUSTOMER_CONTACT = "CustomerContact"


# --------------------------------------------------------------------------
# Reference-data enums
# --------------------------------------------------------------------------
class OrgType(str, Enum):
    SCHOOL = "SCHOOL"
    CLUB = "CLUB"
    COLLEGE = "COLLEGE"
    MUNICIPAL = "MUNICIPAL"


class Sport(str, Enum):
    FOOTBALL = "FOOTBALL"
    LACROSSE = "LACROSSE"
    HOCKEY = "HOCKEY"
    BASEBALL = "BASEBALL"


class ShellMaterial(str, Enum):
    POLYCARBONATE = "POLYCARBONATE"
    ABS = "ABS"


class ComponentCode(str, Enum):
    SHELL = "SHELL"
    LINER = "LINER"
    FACEMASK = "FACEMASK"
    CHINSTRAP = "CHINSTRAP"
    HARDWARE = "HARDWARE"


class MetricDirection(str, Enum):
    HIGHER_IS_WORSE = "HIGHER_IS_WORSE"
    LOWER_IS_WORSE = "LOWER_IS_WORSE"


class TestType(str, Enum):
    DROP_IMPACT = "DROP_IMPACT"
    PNEUMATIC_RAM = "PNEUMATIC_RAM"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class ServiceTier(str, Enum):
    STANDARD = "STANDARD"
    SEASONAL_CONTRACT = "SEASONAL_CONTRACT"
    PRIORITY_RUSH = "PRIORITY_RUSH"


class Conditioning(str, Enum):
    AMBIENT = "AMBIENT"
    HOT = "HOT"
    COLD = "COLD"


class AgeBasis(str, Enum):
    MANUFACTURE_DATE = "MANUFACTURE_DATE"
    FIRST_SEASON = "FIRST_SEASON"


class DiscrepancyResolution(str, Enum):
    MATCHED = "MATCHED"
    CUSTOMER_CONFIRMED = "CUSTOMER_CONFIRMED"
    WRITTEN_OFF = "WRITTEN_OFF"


class DestructionMethod(str, Enum):
    SHELL_CRUSH = "SHELL_CRUSH"
    BAND_SAW_CUT = "BAND_SAW_CUT"
    SHREDDING = "SHREDDING"


class VerifyOutcome(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


# --------------------------------------------------------------------------
# Computed-posture enums
# --------------------------------------------------------------------------
class CustomerAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BILLING_HOLD = "BILLING_HOLD"


class LiabilityWaiverStatus(str, Enum):
    MISSING = "MISSING"
    ON_FILE = "ON_FILE"
    STALE = "STALE"


class LoanerUnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    OUT_ON_LOAN = "OUT_ON_LOAN"


class IntakeShipmentStatus(str, Enum):
    DRAFT = "DRAFT"
    COUNTED = "COUNTED"
    QUARANTINED = "QUARANTINED"
    ACCEPTED = "ACCEPTED"
    IN_PROCESS = "IN_PROCESS"
    READY_FOR_RETURN = "READY_FOR_RETURN"
    CLOSED = "CLOSED"


class ReconStatus(str, Enum):
    RECEIVED = "RECEIVED"
    IDENTIFIED = "IDENTIFIED"
    DISASSEMBLED = "DISASSEMBLED"
    INSPECTED = "INSPECTED"
    TESTED = "TESTED"
    TEST_PASSED = "TEST_PASSED"
    REPAIR_PENDING = "REPAIR_PENDING"
    REPAIRED = "REPAIRED"
    CERTIFIED = "CERTIFIED"
    CONDEMNED = "CONDEMNED"


class CustodyStatus(str, Enum):
    AT_PLANT = "AT_PLANT"
    STAGED_FOR_RETURN = "STAGED_FOR_RETURN"
    RETURNED = "RETURNED"
    PENDING_DISPOSAL = "PENDING_DISPOSAL"
    DISPOSED = "DISPOSED"


class InspectionVerdictSummary(str, Enum):
    PENDING = "PENDING"
    CLEAR = "CLEAR"
    REPLACE_REQUIRED = "REPLACE_REQUIRED"
    FAIL = "FAIL"


class WarrantyCoverage(str, Enum):
    PENDING = "PENDING"
    IN_WARRANTY = "IN_WARRANTY"
    OUT_OF_WARRANTY = "OUT_OF_WARRANTY"


class CondemnReason(str, Enum):
    SI_EXCEEDS_LIMIT = "SI_EXCEEDS_LIMIT"
    COMPONENT_FAIL = "COMPONENT_FAIL"
    LIFE_EXPIRED = "LIFE_EXPIRED"
    NOT_RECONDITIONABLE = "NOT_RECONDITIONABLE"
    REPAIR_UNSUCCESSFUL = "REPAIR_UNSUCCESSFUL"


class ComponentVerdict(str, Enum):
    PASS = "PASS"
    REPLACE = "REPLACE"
    FAIL = "FAIL"


class ShellTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    DETERMINED = "DETERMINED"


class ShellTestResult(str, Enum):
    PASS = "PASS"
    REPAIR = "REPAIR"
    CONDEMN = "CONDEMN"


class RepairOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PARTS_PENDING = "PARTS_PENDING"
    INSTALLED = "INSTALLED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PartLineStatus(str, Enum):
    DRAFT = "DRAFT"
    RESERVED = "RESERVED"
    INSTALLED = "INSTALLED"


class CertificationLabelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class DestructionRecordStatus(str, Enum):
    PENDING = "PENDING"
    WITNESSED = "WITNESSED"
    VERIFIED = "VERIFIED"


class LoanerAssignmentStatus(str, Enum):
    RESERVED = "RESERVED"
    OUT_ON_LOAN = "OUT_ON_LOAN"
    RETURNED = "RETURNED"


class LoanerSelectedBy(str, Enum):
    EXPLICIT = "EXPLICIT"
    SERVER_SELECTED = "SERVER_SELECTED"


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------
class CustomerAccount(TypedDict):
    id: str
    org_name: str
    org_type: str
    sport: str
    contact_email: str
    status: str
    billing_hold_reason: Optional[str]
    liability_waiver_version: Optional[str]
    liability_waiver_signed_at: Optional[str]
    liability_waiver_signer: Optional[str]
    liability_waiver_status: str
    open_shipment_count: int
    loaner_recall_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ModelSpec(TypedDict):
    id: str
    manufacturer: str
    model_code: str
    standard_code: str
    shell_material: str
    max_service_life_years: int
    warranty_years: int
    record_retention_years: int
    pass_si_max: float
    repair_si_max: float
    max_retest_count: int
    reconditionable: bool
    required_component_codes: List[str]
    component_criteria: List[dict]
    created_at: str
    updated_at: str
    version: int


class ApprovedPart(TypedDict):
    id: str
    model_spec_id: str
    part_number: str
    component_code: str
    oem_approved: bool
    unit_price_cents: int
    received_qty: int
    on_hand_qty: int
    reserved_qty: int
    consumed_qty: int
    created_at: str
    updated_at: str
    version: int


class TestBench(TypedDict):
    id: str
    bench_code: str
    test_type: str
    cooldown_minutes: int
    daily_session_quota: int
    calibration_valid_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LoanerUnit(TypedDict):
    id: str
    model_spec_id: str
    asset_tag: str
    condition_grade: str
    certification_valid_until: str
    assignment_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IntakeShipment(TypedDict):
    id: str
    customer_account_id: str
    sport: str
    service_tier: str
    declared_unit_count: int
    season_start_date: str
    season_end_date: str
    counted_unit_count: Optional[int]
    discrepancy_count: Optional[int]
    discrepancy_resolution: Optional[str]
    units_registered: int
    units_in_process: int
    units_certified: int
    units_condemned: int
    units_released: int
    accepted_at: Optional[str]
    raw_due_at: Optional[str]
    committed_due_at: Optional[str]
    loaner_required: bool
    provisional_total_cents: Optional[int]
    final_total_cents: Optional[int]
    settlement_locked: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentUnit(TypedDict):
    id: str
    intake_shipment_id: str
    serial_number: str
    declared_model_code: Optional[str]
    model_spec_id: Optional[str]
    manufacture_date: Optional[str]
    age_basis: Optional[str]
    service_age_years: Optional[int]
    life_expired: bool
    inspection_verdict_summary: str
    condemn_required: bool
    warranty_coverage: str
    retest_count: int
    current_si: Optional[float]
    certified_at: Optional[str]
    record_retention_until: Optional[str]
    records_purged_at: Optional[str]
    condemn_reason: Optional[str]
    recon_status: str
    custody_status: str
    released_to: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComponentInspection(TypedDict):
    """Append-only inspection record: only ``id`` and ``created_at`` system fields."""
    id: str
    equipment_unit_id: str
    component_code: str
    measurement_value: float
    measurement_unit: str
    note: Optional[str]
    replace_threshold_applied: float
    fail_threshold_applied: float
    metric_direction_applied: str
    verdict: str
    inspector_user_id: str
    created_at: str


class ShellTest(TypedDict):
    id: str
    equipment_unit_id: str
    test_bench_id: str
    window_start: str
    window_end: str
    conditioning: str
    attempt_index: int
    peak_g_front: Optional[float]
    peak_g_side: Optional[float]
    peak_g_crown: Optional[float]
    severity_index: Optional[float]
    computed_result: Optional[str]
    determination: Optional[str]
    override_reason: Optional[str]
    determined_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RepairOrder(TypedDict):
    id: str
    equipment_unit_id: str
    part_lines: List[dict]
    reserved_parts_cents: int
    installed_parts_cents: int
    labor_cents: int
    warranty_claim_ref: Optional[str]
    verification_failure_count: int
    opened_by_user_id: str
    installed_by_user_id: Optional[str]
    verified_by_user_id: Optional[str]
    cancel_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CertificationLabel(TypedDict):
    id: str
    equipment_unit_id: str
    label_code: str
    standard_code_snapshot: str
    certified_on: str
    daily_sequence: int
    issued_by_user_id: str
    void_reason: Optional[str]
    voided_at: Optional[str]
    voided_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DestructionRecord(TypedDict):
    id: str
    equipment_unit_id: str
    condemn_reason_snapshot: str
    method: Optional[str]
    witness_name: Optional[str]
    witnessed_by_user_id: Optional[str]
    witnessed_at: Optional[str]
    verification_ref: Optional[str]
    verified_by_user_id: Optional[str]
    verified_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LoanerAssignment(TypedDict):
    id: str
    customer_account_id: str
    requested_model_spec_id: str
    loaner_unit_id: str
    window_start: str
    window_end: str
    selected_by: str
    returned_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
