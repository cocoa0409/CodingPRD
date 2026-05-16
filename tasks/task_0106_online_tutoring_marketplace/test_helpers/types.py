"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 distinguishes two common-fields shapes:

- Entities with the "four common properties" (id, created_at, updated_at,
  version): Tutor, Student, Parent, Credential, SubjectTag, Session,
  RefundDispute.
- Bookkeeping records that carry ONLY id and created_at: ParentChildLink,
  PayoutBatch.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    TUTOR = "Tutor"
    STUDENT = "Student"
    PARENT = "Parent"
    CREDENTIAL_VERIFIER = "CredentialVerifier"
    PLATFORM_ARBITER = "PlatformArbiter"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Status enums — PRD §3 (state machines)
# ---------------------------------------------------------------------------
class TutorVerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    PENDING_REVIEW = "PENDING_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class StudentAccountType(str, Enum):
    ADULT = "ADULT"
    MINOR = "MINOR"


class CredentialType(str, Enum):
    GOVERNMENT_ID = "GOVERNMENT_ID"
    DEGREE = "DEGREE"
    TEACHING_LICENSE = "TEACHING_LICENSE"
    BACKGROUND_CHECK = "BACKGROUND_CHECK"


class CredentialStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class SubjectTagStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REMOVED = "REMOVED"


class ProficiencyLevel(str, Enum):
    BEGINNER = "BEGINNER"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"
    EXPERT = "EXPERT"


class SessionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED_BY_STUDENT = "CANCELLED_BY_STUDENT"
    CANCELLED_BY_TUTOR = "CANCELLED_BY_TUTOR"
    DISPUTED = "DISPUTED"
    REFUNDED = "REFUNDED"
    SETTLED = "SETTLED"


class RefundDisputeStatus(str, Enum):
    OPEN = "OPEN"
    TUTOR_RESPONDED = "TUTOR_RESPONDED"
    COUNTER_PROPOSED = "COUNTER_PROPOSED"
    ARBITRATION = "ARBITRATION"
    RESOLVED_REFUND = "RESOLVED_REFUND"
    RESOLVED_DENY = "RESOLVED_DENY"
    WITHDRAWN = "WITHDRAWN"


class DisputeReasonCode(str, Enum):
    TUTOR_NO_SHOW = "TUTOR_NO_SHOW"
    QUALITY_ISSUE = "QUALITY_ISSUE"
    TECHNICAL_FAILURE = "TECHNICAL_FAILURE"
    OTHER = "OTHER"


class ParentChildLinkStatus(str, Enum):
    PENDING_PARENT_APPROVAL = "PENDING_PARENT_APPROVAL"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class PayoutBatchStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PAID = "PAID"
    REVERSED = "REVERSED"


class ArbitrationDecision(str, Enum):
    REFUND = "REFUND"
    DENY = "DENY"


# ---------------------------------------------------------------------------
# Entities carrying the four common fields (id, created_at, updated_at, version)
# ---------------------------------------------------------------------------
class Tutor(TypedDict, total=False):
    id: str
    display_name: str
    email: str
    hourly_rate_cents: int
    trial_rate_cents: int
    verification_status: str
    subject_tags: List[str]
    payout_balance_cents: int
    lifetime_completed_sessions: int
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict, total=False):
    id: str
    display_name: str
    email: str
    account_type: str
    parent_id: Optional[str]
    credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Parent(TypedDict, total=False):
    id: str
    display_name: str
    email: str
    managed_child_count: int
    created_at: str
    updated_at: str
    version: int


class Credential(TypedDict, total=False):
    id: str
    tutor_id: str
    credential_type: str
    document_ref: str
    status: str
    reviewed_by: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubjectTag(TypedDict, total=False):
    id: str
    tutor_id: str
    subject_code: str
    proficiency_level: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict, total=False):
    id: str
    tutor_id: str
    student_id: str
    subject_code: str
    start_at: str
    end_at: str
    is_trial: bool
    apply_credits: bool
    status: str
    gross_price_cents: int
    credit_applied_cents: int
    charged_amount_cents: int
    provisional_commission_cents: int
    final_commission_cents: int
    actual_gross_cents: int
    arbitration_refund_cents: int
    tutor_payout_cents: int
    adjusted_minutes: Optional[int]
    cancellation_fee_cents: int
    refund_to_student_cents: int
    created_at: str
    updated_at: str
    version: int


class RefundDispute(TypedDict, total=False):
    id: str
    session_id: str
    opened_by_role: str
    opened_by_user_id: str
    reason_code: str
    requested_amount_cents: int
    status: str
    round_count: int
    arbitrated_by: Optional[str]
    resolved_refund_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Bookkeeping records — id + created_at ONLY (no updated_at, no version)
# PRD §2.4: "The ParentChildLink and PayoutBatch entities are bookkeeping
# records and carry only id and created_at; they have neither updated_at
# nor version."
# ---------------------------------------------------------------------------
class ParentChildLink(TypedDict, total=False):
    id: str
    parent_id: str
    student_id: str
    link_status: str
    approved_at: Optional[str]
    created_at: str


class PayoutBatch(TypedDict, total=False):
    id: str
    tutor_id: str
    status: str
    amount_cents: int
    session_ids: List[str]
    requested_by: str
    created_at: str


__all__ = [
    "UserRole",
    "TutorVerificationStatus",
    "StudentAccountType",
    "CredentialType",
    "CredentialStatus",
    "SubjectTagStatus",
    "ProficiencyLevel",
    "SessionStatus",
    "RefundDisputeStatus",
    "DisputeReasonCode",
    "ParentChildLinkStatus",
    "PayoutBatchStatus",
    "ArbitrationDecision",
    "Tutor",
    "Student",
    "Parent",
    "Credential",
    "SubjectTag",
    "Session",
    "RefundDispute",
    "ParentChildLink",
    "PayoutBatch",
]
