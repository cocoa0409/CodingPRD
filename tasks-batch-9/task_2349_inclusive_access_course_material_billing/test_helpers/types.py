"""Domain types for the Inclusive Access Course Material Billing API.

Status enums, role enum and entity TypedDicts, all named exactly as the PRD
names them.  Per PRD §2.5 every resource carries ``id`` and ``created_at``;
all resources *except* ``LedgerEntry`` additionally carry ``updated_at`` and
``version``.  ``LedgerEntry`` is append-only and therefore carries only ``id``
and ``created_at``.
"""

from enum import Enum
from typing import Optional, TypedDict


# ─── Roles (PRD §2.1) ────────────────────────────────────────────────────────

class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    FACULTY = "Faculty"
    REGISTRAR = "Registrar"
    BURSAR_OFFICER = "BursarOfficer"
    STUDENT = "Student"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# ─── Status enums ────────────────────────────────────────────────────────────

class AcademicTermStatus(str, Enum):
    PLANNING = "PLANNING"
    OPEN = "OPEN"
    BILLING_LOCKED = "BILLING_LOCKED"
    CLOSED = "CLOSED"


class StudentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class PublisherAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ReconciliationStatus(str, Enum):
    """The PublisherAgreement's second, independent state dimension (PRD §2.8)."""
    NOT_STARTED = "NOT_STARTED"
    COMPUTED = "COMPUTED"
    STALE = "STALE"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"


class CourseMaterialTitleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class TitleFormat(str, Enum):
    DIGITAL = "DIGITAL"
    DIGITAL_PLUS_PRINT = "DIGITAL_PLUS_PRINT"


class SectionIaStatus(str, Enum):
    NOT_FLAGGED = "NOT_FLAGGED"
    FLAGGED = "FLAGGED"
    BILLED = "BILLED"
    AT_RISK = "AT_RISK"


class AdoptionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CHANGE_REQUESTED = "CHANGE_REQUESTED"
    APPROVED = "APPROVED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    DROPPED = "DROPPED"


class RegistrationType(str, Enum):
    REGULAR = "REGULAR"
    LATE = "LATE"


class BillingStatus(str, Enum):
    """StudentCharge money dimension (PRD §2.8)."""
    PENDING = "PENDING"
    POSTED = "POSTED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"
    REBILLED = "REBILLED"


class AccessStatus(str, Enum):
    """StudentCharge LMS entitlement dimension (PRD §2.8)."""
    NOT_PROVISIONED = "NOT_PROVISIONED"
    PROVISIONED = "PROVISIONED"
    REVOKED = "REVOKED"
    RESTORED = "RESTORED"


class LedgerEntryType(str, Enum):
    CHARGE = "CHARGE"
    REFUND = "REFUND"
    REBILL_CREDIT = "REBILL_CREDIT"
    REBILL_CHARGE = "REBILL_CHARGE"


class LedgerReasonCode(str, Enum):
    INITIAL_POST = "INITIAL_POST"
    LATE_REGISTRATION_POST = "LATE_REGISTRATION_POST"
    OPT_OUT_REFUND = "OPT_OUT_REFUND"
    DROP_PRORATION = "DROP_PRORATION"
    TITLE_CHANGE_REBILL = "TITLE_CHANGE_REBILL"
    OPT_IN_RECHARGE = "OPT_IN_RECHARGE"


class OptOutRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    RESCINDED = "RESCINDED"


class OptOutReasonCode(str, Enum):
    OWNS_COPY = "OWNS_COPY"
    COST = "COST"
    ALTERNATE_SOURCE = "ALTERNATE_SOURCE"
    OTHER = "OTHER"


class ReconciliationRunStatus(str, Enum):
    COMPUTED = "COMPUTED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    SUPERSEDED = "SUPERSEDED"


class ReconciliationMethod(str, Enum):
    ENROLLMENT_SNAPSHOT = "ENROLLMENT_SNAPSHOT"
    ACCESS_DAYS_WEIGHTED = "ACCESS_DAYS_WEIGHTED"


class DisclosureReportStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    PUBLISHED = "PUBLISHED"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"
    NOT_APPLICABLE = "NOT_APPLICABLE"


# ─── Entity TypedDicts ───────────────────────────────────────────────────────

class AcademicTerm(TypedDict):
    id: str
    code: str
    name: str
    term_start_date: str
    term_end_date: str
    total_term_days: int
    instructional_days: int
    census_date: str
    add_drop_deadline: str
    late_registration_cutoff_date: str
    adoption_deadline_date: str
    disclosure_deadline_date: str
    opt_out_window_days: int
    status: str
    ia_section_count: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    external_id: str
    full_name: str
    email: str
    program_code: str
    status: str
    bursar_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class PublisherAgreement(TypedDict):
    id: str
    publisher_name: str
    agreement_code: str
    effective_from: str
    effective_to: str
    admin_fee_pct: float
    bookstore_margin_pct: float
    price_floor_cents: int
    max_list_price_pct: float
    rebate_threshold_cents: int
    rebate_pct: float
    status: str
    reconciliation_status: str
    settled_amount_cents: Optional[int]
    suspend_reason_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CourseMaterialTitle(TypedDict):
    id: str
    agreement_id: str
    isbn: str
    title: str
    list_price_cents: int
    format: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PricingTier(TypedDict):
    id: str
    title_id: str
    min_enrollment: int
    max_enrollment: Optional[int]
    per_student_price_cents: int
    created_at: str
    updated_at: str
    version: int


