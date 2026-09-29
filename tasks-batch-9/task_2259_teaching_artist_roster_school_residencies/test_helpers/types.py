"""Domain types: entity TypedDicts, status enums, role enum.

Primary resources carry id/created_at/updated_at/version (PRD §2.4).
The four append-only observation types — calendar blackout windows,
portfolio reviews, background screenings and evaluation records — carry
only id and created_at, so their TypedDicts omit updated_at and version.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PROGRAM_DIRECTOR = "ProgramDirector"
    ROSTER_COORDINATOR = "RosterCoordinator"
    CURRICULUM_SPECIALIST = "CurriculumSpecialist"
    TEACHING_ARTIST = "TeachingArtist"
    SCHOOL_LIAISON = "SchoolLiaison"
    FISCAL_OFFICER = "FiscalOfficer"


ALL_ROLES = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class PartnershipHealth(str, Enum):
    HEALTHY = "HEALTHY"
    WATCH = "WATCH"
    INTAKE_SUSPENDED = "INTAKE_SUSPENDED"


class VettingStatus(str, Enum):
    APPLIED = "APPLIED"
    PORTFOLIO_REVIEW = "PORTFOLIO_REVIEW"
    DEMO_SCHEDULED = "DEMO_SCHEDULED"
    DEMO_FAILED = "DEMO_FAILED"
    DEMO_PASSED = "DEMO_PASSED"
    SCREENING_PENDING = "SCREENING_PENDING"
    CLEARED = "CLEARED"
    DECLINED = "DECLINED"
    SCREEN_FAILED = "SCREEN_FAILED"


class RosterStatus(str, Enum):
    NOT_LISTED = "NOT_LISTED"
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class ClearanceStatus(str, Enum):
    NONE = "NONE"
    CLEARED = "CLEARED"
    EXPIRED = "EXPIRED"


class RosterTier(str, Enum):
    APPRENTICE = "APPRENTICE"
    TEACHING_ARTIST = "TEACHING_ARTIST"
    MASTER = "MASTER"


class Discipline(str, Enum):
    VISUAL_ARTS = "VISUAL_ARTS"
    DANCE = "DANCE"
    MUSIC = "MUSIC"
    THEATER = "THEATER"
    MEDIA_ARTS = "MEDIA_ARTS"
    LITERARY_ARTS = "LITERARY_ARTS"


class GradeBand(str, Enum):
    K_2 = "K_2"
    G3_5 = "G3_5"
    G6_8 = "G6_8"
    G9_12 = "G9_12"


class Strand(str, Enum):
    CREATING = "CREATING"
    PERFORMING = "PERFORMING"
    RESPONDING = "RESPONDING"
    CONNECTING = "CONNECTING"


class BlackoutType(str, Enum):
    HOLIDAY = "HOLIDAY"
    TESTING_WINDOW = "TESTING_WINDOW"
    PROFESSIONAL_DEVELOPMENT = "PROFESSIONAL_DEVELOPMENT"
    CLOSURE = "CLOSURE"


class ScreeningType(str, Enum):
    STATE_CRIMINAL = "STATE_CRIMINAL"
    FBI_FINGERPRINT = "FBI_FINGERPRINT"
    CHILD_ABUSE_REGISTRY = "CHILD_ABUSE_REGISTRY"


class ScreeningOutcome(str, Enum):
    CLEARED = "CLEARED"
    FAILED = "FAILED"


class PortfolioRecommendation(str, Enum):
    ADVANCE = "ADVANCE"
    DECLINE = "DECLINE"


class ResidencyStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class StaffingStatus(str, Enum):
    LEAD_VACANT = "LEAD_VACANT"
    AT_RISK = "AT_RISK"
    STAFFED = "STAFFED"


class CollaborationExpectation(str, Enum):
    CO_TEACH = "CO_TEACH"
    OBSERVE = "OBSERVE"
    PLANNING_ONLY = "PLANNING_ONLY"


class LessonPlanStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    ALIGNED = "ALIGNED"
    ARCHIVED = "ARCHIVED"


class LessonPlanDecision(str, Enum):
    ALIGN = "ALIGN"
    REQUEST_CHANGES = "REQUEST_CHANGES"


class SessionStatus(str, Enum):
    PLANNED = "PLANNED"
    CONFIRMED = "CONFIRMED"
    VACATED = "VACATED"
    DELIVERED = "DELIVERED"
    CANCELLED_SCHOOL = "CANCELLED_SCHOOL"
    CANCELLED_ARTIST = "CANCELLED_ARTIST"


class SessionType(str, Enum):
    REGULAR = "REGULAR"
    MAKEUP = "MAKEUP"


class CancelReason(str, Enum):
    SCHOOL_CLOSURE = "SCHOOL_CLOSURE"
    TESTING_CONFLICT = "TESTING_CONFLICT"
    LOW_ENROLLMENT = "LOW_ENROLLMENT"
    ARTIST_ILLNESS = "ARTIST_ILLNESS"
    ARTIST_NO_SHOW = "ARTIST_NO_SHOW"
    RESIDENCY_DESCOPED = "RESIDENCY_DESCOPED"


class VoucherStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class ReviewTrackStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ReviewTrack(str, Enum):
    FISCAL = "FISCAL"
    PROGRAM = "PROGRAM"


class ReviewDecision(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class EvaluationType(str, Enum):
    OBSERVATION_RUBRIC = "OBSERVATION_RUBRIC"
    TEACHER_SURVEY = "TEACHER_SURVEY"
    STUDENT_WORK_SAMPLE = "STUDENT_WORK_SAMPLE"


class FunderReportStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPILED = "COMPILED"
    CERTIFIED = "CERTIFIED"


class HeadcountBasis(str, Enum):
    UNDUPLICATED = "UNDUPLICATED"
    ENCOUNTERS = "ENCOUNTERS"


class InvalidatedReason(str, Enum):
    SCOPE_DELIVERY_CHANGED = "SCOPE_DELIVERY_CHANGED"


# --------------------------------------------------------------------------
# Primary resources — id + created_at + updated_at + version
# --------------------------------------------------------------------------
class SchoolPartner(TypedDict):
    id: str
    name: str
    district_name: str
    grade_span: str
    concurrent_session_capacity: int
    total_enrollment: int
    frl_pct: float
    ell_pct: float
    iep_pct: float
    partnership_health: str
    open_residency_count: int
    created_at: str
    updated_at: str
    version: int


class TeachingArtist(TypedDict):
    id: str
    full_name: str
    email: str
    primary_discipline: str
    secondary_disciplines: List[str]
    grade_bands: List[str]
    languages: List[str]
    vetting_status: str
    roster_status: str
    roster_tier_assigned: str
    roster_tier_effective: str
    portfolio_review_count: int
    portfolio_mean_composite: Optional[float]
    demo_attempt_count: int
    demo_rubric_score: Optional[float]
    demo_evaluator_user_id: Optional[str]
    clearance_status: str
    clearance_expires_on: Optional[str]
    lifetime_delivered_count: int
    no_show_count: int
    reliability_bps_rolling: int
    reliability_bps_program_year: int
    created_at: str
    updated_at: str
    version: int


class ArtsStandard(TypedDict):
    id: str
    code: str
    discipline: str
    grade_band: str
    strand: str
    description: str
    created_at: str
    updated_at: str
    version: int


class Residency(TypedDict):
    id: str
    school_partner_id: str
    title: str
    discipline: str
    grade_band: str
    instruction_language: str
    lead_artist_id: Optional[str]
    contracted_session_count: int
    session_length_minutes: int
    budget_cents: int
    materials_stipend_cents: int
    collaboration_expectation: str
    co_planning_hours_required: int
    required_strands: List[str]
    term_start_date: str
    term_end_date: str
    enrolled_student_count: int
    status: str
    staffing_status: str
    sessions_unscheduled_count: int
    sessions_open_count: int
    sessions_delivered_count: int
    sessions_forfeited_count: int
    makeup_credits_outstanding: int
    vacated_session_count: int
    encumbered_cents: int
    disbursed_cents: int
    available_cents: int
    earned_to_date_cents: int
    projected_cost_cents: int
    evaluation_index: Optional[float]
    created_at: str
    updated_at: str
    version: int


class LessonPlan(TypedDict):
    id: str
    residency_id: str
    title: str
    session_sequence_no: int
    standard_codes: List[str]
    covered_strands: List[str]
    materials_list: Optional[str]
    adaptation_summary: Optional[str]
    author_artist_id: Optional[str]
    status: str
    revision_round: int
    reviewer_note: Optional[str]
    reviewer_user_id: Optional[str]
    aligned_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict):
    id: str
    residency_id: str
    assigned_artist_id: Optional[str]
    vacated_artist_id: Optional[str]
    lesson_plan_id: Optional[str]
    session_date: str
    start_time: str
    end_time: str
    session_type: str
    makeup_for_session_id: Optional[str]
    status: str
    is_substitute: bool
    classroom_teacher_name: Optional[str]
    co_planning_completed: bool
    makeup_eligible: bool
    makeup_consumed: bool
    cancel_reason: Optional[str]
    students_present_count: Optional[int]
    minutes_delivered: Optional[int]
    travel_miles: Optional[float]
    materials_spend_cents: Optional[int]
    fee_cents: int
    travel_reimbursement_cents: int
    materials_reimbursement_cents: int
    payable_cents: int
    encumbered_cents: int
    payment_voucher_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PaymentVoucher(TypedDict):
    id: str
    teaching_artist_id: str
    residency_id: str
    session_ids: List[str]
    period_start: str
    period_end: str
    status: str
    fiscal_review_status: str
    program_review_status: str
    fiscal_reviewed_by: Optional[str]
    program_reviewed_by: Optional[str]
    session_fee_subtotal_cents: int
    travel_reimbursement_cents: int
    materials_reimbursement_cents: int
    total_cents: int
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FunderReport(TypedDict):
    id: str
    funder_name: str
    grant_code: str
    period_start: str
    period_end: str
    scope_residency_ids: List[str]
    headcount_basis: str
    status: str
    sessions_delivered_total: int
    students_served: int
    frl_students_reached: int
    ell_students_reached: int
    iep_students_reached: int
    direct_cost_cents: int
    indirect_cost_cents: int
    total_spend_cents: int
    cost_per_student_cents: int
    compiled_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]
    attestation_text: Optional[str]
    invalidated_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Append-only observations — id + created_at ONLY (PRD §2.4)
# --------------------------------------------------------------------------
class CalendarBlackout(TypedDict):
    id: str
    school_partner_id: str
    blackout_type: str
    start_date: str
    end_date: str
    note: Optional[str]
    created_at: str


class PortfolioReview(TypedDict):
    id: str
    teaching_artist_id: str
    reviewer_user_id: str
    artistic_quality_score: float
    pedagogical_clarity_score: float
    cultural_responsiveness_score: float
    composite_score: float
    recommendation: str
    created_at: str


class BackgroundScreening(TypedDict):
    id: str
    teaching_artist_id: str
    screening_type: str
    outcome: str
    effective_on: str
    expires_on: Optional[str]
    adjudication_note: Optional[str]
    superseded: bool
    created_at: str


class EvaluationRecord(TypedDict):
    id: str
    session_id: str
    evaluation_type: str
    evaluator_user_id: str
    rubric_engagement_score: Optional[int]
    rubric_craft_score: Optional[int]
    rubric_standards_evidence_score: Optional[int]
    rubric_composite: Optional[float]
    teacher_survey_score: Optional[int]
    student_work_artifact_count: Optional[int]
    created_at: str
