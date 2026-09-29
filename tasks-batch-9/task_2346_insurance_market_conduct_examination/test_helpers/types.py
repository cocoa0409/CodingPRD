"""Domain types for the market conduct examination API.

Status enums, role enum and entity TypedDicts, all named exactly as the PRD
names them.  Two record types are append-only workpapers and therefore carry
only ``id`` and ``created_at``: ``FieldworkActivity`` and ``CompanyResponse``.
"""

from enum import Enum
from typing import List, Optional, TypedDict

# ─── Roles ────────────────────────────────────────────────────────────────


class UserRole(str, Enum):
    MARKET_ANALYST = "MarketAnalyst"
    EXAMINER_IN_CHARGE = "ExaminerInCharge"
    SUPERVISING_EXAMINER = "SupervisingExaminer"
    MULTISTATE_COORDINATOR = "MultistateCoordinator"
    INSURER_RESPONDENT = "InsurerRespondent"


# ─── Enumerated field domains ─────────────────────────────────────────────


class LicenseStatus(str, Enum):
    LICENSED = "LICENSED"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class RiskTier(str, Enum):
    UNRATED = "UNRATED"
    LOW = "LOW"
    MODERATE = "MODERATE"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"


class MarketAnalysisCycleStatus(str, Enum):
    DRAFT = "DRAFT"
    SCORED = "SCORED"
    TARGETS_SELECTED = "TARGETS_SELECTED"
    CLOSED = "CLOSED"


class ExamMode(str, Enum):
    ON_SITE = "ON_SITE"
    DESK = "DESK"


class SelectionReason(str, Enum):
    SELECTED = "SELECTED"
    BELOW_THRESHOLD = "BELOW_THRESHOLD"
    CAPACITY_EXHAUSTED = "CAPACITY_EXHAUSTED"
    WINDOW_CONFLICT_DEFERRED = "WINDOW_CONFLICT_DEFERRED"
    LICENSE_INELIGIBLE = "LICENSE_INELIGIBLE"


class ExamType(str, Enum):
    MARKET_CONDUCT_EXAM = "MARKET_CONDUCT_EXAM"
    TARGETED_EXAM = "TARGETED_EXAM"


class ExaminationStatus(str, Enum):
    SCOPING = "SCOPING"
    DATA_CALL = "DATA_CALL"
    FIELDWORK = "FIELDWORK"
    CRITICISM = "CRITICISM"
    NEGOTIATION = "NEGOTIATION"
    ORDER_PENDING = "ORDER_PENDING"
    PUBLISHED = "PUBLISHED"
    ABORTED = "ABORTED"


class ScopeAreaName(str, Enum):
    UNDERWRITING = "UNDERWRITING"
    RATING = "RATING"
    CLAIMS = "CLAIMS"
    PRODUCER = "PRODUCER"


class ExamScopeAreaStatus(str, Enum):
    PLANNED = "PLANNED"
    FIELDWORK = "FIELDWORK"
    TESTED = "TESTED"
    CLOSED = "CLOSED"


class DataCallStatus(str, Enum):
    ISSUED = "ISSUED"
    OVERDUE = "OVERDUE"
    RESPONDED = "RESPONDED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class SamplingMethod(str, Enum):
    SYSTEMATIC_INTERVAL = "SYSTEMATIC_INTERVAL"