class CourseSection(TypedDict):
    id: str
    term_id: str
    subject_code: str
    catalog_number: str
    section_number: str
    instructor_user_id: str
    max_concurrent_titles: int
    inclusive_access_flag: bool
    ia_status: str
    enrolled_count: int
    provisioned_access_count: int
    revoked_access_count: int
    opted_out_count: int
    participation_rate: float
    billing_basis_enrollment_count: Optional[int]
    first_posted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Adoption(TypedDict):
    id: str
    section_id: str
    title_id: str
    supersedes_adoption_id: Optional[str]
    status: str
    access_start_date: str
    access_end_date: str
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    submitted_at: Optional[str]
    approved_at: Optional[str]
    locked_list_price_cents: Optional[int]
    change_note: Optional[str]
    revision_count: int
    requires_rebill: bool
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    section_id: str
    student_id: str
    enrolled_on: str
    registration_type: str
    status: str
    dropped_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StudentCharge(TypedDict):
    id: str
    enrollment_id: str
    adoption_id: str
    student_id: str
    gross_price_cents: int
    proration_pct: float
    billed_amount_cents: int
    refunded_amount_cents: int
    net_billed_cents: int
    publisher_share_cents: int
    billing_status: str
    access_status: str
    posted_at: Optional[str]
    opt_out_deadline_at: Optional[str]
    access_start_at: Optional[str]
    access_revoked_at: Optional[str]
    access_restored_at: Optional[str]
    rebill_count: int
    created_at: str
    updated_at: str
    version: int


class LedgerEntry(TypedDict):
    """Append-only bursar movement.

    PRD §2.5: a LedgerEntry carries only ``id`` and ``created_at`` — it has no
    ``updated_at`` and no ``version``.
    """
    id: str
    charge_id: str
    student_id: str
    entry_type: str
    reason_code: str
    amount_cents: int
    posted_at: str
    source_event: str
    created_at: str


class OptOutRequest(TypedDict):
    id: str
    charge_id: str
    status: str
    reason_code: str
    submitted_at: str
    decided_at: Optional[str]
    decided_by_user_id: Optional[str]
    denial_note: Optional[str]
    refund_amount_cents: int
    rescinded_at: Optional[str]
    recharge_amount_cents: int
    cycle_count: int
    created_at: str
    updated_at: str
    version: int


class ReconciliationRun(TypedDict):
    id: str
    agreement_id: str
    term_id: str
    supersedes_run_id: Optional[str]
    method: str
    status: str
    billable_count: int
    opted_out_count: int
    gross_invoice_cents: int
    rebate_cents: int
    settlement_amount_cents: int
    publisher_reported_count: int
    publisher_reported_amount_cents: int
    count_variance: int
    variance_cents: int
    dispute_note: Optional[str]
    computed_by_user_id: str
    settled_by_user_id: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisclosureReport(TypedDict):
    id: str
    term_id: str
    reporting_state_code: str
    status: str
    ia_section_count: int
    charge_count: int
    enrolled_student_count: int
    opted_out_student_count: int
    total_list_price_cents: int
    total_net_billed_cents: int
    average_net_cost_cents: int
    savings_pct: float
    compliance_status: str
    certified_by_user_id: Optional[str]
    certified_at: Optional[str]
    published_at: Optional[str]
    amendment_note: Optional[str]
    amendment_count: int
    created_at: str
    updated_at: str
    version: int


class SectionBillingSummary(TypedDict):
    """The purely derived section read of PRD §3.5 — exactly fifteen fields."""
    section_id: str
    ia_status: str
    billing_basis_enrollment_count: Optional[int]
    tier_basis_posting_count: Optional[int]
    tier_basis_census_count: int
    gross_per_student_posting_cents: Optional[int]
    gross_per_student_census_cents: Optional[int]
    charge_count: int
    posted_charge_count: int
    refunded_charge_count: int
    total_net_billed_cents: int
    total_publisher_share_cents: int
    provisioned_access_count: int
    revoked_access_count: int
    participation_rate: float


BILLING_SUMMARY_FIELDS = (
    "section_id",
    "ia_status",
    "billing_basis_enrollment_count",
    "tier_basis_posting_count",
    "tier_basis_census_count",
    "gross_per_student_posting_cents",
    "gross_per_student_census_cents",
    "charge_count",
    "posted_charge_count",
    "refunded_charge_count",
    "total_net_billed_cents",
    "total_publisher_share_cents",
    "provisioned_access_count",
    "revoked_access_count",
    "participation_rate",
)
