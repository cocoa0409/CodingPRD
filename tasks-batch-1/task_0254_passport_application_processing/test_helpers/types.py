"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Passport Application Processing PRD. Status enums mirror the
lifecycle states; TypedDicts list the fields each entity exposes on its response.
Photo and ApplicationStatusEvent are append-only (id + created_at only).
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Role enum ────────────────────────────────────────
class UserRole(str, Enum):
    APPLICANT = "Applicant"
    ACCEPTANCE_AGENT = "AcceptanceAgent"
    ADJUDICATOR = "Adjudicator"


# ─── Status / enum vocabularies ───────────────────────
class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_VERIFICATION = "IN_VERIFICATION"
    REVIEW_HOLD = "REVIEW_HOLD"
    ADJUDICATING = "ADJUDICATING"
    APPROVED = "APPROVED"
    ISSUED = "ISSUED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class NameChangeStatus(str, Enum):
    NONE = "NONE"
    PENDING_EVIDENCE = "PENDING_EVIDENCE"
    EVIDENCE_VERIFIED = "EVIDENCE_VERIFIED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ApplicationType(str, Enum):
    NEW = "NEW"
    RENEWAL = "RENEWAL"
    MINOR = "MINOR"


class ProductType(str, Enum):
    BOOK = "BOOK"
    CARD = "CARD"
    BOOK_AND_CARD = "BOOK_AND_CARD"


class ServiceLevel(str, Enum):
    ROUTINE = "ROUTINE"
    EXPEDITE = "EXPEDITE"


class DocCategory(str, Enum):
    IDENTITY = "IDENTITY"
    CITIZENSHIP = "CITIZENSHIP"
    GUARDIAN_CONSENT = "GUARDIAN_CONSENT"
    NAME_CHANGE_EVIDENCE = "NAME_CHANGE_EVIDENCE"


class DocVerificationStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class PhotoValidationResult(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class FeePaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class ResourceKind(str, Enum):
    ACCEPTANCE_FACILITY = "ACCEPTANCE_FACILITY"
    URGENT_TRAVEL_COUNTER = "URGENT_TRAVEL_COUNTER"


class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AdjudicationDecisionType(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    RETURN_FOR_REVIEW = "RETURN_FOR_REVIEW"


# ─── Entities with full common_fields (id/created_at/updated_at/version) ──
class Applicant(TypedDict, total=False):
    id: str
    full_legal_name: str
    date_of_birth: str
    email: str
    is_minor: bool
    verification_risk_score: float
    guardian_applicant_id: Optional[str]
    total_fees_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    applicant_id: str
    application_type: str
    product_type: str
    service_level: str
    applicant_is_minor: bool
    requires_execution: bool
    name_change_requested: bool
    prior_name: Optional[str]
    name_change_status: str
    status: str
    urgent_travel: bool
    submitted_at: Optional[str]
    verification_completed_at: Optional[str]
    target_completion_date: Optional[str]
    assigned_acceptance_agent_id: Optional[str]
    adjudicator_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AcceptanceAgent(TypedDict, total=False):
    id: str
    name: str
    badge_number: str
    facility_id: str
    created_at: str
    updated_at: str
    version: int


class Adjudicator(TypedDict, total=False):
    id: str
    name: str
    passport_office_code: str
    created_at: str
    updated_at: str
    version: int


class SupportingDocument(TypedDict, total=False):
    id: str
    application_id: str
    doc_category: str
    doc_kind: str
    declared_quality: int
    verification_status: str
    reviewed_by_agent_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeeAssessment(TypedDict, total=False):
    id: str
    application_id: str
    base_fee_cents: int
    execution_fee_cents: int
    expedite_fee_cents: int
    urgent_surcharge_cents: int
    one_day_delivery_cents: int
    one_day_delivery: bool
    total_due_cents: int
    amount_paid_cents: int
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict, total=False):
    id: str
    application_id: str
    resource_kind: str
    facility_id: Optional[str]
    counter_id: Optional[str]
    start_utc: str
    end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AcceptanceFacility(TypedDict, total=False):
    id: str
    name: str
    state_code: str
    created_at: str
    updated_at: str
    version: int


class UrgentTravelCounter(TypedDict, total=False):
    id: str
    name: str
    cleanup_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class AdjudicationDecision(TypedDict, total=False):
    id: str
    application_id: str
    adjudicator_id: str
    decision: str
    reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── Append-only entities (id + created_at only, NO updated_at/version) ──
class Photo(TypedDict, total=False):
    id: str
    application_id: str
    width_px: int
    height_px: int
    head_height_fraction: float
    background_is_white: bool
    validation_result: str
    failure_reasons: List[str]
    created_at: str


class ApplicationStatusEvent(TypedDict, total=False):
    id: str
    application_id: str
    from_status: Optional[str]
    to_status: str
    actor_role: str
    occurred_at: str
    created_at: str
