"""Domain types for the Continuing Ed Noncredit API: status enums, role enum, entity shapes."""

from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    REGISTRAR = "Registrar"
    LEARNER = "Learner"
    INSTRUCTOR = "Instructor"
    CORPORATE_SPONSOR = "CorporateSponsor"
    ANONYMOUS = "Anonymous"


class CourseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class DeliveryMode(str, Enum):
    IN_PERSON = "IN_PERSON"
    ONLINE_SYNC = "ONLINE_SYNC"
    ONLINE_ASYNC = "ONLINE_ASYNC"


class OfferingStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    WAITLIST_ONLY = "WAITLIST_ONLY"
    CENSUS_LOCKED = "CENSUS_LOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SchedulingMode(str, Enum):
    TERM = "TERM"
    ROLLING = "ROLLING"


class CancellationReason(str, Enum):
    MIN_ENROLLMENT_NOT_MET = "MIN_ENROLLMENT_NOT_MET"
    ADMIN_DISCRETION = "ADMIN_DISCRETION"


class MarketingStatus(str, Enum):
    SUBSCRIBED = "SUBSCRIBED"
    UNSUBSCRIBED = "UNSUBSCRIBED"


class LoyaltyTier(str, Enum):
    NEW = "NEW"
    RETURNING = "RETURNING"
    LOYAL = "LOYAL"
    CHAMPION = "CHAMPION"


class CredentialLevel(str, Enum):
    ADJUNCT = "ADJUNCT"
    SENIOR = "SENIOR"
    MASTER = "MASTER"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class VoucherStatus(str, Enum):
    ISSUED = "ISSUED"
    ASSIGNED = "ASSIGNED"
    PARTIALLY_REDEEMED = "PARTIALLY_REDEEMED"
    EXHAUSTED = "EXHAUSTED"
    VOIDED = "VOIDED"


class EnrollmentStatus(str, Enum):
    PENDING = "PENDING"
    ENROLLED = "ENROLLED"
    WAITLISTED = "WAITLISTED"
    WITHDRAWN = "WITHDRAWN"
    TRANSFERRED_OUT = "TRANSFERRED_OUT"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    VOUCHER_COMMITTED = "VOUCHER_COMMITTED"
    PAID = "PAID"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"


class PaymentMethod(str, Enum):
    SELF_PAY = "SELF_PAY"
    VOUCHER = "VOUCHER"


class ContractStatus(str, Enum):
    OFFERED = "OFFERED"
    SIGNED = "SIGNED"
    ACTIVE = "ACTIVE"
    SETTLED = "SETTLED"
    DECLINED = "DECLINED"
    TERMINATED_NO_FAULT = "TERMINATED_NO_FAULT"


class PayBasis(str, Enum):
    CENSUS_LOCKED = "CENSUS_LOCKED"
    FINAL_COMPLETION = "FINAL_COMPLETION"


class CompletionRecordStatus(str, Enum):
    ISSUED = "ISSUED"
    REVOKED = "REVOKED"


class PetitionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class RequestType(str, Enum):
    REFUND = "REFUND"
    TRANSFER = "TRANSFER"


class RefundBasis(str, Enum):
    POLICY_SCHEDULE = "POLICY_SCHEDULE"
    PRO_RATA_ATTENDANCE = "PRO_RATA_ATTENDANCE"


class RefundTransferStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    REFUND_APPROVED = "REFUND_APPROVED"
    TRANSFER_APPROVED = "TRANSFER_APPROVED"
    DENIED = "DENIED"
    SETTLED = "SETTLED"


class MarketingSegment(str, Enum):
    PROSPECT = "PROSPECT"
    FIRST_TIME = "FIRST_TIME"
    REPEAT = "REPEAT"
    CORPORATE_SPONSORED = "CORPORATE_SPONSORED"
    LAPSED = "LAPSED"


class MembershipState(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


# --- Entity shapes -------------------------------------------------------
# Every resource carries id + created_at. Most also carry updated_at + version.
# CplCitation is the sole exception: it carries only id and created_at.


class Course(TypedDict):
    id: str
    course_code: str
    title: str
    ceu_units: float
    contact_hours: float
    list_price_cents: int
    delivery_mode: str
    prerequisite_course_id: Optional[str]
    cpl_credit_units: float
    status: str
    active_offering_count: int
    created_at: str
    updated_at: str
    version: int


class Offering(TypedDict):
    id: str
    course_id: str
    scheduling_mode: str
    term_code: Optional[str]
    start_date: str
    end_date: str
    census_at: str
    session_count: int
    min_enrollment: int
    max_enrollment: int
    tuition_cents: int
    status: str
    cancellation_reason: Optional[str]
    confirmed_enrollment_count: int
    paid_enrollment_count: int
    waitlist_count: int
    net_program_revenue_cents: int
    created_at: str
    updated_at: str
    version: int


class Learner(TypedDict):
    id: str
    email: str
    full_name: str
    marketing_status: str
    lifetime_completed_count: int
    lifetime_ceu_total: float
    loyalty_tier: str
    created_at: str
    updated_at: str
    version: int


class Instructor(TypedDict):
    id: str
    email: str
    full_name: str
    credential_level: str
    active_contract_count: int
    created_at: str
    updated_at: str
    version: int


class CorporateAccount(TypedDict):
    id: str
    org_name: str
    billing_email: str
    status: str
    funded_cents: int
    available_cents: int
    unallocated_voucher_cents: int
    committed_cents: int
    consumed_cents: int
    created_at: str
    updated_at: str
    version: int


class Voucher(TypedDict):
    id: str
    corporate_account_id: str
    assigned_learner_id: Optional[str]
    face_value_cents: int
    remaining_cents: int
    committed_cents: int
    consumed_cents: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict):
    id: str
    offering_id: str
    learner_id: str
    voucher_id: Optional[str]
    transferred_to_registration_id: Optional[str]
    enrollment_status: str
    payment_status: str
    list_tuition_cents: int
    loyalty_discount_cents: int
    processing_fee_cents: int
    total_due_cents: int
    amount_paid_cents: int
    amount_refunded_cents: int
    sessions_attended: int
    total_sessions: int
    enrolled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InstructorContract(TypedDict):
    id: str
    offering_id: str
    instructor_id: str
    base_stipend_cents: int
    per_enrollment_cents: int
    enrollment_cap_for_pay: int
    pay_basis: str
    status: str
    census_headcount: Optional[int]
    final_headcount: Optional[int]
    settled_pay_cents: Optional[int]
    kill_fee_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CompletionRecord(TypedDict):
    id: str
    registration_id: str
    learner_id: str
    ceu_awarded: float
    attendance_ratio: float
    certificate_number: str
    issued_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CplPetition(TypedDict):
    id: str
    learner_id: str
    target_course_id: str
    status: str
    revision_round: int
    assessed_by_user_id: Optional[str]
    claimed_ceu_total: Optional[float]
    awarded_credit_units: Optional[float]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CplCitation(TypedDict):
    """Citations do not participate in versioning: only id and created_at."""

    id: str
    petition_id: str
    completion_record_id: str
    weight: float
    created_at: str


class RefundTransferRequest(TypedDict):
    id: str
    registration_id: str
    target_offering_id: Optional[str]
    request_type: str
    refund_basis: str
    days_before_start: int
    computed_refund_cents: int
    status: str
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MarketingMembership(TypedDict):
    id: str
    learner_id: str
    segment: str
    state: str
    recomputed_at: str
    created_at: str
    updated_at: str
    version: int
