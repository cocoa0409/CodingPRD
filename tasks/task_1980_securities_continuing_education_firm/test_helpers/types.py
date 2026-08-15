"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------

class RegistrationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE_CE = "INACTIVE_CE"
    TERMINATED = "TERMINATED"


class RoleTier(str, Enum):
    RR = "RR"
    PRINCIPAL = "PRINCIPAL"


class ContentStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RETIRED = "RETIRED"


class CeCategory(str, Enum):
    REGULATORY_ELEMENT = "REGULATORY_ELEMENT"
    FIRM_ELEMENT = "FIRM_ELEMENT"
    PRODUCT = "PRODUCT"
    STATE_INSURANCE = "STATE_INSURANCE"


class DeliveryFormat(str, Enum):
    ELEARNING = "ELEARNING"
    INSTRUCTOR_LED = "INSTRUCTOR_LED"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    OVERDUE = "OVERDUE"
    LAPSED = "LAPSED"
    COMPLETED = "COMPLETED"


class PlanStatus(str, Enum):
    NEEDS_ANALYSIS = "NEEDS_ANALYSIS"
    PLAN_PUBLISHED = "PLAN_PUBLISHED"
    CLOSED = "CLOSED"
    SUPERSEDED = "SUPERSEDED"


class AttestationStatus(str, Enum):
    PENDING = "PENDING"
    ATTESTED = "ATTESTED"
    VOIDED = "VOIDED"


class ProductStatus(str, Enum):
    PROPOSED = "PROPOSED"
    LAUNCHED = "LAUNCHED"
    WITHDRAWN = "WITHDRAWN"


class CertStatus(str, Enum):
    PENDING_TRAINING = "PENDING_TRAINING"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"


class SuspendedReason(str, Enum):
    REGISTRATION_INACTIVE = "REGISTRATION_INACTIVE"
    REGISTRATION_TERMINATED = "REGISTRATION_TERMINATED"
    CONTENT_RETIRED = "CONTENT_RETIRED"
    PRODUCT_WITHDRAWN = "PRODUCT_WITHDRAWN"
    TRAINING_VOIDED = "TRAINING_VOIDED"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"


class AuditEventType(str, Enum):
    CONTENT_APPROVED = "CONTENT_APPROVED"
    CONTENT_REJECTED = "CONTENT_REJECTED"
    CONTENT_RETIRED = "CONTENT_RETIRED"
    ENROLLMENT_COMPLETED = "ENROLLMENT_COMPLETED"
    ENROLLMENT_VOIDED = "ENROLLMENT_VOIDED"
    ATTESTATION_ATTESTED = "ATTESTATION_ATTESTED"
    ATTESTATION_VOIDED = "ATTESTATION_VOIDED"
    ASSIGNMENT_LAPSED = "ASSIGNMENT_LAPSED"
    ASSIGNMENT_COMPLETED = "ASSIGNMENT_COMPLETED"
    REGISTRATION_STATUS_CHANGED = "REGISTRATION_STATUS_CHANGED"
    PRODUCT_LAUNCHED = "PRODUCT_LAUNCHED"
    CERTIFICATION_STATUS_CHANGED = "CERTIFICATION_STATUS_CHANGED"
    ENFORCEMENT_SWEEP_RUN = "ENFORCEMENT_SWEEP_RUN"
    PLAN_PUBLISHED = "PLAN_PUBLISHED"
    PLAN_CLOSED = "PLAN_CLOSED"
    PLAN_REOPENED = "PLAN_REOPENED"


class UserRole(str, Enum):
    TRAINING_ADMIN = "TrainingAdmin"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    REGISTERED_REP = "RegisteredRep"
    AUDITOR = "Auditor"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.5 common fields: id, created_at, updated_at,
# version — except the append-only audit log which carries id+created_at only)
# ---------------------------------------------------------------------------

class Representative(TypedDict, total=False):
    id: str
    crd_number: str
    full_name: str
    email: str
    role_tier: str
    insurance_licensed: bool
    resident_state_code: str
    prior_year_excess_hours: float
    registration_status: str
    created_at: str
    updated_at: str
    version: int


class TrainingContent(TypedDict, total=False):
    id: str
    code: str
    title: str
    ce_category: str
    delivery_format: str
    credit_hours: float
    min_passing_score: int
    content_status: str
    author_user_id: str
    approved_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CourseSession(TypedDict, total=False):
    id: str
    content_id: str
    room_name: str
    start_at: str
    end_at: str
    capacity: int
    session_status: str
    available_seats: int
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    rep_id: str
    content_id: str
    session_id: Optional[str]
    enrollment_status: str
    attempt_count: int
    last_score: Optional[int]
    expires_at: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RegulatoryAssignment(TypedDict, total=False):
    id: str
    rep_id: str
    cycle_year: int
    assignment_status: str
    due_at: str
    lapse_after: str
    enrollment_id: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FirmElementPlan(TypedDict, total=False):
    id: str
    rep_id: str
    plan_year: int
    plan_status: str
    needs_analysis_document_ref: Optional[str]
    needs_analysis_notes: Optional[str]
    needs_analysis_completed_at: Optional[str]
    required_hours: Optional[float]
    certified_hours: float
    projected_hours: float
    published_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AnnualAttestation(TypedDict, total=False):
    id: str
    rep_id: str
    plan_id: str
    attestation_status: str
    attestation_statement: Optional[str]
    attested_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductOffering(TypedDict, total=False):
    id: str
    product_code: str
    name: str
    required_training_content_id: str
    product_status: str
    launched_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductCertification(TypedDict, total=False):
    id: str
    rep_id: str
    product_id: str
    enrollment_id: Optional[str]
    cert_status: str
    certified_at: Optional[str]
    suspended_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StateCELicense(TypedDict, total=False):
    id: str
    rep_id: str
    state_code: str
    required_hours: float
    period_start: str
    period_end: str
    license_status: str
    earned_hours_strict: float
    earned_hours_effective: float
    reported_hours: float
    carried_excess_hours: float
    created_at: str
    updated_at: str
    version: int


class TrainingBlackoutWindow(TypedDict, total=False):
    id: str
    label: str
    start_at: str
    end_at: str
    created_at: str
    updated_at: str
    version: int


class AuditEvent(TypedDict, total=False):
    # Append-only evidence log (PRD §2.5/§2.9): id + created_at only,
    # NO updated_at and NO version.
    id: str
    event_type: str
    entity_type: str
    entity_id: str
    actor_user_id: str
    actor_role: str
    detail: str
    created_at: str
