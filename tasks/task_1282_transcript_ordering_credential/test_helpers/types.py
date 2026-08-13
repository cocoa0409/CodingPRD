"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class StudentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    GRADUATED = "GRADUATED"
    WITHDRAWN = "WITHDRAWN"
    DECEASED = "DECEASED"


class RecipientKind(str, Enum):
    ELECTRONIC_NETWORK = "ELECTRONIC_NETWORK"
    EMAIL_PDF = "EMAIL_PDF"
    PAPER_MAIL = "PAPER_MAIL"
    PICKUP = "PICKUP"


class HoldType(str, Enum):
    FINANCIAL = "FINANCIAL"
    LIBRARY = "LIBRARY"
    REGISTRAR = "REGISTRAR"
    DISCIPLINARY = "DISCIPLINARY"


class HoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class BlockingScope(str, Enum):
    OFFICIAL = "OFFICIAL"
    ALL = "ALL"
    NONE = "NONE"


class IdentityMethod(str, Enum):
    SSN_DOB = "SSN_DOB"
    GOVERNMENT_ID = "GOVERNMENT_ID"
    IN_PERSON = "IN_PERSON"
    NOTARIZED = "NOTARIZED"


class IdentityVerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class OrderKind(str, Enum):
    OFFICIAL = "OFFICIAL"
    UNOFFICIAL = "UNOFFICIAL"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IDENTITY_PENDING = "IDENTITY_PENDING"
    HOLD_CHECK = "HOLD_CHECK"
    READY_TO_FULFILL = "READY_TO_FULFILL"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    REISSUE_PENDING = "REISSUE_PENDING"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class OrderPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"
    WAIVED = "WAIVED"


class LineStatus(str, Enum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    BOUNCED = "BOUNCED"
    CANCELLED = "CANCELLED"


class RetrievalStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PULLED = "PULLED"
    DIGITIZED = "DIGITIZED"
    ATTACHED = "ATTACHED"
    FAILED = "FAILED"


class ConsentScope(str, Enum):
    ENROLLMENT_ONLY = "ENROLLMENT_ONLY"
    DEGREE_ONLY = "DEGREE_ONLY"
    FULL_RECORD = "FULL_RECORD"


class ConsentGrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class VerificationRequestStatus(str, Enum):
    RECEIVED = "RECEIVED"
    CONSENT_CHECK = "CONSENT_CHECK"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REPORTED = "REPORTED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"
    VOIDED = "VOIDED"
    FAILED = "FAILED"


class ReissueReason(str, Enum):
    NAME_CORRECTION = "NAME_CORRECTION"
    RECORD_CORRECTION = "RECORD_CORRECTION"
    DAMAGED_IN_MAIL = "DAMAGED_IN_MAIL"
    NEVER_RECEIVED = "NEVER_RECEIVED"
    WRONG_RECIPIENT = "WRONG_RECIPIENT"


class ReissueStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FULFILLED = "FULFILLED"


class BatchStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    TRANSMITTED = "TRANSMITTED"
    ACKED = "ACKED"
    FAILED = "FAILED"


class UserRole(str, Enum):
    STUDENT = "Student"
    REGISTRAR_OPERATOR = "RegistrarOperator"
    REGISTRAR_REVIEWER = "RegistrarReviewer"
    REGISTRAR_ADMIN = "RegistrarAdmin"
    BURSAR_OFFICE = "BursarOffice"
    LIBRARY_OFFICE = "LibraryOffice"
    ARCHIVE_CLERK = "ArchiveClerk"
    VERIFICATION_REQUESTER = "VerificationRequester"


class Student(TypedDict, total=False):
    id: str
    student_number: str
    full_name: str
    date_of_birth: str
    email: str
    status: str
    ferpa_restricted: bool
    archived_record_flag: bool
    created_at: str
    updated_at: str
    version: int


class StudentRecord(TypedDict, total=False):
    id: str
    student_id: str
    effective_term: str
    gpa_cents: int
    earned_credits: int
    degree_awarded: bool
    record_version: int
    is_current: bool
    created_at: str
    updated_at: str
    version: int


class Recipient(TypedDict, total=False):
    id: str
    kind: str
    display_name: str
    network_code: Optional[str]
    email_address: Optional[str]
    postal_address: Optional[str]
    active: bool
    created_at: str
    updated_at: str
    version: int


class Hold(TypedDict, total=False):
    id: str
    student_id: str
    hold_type: str
    status: str
    blocking_scope: str
    amount_cents: int
    placed_at: Optional[str]
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — carries ONLY id + created_at (no updated_at, no version)
class IdentityVerification(TypedDict, total=False):
    id: str
    student_id: str
    order_id: str
    method: str
    status: str
    verification_token: str
    expires_at: str
    created_at: str


class TranscriptOrder(TypedDict, total=False):
    id: str
    student_id: str
    order_kind: str
    fulfillment_status: str
    payment_status: str
    rush_requested: bool
    rush_qualified: bool
    quoted_fee_cents: int
    final_fee_cents: int
    submitted_at: Optional[str]
    cancelled_reason: Optional[str]
    reissue_of_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLineItem(TypedDict, total=False):
    id: str
    order_id: str
    recipient_id: str
    delivery_kind: str
    quantity: int
    unit_price_cents: int
    line_status: str
    tracking_ref: Optional[str]
    archived_retrieval_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ArchivedRecordRetrieval(TypedDict, total=False):
    id: str
    student_id: str
    requested_by_order_id: str
    retrieval_status: str
    sla_due_at: str
    digitized_record_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConsentGrant(TypedDict, total=False):
    id: str
    student_id: str
    grantee_name: str
    scope: str
    status: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class VerificationRequest(TypedDict, total=False):
    id: str
    requester_name: str
    subject_student_id: str
    consent_grant_id: Optional[str]
    scope: str
    status: str
    fee_cents: int
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeeSchedule(TypedDict, total=False):
    id: str
    code: str
    official_base_cents: int
    unofficial_base_cents: int
    paper_surcharge_cents: int
    pickup_surcharge_cents: int
    rush_flat_cents: int
    rush_multiplier_bp: int
    volume_tiers: list
    effective_from: str
    effective_to: Optional[str]
    active: bool
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    order_id: str
    amount_cents: int
    captured_cents: int
    refunded_cents: int
    status: str
    idempotency_key: str
    gateway_ref: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReissueRequest(TypedDict, total=False):
    id: str
    original_order_id: str
    reason: str
    status: str
    replacement_order_id: Optional[str]
    reviewed_by: Optional[str]
    fee_waived: bool
    created_at: str
    updated_at: str
    version: int


class ClearinghouseReportBatch(TypedDict, total=False):
    id: str
    report_period_start: str
    report_period_end: str
    status: str
    order_count: int
    verification_count: int
    transmitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only audit trail; carries ONLY id + created_at
class AuditEvent(TypedDict, total=False):
    id: str
    aggregate_type: str
    aggregate_id: str
    actor_role: str
    actor_id: Optional[str]
    action: str
    payload_hash: str
    recorded_at: str
    created_at: str
