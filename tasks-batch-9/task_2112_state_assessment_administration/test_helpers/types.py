"""Domain types for the State Assessment Administration API.

Entity TypedDicts, status enums and the role enum, mirroring the resource
shapes described in the PRD.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    STATE_ASSESSMENT_OFFICER = "StateAssessmentOfficer"
    DISTRICT_TEST_COORDINATOR = "DistrictTestCoordinator"
    SCHOOL_TEST_COORDINATOR = "SchoolTestCoordinator"
    PROCTOR = "Proctor"


# ─── Status enums ─────────────────────────────────────────────────────────

class TestWindowStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    MAKEUP = "MAKEUP"
    SCORING = "SCORING"
    RELEASED = "RELEASED"
    FINALIZED = "FINALIZED"
    CANCELLED = "CANCELLED"


class SessionStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    INVALIDATED = "INVALIDATED"


class SessionType(str, Enum):
    INITIAL = "INITIAL"
    MAKEUP = "MAKEUP"


class AttendanceStatus(str, Enum):
    PENDING = "PENDING"
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    EXCUSED = "EXCUSED"
    WITHDRAWN = "WITHDRAWN"


class AccommodationStatus(str, Enum):
    NONE = "NONE"
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ScoreStatus(str, Enum):
    NOT_SCORED = "NOT_SCORED"
    SCORED = "SCORED"
    RELEASED = "RELEASED"
    UNDER_APPEAL = "UNDER_APPEAL"
    CORRECTED = "CORRECTED"
    INVALIDATED = "INVALIDATED"
    FINAL = "FINAL"


class ReportDeliveryStatus(str, Enum):
    NOT_QUEUED = "NOT_QUEUED"
    DELIVERED = "DELIVERED"
    SUPPRESSED = "SUPPRESSED"


class ReportSuppressedReason(str, Enum):
    UNDER_APPEAL = "UNDER_APPEAL"
    INVALIDATED = "INVALIDATED"
    MISSING_GUARDIAN_EMAIL = "MISSING_GUARDIAN_EMAIL"


class MaterialLotStatus(str, Enum):
    SHIPPED = "SHIPPED"
    RECEIVED = "RECEIVED"
    IN_DISTRIBUTION = "IN_DISTRIBUTION"
    RETURNED_PENDING = "RETURNED_PENDING"
    RECONCILED = "RECONCILED"
    DISCREPANT = "DISCREPANT"


class CustodyEventType(str, Enum):
    RECEIPT = "RECEIPT"
    TRANSFER_TO_SCHOOL = "TRANSFER_TO_SCHOOL"
    SESSION_CHECKOUT = "SESSION_CHECKOUT"
    SESSION_CHECKIN = "SESSION_CHECKIN"
    RETURN_TO_DISTRICT = "RETURN_TO_DISTRICT"
    DESTRUCTION = "DESTRUCTION"


class HolderType(str, Enum):
    STATE = "STATE"
    DISTRICT = "DISTRICT"
    SCHOOL = "SCHOOL"
    SESSION = "SESSION"
    DESTROYED = "DESTROYED"


class ProctorTrainingStatus(str, Enum):
    NOT_TRAINED = "NOT_TRAINED"
    FAILED = "FAILED"
    PASSED = "PASSED"


class ProctorCertificationStatus(str, Enum):
    NOT_CERTIFIED = "NOT_CERTIFIED"
    CERTIFIED = "CERTIFIED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class AffidavitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class IrregularityReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RETURNED_FOR_INFO = "RETURNED_FOR_INFO"
    ADJUDICATED = "ADJUDICATED"
    WITHDRAWN = "WITHDRAWN"


class IrregularityCategory(str, Enum):
    ADMIN_ERROR = "ADMIN_ERROR"
    SECURITY_BREACH = "SECURITY_BREACH"
    TECH_FAILURE = "TECH_FAILURE"
    STUDENT_MISCONDUCT = "STUDENT_MISCONDUCT"


class IrregularitySeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class IrregularityDisposition(str, Enum):
    DISMISSED = "DISMISSED"
    INVALIDATE_REGISTRATION = "INVALIDATE_REGISTRATION"
    INVALIDATE_SESSION = "INVALIDATE_SESSION"
    BREACH_CONFIRMED = "BREACH_CONFIRMED"


class ScoreAppealStatus(str, Enum):
    FILED = "FILED"
    UPHELD = "UPHELD"
    DENIED = "DENIED"


class AppealReasonCode(str, Enum):
    SCORING_ERROR = "SCORING_ERROR"
    ROSTER_ERROR = "ROSTER_ERROR"
    ACCOMMODATION_NOT_PROVIDED = "ACCOMMODATION_NOT_PROVIDED"
    IRREGULARITY_IMPACT = "IRREGULARITY_IMPACT"


class AccommodationCode(str, Enum):
    EXTENDED_TIME = "EXTENDED_TIME"
    SMALL_GROUP = "SMALL_GROUP"
    ASSISTIVE_TECH = "ASSISTIVE_TECH"
    SEPARATE_ROOM = "SEPARATE_ROOM"
    READ_ALOUD = "READ_ALOUD"
    SCRIBE = "SCRIBE"
    BRAILLE_FORM = "BRAILLE_FORM"


class Subject(str, Enum):
    ELA = "ELA"
    MATH = "MATH"
    SCIENCE = "SCIENCE"
    SOCIAL_STUDIES = "SOCIAL_STUDIES"


class GradeBand(str, Enum):
    G3_5 = "G3_5"
    G6_8 = "G6_8"
    G9_12 = "G9_12"


# ─── Entity shapes ────────────────────────────────────────────────────────
# Every entity below except CustodyEvent carries id / created_at / updated_at
# / version. CustodyEvent is the append-only exception and carries only id and
# created_at.

class District(TypedDict):
    id: str
    name: str
    district_code: str
    state_code: str
    replacement_charge_total_cents: int
    security_assessment_cents: int
    open_discrepancy_count: int
    created_at: str
    updated_at: str
    version: int


class School(TypedDict):
    id: str
    district_id: str
    name: str
    school_code: str
    max_concurrent_seats: int
    created_at: str
    updated_at: str
    version: int


class TestWindow(TypedDict):
    id: str
    name: str
    subject: str
    grade_band: str
    window_start: str
    window_end: str
    makeup_start: str
    makeup_end: str
    appeal_window_days: int
    min_participation_pct: float
    status: str
    released_at: Optional[str]
    appeal_window_closes_at: Optional[str]
    participation_rate_provisional_pct: Optional[float]
    participation_rate_final_pct: Optional[float]
    registered_distinct_count: int
    present_distinct_count: int
    open_breach_count: int
    security_hold: bool
    created_at: str
    updated_at: str
    version: int


class Proctor(TypedDict):
    id: str
    school_id: str
    full_name: str
    email: str
    training_status: str
    quiz_score_pct: Optional[float]
    training_completed_at: Optional[str]
    revoked_at: Optional[str]
    certification_status: str
    strike_count: int
    latest_affidavit_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SecurityAffidavit(TypedDict):
    id: str
    proctor_id: str
    window_id: str
    affidavit_version: str
    signed_at: str
    signer_user_id: str
    status: str
    revoked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict):
    id: str
    window_id: str
    school_id: str
    proctor_id: Optional[str]
    room_code: str
    scheduled_start: str
    scheduled_end: str
    seat_capacity: int
    session_type: str
    status: str
    seats_consumed: int
    effective_seat_capacity: int
    separate_setting_count: int
    materials_checked_out: int
    materials_checked_in: int
    opened_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict):
    id: str
    session_id: str
    makeup_of_registration_id: Optional[str]
    student_state_id: str
    grade: int
    guardian_email: Optional[str]
    accommodation_codes: List[str]
    accommodation_status: str
    accommodation_decision_note: Optional[str]
    attendance_status: str
    raw_score: Optional[int]
    score_status: str
    report_delivery_status: str
    report_suppressed_reason: Optional[str]
    report_delivered_at: Optional[str]
    seats_required: int
    created_at: str
    updated_at: str
    version: int


class MaterialLot(TypedDict):
    id: str
    window_id: str
    district_id: str
    lot_code: str
    quantity_shipped: int
    seal_range_start: int
    seal_range_end: int
    status: str
    quantity_at_district: int
    quantity_at_school: int
    quantity_in_sessions: int
    quantity_destroyed: int
    chain_accounted_count: int
    declared_accounted_count: Optional[int]
    chain_vs_declared_delta: Optional[int]
    missing_count: int
    seal_broken_count: int
    replacement_charge_cents: int
    charge_reversed: bool
    reconciled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CustodyEvent(TypedDict):
    """Append-only custody entry — carries only id and created_at."""
    id: str
    material_lot_id: str
    previous_event_id: Optional[str]
    session_id: Optional[str]
    sequence_no: int
    event_type: str
    quantity: int
    sealed_count: int
    from_holder_type: str
    to_holder_type: str
    actor_user_id: str
    actor_role: str
    occurred_at: str
    chain_balance_after: int
    note: Optional[str]
    created_at: str


class IrregularityReport(TypedDict):
    id: str
    session_id: Optional[str]
    registration_id: Optional[str]
    reporter_proctor_id: Optional[str]
    material_lot_id: Optional[str]
    category: str
    severity: str
    narrative: str
    status: str
    disposition: Optional[str]
    return_count: int
    adjudicated_at: Optional[str]
    system_generated: bool
    created_at: str
    updated_at: str
    version: int


class ScoreAppeal(TypedDict):
    id: str
    registration_id: str
    reason_code: str
    narrative: str
    filed_by_role: str
    filed_by_user_id: str
    filed_at: str
    status: str
    corrected_raw_score: Optional[int]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
