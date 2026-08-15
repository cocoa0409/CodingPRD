"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class SecurityClearanceTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class LedgerDirection(str, Enum):
    DISTRIBUTE = "DISTRIBUTE"
    DESTROY = "DESTROY"


class InstrumentType(str, Enum):
    COGNITIVE_ABILITY = "COGNITIVE_ABILITY"
    PERSONALITY = "PERSONALITY"
    SKILLS_SIMULATION = "SKILLS_SIMULATION"
    JOB_KNOWLEDGE = "JOB_KNOWLEDGE"


class ValidationStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATION_REVIEW = "VALIDATION_REVIEW"
    VALIDATED = "VALIDATED"
    EXPIRED = "EXPIRED"
    REVALIDATION = "REVALIDATION"
    RETIRED = "RETIRED"


class EvidenceType(str, Enum):
    CRITERION = "CRITERION"
    CONTENT = "CONTENT"
    CONSTRUCT = "CONSTRUCT"


class GuideStatus(str, Enum):
    DRAFT = "DRAFT"
    PILOT = "PILOT"
    APPROVED = "APPROVED"
    RETIRED = "RETIRED"


class ScoringMode(str, Enum):
    RAW = "RAW"
    LENIENCY_ADJUSTED = "LENIENCY_ADJUSTED"


class RequisitionStatus(str, Enum):
    OPEN = "OPEN"
    FILLED = "FILLED"
    CLOSED = "CLOSED"


class CyclePosture(str, Enum):
    SETUP = "SETUP"
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    SCORING = "SCORING"
    DECIDED = "DECIDED"
    CLOSED = "CLOSED"


class FrozenReason(str, Enum):
    MANUAL = "MANUAL"
    ADVERSE_IMPACT = "ADVERSE_IMPACT"
    VENDOR_HOLD = "VENDOR_HOLD"


class CandidateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class GroupCode(str, Enum):
    GROUP_A = "GROUP_A"
    GROUP_B = "GROUP_B"
    GROUP_C = "GROUP_C"
    GROUP_D = "GROUP_D"
    UNDISCLOSED = "UNDISCLOSED"


class AdminStatus(str, Enum):
    INVITED = "INVITED"
    SCHEDULED = "SCHEDULED"
    ACCOMMODATION_HOLD = "ACCOMMODATION_HOLD"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"
    PURGED = "PURGED"


class FeedbackStatus(str, Enum):
    NOT_SENT = "NOT_SENT"
    SENT = "SENT"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AccommodationRequestType(str, Enum):
    EXTENDED_TIME = "EXTENDED_TIME"
    ALTERNATE_FORMAT = "ALTERNATE_FORMAT"
    SCREEN_READER = "SCREEN_READER"
    OTHER = "OTHER"


class AccommodationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class CalibrationStatus(str, Enum):
    TRAINED = "TRAINED"
    CALIBRATED = "CALIBRATED"
    LAPSED = "LAPSED"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    SCORED = "SCORED"
    CANCELLED = "CANCELLED"


class CancellationReason(str, Enum):
    MANUAL = "MANUAL"
    VENDOR_HOLD = "VENDOR_HOLD"
    CANDIDATE_WITHDRAWN = "CANDIDATE_WITHDRAWN"
    CYCLE_CLOSED = "CYCLE_CLOSED"


class ScorecardStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VOIDED = "VOIDED"


class OverallRecommendation(str, Enum):
    STRONG_YES = "STRONG_YES"
    YES = "YES"
    NO = "NO"
    STRONG_NO = "STRONG_NO"


class DecisionValue(str, Enum):
    ADVANCE = "ADVANCE"
    HOLD = "HOLD"
    REJECT = "REJECT"


class DecisionStatus(str, Enum):
    FINALIZED = "FINALIZED"