class ReviewStatus(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    COMPLIANT = "COMPLIANT"
    ERROR = "ERROR"


class ErrorSeverity(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    MATERIAL = "MATERIAL"


class ActivityType(str, Enum):
    INTERVIEW = "INTERVIEW"
    SYSTEM_WALKTHROUGH = "SYSTEM_WALKTHROUGH"


class CriticismSeverity(str, Enum):
    MINOR = "MINOR"
    MATERIAL = "MATERIAL"
    EGREGIOUS = "EGREGIOUS"


class CriticismStatus(str, Enum):
    ISSUED = "ISSUED"
    RESPONDED = "RESPONDED"
    SUSTAINED = "SUSTAINED"
    WITHDRAWN = "WITHDRAWN"


class RestitutionMethod(str, Enum):
    SAMPLE_ACTUAL = "SAMPLE_ACTUAL"
    POPULATION_EXTRAPOLATED = "POPULATION_EXTRAPOLATED"


class ResponsePosition(str, Enum):
    CONCUR = "CONCUR"
    PARTIAL_CONCUR = "PARTIAL_CONCUR"
    DISPUTE = "DISPUTE"


class CorrectiveActionPlanStatus(str, Enum):
    PROPOSED = "PROPOSED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class PlanDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_REVISION = "REQUEST_REVISION"


class ConsentOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    VOIDED = "VOIDED"


class PenaltyVariant(str, Enum):
    PER_VIOLATION = "PER_VIOLATION"
    TIERED_AGGREGATE = "TIERED_AGGREGATE"


class CollaborationStatus(str, Enum):
    LEAD_ASSIGNED = "LEAD_ASSIGNED"
    ACTIVE = "ACTIVE"
    SETTLED = "SETTLED"
    DISSOLVED = "DISSOLVED"


class CriticismDisposition(str, Enum):
    SUSTAINED = "SUSTAINED"
    WITHDRAWN = "WITHDRAWN"


class DataCallDisposition(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


# ─── Entities carrying id + created_at + updated_at + version ─────────────


class Insurer(TypedDict):
    id: str
    name: str
    naic_code: str
    license_status: str
    annual_premium_written_cents: int
    policy_count_in_force: int
    confirmed_complaints_12mo: int
    financial_stress_score: int
    consumer_trend_score: int
    complaint_ratio_per_1k: float
    risk_tier: str
    open_exam_count: int
    pending_enforcement_exam_count: int
    lifetime_restitution_ordered_cents: int
    created_at: str
    updated_at: str
    version: int


class MarketAnalysisCycle(TypedDict):
    id: str
    cycle_label: str
    reference_period_start: str
    reference_period_end: str
    target_slot_capacity: int
    default_fieldwork_start: str
    default_fieldwork_end: str
    default_exam_mode: str
    status: str
    scored_at: Optional[str]
    scored_insurer_count: int
    selected_target_count: int
    slots_committed: int
    slots_available: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AnalysisScore(TypedDict):
    id: str
    cycle_id: str
    insurer_id: str
    complaint_ratio_at_scoring: float
    complaint_component: float
    financial_component: float
    trend_component: float
    volume_multiplier: float
    composite_score: float
    rank_position: int
    selected: bool
    selection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Examination(TypedDict):
    id: str
    insurer_id: str
    cycle_id: Optional[str]
    predecessor_exam_id: Optional[str]
    exam_type: str
    mode: str
    lead_state_code: str
    fieldwork_start_date: str
    fieldwork_end_date: str
    status: str
    scope_locked: bool
    scope_area_count: int
    rejected_data_call_count: int
    open_criticism_count: int
    sustained_criticism_count: int
    pending_restitution_cents: int
    aggregate_restitution_cents: int
    penalty_units_total: int
    criticism_phase_opened_at: Optional[str]
    report_published_at: Optional[str]
    public_summary: Optional[str]
    followup_required: bool
    followup_due_date: Optional[str]
    abort_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExamScopeArea(TypedDict):
    id: str
    exam_id: str
    area: str
    population_size: int
    sample_size: int
    error_tolerance_pct: float
    status: str
    reviewed_sample_count: int
    error_count: int
    material_error_count: int
    error_rate_pct: float
    material_error_rate_pct: float
    tolerance_breached: bool
    escalation_required: bool
    tested_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DataCall(TypedDict):
    id: str
    scope_area_id: str
    records_requested: int
    issued_date: str
    response_due_date: str
    sampling_method: str
    status: str
    records_received: int
    submitted_by_contact: Optional[str]
    responded_at: Optional[str]
    is_late: bool
    days_late: int
    completeness_pct: float
    effective_completeness_pct: float
    disposition_reason: Optional[str]
    sample_draw_interval: int
    samples_drawn_count: int
    created_at: str
    updated_at: str
    version: int


class FileSample(TypedDict):
    id: str
    data_call_id: str
    file_reference: str
    population_index: int
    review_status: str
    error_severity: str
    underpaid_amount_cents: int
    days_to_pay: int
    reviewed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Criticism(TypedDict):
    id: str
    exam_id: str
    scope_area_id: str
    statute_citation: str
    severity: str
    affected_file_count: int
    status: str
    response_round: int
    rebuttal_count: int
    restitution_method: str
    restitution_exposure_cents: int
    penalty_units: int
    issued_by_user_id: str
    finalized_by_user_id: Optional[str]
    finalized_at: Optional[str]
    disposition_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CorrectiveActionPlan(TypedDict):
    id: str
    exam_id: str
    status: str
    revision_round: int
    milestone_count: int
    completion_due_date: str
    narrative: str
    reviewed_by_user_id: Optional[str]
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConsentOrder(TypedDict):
    id: str
    exam_id: str
    order_number: str
    status: str
    penalty_variant: str
    restitution_cents: int
    penalty_gross_cents: int
    cooperation_credit_pct: float
    penalty_net_cents: int
    order_total_cents: int
    drafted_by_user_id: str
    signed_by: Optional[str]
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ParticipatingState(TypedDict):
    state_code: str
    policy_count_in_state: int
    has_examiner_resources: bool
    allocated_cents: int


class MultistateCollaboration(TypedDict):
    id: str
    exam_id: str
    call_reference: Optional[str]
    participating_states: List[ParticipatingState]
    lead_state_code: str
    status: str
    participant_count: int
    allocated_total_cents: int
    allocation_completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── Append-only records: id + created_at only ────────────────────────────


class FieldworkActivity(TypedDict):
    """Append-only workpaper: no ``updated_at`` and no ``version``."""

    id: str
    exam_id: str
    activity_type: str
    area: str
    participant_name: str
    participant_title: str
    summary: str
    evidence_ref: Optional[str]
    conducted_at: str
    documented: bool
    created_at: str


class CompanyResponse(TypedDict):
    """Append-only workpaper: no ``updated_at`` and no ``version``."""

    id: str
    criticism_id: str
    round_number: int
    position: str
    narrative: str
    remediation_offer_cents: int
    submitted_at: str
    created_at: str
