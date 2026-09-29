"""Domain types for the Professional Certification Body API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them. Every entity in this system exposes ``id``, ``created_at``,
``updated_at`` and ``version`` (PRD §2.4: "No entity in this system is exempt").
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    ITEM_SPECIALIST = "ItemSpecialist"
    PSYCHOMETRICIAN = "Psychometrician"
    PANELIST = "Panelist"
    ELIGIBILITY_REVIEWER = "EligibilityReviewer"
    EXAM_OPERATIONS = "ExamOperations"
    CANDIDATE = "Candidate"
    CERTIFICANT = "Certificant"
    ETHICS_OFFICER = "EthicsOfficer"
    PUBLIC = "Public"


# --------------------------------------------------------------------------
# CertificationProgram (PRD §3.1)
# --------------------------------------------------------------------------


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class BlueprintPosture(str, Enum):
    COMPLETE = "COMPLETE"
    DEFICIENT = "DEFICIENT"


class PsychometricStatBasis(str, Enum):
    POOLED = "POOLED"
    OPERATIONAL_ONLY = "OPERATIONAL_ONLY"


class CeuCreditAccrualBasis(str, Enum):
    STRICT_CYCLE = "STRICT_CYCLE"
    CARRYOVER_ALLOWED = "CARRYOVER_ALLOWED"


class CertificationProgram(TypedDict, total=False):
    id: str
    name: str
    credential_code: str
    jta_version: str
    domain_specs: List[Dict[str, Any]]
    form_length: int
    psychometric_stat_basis: str
    min_discrimination: float
    min_p_value: float
    max_p_value: float
    min_responses_for_stats: int
    form_retirement_tolerance_pct: int
    min_panelists: int
    panel_trim_count: int
    cut_score_sem_multiplier: float
    accepted_education_credentials: List[str]
    education_recency_years: int
    min_experience_months: int
    audit_every_nth: int
    eligibility_valid_days: int
    exam_fee_cents: int
    max_attempts_per_cycle: int
    retake_wait_days: int
    cycle_length_months: int
    required_ceu_credits: float
    ceu_credit_accrual_basis: str
    ceu_carryover_max_credits: float
    recert_grace_days: int
    status: str
    operational_item_count: int
    deficient_domain_codes: List[str]
    blueprint_posture: str
    verified_application_counter: int
    certificants_issued_count: int
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Item (PRD §3.2 – §3.4)
# --------------------------------------------------------------------------


class ItemStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
    PRETEST = "PRETEST"
    OPERATIONAL = "OPERATIONAL"
    FLAGGED = "FLAGGED"
    RETIRED = "RETIRED"


class CognitiveLevel(str, Enum):
    RECALL = "RECALL"
    APPLICATION = "APPLICATION"
    ANALYSIS = "ANALYSIS"


class StatBasisApplied(str, Enum):
    POOLED = "POOLED"
    OPERATIONAL_ONLY = "OPERATIONAL_ONLY"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class FlagReason(str, Enum):
    LOW_DISCRIMINATION = "LOW_DISCRIMINATION"
    TOO_EASY = "TOO_EASY"
    TOO_HARD = "TOO_HARD"


class RetirementReason(str, Enum):
    PSYCHOMETRIC = "PSYCHOMETRIC"
    CONTENT_OBSOLETE = "CONTENT_OBSOLETE"
    EXPOSED = "EXPOSED"
    PRETEST_FAILED = "PRETEST_FAILED"


class ItemReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    REVISE = "REVISE"
    REJECT = "REJECT"


class Item(TypedDict, total=False):
    id: str
    program_id: str
    domain_code: str
    cognitive_level: str
    stem: str
    author_user_id: str
    approver_user_ids: List[str]
    review_round: int
    status: str
    pretest_response_count: int
    pretest_correct_count: int
    pretest_upper_n: int
    pretest_upper_correct: int
    pretest_lower_n: int
    pretest_lower_correct: int
    operational_response_count: int
    operational_correct_count: int
    operational_upper_n: int
    operational_upper_correct: int
    operational_lower_n: int
    operational_lower_correct: int
    p_value: Optional[float]
    discrimination_index: Optional[float]
    stat_basis_applied: str
    flag_reason: Optional[str]
    retirement_reason: Optional[str]
    retired_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# ExamForm (PRD §3.5)
# --------------------------------------------------------------------------


class FormStatus(str, Enum):
    ASSEMBLED = "ASSEMBLED"
    CUT_SCORE_SET = "CUT_SCORE_SET"
    PUBLISHED = "PUBLISHED"
    NEEDS_REBUILD = "NEEDS_REBUILD"


class PanelStatus(str, Enum):
    OPEN = "OPEN"
    RATINGS_COMPLETE = "RATINGS_COMPLETE"
    ADOPTED = "ADOPTED"


class PanelMethod(str, Enum):
    MODIFIED_ANGOFF = "MODIFIED_ANGOFF"
    BOOKMARK = "BOOKMARK"


class ExamForm(TypedDict, total=False):
    id: str
    program_id: str
    form_code: str
    item_ids: List[str]
    pretest_item_ids: List[str]
    panelist_user_ids: List[str]
    panel_method: str
    panel_status: str
    panel_ratings: List[Dict[str, Any]]
    mean_expected_pass_rate: Optional[float]
    raw_cut_score: Optional[int]
    scored_item_count: int
    retired_item_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Candidate (PRD §3.6)
# --------------------------------------------------------------------------


class CandidateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BARRED = "BARRED"


class BarReason(str, Enum):
    SECURITY_INCIDENT = "SECURITY_INCIDENT"
    DISCIPLINARY = "DISCIPLINARY"


class Candidate(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    status: str
    barred_until: Optional[str]
    bar_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# EligibilityApplication (PRD §3.6)
# --------------------------------------------------------------------------


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    AUDIT_SELECTED = "AUDIT_SELECTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class DimensionStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class EducationCredential(str, Enum):
    DIPLOMA = "DIPLOMA"
    ASSOCIATE = "ASSOCIATE"
    BACHELOR = "BACHELOR"
    MASTER = "MASTER"
    DOCTORATE = "DOCTORATE"


class DenialReason(str, Enum):
    EDUCATION_FAILED = "EDUCATION_FAILED"
    EXPERIENCE_FAILED = "EXPERIENCE_FAILED"
    AUDIT_FAILED = "AUDIT_FAILED"


class VerificationDimension(str, Enum):
    EDUCATION = "EDUCATION"
    EXPERIENCE = "EXPERIENCE"


class EligibilityApplication(TypedDict, total=False):
    id: str
    candidate_id: str
    program_id: str
    education_credential: str
    education_completion_year: int
    experience_months: int
    attestation_signed: bool
    education_status: str
    experience_status: str
    status: str
    verifier_user_ids: List[Dict[str, Any]]
    auditor_user_id: Optional[str]
    audit_sequence_number: Optional[int]
    eligibility_expires_on: Optional[str]
    denial_reason: Optional[str]
    attempts_consumed: int
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# ExamSession (PRD §3.7)
# --------------------------------------------------------------------------


class SessionModality(str, Enum):
    TEST_CENTER = "TEST_CENTER"
    ONLINE_PROCTORED = "ONLINE_PROCTORED"


class SessionStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    CLOSED = "CLOSED"


class ExamSession(TypedDict, total=False):
    id: str
    modality: str
    center_code: Optional[str]
    room_code: Optional[str]
    proctor_pool_code: Optional[str]
    starts_at: str
    ends_at: str
    seat_capacity: int
    seats_reserved: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# ExamRegistration (PRD §3.7 – §3.8)
# --------------------------------------------------------------------------


class SeatStatus(str, Enum):
    UNSCHEDULED = "UNSCHEDULED"
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ScoreStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING = "PENDING"
    SCORED = "SCORED"
    REPORTED = "REPORTED"
    WITHHELD = "WITHHELD"
    VOIDED = "VOIDED"


class ExamOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ExamRegistration(TypedDict, total=False):
    id: str
    candidate_id: str
    application_id: str
    form_id: str
    session_id: Optional[str]
    session_ends_at: Optional[str]
    fee_paid_cents: int
    attempt_number: int
    eligibility_expires_on_snapshot: Optional[str]
    seat_status: str
    score_status: str
    score_status_before_hold: Optional[str]
    raw_score: Optional[int]
    scaled_score: Optional[int]
    outcome: Optional[str]
    form_reassignment_required: bool
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# SecurityIncident (PRD §3.9)
# --------------------------------------------------------------------------


class IncidentType(str, Enum):
    PROHIBITED_DEVICE = "PROHIBITED_DEVICE"
    IMPERSONATION = "IMPERSONATION"
    CONTENT_DISCLOSURE = "CONTENT_DISCLOSURE"
    PROCTOR_INTERRUPTION = "PROCTOR_INTERRUPTION"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"


class IncidentAdjudication(str, Enum):
    SUBSTANTIATE = "SUBSTANTIATE"
    DISMISS = "DISMISS"


class SecurityIncident(TypedDict, total=False):
    id: str
    registration_id: str
    incident_type: str
    severity: str
    description: str
    status: str
    outcome_note: Optional[str]
    placed_hold: bool
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Certificant (PRD §3.10)
# --------------------------------------------------------------------------


class CertificantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class PublicationStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    WITHHELD = "WITHHELD"
    REMOVED = "REMOVED"


class Certificant(TypedDict, total=False):
    id: str
    candidate_id: str
    program_id: str
    certificate_number: str
    issued_on: str
    valid_through: str
    status: str
    suspension_until: Optional[str]
    publication_status: str
    ceu_credits_applied: float
    current_cycle_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# RecertificationCycle (PRD §3.11)
# --------------------------------------------------------------------------


class CycleStatus(str, Enum):
    OPEN = "OPEN"
    SATISFIED = "SATISFIED"
    CLOSED = "CLOSED"
    LAPSED = "LAPSED"
    VOID = "VOID"


class CyclePath(str, Enum):
    CEU = "CEU"
    RE_EXAM = "RE_EXAM"


class RecertificationCycle(TypedDict, total=False):
    id: str
    certificant_id: str
    reexam_registration_id: Optional[str]
    cycle_number: int
    starts_on: str
    ends_on: str
    grace_ends_on: str
    required_credits: float
    accrual_basis_snapshot: str
    carryover_credits_in: float
    credits_applied: float
    carryover_credits_out: float
    path: str
    status: str
    reinstatement_fee_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# CEUActivity (PRD §3.11)
# --------------------------------------------------------------------------


class CeuCategory(str, Enum):
    LIVE_INSTRUCTION = "LIVE_INSTRUCTION"
    SELF_STUDY = "SELF_STUDY"
    PRESENTING = "PRESENTING"
    PUBLICATION = "PUBLICATION"
    VOLUNTEER = "VOLUNTEER"


class CeuActivityStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    AUDIT_SELECTED = "AUDIT_SELECTED"
    VERIFIED = "VERIFIED"
    REVOKED = "REVOKED"


class CeuReviewOutcome(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    SELECT_FOR_AUDIT = "SELECT_FOR_AUDIT"


class CeuAuditOutcome(str, Enum):
    VERIFY = "VERIFY"
    REVOKE = "REVOKE"


class CEUActivity(TypedDict, total=False):
    id: str
    cycle_id: str
    activity_date: str
    category: str
    provider: str
    contact_hours: float
    credits_awarded: float
    credits_counted: float
    counted: bool
    status: str
    reviewer_user_id: Optional[str]
    audit_verifier_user_id: Optional[str]
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# DisciplinaryCase (PRD §3.12)
# --------------------------------------------------------------------------


class AllegationType(str, Enum):
    CREDENTIAL_MISUSE = "CREDENTIAL_MISUSE"
    EXAM_MISCONDUCT = "EXAM_MISCONDUCT"
    CEU_FALSIFICATION = "CEU_FALSIFICATION"
    ETHICS_VIOLATION = "ETHICS_VIOLATION"


class CaseStatus(str, Enum):
    OPENED = "OPENED"
    RESPONSE_REQUESTED = "RESPONSE_REQUESTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLOSED = "CLOSED"


class CaseOutcome(str, Enum):
    DISMISSED = "DISMISSED"
    SANCTIONED = "SANCTIONED"
    REVOKED = "REVOKED"


class DisciplinaryCase(TypedDict, total=False):
    id: str
    certificant_id: str
    allegation_type: str
    description: str
    status: str
    response_round: int
    response_text: Optional[str]
    outcome: Optional[str]
    sanction_months: Optional[int]
    decided_on: Optional[str]
    opened_by_user_id: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Purpose-built (non-entity) response objects (PRD §2.10, §3.10, §3.13)
# --------------------------------------------------------------------------


class RegistryVerification(TypedDict, total=False):
    certificate_number: str
    credential_code: str
    full_name: str
    credential_status: str
    publication_status: str
    issued_on: str
    valid_through: str
    verified_at: str


class MaintenanceRunReport(TypedDict, total=False):
    run_at: str
    no_show_registration_ids: List[str]
    expired_application_ids: List[str]
    lapsed_cycle_ids: List[str]
    expired_certificant_ids: List[str]
    reactivated_certificant_ids: List[str]
    unbarred_candidate_ids: List[str]
