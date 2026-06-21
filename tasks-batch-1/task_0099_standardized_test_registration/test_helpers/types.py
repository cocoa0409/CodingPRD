"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resources and lifecycle states described in the Standardized Test
Registration PRD. Every resource carries the full id/created_at/updated_at/version
set (PRD §2.4 — there are no immutable-after-creation resources in this domain).
"""
from enum import Enum
from typing import TypedDict, Optional, List, Dict


# ─── Role enum ────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    CANDIDATE = "Candidate"
    TEST_CENTER_ADMIN = "TestCenterAdmin"
    ACCOMMODATION_REVIEWER = "AccommodationReviewer"
    SCORE_OPS = "ScoreOps"


# ─── Status enums ─────────────────────────────────────────────────────────────

class RegistrationLifecycleStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class RegistrationScoreStatus(str, Enum):
    PENDING = "PENDING"
    SCORED = "SCORED"
    RELEASED = "RELEASED"
    CANCELLED_SCORE = "CANCELLED_SCORE"


class SeatKind(str, Enum):
    STANDARD = "STANDARD"
    ACCOMMODATED = "ACCOMMODATED"


class RegistrationStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ExamType(str, Enum):
    SAT = "SAT"
    ACT = "ACT"
    AP = "AP"


class AccommodationType(str, Enum):
    EXTENDED_TIME_50 = "EXTENDED_TIME_50"
    EXTENDED_TIME_100 = "EXTENDED_TIME_100"
    SEPARATE_ROOM = "SEPARATE_ROOM"
    BREAKS_ONLY = "BREAKS_ONLY"


class AccommodationBasis(str, Enum):
    PLAN_504 = "PLAN_504"
    IEP = "IEP"


class AccommodationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    MORE_INFO_NEEDED = "MORE_INFO_NEEDED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class PriorityTier(str, Enum):
    FEE_WAIVER = "FEE_WAIVER"
    SCHOOL_DAY = "SCHOOL_DAY"
    GENERAL = "GENERAL"


class StandbyStatus(str, Enum):
    WAITING = "WAITING"
    OFFERED = "OFFERED"
    CLAIMED = "CLAIMED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class RefundTier(str, Enum):
    FULL = "FULL"
    PARTIAL_75 = "PARTIAL_75"
    PARTIAL_50 = "PARTIAL_50"
    NONE = "NONE"


class ScoreSendStatus(str, Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"


class CLEPClaimStatus(str, Enum):
    PENDING = "PENDING"
    RECOGNIZED = "RECOGNIZED"
    REJECTED = "REJECTED"


class IDVerificationOutcome(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"


# ─── Entity TypedDicts (all carry id/created_at/updated_at/version) ────────────

class TestCenter(TypedDict):
    id: str
    name: str
    state_code: str
    room_capacity_standard: int
    room_capacity_accommodated: int
    net_revenue_cents: int
    created_at: str
    updated_at: str
    version: int


class TestSession(TypedDict):
    id: str
    test_center_id: str
    exam_type: str
    exam_subject: str
    test_date: str
    window_start_utc: str
    window_end_utc: str
    base_fee_cents: int
    standard_seats_reserved: int
    accommodated_seats_reserved: int
    registration_status: str
    created_at: str
    updated_at: str
    version: int


class Candidate(TypedDict):
    id: str
    legal_first_name: str
    legal_last_name: str
    date_of_birth: str
    home_state_code: str
    id_document_state_code: str
    has_active_504_iep: bool
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict):
    id: str
    test_session_id: str
    candidate_id: str
    accommodation_request_id: Optional[str]
    seat_kind: str
    allotted_minutes: int
    amount_paid_cents: int
    amount_refunded_cents: int
    refund_tier: Optional[str]
    lifecycle_status: str
    score_status: str
    is_standby_origin: bool
    created_at: str
    updated_at: str
    version: int


class AccommodationRequest(TypedDict):
    id: str
    candidate_id: str
    target_registration_id: str
    accommodation_type: str
    basis: str
    reviewer_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StandbyEntry(TypedDict):
    id: str
    test_session_id: str
    candidate_id: str
    priority_tier: str
    promoted_from_entry_id: Optional[str]
    promotion_score: float
    offered_registration_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ScoreReport(TypedDict):
    id: str
    registration_id: str
    candidate_id: str
    exam_type: str
    section_scores: Dict[str, int]
    sitting_composite: int
    super_composite: int
    created_at: str
    updated_at: str
    version: int


class ScoreSend(TypedDict):
    id: str
    registration_id: str
    recipient_code: str
    use_super_score: bool
    sent_composite: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CLEPClaim(TypedDict):
    id: str
    candidate_id: str
    clep_subject: str
    clep_scaled_score: int
    recommended_credit_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IDVerification(TypedDict):
    id: str
    registration_id: str
    presented_first_name: str
    presented_last_name: str
    presented_id_state_code: str
    cross_state: bool
    outcome: str
    created_at: str
    updated_at: str
    version: int
