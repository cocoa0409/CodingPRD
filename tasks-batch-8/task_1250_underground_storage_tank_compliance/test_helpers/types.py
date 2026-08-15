"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    FACILITY_OWNER = "FacilityOwner"
    CONTRACTOR_ADMIN = "ContractorAdmin"
    TECHNICIAN = "Technician"
    COMPLIANCE_REVIEWER = "ComplianceReviewer"
    STATE_REGULATOR = "StateRegulator"
    ANY = "Any"


class FacilityStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class CompliancePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    DEFICIENT = "DEFICIENT"
    NON_COMPLIANT = "NON_COMPLIANT"


class FundProgramElection(str, Enum):
    PER_OCCURRENCE = "PER_OCCURRENCE"
    AGGREGATE = "AGGREGATE"


class TankSystemStatus(str, Enum):
    REGISTERED = "REGISTERED"
    IN_SERVICE = "IN_SERVICE"
    TEMPORARILY_CLOSED = "TEMPORARILY_CLOSED"
    PERMANENTLY_CLOSED = "PERMANENTLY_CLOSED"


class Substance(str, Enum):
    GASOLINE = "GASOLINE"
    DIESEL = "DIESEL"
    KEROSENE = "KEROSENE"
    USED_OIL = "USED_OIL"


class TankConstruction(str, Enum):
    STEEL = "STEEL"
    FRP = "FRP"
    COMPOSITE = "COMPOSITE"


class PipingType(str, Enum):
    PRESSURIZED = "PRESSURIZED"
    SUCTION = "SUCTION"
    GRAVITY = "GRAVITY"


class ReleaseDetectionMode(str, Enum):
    INTERSTITIAL_MONITORING = "INTERSTITIAL_MONITORING"
    ATG_INVENTORY = "ATG_INVENTORY"
    MANUAL_GAUGING = "MANUAL_GAUGING"


class ComponentType(str, Enum):
    SPILL_BUCKET = "SPILL_BUCKET"
    OVERFILL_DEVICE = "OVERFILL_DEVICE"
    LINE_LEAK_DETECTOR = "LINE_LEAK_DETECTOR"
    CATHODIC_PROTECTION = "CATHODIC_PROTECTION"


class ComponentStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    DEFICIENT = "DEFICIENT"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class Endorsement(str, Enum):
    TIGHTNESS_TESTER = "TIGHTNESS_TESTER"
    LLD_TESTER = "LLD_TESTER"
    CP_TESTER = "CP_TESTER"
    INSPECTOR = "INSPECTOR"


class ServiceType(str, Enum):
    TANK_TIGHTNESS = "TANK_TIGHTNESS"
    LINE_TIGHTNESS = "LINE_TIGHTNESS"
    LLD_FUNCTION = "LLD_FUNCTION"
    CP_SURVEY = "CP_SURVEY"
    SPILL_OVERFILL_INSPECTION = "SPILL_OVERFILL_INSPECTION"


class ServiceOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    UNDER_REVIEW = "UNDER_REVIEW"
    CERTIFIED = "CERTIFIED"
    CANCELLED = "CANCELLED"


class ResultOutcome(str, Enum):
    NONE = "NONE"
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


class DeficiencyStatus(str, Enum):
    OPEN = "OPEN"
    CORRECTION_ORDERED = "CORRECTION_ORDERED"
    CORRECTED = "CORRECTED"
    RE_TEST_SCHEDULED = "RE_TEST_SCHEDULED"
    ESCALATED = "ESCALATED"
    VERIFIED_CLOSED = "VERIFIED_CLOSED"


class DeficiencyOrigin(str, Enum):
    TEST_FAILURE = "TEST_FAILURE"
    CLOSE_SWEEP = "CLOSE_SWEEP"


class DeficiencySeverity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class SubmissionType(str, Enum):
    MONTHLY_RELEASE_DETECTION = "MONTHLY_RELEASE_DETECTION"
    TEST_REPORT = "TEST_REPORT"
    RELEASE_NOTIFICATION = "RELEASE_NOTIFICATION"


class SubmissionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class RecordStatus(str, Enum):
    RECORDED = "RECORDED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"


class OperatorClass(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class OperatorStatus(str, Enum):
    DESIGNATED = "DESIGNATED"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    REVOKED = "REVOKED"


class ReleaseEventStatus(str, Enum):
    SUSPECTED = "SUSPECTED"
    CONFIRMED = "CONFIRMED"
    CLEANUP_IN_PROGRESS = "CLEANUP_IN_PROGRESS"
    CLOSED = "CLOSED"
    DISMISSED = "DISMISSED"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class CPCriterion(str, Enum):
    INSTANT_OFF = "INSTANT_OFF"
    POLARIZATION_SHIFT = "POLARIZATION_SHIFT"


# --- Entity TypedDicts (PRD §2.5 common properties; §3 entity fields) ---

class Facility(TypedDict, total=False):
    id: str
    facility_name: str
    state_code: str
    owner_account_id: str
    annual_fee_paid_through: str
    fund_program_election: str
    posture_score: int
    compliance_posture: str
    fund_cap_remaining_cents: int
    fund_year_deductible_remaining_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TankSystem(TypedDict, total=False):
    id: str
    facility_id: str
    tank_tag: str
    substance: str
    capacity_gallons: int
    installed_on: str
    tank_construction: str
    piping_type: str
    release_detection_mode: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Component(TypedDict, total=False):
    id: str
    tank_system_id: str
    component_type: str
    install_date: str
    serial_no: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict, total=False):
    id: str
    full_name: str
    endorsements: List[str]
    trainer: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class ServiceOrder(TypedDict, total=False):
    id: str
    facility_id: str
    tank_system_id: str
    component_id: Optional[str]
    service_type: str
    technician_id: Optional[str]
    window_start: Optional[str]
    window_end: Optional[str]
    line_items: List[dict]
    quote_total_cents: int
    result_outcome: str
    performed_by_technician_id: Optional[str]
    certified_by_technician_id: Optional[str]
    linked_deficiency_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only ledger (PRD §2.5): carries only id + created_at of the common set;
# no updated_at, no version.
class ResultRecord(TypedDict, total=False):
    id: str
    service_order_id: str
    readings: dict
    outcome: str
    recorded_at: str
    created_at: str


class Deficiency(TypedDict, total=False):
    id: str
    facility_id: str
    tank_system_id: str
    component_id: Optional[str]
    source_service_order_id: Optional[str]
    verified_by_service_order_id: Optional[str]
    origin: str
    period_month: Optional[str]
    severity: str
    description: str
    correction_deadline: str
    escalated_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RegulatorySubmission(TypedDict, total=False):
    id: str
    facility_id: str
    submission_type: str
    period_month: Optional[str]
    release_detection_record_ids: Optional[List[str]]
    service_order_ids: Optional[List[str]]
    release_event_id: Optional[str]
    submitted_at: Optional[str]
    is_late: bool
    state_reviewer_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReleaseDetectionRecord(TypedDict, total=False):
    id: str
    tank_system_id: str
    period_month: str
    method: str
    readings_summary: dict
    status: str
    created_at: str
    updated_at: str
    version: int


class OperatorPerson(TypedDict, total=False):
    id: str
    facility_id: str
    full_name: str
    operator_class: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only ledger (PRD §2.5): no updated_at, no version.
class TrainingRecord(TypedDict, total=False):
    id: str
    operator_id: str
    instructor_technician_id: str
    course_class: str
    completed_at: str
    expires_at: str
    created_at: str


class ReleaseEvent(TypedDict, total=False):
    id: str
    facility_id: str
    tank_system_id: Optional[str]
    discovered_at: str
    source_description: str
    report_deadline: str
    reported_to_state_at: Optional[str]
    late_notification: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class StateFundClaim(TypedDict, total=False):
    id: str
    facility_id: str
    release_event_id: str
    expense_lines: List[dict]
    deductible_applied_cents: int
    eligible_amount_cents: int
    payable_amount_cents: int
    approved_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
