"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PRODUCTION_EXECUTIVE = "ProductionExecutive"
    STUNT_COORDINATOR = "StuntCoordinator"
    SAFETY_OFFICER = "SafetyOfficer"
    DEPARTMENT_HEAD = "DepartmentHead"
    PERFORMER = "Performer"
    EQUIPMENT_INSPECTOR = "EquipmentInspector"


class ProductionPosture(str, Enum):
    SETUP = "SETUP"
    ACTIVE = "ACTIVE"
    STOPPED = "STOPPED"
    WRAPPED = "WRAPPED"


class InsuranceStatus(str, Enum):
    UNFILED = "UNFILED"
    FILED = "FILED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class SequenceStatus(str, Enum):
    DRAFT = "DRAFT"
    DESIGN_LOCKED = "DESIGN_LOCKED"
    READY = "READY"
    SAFETY_HOLD = "SAFETY_HOLD"
    EXECUTED = "EXECUTED"
    REVIEWED = "REVIEWED"
    CANCELLED = "CANCELLED"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class PerformerStatus(str, Enum):
    REGISTERED = "REGISTERED"
    QUALIFIED = "QUALIFIED"
    SUSPENDED = "SUSPENDED"


class RehearsalStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"
    VOIDED = "VOIDED"


class MeetingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_SESSION = "IN_SESSION"
    COMPLETED = "COMPLETED"
    ADJOURNED = "ADJOURNED"


class SignoffStatus(str, Enum):
    PENDING = "PENDING"
    SIGNED = "SIGNED"
    SIGNED_WITH_CONDITIONS = "SIGNED_WITH_CONDITIONS"
    REFUSED = "REFUSED"


class EquipmentStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    QUARANTINED = "QUARANTINED"
    RETIRED = "RETIRED"


class InspectionOutcome(str, Enum):
    PASSED = "PASSED"
    CONDITIONAL = "CONDITIONAL"
    FAILED = "FAILED"


class PermitStatus(str, Enum):
    APPLIED = "APPLIED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class AdjustmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    AGREED = "AGREED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class NegotiationSide(str, Enum):
    PERFORMER = "PERFORMER"
    COORDINATOR = "COORDINATOR"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    CLOSED = "CLOSED"


class ExecutionStatus(str, Enum):
    ATTEMPTED = "ATTEMPTED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class ReviewStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ReviewOutcome(str, Enum):
    ACCEPTED_AS_SHOT = "ACCEPTED_AS_SHOT"
    RESHOOT_REQUIRED = "RESHOOT_REQUIRED"
    SAFETY_DEFICIENCY = "SAFETY_DEFICIENCY"


class HazardClass(str, Enum):
    FIRE = "FIRE"
    HEIGHT = "HEIGHT"
    VEHICLE = "VEHICLE"
    WATER = "WATER"
    PYRO = "PYRO"
    AERIAL = "AERIAL"
    FIGHT = "FIGHT"


