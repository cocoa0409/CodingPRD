"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the Coding Bootcamp ISA PRD §2.4 / §3 entity definitions. Mutable
resources carry id/created_at/updated_at/version; the AttendanceRecord is an
append-only event log carrying only id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    ADMISSIONS_OFFICER = "AdmissionsOfficer"
    SERVICING_OFFICER = "ServicingOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    STUDENT = "Student"


# --- Status enums (PRD §3 lifecycles) ---
class CohortStatus(str, Enum):
    PLANNING = "PLANNING"
    OPEN = "OPEN"
    RUNNING = "RUNNING"
    GRADUATED = "GRADUATED"
    ARCHIVED = "ARCHIVED"


class ApplicantStatus(str, Enum):
    APPLIED = "APPLIED"
    ADMITTED = "ADMITTED"
    REJECTED = "REJECTED"
    ENROLLED = "ENROLLED"
    WITHDRAWN_APP = "WITHDRAWN_APP"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    ACTIVE = "ACTIVE"
    GRADUATED = "GRADUATED"
    DISMISSED = "DISMISSED"
    WITHDRAWN = "WITHDRAWN"


class ISAContractStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    DEFERRED = "DEFERRED"
    COMPLETED = "COMPLETED"
    SETTLED_TERM = "SETTLED_TERM"
    VOIDED = "VOIDED"


class ScholarshipStatus(str, Enum):
    APPLIED = "APPLIED"
    SUPERSEDED = "SUPERSEDED"


class DepositStatus(str, Enum):
    HELD = "HELD"
    REFUNDED = "REFUNDED"
    FORFEITED = "FORFEITED"


class PaymentCollectionStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    FAILED = "FAILED"


class PaymentRefundStatus(str, Enum):
    NONE = "NONE"
    REFUNDED = "REFUNDED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    FAILED = "FAILED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class DefermentRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    ENDED = "ENDED"


class RefundRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CIRRReportStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


# --- Value enums ---
class Track(str, Enum):
    FULLSTACK = "FULLSTACK"
    DATA = "DATA"
    CYBER = "CYBER"


class FinancingChoice(str, Enum):
    ISA = "ISA"
    UPFRONT = "UPFRONT"


class ScholarshipKind(str, Enum):
    DEI = "DEI"
    MERIT = "MERIT"
    NEED = "NEED"


class EmploymentStatus(str, Enum):
    EMPLOYED = "EMPLOYED"
    UNEMPLOYED = "UNEMPLOYED"
    UNDEREMPLOYED = "UNDEREMPLOYED"


class DefermentReason(str, Enum):
    UNEMPLOYMENT = "UNEMPLOYMENT"
    INCOME_FLOOR = "INCOME_FLOOR"


class RefundReason(str, Enum):
    COOLING_OFF = "COOLING_OFF"
    WITHDRAWAL = "WITHDRAWAL"
    DISMISSAL_APPEAL = "DISMISSAL_APPEAL"


class PlacementCategory(str, Enum):
    EMPLOYED_IN_FIELD = "EMPLOYED_IN_FIELD"
    EMPLOYED_OUT_OF_FIELD = "EMPLOYED_OUT_OF_FIELD"
    SELF_EMPLOYED = "SELF_EMPLOYED"
    CONTINUED_EDUCATION = "CONTINUED_EDUCATION"
    STILL_SEEKING = "STILL_SEEKING"
    OUT_OF_PROGRAM = "OUT_OF_PROGRAM"


class DenominatorBasis(str, Enum):
    GRADUATES_ONLY = "GRADUATES_ONLY"
    ALL_ENROLLED = "ALL_ENROLLED"


# --- Entity TypedDicts (mutable resources: id + created_at + updated_at + version) ---
class Cohort(TypedDict):
    id: str
    name: str
    track: str
    capacity: int
    tuition_sticker_cents: int
    start_date: str
    end_date: str
    cirr_period_label: str
    status: str
    seats_committed: int
    seats_available: int
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict, total=False):
    id: str
    cohort_id: str
    full_name: str
    email: str
    reported_prior_income_cents: int
    status: str
    admitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    applicant_id: str
    cohort_id: str
    financing_choice: str
    status: str
    attendance_pct: float
    progress_pct: float
    enrolled_at: str
    isa_status: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ISAContract(TypedDict):
    id: str
    enrollment_id: str
    income_share_pct: float
    cap_cents: int
    term_months: int
    income_threshold_cents: int
    status: str
    payments_made_count: int
    amount_paid_cents: int
    remaining_cap_cents: int
    projected_payoff_cents: int
    created_at: str
    updated_at: str
    version: int


class Scholarship(TypedDict):
    id: str
    enrollment_id: str
    kind: str
    cap_reduction_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Deposit(TypedDict, total=False):
    id: str
    enrollment_id: str
    amount_cents: int
    status: str
    refunded_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class IncomeReport(TypedDict, total=False):
    id: str
    isa_contract_id: str
    period_start: str
    period_end: str
    gross_income_cents: int
    employment_status: str
    obligation_cents: int
    payment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    isa_contract_id: str
    income_report_id: str
    amount_cents: int
    collection_status: str
    refund_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DefermentRequest(TypedDict):
    id: str
    isa_contract_id: str
    reason: str
    period_start: str
    period_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RefundRequest(TypedDict, total=False):
    id: str
    enrollment_id: str
    reason: str
    requested_at: str
    gross_refund_cents: int
    net_refund_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PlacementOutcome(TypedDict, total=False):
    id: str
    enrollment_id: str
    category: str
    annual_salary_cents: Optional[int]
    placement_days: Optional[int]
    reported_at: str
    cirr_eligible: bool
    created_at: str
    updated_at: str
    version: int


class CIRRReport(TypedDict):
    id: str
    cohort_id: str
    denominator_basis: str
    graduates_count: int
    enrolled_count: int
    placed_count: int
    placement_rate: float
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only event log (common_fields: false) — ONLY id + created_at ---
class AttendanceRecord(TypedDict):
    id: str
    enrollment_id: str
    session_date: str
    present: bool
    cumulative_progress_pct: float
    created_at: str
