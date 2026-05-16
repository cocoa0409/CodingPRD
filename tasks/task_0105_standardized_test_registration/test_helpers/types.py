"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 sets the canonical envelope rules:
  - Mutable entities (TestEvent, TestCenter, TestCenterCapacity, Candidate,
    Registration, AccommodationRequest, IDVerification) carry
    id + created_at + updated_at + version.
  - Append-only / immutable entities (ScoreReport, CLEPCreditAward,
    RefundTransaction) carry only id + created_at — neither updated_at
    nor version is present.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CANDIDATE = "Candidate"
    PROCTOR = "Proctor"
    ACCOMMODATIONS_OFFICER = "AccommodationsOfficer"
    REGISTRAR = "Registrar"
    CREDITS_OFFICER = "CreditsOfficer"


# ---------------------------------------------------------------------------
# TestEvent / TestCenter / TestCenterCapacity enums (PRD §3.1, §3.2)
# ---------------------------------------------------------------------------
class TestType(str, Enum):
    SAT = "SAT"
    ACT = "ACT"
    AP = "AP"
    CLEP = "CLEP"


class TestEventStatus(str, Enum):
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    REGISTRATION_CLOSED = "REGISTRATION_CLOSED"
    SCORES_PENDING = "SCORES_PENDING"
    COMPLETED = "COMPLETED"


class TestCenterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


# ---------------------------------------------------------------------------
# Registration enums (PRD §3.4, §3.8)
# ---------------------------------------------------------------------------
class RegistrationStatus(str, Enum):
    STANDBY = "STANDBY"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    NO_SHOW = "NO_SHOW"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RegistrationChannel(str, Enum):
    SELF_INITIATED = "SELF_INITIATED"
    OFFICIAL_CANCELLATION = "OFFICIAL_CANCELLATION"


# ---------------------------------------------------------------------------
# IDVerification enums (PRD §3.5)
# ---------------------------------------------------------------------------
class IDDocumentType(str, Enum):
    DRIVERS_LICENSE = "DRIVERS_LICENSE"
    STATE_ID = "STATE_ID"
    PASSPORT = "PASSPORT"
    SCHOOL_ID_WITH_PHOTO = "SCHOOL_ID_WITH_PHOTO"


class IDVerificationStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    DOCS_SUBMITTED = "DOCS_SUBMITTED"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# AccommodationRequest enums (PRD §3.6)
# ---------------------------------------------------------------------------
class AccommodationKind(str, Enum):
    EXTENDED_TIME_50 = "EXTENDED_TIME_50"
    EXTENDED_TIME_100 = "EXTENDED_TIME_100"
    BREAKS_EXTENDED = "BREAKS_EXTENDED"
    READER = "READER"
    SCRIBE = "SCRIBE"
    LARGE_PRINT = "LARGE_PRINT"


class AccommodationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_MORE_INFO = "NEEDS_MORE_INFO"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


# ---------------------------------------------------------------------------
# ScoreReport / SuperScore enums (PRD §3.9)
# ---------------------------------------------------------------------------
class ScoreReportType(str, Enum):
    OFFICIAL = "OFFICIAL"
    RESCORED = "RESCORED"


class SuperScoreReportingMode(str, Enum):
    COLLEGE_BOARD_OFFICIAL = "COLLEGE_BOARD_OFFICIAL"
    INSTITUTIONAL_SUBMISSION = "INSTITUTIONAL_SUBMISSION"


# ---------------------------------------------------------------------------
# CLEPCreditAward / RefundTransaction enums (PRD §3.8, §3.10)
# ---------------------------------------------------------------------------
class CLEPCreditStatus(str, Enum):
    AWARDED = "AWARDED"
    DENIED = "DENIED"


class RefundTierLabel(str, Enum):
    FULL = "FULL"
    PARTIAL_75 = "PARTIAL_75"
    PARTIAL_50 = "PARTIAL_50"
    NONE = "NONE"


# ---------------------------------------------------------------------------
# Mutable entities (PRD §2.4) — id + created_at + updated_at + version
# ---------------------------------------------------------------------------
class TestEvent(TypedDict, total=False):
    id: str
    test_type: str
    form_code: str
    subject: Optional[str]
    test_date: str
    registration_deadline: str
    late_registration_deadline: str
    score_release_date: str
    base_fee_cents: int
    late_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TestCenter(TypedDict, total=False):
    id: str
    name: str
    address: str
    state_code: str
    timezone: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TestCenterCapacity(TypedDict, total=False):
    id: str
    test_event_id: str
    test_center_id: str
    total_capacity: int
    accommodation_capacity: int
    confirmed_seats_used: int
    accommodation_seats_used: int
    standby_seats_pending: int
    available_seats: int
    created_at: str
    updated_at: str
    version: int


class Candidate(TypedDict, total=False):
    id: str
    legal_name: str
    email: str
    date_of_birth: str
    home_state_code: str
    has_iep_or_504: bool
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict, total=False):
    id: str
    candidate_id: str
    test_event_id: str
    test_center_id: str
    status: str
    registered_at: str
    registration_channel: str
    accommodation_required: bool
    base_fee_cents_charged: int
    late_fee_cents_charged: int
    accommodation_fee_cents_charged: int
    amount_charged_cents: int
    amount_refunded_cents: int
    amount_retained_cents: int
    standby_promotion_eligibility_at: Optional[str]
    locked_accommodation_request_version: Optional[int]
    created_at: str
    updated_at: str
    version: int


class AccommodationRequest(TypedDict, total=False):
    id: str
    candidate_id: str
    test_event_id: str
    requested_accommodations: List[str]
    supporting_documents: List[str]
    status: str
    reviewer_user_id: Optional[str]
    submission_deadline_at: str
    review_deadline_at: str
    created_at: str
    updated_at: str
    version: int


class IDVerification(TypedDict, total=False):
    id: str
    registration_id: str
    id_document_type: str
    issuing_state_code: Optional[str]
    id_expires_on: str
    status: str
    rejection_reason: Optional[str]
    cross_state_override_granted: bool
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities (PRD §2.4) — id + created_at only
# ---------------------------------------------------------------------------
class ScoreReport(TypedDict, total=False):
    id: str
    registration_id: str
    section_scores: dict
    total_score: int
    report_type: str
    created_at: str


class CLEPCreditAward(TypedDict, total=False):
    id: str
    score_report_id: str
    candidate_id: str
    credit_status: str
    credit_units: int
    posted_by_user_id: str
    created_at: str


class RefundTransaction(TypedDict, total=False):
    id: str
    registration_id: str
    amount_cents: int
    tier_label: str
    refund_channel: str
    created_at: str


__all__ = [
    "UserRole",
    "TestType",
    "TestEventStatus",
    "TestCenterStatus",
    "RegistrationStatus",
    "RegistrationChannel",
    "IDDocumentType",
    "IDVerificationStatus",
    "AccommodationKind",
    "AccommodationStatus",
    "ScoreReportType",
    "SuperScoreReportingMode",
    "CLEPCreditStatus",
    "RefundTierLabel",
    "TestEvent",
    "TestCenter",
    "TestCenterCapacity",
    "Candidate",
    "Registration",
    "AccommodationRequest",
    "IDVerification",
    "ScoreReport",
    "CLEPCreditAward",
    "RefundTransaction",
]