class RiskCategory(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class UnionStatus(str, Enum):
    SAG_AFTRA = "SAG_AFTRA"
    NON_UNION = "NON_UNION"


class CertLevel(str, Enum):
    BASIC = "BASIC"
    ADVANCED = "ADVANCED"
    MASTER = "MASTER"


class Department(str, Enum):
    CAMERA = "CAMERA"
    ELECTRIC = "ELECTRIC"
    GRIP = "GRIP"
    STUNTS = "STUNTS"
    MEDIC = "MEDIC"
    FIRE_SAFETY = "FIRE_SAFETY"


class EquipmentType(str, Enum):
    RIGGING = "RIGGING"
    PYRO_DEVICE = "PYRO_DEVICE"
    VEHICLE = "VEHICLE"
    HARNESS = "HARNESS"
    AIRBAG = "AIRBAG"
    CRANE = "CRANE"


class PermitType(str, Enum):
    PYROTECHNICS = "PYROTECHNICS"
    CRANE_OPERATION = "CRANE_OPERATION"
    AERIAL_WORK = "AERIAL_WORK"
    FIRE_EFFECTS = "FIRE_EFFECTS"
    WATER_WORK = "WATER_WORK"


class IncidentSeverity(str, Enum):
    NEAR_MISS = "NEAR_MISS"
    MINOR = "MINOR"
    SERIOUS = "SERIOUS"
    CRITICAL = "CRITICAL"


class AdjustmentType(str, Enum):
    HAZARD_BUMP = "HAZARD_BUMP"
    STUNT_DOUBLE = "STUNT_DOUBLE"


# --- Entity representations (PRD §2.4 common fields, §3 per-entity fields) ---

class Production(TypedDict, total=False):
    id: str
    name: str
    total_budget_cents: int
    posture: str
    insurance_status: str
    declared_exposure_cents: int
    endorsement_premium_cents: int
    committed_pay_cents: int
    stopped_at: Optional[str]
    stop_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StuntSequence(TypedDict, total=False):
    id: str
    production_id: str
    name: str
    hazard_class: str
    risk_category: str
    status: str
    coordinator_user_id: str
    scheduled_execution_start: str
    scheduled_execution_end: str
    required_equipment_ids: List[str]
    required_rehearsal_count: Optional[int]
    completed_rehearsal_count: int
    completed_rehearsal_minutes: int
    current_assessment_id: Optional[str]
    board_score: Optional[int]
    design_revision: int
    medic_standby_required: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class RiskAssessment(TypedDict, total=False):
    id: str
    production_id: str
    sequence_id: str
    assessor_user_id: str
    severity_rating: int
    likelihood_rating: int
    mitigation_notes: str
    screening_score: int
    status: str
    supersedes_assessment_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StuntPerformer(TypedDict, total=False):
    id: str
    production_id: str
    first_name: str
    last_name: str
    base_day_rate_cents: int
    union_status: str
    status: str
    completed_rehearsal_minutes: int
    created_at: str
    updated_at: str
    version: int


# Immutable record per PRD §2.4: id + created_at only (no updated_at, no version)
class Certification(TypedDict, total=False):
    id: str
    performer_id: str
    discipline: str
    level: str
    issued_at: str
    expires_at: str
    revoked: bool
    created_at: str


class Rehearsal(TypedDict, total=False):
    id: str
    production_id: str
    sequence_id: str
    performer_id: str
    facility: str
    scheduled_start: str
    scheduled_end: str
    duration_minutes: int
    status: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SafetyMeeting(TypedDict, total=False):
    id: str
    production_id: str
    sequence_id: str
    facility: str
    scheduled_start: str
    scheduled_end: str
    status: str
    design_revision: int
    chair_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DepartmentSignoff(TypedDict, total=False):
    id: str
    meeting_id: str
    department: str
    status: str
    signer_user_id: Optional[str]
    conditions: Optional[str]
    refusal_reason: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EquipmentItem(TypedDict, total=False):
    id: str
    production_id: str
    name: str
    equipment_type: str
    serial_number: str
    inspection_interval_hours: int
    status: str
    registered_by_user_id: str
    last_passed_inspection_at: Optional[str]
    inspection_current: bool
    created_at: str
    updated_at: str
    version: int


# Immutable record per PRD §2.4: id + created_at only (no updated_at, no version)
class Inspection(TypedDict, total=False):
    id: str
    equipment_id: str
    inspector_user_id: str
    outcome: str
    notes: str
    inspected_at: str
    created_at: str


class Permit(TypedDict, total=False):
    id: str
    production_id: str
    permit_type: str
    jurisdiction: str
    valid_from: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PayAdjustment(TypedDict, total=False):
    id: str
    production_id: str
    sequence_id: str
    performer_id: str
    adjustment_type: str
    base_amount_cents: int
    requested_pct: float
    current_pct: float
    proposer_by: str
    last_offer_by: str
    round_count: int
    status: str
    provisional_estimate_cents: int
    final_amount_cents: Optional[int]
    payable_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict, total=False):
    id: str
    production_id: str
    sequence_id: Optional[str]
    severity: str
    occurred_at: str
    description: str
    reporter_user_id: str
    status: str
    corrective_action: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StuntExecution(TypedDict, total=False):
    id: str
    production_id: str
    sequence_id: str
    take_number: int
    status: str
    executed_at: str
    abort_reason: Optional[str]
    safety_related: bool
    created_at: str
    updated_at: str
    version: int


class PostStuntReview(TypedDict, total=False):
    id: str
    production_id: str
    sequence_id: str
    reviewer_user_id: str
    status: str
    outcome: Optional[str]
    findings: Optional[str]
    created_at: str
    updated_at: str
    version: int
