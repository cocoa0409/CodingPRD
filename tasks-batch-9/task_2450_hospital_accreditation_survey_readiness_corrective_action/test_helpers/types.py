"""Domain types for the Hospital Accreditation Survey Readiness API.

Entity TypedDicts, state enums and the role enum, all named exactly as the PRD
names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    ACCREDITATION_DIRECTOR = "AccreditationDirector"
    STANDARD_OWNER = "StandardOwner"
    EVIDENCE_VALIDATOR = "EvidenceValidator"
    TRACER_SURVEYOR = "TracerSurveyor"
    SAFETY_OFFICER = "SafetyOfficer"
    UNIT_MANAGER = "UnitManager"
    EXTERNAL_SURVEYOR = "ExternalSurveyor"


ALL_ROLES = [r.value for r in UserRole]


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class ChapterReadinessFlag(str, Enum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"


class RiskTier(str, Enum):
    DIRECT_IMPACT = "DIRECT_IMPACT"
    INDIRECT_IMPACT = "INDIRECT_IMPACT"
    SITUATIONAL_DECISION_RULE = "SITUATIONAL_DECISION_RULE"


class ComplianceState(str, Enum):
    UNMAPPED = "UNMAPPED"
    MAPPED = "MAPPED"
    EVIDENCE_COMPLETE = "EVIDENCE_COMPLETE"
    DEFICIENT = "DEFICIENT"


class OwnerDesignation(str, Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"


class OwnerAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class DocType(str, Enum):
    POLICY = "POLICY"
    LOG = "LOG"
    TRAINING_RECORD = "TRAINING_RECORD"
    INSPECTION_REPORT = "INSPECTION_REPORT"
    CONTRACT = "CONTRACT"


class ValidationState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class EvidenceAction(str, Enum):
    SUBMIT = "SUBMIT"
    VALIDATE = "VALIDATE"
    REJECT = "REJECT"


class UnitType(str, Enum):
    MED_SURG = "MED_SURG"
    ICU = "ICU"
    ED = "ED"
    OR = "OR"
    BEHAVIORAL_HEALTH = "BEHAVIORAL_HEALTH"
    AMBULATORY = "AMBULATORY"


class UnitPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    LOCKED_FOR_SURVEY = "LOCKED_FOR_SURVEY"


class ReadinessBand(str, Enum):
    READY = "READY"
    CONDITIONAL = "CONDITIONAL"
    AT_RISK = "AT_RISK"
    NOT_READY = "NOT_READY"
    NOT_ASSESSED = "NOT_ASSESSED"


class ReadinessMode(str, Enum):
    ATTESTED = "ATTESTED"
    PROJECTED = "PROJECTED"


class TracerType(str, Enum):
    PATIENT = "PATIENT"
    SYSTEM = "SYSTEM"
    INDIVIDUAL = "INDIVIDUAL"


class TracerState(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class TracerAction(str, Enum):
    START = "START"
    COMPLETE = "COMPLETE"
    ABORT = "ABORT"


class AbortReason(str, Enum):
    UNIT_POSTURE_RESTRICTED = "UNIT_POSTURE_RESTRICTED"
    SURVEY_ACTIVE = "SURVEY_ACTIVE"


class ObservationResult(str, Enum):
    COMPLIANT = "COMPLIANT"
    PARTIAL = "PARTIAL"
    NON_COMPLIANT = "NON_COMPLIANT"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class RoundType(str, Enum):
    LIFE_SAFETY = "LIFE_SAFETY"
    ENVIRONMENT_OF_CARE = "ENVIRONMENT_OF_CARE"


class RoundingSessionState(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class Severity(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    IMMEDIATE_THREAT = "IMMEDIATE_THREAT"


class TicketState(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    REMEDIATED = "REMEDIATED"
    ESCALATED = "ESCALATED"
    VERIFIED = "VERIFIED"


class TicketAction(str, Enum):
    START_WORK = "START_WORK"
    MARK_REMEDIATED = "MARK_REMEDIATED"
    VERIFY = "VERIFY"
    FAIL_VERIFICATION = "FAIL_VERIFICATION"
    ESCALATE = "ESCALATE"


class WindowState(str, Enum):
    PROJECTED = "PROJECTED"
    ELIGIBLE = "ELIGIBLE"
    ACTIVE_SURVEY = "ACTIVE_SURVEY"
    CLOSED = "CLOSED"


class CommandCenterState(str, Enum):
    STANDBY = "STANDBY"
    ACTIVATED = "ACTIVATED"
    DEMOBILIZED = "DEMOBILIZED"


class WindowAction(str, Enum):
    ACTIVATE_COMMAND_CENTER = "ACTIVATE_COMMAND_CENTER"
    DEMOBILIZE_COMMAND_CENTER = "DEMOBILIZE_COMMAND_CENTER"
    OPEN_SURVEY = "OPEN_SURVEY"
    CLOSE_SURVEY = "CLOSE_SURVEY"


class FindingClassification(str, Enum):
    LIMITED = "LIMITED"
    PATTERN = "PATTERN"
    WIDESPREAD = "WIDESPREAD"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    IMMEDIATE_THREAT = "IMMEDIATE_THREAT"


class FindingState(str, Enum):
    DRAFT = "DRAFT"
    RESPONSE_PENDING = "RESPONSE_PENDING"
    CONDITION_LEVEL_ESCALATED = "CONDITION_LEVEL_ESCALATED"
    RESPONSE_SUBMITTED = "RESPONSE_SUBMITTED"
    CLARIFICATION_REQUESTED = "CLARIFICATION_REQUESTED"
    FOLLOW_UP_PENDING = "FOLLOW_UP_PENDING"
    ACCEPTED = "ACCEPTED"


class EscDecision(str, Enum):
    PENDING = "PENDING"
    CLARIFICATION_REQUESTED = "CLARIFICATION_REQUESTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class PprState(str, Enum):
    SUBMITTED = "SUBMITTED"
    RETURNED_FOR_REASSESSMENT = "RETURNED_FOR_REASSESSMENT"
    ATTESTED = "ATTESTED"


class PprRating(str, Enum):
    COMPLIANT = "COMPLIANT"
    PARTIAL = "PARTIAL"
    NON_COMPLIANT = "NON_COMPLIANT"


# ---------------------------------------------------------------------------
# Entities carrying id + created_at + updated_at + version (PRD §2.5)
# ---------------------------------------------------------------------------

class Chapter(TypedDict):
    id: str
    code: str
    name: str
    weight_pct: float
    evidence_min_count: int
    standard_count: int
    mapped_standard_count: int
    evidence_complete_standard_count: int
    deficient_standard_count: int
    ppr_escalation_count: int
    readiness_flag: str
    created_at: str
    updated_at: str
    version: int


class Standard(TypedDict):
    id: str
    chapter_id: str
    standard_code: str
    title: str
    risk_tier: str
    compliance_state: str
    active_owner_count: int
    validated_evidence_count: int
    last_noncompliant_observed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OwnerAssignment(TypedDict):
    id: str
    standard_id: str
    owner_user_id: str
    designation: str
    status: str
    revoked_at: Optional[str]
    reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EvidenceItem(TypedDict):
    id: str
    standard_id: str
    title: str
    doc_type: str
    effective_date: str
    expires_at: Optional[str]
    validation_state: str
    submitted_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    review_note: Optional[str]
    rejection_count: int
    created_at: str
    updated_at: str
    version: int


class HospitalUnit(TypedDict):
    id: str
    name: str
    unit_type: str
    bed_count: int
    posture: str
    open_deficiency_penalty_points: int
    scheduled_tracer_count: int
    readiness_score: float
    readiness_band: str
    created_at: str
    updated_at: str
    version: int


class MockTracer(TypedDict):
    id: str
    unit_id: str
    chapter_id: str
    tracer_type: str
    window_start: str
    window_end: str
    state: str
    started_at: Optional[str]
    completed_at: Optional[str]
    abort_reason: Optional[str]
    scored_weight: float
    earned_weight: float
    tracer_score: float
    contributes_to_readiness: bool
    created_at: str
    updated_at: str
    version: int


class RoundingSession(TypedDict):
    id: str
    unit_id: str
    round_type: str
    window_start: str
    window_end: str
    state: str
    deficiency_count: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeficiencyTicket(TypedDict):
    id: str
    rounding_session_id: str
    standard_id: str
    description: str
    severity: str
    state: str
    penalty_points: int
    accelerated: bool
    due_at: str
    verified_by_user_id: Optional[str]
    failed_verification_count: int
    created_at: str
    updated_at: str
    version: int


class SurveyWindow(TypedDict):
    id: str
    cycle_label: str
    prior_survey_end_date: str
    predicted_open_date: str
    predicted_close_date: str
    command_center_activation_allowed_from: str
    window_state: str
    command_center_state: str
    survey_opened_at: Optional[str]
    survey_closed_at: Optional[str]
    condition_level_finding_count: int
    follow_up_required: bool
    follow_up_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SurveyFinding(TypedDict):
    id: str
    survey_window_id: str
    standard_id: str
    unit_id: str
    sampled_count: int
    observed_noncompliance_count: int
    patient_harm_observed: bool
    noncompliance_rate: float
    classification: str
    risk_level: str
    condition_level: bool
    response_deadline_days: int
    state: str
    initial_response_due_at: Optional[str]
    response_due_at: Optional[str]
    clarification_round_count: int
    submission_count: int
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PprSelfAssessment(TypedDict):
    id: str
    chapter_id: str
    period_label: str
    self_ratings: List[dict]
    self_score: float
    verified_score: float
    gap: float
    flagged_overstatement: bool
    state: str
    requires_reassessment: bool
    attested_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only records: ONLY id + created_at (PRD §2.5)
# ---------------------------------------------------------------------------

class TracerObservation(TypedDict):
    id: str
    mock_tracer_id: str
    standard_id: str
    result: str
    weight: float
    note: Optional[str]
    recorded_by_user_id: str
    created_at: str


class EscSubmission(TypedDict):
    id: str
    survey_finding_id: str
    submission_round: int
    corrective_action_summary: str
    measure_of_success: str
    leadership_signoff: bool
    submitted_by_user_id: str
    decision: str
    decision_note: Optional[str]
    created_at: str


# ---------------------------------------------------------------------------
# Computed reads (not persisted entities)
# ---------------------------------------------------------------------------

class ChapterBreakdownEntry(TypedDict):
    chapter_id: str
    weight_pct: float
    rate: float
    contribution: float


class UnitReadiness(TypedDict):
    unit_id: str
    mode: str
    base_score: float
    penalty_points_applied: int
    participating_weight_pct: float
    readiness_score: float
    readiness_band: str
    chapter_breakdown: List[ChapterBreakdownEntry]


class ClockResult(TypedDict):
    current_utc: str
    expired_evidence_count: int
    eligible_window_count: int
