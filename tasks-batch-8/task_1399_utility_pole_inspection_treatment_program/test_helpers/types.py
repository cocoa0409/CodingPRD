"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_MANAGER = "ProgramManager"
    INSPECTOR = "Inspector"
    QA_REVIEWER = "QAReviewer"
    CONTRACTOR = "Contractor"
    ATTACHER_REP = "AttacherRep"


class CycleStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    RECONCILED = "RECONCILED"


class PoleStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    MONITOR = "MONITOR"
    PRIORITY_REJECT = "PRIORITY_REJECT"
    REPLACED = "REPLACED"


class TaskStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    REJECTED = "REJECTED"
    ACCEPTED = "ACCEPTED"
    WAIVED = "WAIVED"
    ESCALATED = "ESCALATED"


class TreatmentStatus(str, Enum):
    CREATED = "CREATED"
    SCHEDULED = "SCHEDULED"
    APPLIED = "APPLIED"
    VERIFIED = "VERIFIED"
    FAILED_QA = "FAILED_QA"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    HONORED = "HONORED"
    DENIED = "DENIED"


class CrewStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ReplacementStatus(str, Enum):
    QUEUED = "QUEUED"
    FUNDED = "FUNDED"
    DEFERRED = "DEFERRED"
    COMPLETED = "COMPLETED"


class AuditReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ADJUDICATED = "ADJUDICATED"


class ViolationStatus(str, Enum):
    NONE = "NONE"
    DETECTED = "DETECTED"
    NOTIFIED = "NOTIFIED"
    CURED = "CURED"
    ESCALATED = "ESCALATED"


class Species(str, Enum):
    SOUTHERN_PINE = "SOUTHERN_PINE"
    DOUGLAS_FIR = "DOUGLAS_FIR"
    WESTERN_RED_CEDAR = "WESTERN_RED_CEDAR"
    LARCH = "LARCH"


class PoleClass(str, Enum):
    H1 = "H1"
    C1 = "1"
    C2 = "2"
    C3 = "3"
    C4 = "4"
    C5 = "5"


class ProductCode(str, Enum):
    CCA_WRAP = "CCA_WRAP"
    PENTA_GEL = "PENTA_GEL"
    COPPER_NAPHTHENATE = "COPPER_NAPHTHENATE"


class ClaimReason(str, Enum):
    DECAY_RECURRENCE = "DECAY_RECURRENCE"
    PRODUCT_FAILURE = "PRODUCT_FAILURE"


class StrengthVariantPolicy(str, Enum):
    CONSERVATIVE = "CONSERVATIVE"
    STATISTICAL = "STATISTICAL"


class PhotoType(str, Enum):
    GROUNDLINE = "GROUNDLINE"
    DECAY_POCKET = "DECAY_POCKET"
    TAG = "TAG"
    ATTACHMENT = "ATTACHMENT"


class TaskQaDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class TreatmentQaDecision(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ClaimOutcome(str, Enum):
    HONOR = "HONOR"
    DENY = "DENY"


class PoleClassification(str, Enum):
    NONE = "NONE"
    SERVICEABLE = "SERVICEABLE"
    MONITOR = "MONITOR"
    REJECT_ROUTINE = "REJECT_ROUTINE"
    REJECT_PRIORITY = "REJECT_PRIORITY"


# --- Entity TypedDicts -------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version (PRD §2.4).

class ProgramBudget(TypedDict, total=False):
    id: str
    fiscal_year: int
    total_cents: int
    committed_cents: int
    spent_cents: int
    available_cents: int
    created_at: str
    updated_at: str
    version: int


class InspectionCycle(TypedDict, total=False):
    id: str
    year: int
    cycle_length_years: int
    sample_pct: float
    mandatory_zone_tags: List[str]
    strength_variant_policy: str
    status: str
    opened_at: Optional[str]
    reconciled_at: Optional[str]
    sample_pool_size: int
    tasks_total: int
    tasks_terminal: int
    pending_replacement_count: int
    created_at: str
    updated_at: str
    version: int


class Pole(TypedDict, total=False):
    id: str
    pole_number: str
    species: str
    original_class: str
    install_date: str
    gis_lat: float
    gis_lon: float
    gis_tag: str
    height_ft: float
    joint_use: bool
    attachment_count_declared: int
    status: str
    last_inspection_date: Optional[str]
    last_treatment_date: Optional[str]
    current_remaining_strength_pct: Optional[float]
    current_classification: str
    open_treatment_count: int
    created_at: str
    updated_at: str
    version: int


class InspectionTask(TypedDict, total=False):
    id: str
    cycle_id: str
    pole_id: str
    due_window_start: str
    due_window_end: str
    status: str
    rework_count: int
    shell_thickness_in: Optional[float]
    sound_wood_pct: Optional[float]
    decay_pocket_depth_in: Optional[float]
    moisture_pct: Optional[float]
    hazard_flag: bool
    photos: List[Dict[str, Any]]
    submitted_by_user_id: Optional[str]
    qa_reviewed_by_user_id: Optional[str]
    rs_conservative_pct: Optional[float]
    rs_statistical_pct: Optional[float]
    effective_rs_pct: Optional[float]
    classification: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TreatmentWorkOrder(TypedDict, total=False):
    id: str
    pole_id: str
    product_code: str
    crew_id: Optional[str]
    work_start_date: Optional[str]
    work_end_date: Optional[str]
    cost_cents: int
    is_warranty_retreat: bool
    source_claim_id: Optional[str]
    status: str
    applied_at: Optional[str]
    applied_by_crew_id: Optional[str]
    warranty_years: Optional[int]
    warranty_end_date: Optional[str]
    qa_fail_events: int
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    treatment_order_id: str
    claim_reason: str
    status: str
    filed_at: str
    filed_by_user_id: str
    adjudication_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContractorCrew(TypedDict, total=False):
    id: str
    crew_code: str
    region: str
    status: str
    qa_pass_count: int
    qa_fail_count: int
    quality_score_lifetime: float
    quality_score_rolling: float
    qa_event_log: List[Dict[str, Any]]
    current_cycle_billing_cents: int
    created_at: str
    updated_at: str
    version: int


class ReplacementWorkOrder(TypedDict, total=False):
    id: str
    pole_id: str
    cycle_id: Optional[str]
    budget_id: Optional[str]
    estimated_cost_cents: int
    actual_cost_cents: Optional[int]
    deferral_count: int
    escalated_cost_cents: int
    priority_score: int
    status: str
    funded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AttachmentAudit(TypedDict, total=False):
    id: str
    pole_id: str
    inspection_task_id: str
    audit_status: str
    violation_status: str
    found_attachment_count: int
    unauthorized_count: int
    cure_deadline: Optional[str]
    adjudicated_at: Optional[str]
    cured_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only record (PRD §2.4): carries id and created_at ONLY — no
# updated_at, no version.
class BacklogSnapshot(TypedDict, total=False):
    id: str
    cycle_id: str
    budget_id: str
    snapshot_seq: int
    queued_count: int
    queued_escalated_cost_cents: int
    funded_count: int
    budget_available_cents: int
    budget_committed_cents: int
    crew_billings: List[Dict[str, Any]]
    created_at: str
