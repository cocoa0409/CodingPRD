"""Typed shapes and enumerations for the adult-education HSE testing service.

Every record type carries the four common fields described in the PRD: ``id``,
``created_at``, ``updated_at`` and ``version``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class Role:
    """The seven declared caller roles."""

    STATE_AUTHORITY = "StateAuthority"
    PROGRAM_COORDINATOR = "ProgramCoordinator"
    REGISTRAR = "Registrar"
    INSTRUCTOR = "Instructor"
    CENTER_ADMINISTRATOR = "CenterAdministrator"
    PROCTOR = "Proctor"
    STUDENT = "Student"

    ALL = (
        STATE_AUTHORITY,
        PROGRAM_COORDINATOR,
        REGISTRAR,
        INSTRUCTOR,
        CENTER_ADMINISTRATOR,
        PROCTOR,
        STUDENT,
    )


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class IntakeStatus:
    INTAKE_STARTED = "INTAKE_STARTED"
    ORIENTED = "ORIENTED"
    PLACED = "PLACED"
    ENROLLED = "ENROLLED"
    EXITED = "EXITED"


class ProgramTrack:
    LITERACY = "LITERACY"
    HSE_PREP = "HSE_PREP"
    ESL = "ESL"


class CredentialStanding:
    NONE = "NONE"
    ISSUED = "ISSUED"
    REVOKED = "REVOKED"


class CenterAuthorizationStatus:
    APPLIED = "APPLIED"
    PROVISIONAL = "PROVISIONAL"
    FULL_AUTHORIZED = "FULL_AUTHORIZED"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class CenterDecision:
    GRANT_PROVISIONAL = "GRANT_PROVISIONAL"
    GRANT_FULL = "GRANT_FULL"
    WITHDRAW = "WITHDRAW"


class RoomStatus:
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class ProctorCertificationStatus:
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"
    LAPSED = "LAPSED"
    REVOKED = "REVOKED"


class ProctorDecision:
    CERTIFY = "CERTIFY"
    RENEW = "RENEW"
    REVOKE = "REVOKE"


class SectionStatus:
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    IN_SESSION = "IN_SESSION"
    CLOSED = "CLOSED"


class EnrollmentStatus:
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class ExitReason:
    SECTION_CLOSED = "SECTION_CLOSED"


class AttendanceStatus:
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class TestEventPurpose:
    PRE_TEST = "PRE_TEST"
    POST_TEST = "POST_TEST"


class TestForm:
    CASAS_R_900 = "CASAS_R_900"
    CASAS_M_900 = "CASAS_M_900"
    BEST_PLUS = "BEST_PLUS"


class TestEventStatus:
    SCHEDULED = "SCHEDULED"
    SCORED = "SCORED"
    INVALIDATED = "INVALIDATED"


class InvalidationReason:
    HOURS_WITHDRAWN = "HOURS_WITHDRAWN"


class Subtest:
    MATH = "MATH"
    RLA = "RLA"
    SCIENCE = "SCIENCE"
    SOCIAL_STUDIES = "SOCIAL_STUDIES"

    ALL = (MATH, RLA, SCIENCE, SOCIAL_STUDIES)


class TestFormat:
    STANDARD = "STANDARD"
    EXTRA_TIME = "EXTRA_TIME"
    LARGE_PRINT = "LARGE_PRINT"
    BRAILLE = "BRAILLE"
    AUDIO = "AUDIO"


class SessionStatus:
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CancelReason:
    CENTER_SUSPENDED = "CENTER_SUSPENDED"


class RegistrationStatus:
    REGISTERED = "REGISTERED"
    CHECKED_IN = "CHECKED_IN"
    SCORED = "SCORED"
    CANCELLED = "CANCELLED"
    CANCELLED_BY_CENTER = "CANCELLED_BY_CENTER"
    RESULT_INVALIDATED = "RESULT_INVALIDATED"


class IdentityStatus:
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    ID_REJECTED = "ID_REJECTED"


class IdentityDecision:
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ResultOutcome:
    PASSED = "PASSED"
    FAILED = "FAILED"


class AccommodationStatus:
    SUBMITTED = "SUBMITTED"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class AccommodationDecision:
    APPROVE = "APPROVE"
    DENY = "DENY"


class MeasureType:
    EFL_GAIN = "EFL_GAIN"
    CREDENTIAL_ATTAINMENT = "CREDENTIAL_ATTAINMENT"
    EMPLOYMENT_Q2 = "EMPLOYMENT_Q2"
    POSTSECONDARY_ENROLLMENT = "POSTSECONDARY_ENROLLMENT"


class OutcomeStatus:
    RECORDED = "RECORDED"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"
    RESCINDED = "RESCINDED"


class OutcomeDecision:
    CERTIFY = "CERTIFY"
    REJECT = "REJECT"


class AllocationStatus:
    UNALLOCATED = "UNALLOCATED"
    COMMITTED = "COMMITTED"
    DEFERRED = "DEFERRED"
    REVOKED = "REVOKED"


class RescissionReason:
    POST_TEST_INVALIDATED = "POST_TEST_INVALIDATED"
    CREDENTIAL_VOIDED = "CREDENTIAL_VOIDED"


class CredentialType:
    HSE_DIPLOMA = "HSE_DIPLOMA"


class CredentialIssuanceStatus:
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class VoidReason:
    PROCTOR_REVOKED = "PROCTOR_REVOKED"


class TranscriptDelivery:
    STANDARD = "STANDARD"
    RUSH = "RUSH"


class TranscriptDestination:
    SELF = "SELF"
    EMPLOYER = "EMPLOYER"
    POSTSECONDARY = "POSTSECONDARY"
    STATE_RECORDS = "STATE_RECORDS"


class TranscriptOrderStatus:
    QUEUED = "QUEUED"
    FULFILLED = "FULFILLED"
    HELD = "HELD"


class HoldReason:
    CREDENTIAL_VOIDED = "CREDENTIAL_VOIDED"


class FundingPeriodStatus:
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class AllocationVariant:
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class MsgVariant:
    BEST_POST = "BEST_POST"
    LATEST_POST = "LATEST_POST"


# ---------------------------------------------------------------------------
# Record shapes
# ---------------------------------------------------------------------------


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Student(CommonFields):
    full_name: str
    email: str
    primary_track: str
    intake_status: str
    orientation_completed_at: Optional[str]
    placement_efl_level: Optional[int]
    total_instructional_hours: float
    voucher_granted_cents: int
    voucher_balance_cents: int
    voucher_spent_cents: int
    self_pay_authorized: bool
    exam_fee_owed_cents: int
    credential_status: str
    active_enrollment_count: int


class TestingCenter(CommonFields):
    name: str
    state_code: str
    authorization_status: str
    allowed_subtests: List[str]
    max_sessions_per_week: int
    authorized_at: Optional[str]
    suspended_reason: Optional[str]


class TestingRoom(CommonFields):
    testing_center_id: str
    room_code: str
    seat_capacity: int
    turnaround_buffer_minutes: int
    status: str
    service_note: Optional[str]


class Proctor(CommonFields):
    testing_center_id: str
    full_name: str
    certification_status: str
    certification_expires_at: Optional[str]
    daily_hour_cap: float
    assigned_session_count: int


class ClassSection(CommonFields):
    program_track: str
    title: str
    instructor_user_id: str
    min_efl_level: int
    max_efl_level: int
    seats_total: int
    seats_taken: int
    seats_available: int
    weekly_hours: float
    status: str


class Enrollment(CommonFields):
    student_id: str
    class_section_id: str
    status: str
    entry_efl_level: int
    posted_hours: float
    post_test_eligible: bool
    withdrawn_at: Optional[str]
    exit_reason: Optional[str]


class AttendanceEntry(CommonFields):
    enrollment_id: str
    attendance_date: str
    hours: float
    status: str
    void_reason: Optional[str]
    posted_by_user_id: str


class TestEvent(CommonFields):
    student_id: str
    enrollment_id: Optional[str]
    purpose: str
    test_form: str
    scheduled_for: str
    test_date: Optional[str]
    scale_score: Optional[int]
    efl_level: Optional[int]
    status: str
    invalidation_reason: Optional[str]


class ExamSession(CommonFields):
    testing_room_id: str
    proctor_id: Optional[str]
    subtest: str
    starts_at: str
    ends_at: str
    requested_seats: int
    seat_capacity: int
    seats_taken: int
    duration_hours: float
    supported_formats: List[str]
    status: str
    cancel_reason: Optional[str]


class ExamRegistration(CommonFields):
    student_id: str
    exam_session_id: str
    accommodation_request_id: Optional[str]
    identity_verified_by_proctor_id: Optional[str]
    registration_status: str
    identity_status: str
    identity_document_type: Optional[str]
    prior_scored_attempts: int
    gross_fee_cents: int
    accommodation_surcharge_cents: int
    discount_cents: int
    voucher_applied_cents: int
    fee_due_cents: int
    scale_score: Optional[int]
    result_outcome: Optional[str]
    checked_in_at: Optional[str]
    refunded_cents: int


class AccommodationRequest(CommonFields):
    student_id: str
    requested_format: str
    documentation_ref: str
    status: str
    info_request_rounds: int
    granted_format: Optional[str]
    valid_until: Optional[str]
    decision_note: Optional[str]


class OutcomeRecord(CommonFields):
    student_id: str
    funding_period_id: str
    credential_issuance_id: Optional[str]
    measure_type: str
    evidence_ref: str
    status: str
    recorded_by_user_id: str
    certified_by_user_id: Optional[str]
    weight: float
    allocated_cents: int
    allocation_status: str
    rescission_reason: Optional[str]


class CredentialIssuance(CommonFields):
    student_id: str
    credential_type: str
    composite_score: int
    subtest_scores: Dict[str, Optional[int]]
    qualifying_registration_ids: List[str]
    status: str
    issued_at: str
    void_reason: Optional[str]


class TranscriptOrder(CommonFields):
    student_id: str
    credential_issuance_id: str
    copies: int
    delivery: str
    destination_type: str
    base_charge_cents: int
    waiver_cents: int
    state_records_fee_cents: int
    total_charge_cents: int
    status: str
    fulfilled_at: Optional[str]
    hold_reason: Optional[str]


class FundingPeriod(CommonFields):
    label: str
    start_date: str
    end_date: str
    rate_cents_per_weight: int
    total_cents: int
    committed_cents: int
    available_cents: int
    allocation_run_count: int
    last_allocation_run_at: Optional[str]
    last_allocation_variant: Optional[str]
    status: str


class SkillGainRead(TypedDict):
    student_id: str
    variant: str
    entry_efl_level: Optional[int]
    post_efl_level: Optional[int]
    best_post_scale_score: Optional[int]
    latest_post_scale_score: Optional[int]
    levels_gained: int
    msg_achieved: bool


class AllocationPreview(TypedDict):
    funding_period_id: str
    variant: str
    total_weight: float
    line_count: int
    projected_committed_cents: int
    projected_available_cents: int
    deferred_line_count: int


JsonDict = Dict[str, Any]
