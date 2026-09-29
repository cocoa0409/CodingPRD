"""Domain types for the Alcohol Server Training Certification API.

Entity TypedDicts, status enums and the role enum, named exactly as the PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------------------

class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    STATE_REGULATOR = "StateRegulator"
    TRAINER = "Trainer"
    EMPLOYER_ADMIN = "EmployerAdmin"
    ALCOHOL_SERVER = "AlcoholServer"


# --------------------------------------------------------------------------------------
# Shared vocabularies
# --------------------------------------------------------------------------------------

class MandateType(str, Enum):
    MANDATORY = "MANDATORY"
    CONDITIONAL = "CONDITIONAL"
    VOLUNTARY = "VOLUNTARY"


class Track(str, Enum):
    ON_PREMISE = "ON_PREMISE"
    OFF_PREMISE = "OFF_PREMISE"


class DeliveryMode(str, Enum):
    CLASSROOM = "CLASSROOM"
    ONLINE = "ONLINE"


class PremiseType(str, Enum):
    ON_PREMISE = "ON_PREMISE"
    OFF_PREMISE = "OFF_PREMISE"


class TrainingRequirement(str, Enum):
    MANDATED = "MANDATED"
    VOLUNTARY = "VOLUNTARY"


# --------------------------------------------------------------------------------------
# State machines
# --------------------------------------------------------------------------------------

class CourseStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class ApprovalStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class ApprovalDecision(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    REJECT = "REJECT"


class TrainerStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"
    LAPSED = "LAPSED"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ROSTER_LOCKED = "ROSTER_LOCKED"
    EXAM_OPEN = "EXAM_OPEN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CancellationReason(str, Enum):
    COURSE_SUPERSEDED = "COURSE_SUPERSEDED"
    TRAINER_SUSPENDED = "TRAINER_SUSPENDED"


class EnrollmentState(str, Enum):
    REGISTERED = "REGISTERED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    EXAM_SCHEDULED = "EXAM_SCHEDULED"
    EXAM_IN_PROGRESS = "EXAM_IN_PROGRESS"
    EXAM_FAILED = "EXAM_FAILED"
    PASSED = "PASSED"
    INCOMPLETE = "INCOMPLETE"
    WITHDRAWN = "WITHDRAWN"


class WithdrawalReason(str, Enum):
    SESSION_CANCELLED = "SESSION_CANCELLED"


class PaidBy(str, Enum):
    SELF_PAY = "SELF_PAY"
    EMPLOYER_CREDIT = "EMPLOYER_CREDIT"


class AttemptOutcome(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    PASS = "PASS"
    FAIL = "FAIL"
    VOIDED = "VOIDED"


class AttemptVoidReason(str, Enum):
    PROCTOR_ATTESTATION_WITHHELD = "PROCTOR_ATTESTATION_WITHHELD"


class ValidityState(str, Enum):
    ACTIVE = "ACTIVE"
    GRACE = "GRACE"
    LAPSED = "LAPSED"
    SUSPENDED = "SUSPENDED"
    SUPERSEDED = "SUPERSEDED"


class RegistryState(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING_SUBMISSION = "PENDING_SUBMISSION"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RESUBMIT_REQUIRED = "RESUBMIT_REQUIRED"


class ExpiryAnchorMode(str, Enum):
    ISSUANCE_ANCHORED = "ISSUANCE_ANCHORED"
    ANNIVERSARY_ANCHORED = "ANNIVERSARY_ANCHORED"


class SubmissionState(str, Enum):
    TRANSMITTED = "TRANSMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class SubmissionResult(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class RejectionCode(str, Enum):
    NONE = "NONE"
    DUPLICATE_SERVER_RECORD = "DUPLICATE_SERVER_RECORD"
    INVALID_COURSE_APPROVAL = "INVALID_COURSE_APPROVAL"
    NAME_MISMATCH = "NAME_MISMATCH"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    SUSPENDED = "SUSPENDED"


class DramShopDiscountStatus(str, Enum):
    NOT_DOCUMENTED = "NOT_DOCUMENTED"
    ELIGIBLE = "ELIGIBLE"
    DOCUMENTED = "DOCUMENTED"
    EXPIRED = "EXPIRED"


class DocumentState(str, Enum):
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class DocumentVoidReason(str, Enum):
    COMPLIANCE_RATE_FELL_BELOW_FLOOR = "COMPLIANCE_RATE_FELL_BELOW_FLOOR"
    COVERAGE_PERIOD_ENDED = "COVERAGE_PERIOD_ENDED"


class DiscountTier(str, Enum):
    NONE = "NONE"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class CompliancePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    AT_RISK = "AT_RISK"
    NON_COMPLIANT = "NON_COMPLIANT"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AssignmentState(str, Enum):
    ACTIVE = "ACTIVE"
    WORK_RESTRICTED = "WORK_RESTRICTED"
    ENDED = "ENDED"


class RestrictionReason(str, Enum):
    NONE = "NONE"
    CERTIFICATE_LAPSED = "CERTIFICATE_LAPSED"
    REGISTRY_SUSPENDED = "REGISTRY_SUSPENDED"
    NO_CERTIFICATE = "NO_CERTIFICATE"


class WorkEligibility(str, Enum):
    UNCERTIFIED = "UNCERTIFIED"
    ELIGIBLE = "ELIGIBLE"
    GRACE = "GRACE"
    RESTRICTED = "RESTRICTED"


# --------------------------------------------------------------------------------------
# Entity shapes
#
# Every resource the API mints carries id / created_at / updated_at / version, with one
# deliberate exception: a compliance run is an immutable audit record carrying only
# id and created_at.
# --------------------------------------------------------------------------------------

class StateJurisdiction(TypedDict):
    id: str
    state_code: str
    mandate_type: str
    mandated_tracks: List[str]
    certificate_validity_months: int
    renewal_grace_days: int
    new_hire_training_days: int
    registry_submission_required: bool
    registry_deadline_days: int
    registry_late_fee_cents_per_day: int
    min_passing_score_pct: float
    max_retakes_allowed: int
    retake_cooling_off_hours: int
    proctor_separation_required: bool
    reminder_lead_days: int
    certificates_issued_count: int
    created_at: str
    updated_at: str
    version: int


class Course(TypedDict):
    id: str
    title: str
    track: str
    delivery_mode: str
    contact_hours: float
    question_count: int
    version_label: str
    supersedes_course_id: Optional[str]
    status: str
    content_revision_count: int
    retired_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CourseApproval(TypedDict):
    id: str
    course_id: str
    state_jurisdiction_id: str
    approval_status: str
    review_round: int
    submission_note: Optional[str]
    approval_number: Optional[str]
    effective_from: Optional[str]
    expires_at: Optional[str]
    pinned_course_version: Optional[int]
    changes_requested_note: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Trainer(TypedDict):
    id: str
    full_name: str
    email: str
    trainer_status: str
    certified_tracks: List[str]
    certified_state_codes: List[str]
    credential_expires_at: Optional[str]
    suspension_reason: Optional[str]
    sessions_taught_count: int
    graded_enrollments_count: int
    pass_rate_pct: float
    created_at: str
    updated_at: str
    version: int


class ClassSession(TypedDict):
    id: str
    course_id: str
    state_jurisdiction_id: str
    trainer_id: str
    proctor_trainer_id: Optional[str]
    scheduled_start_at: str
    scheduled_end_at: str
    capacity: int
    session_status: str
    enrolled_count: int
    passed_count: int
    pinned_course_approval_id: str
    pinned_course_version: int
    exam_opened_at: Optional[str]
    completed_at: Optional[str]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AlcoholServer(TypedDict):
    id: str
    full_name: str
    email: str
    state_jurisdiction_id: str
    work_eligibility: str
    active_certificate_id: Optional[str]
    certification_count: int
    restricted_since: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    class_session_id: str
    alcohol_server_id: str
    sponsoring_employer_account_id: Optional[str]
    paid_by: str
    seat_credit_charged: bool
    enrollment_state: str
    attempt_count: int
    best_score_pct: Optional[float]
    last_counted_attempt_ended_at: Optional[str]
    retake_eligible_at: Optional[str]
    withdrawal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExamAttempt(TypedDict):
    id: str
    enrollment_id: str
    attempt_number: int
    question_count: int
    raw_correct_count: Optional[int]
    score_pct: Optional[float]
    outcome: str
    proctor_attestation: Optional[bool]
    started_at: str
    submitted_at: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict):
    id: str
    alcohol_server_id: str
    enrollment_id: str
    state_jurisdiction_id: str
    track: str
    certificate_number: str
    issued_at: str
    expires_at: str
    expiry_anchor_mode: str
    renews_certificate_id: Optional[str]
    validity_state: str
    registry_state: str
    registry_due_at: Optional[str]
    reminder_sent_count: int
    last_reminder_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RegistrySubmission(TypedDict):
    id: str
    certificate_id: str
    attempt_number: int
    batch_reference: Optional[str]
    submission_state: str
    transmitted_at: str
    due_at: Optional[str]
    acknowledged_at: Optional[str]
    late_days: int
    penalty_fee_cents: int
    rejection_code: str
    created_at: str
    updated_at: str
    version: int


class EmployerAccount(TypedDict):
    id: str
    legal_name: str
    billing_state_code: str
    account_status: str
    status_reason: Optional[str]
    seat_credit_balance: int
    seat_credits_purchased_total: int
    seat_credits_consumed_total: int
    seat_credits_refunded_total: int
    last_purchase_discount_pct: float
    last_purchase_total_charged_cents: int
    lifetime_charged_cents: int
    location_count: int
    account_compliance_rate_pct: float
    dram_shop_discount_status: str
    first_documented_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EmployerLocation(TypedDict):
    id: str
    employer_account_id: str
    location_name: str
    state_jurisdiction_id: str
    premise_type: str
    annual_premium_cents: int
    training_requirement: str
    assigned_server_count: int
    compliant_server_count: int
    grace_server_count: int
    restricted_server_count: int
    compliance_rate_strict_pct: float
    compliance_rate_grace_inclusive_pct: float
    compliance_posture: str
    created_at: str
    updated_at: str
    version: int


class ServerAssignment(TypedDict):
    id: str
    employer_location_id: str
    alcohol_server_id: str
    role_title: str
    assignment_state: str
    restriction_reason: str
    assigned_at: str
    restricted_at: Optional[str]
    ended_at: Optional[str]
    end_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DramShopDocument(TypedDict):
    id: str
    employer_account_id: str
    insurer_name: str
    policy_number: str
    coverage_period_start: str
    coverage_period_end: str
    snapshot_at: str
    strict_compliance_rate_pct: float
    months_documented: int
    discount_tier: str
    discount_pct: float
    discount_credit_cents: int
    location_count: int
    document_state: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceRun(TypedDict):
    """A compliance run is an immutable audit record: it carries only id and created_at.

    It has no updated_at and no version at all, and those keys must not appear on it.
    """
    id: str
    run_at: str
    trainers_lapsed_count: int
    approvals_expired_count: int
    certificates_graced_count: int
    certificates_lapsed_count: int
    reminders_sent_count: int
    assignments_restricted_count: int
    assignments_restored_count: int
    locations_recomputed_count: int
    documents_voided_count: int
    created_at: str


class ComplianceDashboard(TypedDict):
    employer_location_id: str
    training_requirement: str
    assigned_server_count: int
    compliant_server_count: int
    grace_server_count: int
    restricted_server_count: int
    compliance_rate_strict_pct: float
    compliance_rate_grace_inclusive_pct: float
    compliance_posture: str