class SnapshotType(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class ExcludedReason(str, Enum):
    INSUFFICIENT_N = "INSUFFICIENT_N"
    NO_SELECTIONS = "NO_SELECTIONS"
    UNDISCLOSED = "UNDISCLOSED"


class PurgeEventType(str, Enum):
    ASSESSMENT_PURGED = "ASSESSMENT_PURGED"


class UserRole(str, Enum):
    TALENT_ASSESSMENT_ADMIN = "TalentAssessmentAdmin"
    HIRING_MANAGER = "HiringManager"
    INTERVIEWER = "Interviewer"
    CANDIDATE = "Candidate"
    DECISION_OFFICER = "DecisionOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    VENDOR_REPRESENTATIVE = "VendorRepresentative"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class AssessmentVendor(TypedDict, total=False):
    id: str
    name: str
    status: str
    security_clearance_tier: str
    content_copies_outstanding: int
    terminated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContentLedgerEvent(TypedDict, total=False):
    # Append-only audit record: carries only id + created_at from common fields.
    id: str
    created_at: str
    vendor_id: str
    direction: str
    copies: int
    note: str
    recorded_by_user_id: str


class AssessmentInstrument(TypedDict, total=False):
    id: str
    vendor_id: str
    code: str
    instrument_type: str
    title: str
    max_score: int
    pass_floor: int
    validation_status: str
    validity_expires_at: Optional[str]
    vendor_suspended: bool
    adverse_impact_monitor_enabled: bool
    created_at: str
    updated_at: str
    version: int


class ValidationEvidence(TypedDict, total=False):
    id: str
    instrument_id: str
    evidence_type: str
    title: str
    issuer: str
    effective_from: str
    effective_until: str
    filed_at: str
    created_at: str
    updated_at: str
    version: int


class RubricItem(TypedDict):
    competency_code: str
    weight: float
    scale_max: int


class InterviewGuide(TypedDict, total=False):
    id: str
    supersedes_guide_id: Optional[str]
    title: str
    status: str
    rubric_items: List[RubricItem]
    scoring_mode: str
    version_label: int
    superseded_by_guide_id: Optional[str]
    created_by_user_id: str
    pinned_cycle_count: int
    created_at: str
    updated_at: str
    version: int


class Requisition(TypedDict, total=False):
    id: str
    hiring_manager_id: str
    title: str
    department: str
    openings_count: int
    filled_count: int
    status: str
    retention_days: int
    created_at: str
    updated_at: str
    version: int


class AssessmentCycle(TypedDict, total=False):
    id: str
    requisition_id: str
    instrument_id: str
    guide_id: str
    label: str
    posture: str
    frozen_from_posture: Optional[str]
    frozen_reason: Optional[str]
    administration_window_start: str
    administration_window_end: str
    max_sessions_per_day: int
    active_candidate_count: int
    decisions_finalized_count: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Candidate(TypedDict, total=False):
    id: str
    external_ref: str
    full_name: str
    email: str
    group_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CandidateAssessment(TypedDict, total=False):
    id: str
    cycle_id: str
    candidate_id: str
    admin_status: str
    feedback_status: str
    scheduled_for: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    raw_score: Optional[float]
    composite_score: Optional[float]
    accommodation_extension_days: int
    retention_expires_at: Optional[str]
    purged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccommodationRequest(TypedDict, total=False):
    id: str
    candidate_assessment_id: str
    request_type: str
    justification: str
    requested_extension_days: int
    status: str
    approved_extension_days: Optional[int]
    decision_note: Optional[str]
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Interviewer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    department: str
    committed_minutes_total: int
    created_at: str
    updated_at: str
    version: int


class CalibrationRecord(TypedDict, total=False):
    id: str
    interviewer_id: str
    guide_id: str
    status: str
    practice_score: Optional[float]
    trained_at: str
    certified_at: Optional[str]
    calibration_index: Optional[float]
    created_at: str
    updated_at: str
    version: int


class InterviewSession(TypedDict, total=False):
    id: str
    cycle_id: str
    candidate_id: str
    interviewer_id: str
    guide_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    completed_at: Optional[str]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RatingItem(TypedDict):
    competency_code: str
    rating: int


class Scorecard(TypedDict, total=False):
    id: str
    session_id: str
    interviewer_id: str
    candidate_id: str
    ratings: Optional[List[RatingItem]]
    overall_recommendation: str
    status: str
    weighted_total: Optional[float]
    submitted_at: Optional[str]
    voided_at: Optional[str]
    void_reason: Optional[str]
    redacted: bool
    created_at: str
    updated_at: str
    version: int


class HiringDecision(TypedDict, total=False):
    id: str
    cycle_id: str
    candidate_id: str
    decision: str
    rationale: str
    decided_by_user_id: str
    status: str
    composite_at_decision: float
    quorum_required_at_decision: int
    quorum_submitted_at_decision: int
    finalized_at: str
    created_at: str
    updated_at: str
    version: int


class GroupBreakdown(TypedDict, total=False):
    group_code: str
    applicants: int
    selected: int
    selection_rate: Optional[float]
    impact_ratio: Optional[float]
    excluded_reason: Optional[str]


class AdverseImpactSnapshot(TypedDict, total=False):
    id: str
    cycle_id: str
    snapshot_type: str
    group_breakdowns: List[GroupBreakdown]
    highest_rate_group_code: Optional[str]
    flagged: bool
    computed_at: str
    created_at: str
    updated_at: str
    version: int


class RetentionPurgeEvent(TypedDict, total=False):
    # Append-only audit record: carries only id + created_at from common fields.
    id: str
    created_at: str
    candidate_assessment_id: str
    event_type: str
    executed_by_user_id: str
    retention_expires_at_snapshot: str


class RetentionSweepResult(TypedDict, total=False):
    purged_count: int
    purged_assessment_ids: List[str]


class ClockSetResult(TypedDict, total=False):
    now: str
    instruments_expired: int
    calibrations_lapsed: int
