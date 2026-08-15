"""Domain types: entity TypedDicts, status enums, role enum.

All enums and field names follow the PRD exactly. Every resource carries the
common system-managed fields of PRD "Common Resource Properties": id,
created_at, updated_at, version.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    INSURED = "Insured"
    AUDITOR = "Auditor"
    AUDIT_MANAGER = "AuditManager"
    UNDERWRITER = "Underwriter"
    BILLING_CLERK = "BillingClerk"


class CoverageLine(str, Enum):
    WC = "WC"
    GL = "GL"


class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    AUDIT_PENDING = "AUDIT_PENDING"
    AUDIT_FINALIZED = "AUDIT_FINALIZED"
    CANCELLED = "CANCELLED"


class AuditorLevel(str, Enum):
    STAFF = "STAFF"
    SENIOR = "SENIOR"


class AuditType(str, Enum):
    PHYSICAL = "PHYSICAL"
    VOLUNTARY_REPORT = "VOLUNTARY_REPORT"
    REAUDIT = "REAUDIT"


class WorkOrderStatus(str, Enum):
    SELECTED = "SELECTED"
    RECORDS_REQUESTED = "RECORDS_REQUESTED"
    APPOINTMENT_SCHEDULED = "APPOINTMENT_SCHEDULED"
    FIELD_WORK_DONE = "FIELD_WORK_DONE"
    RESULT_DRAFTED = "RESULT_DRAFTED"
    BILLED = "BILLED"
    DISPUTED = "DISPUTED"
    NONCOMPLIANT_PENDING = "NONCOMPLIANT_PENDING"
    ESTIMATED_BILLED = "ESTIMATED_BILLED"
    CLOSED = "CLOSED"
    SUPERSEDED_BY_REAUDIT = "SUPERSEDED_BY_REAUDIT"
    CANCELLED = "CANCELLED"


class RecordsRequestType(str, Enum):
    PAYROLL_SUMMARY = "PAYROLL_SUMMARY"
    TAX_FILINGS = "TAX_FILINGS"
    SUBCONTRACTOR_LIST = "SUBCONTRACTOR_LIST"
    CERTIFICATES_OF_INSURANCE = "CERTIFICATES_OF_INSURANCE"
    SALES_LEDGER = "SALES_LEDGER"


class RecordsRequestStatus(str, Enum):
    OPEN = "OPEN"
    RECEIVED = "RECEIVED"
    OVERDUE = "OVERDUE"
    WAIVED = "WAIVED"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class LocationType(str, Enum):
    INSURED_PREMISES = "INSURED_PREMISES"
    VIRTUAL = "VIRTUAL"
    AUDITOR_OFFICE = "AUDITOR_OFFICE"


class AllocationStatus(str, Enum):
    DRAFT = "DRAFT"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ExposureStatus(str, Enum):
    EXCLUDED = "EXCLUDED"
    INCLUDED = "INCLUDED"
    PARTIAL_INCLUDED = "PARTIAL_INCLUDED"


class CertificateStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class RejectionReason(str, Enum):
    INSUFFICIENT_COVERAGE = "INSUFFICIENT_COVERAGE"
    EXPIRED = "EXPIRED"
    OTHER = "OTHER"


class ResultVariant(str, Enum):
    STANDARD = "STANDARD"
    ESTIMATED_NONCOMPLIANCE = "ESTIMATED_NONCOMPLIANCE"


class ResultStatus(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    SUPERSEDED = "SUPERSEDED"


class DisputeGrounds(str, Enum):
    CLASSIFICATION_ERROR = "CLASSIFICATION_ERROR"
    PAYROLL_ERROR = "PAYROLL_ERROR"
    SUBCONTRACTOR_INCLUSION = "SUBCONTRACTOR_INCLUSION"
    CERT_REVIEW_ERROR = "CERT_REVIEW_ERROR"
    OTHER = "OTHER"


class DisputeStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    OVERRULED = "OVERRULED"


class BillingType(str, Enum):
    ADDITIONAL_PREMIUM_INVOICE = "ADDITIONAL_PREMIUM_INVOICE"
    RETURN_PREMIUM_CREDIT = "RETURN_PREMIUM_CREDIT"


class BillingStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    APPLIED = "APPLIED"
    PAST_DUE = "PAST_DUE"
    CANCELLED = "CANCELLED"


class ModRevisionStatus(str, Enum):
    DRAFT = "DRAFT"
    APPLIED = "APPLIED"


class Policy(TypedDict, total=False):
    id: str
    policy_number: str
    insured_name: str
    coverage_line: str
    state_code: str
    effective_date: str
    expiration_date: str
    estimated_annual_premium_cents: int
    minimum_premium_cents: int
    payroll_estimate_dollars: int
    experience_mod_factor: float
    class_code_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Auditor(TypedDict, total=False):
    id: str
    full_name: str
    territory_states: List[str]
    level: str
    created_at: str
    updated_at: str
    version: int


class ClassificationCode(TypedDict, total=False):
    id: str
    code: str
    description: str
    state_code: str
    coverage_line: str
    rate_per_100_cents: int
    high_hazard: bool
    effective_from: str
    effective_to: str
    created_at: str
    updated_at: str
    version: int


class AuditSelectionRun(TypedDict, total=False):
    id: str
    run_at: str
    evaluated_count: int
    physical_count: int
    voluntary_count: int
    exempt_count: int
    created_at: str
    updated_at: str
    version: int


class AuditWorkOrder(TypedDict, total=False):
    id: str
    policy_id: str
    selection_run_id: Optional[str]
    reaudit_of_work_order_id: Optional[str]
    assigned_auditor_id: Optional[str]
    audit_type: str
    audit_period_start: str
    audit_period_end: str
    status: str
    no_show_count: int
    marked_noncompliant_by_user_id: Optional[str]
    total_premium_base_dollars: int
    created_at: str
    updated_at: str
    version: int


class RecordsRequest(TypedDict, total=False):
    id: str
    audit_work_order_id: str
    request_type: str
    status: str
    requested_at: str
    due_at: str
    received_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditAppointment(TypedDict, total=False):
    id: str
    audit_work_order_id: str
    auditor_id: str
    scheduled_start: str
    scheduled_end: str
    location_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PayrollAllocation(TypedDict, total=False):
    id: str
    audit_work_order_id: str
    class_code_id: str
    period_start: str
    period_end: str
    gross_payroll_dollars: int
    overtime_excess_dollars: int
    overtime_documented: bool
    severance_dollars: int
    other_exclusions_dollars: int
    auditable_payroll_dollars: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SubcontractorExposure(TypedDict, total=False):
    id: str
    audit_work_order_id: str
    subcontractor_name: str
    payments_dollars: int
    governing_class_code_id: str
    included_dollars: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CertificateOfInsurance(TypedDict, total=False):
    id: str
    subcontractor_exposure_id: str
    insurer_name: str
    wc_coverage_present: bool
    gl_coverage_present: bool
    coverage_effective_date: str
    coverage_expiration_date: str
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditResult(TypedDict, total=False):
    id: str
    audit_work_order_id: str
    variant: str
    status: str
    total_payroll_dollars: int
    manual_premium_cents: int
    mod_factor_applied: float
    earned_premium_cents: int
    adjustment_cents: Optional[int]
    drafted_by_user_id: Optional[str]
    issued_by_user_id: Optional[str]
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict, total=False):
    id: str
    audit_result_id: str
    grounds: str
    filed_at: str
    status: str
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BillingTransaction(TypedDict, total=False):
    id: str
    audit_result_id: str
    type: str
    amount_cents: int
    paid_cents: int
    issued_at: str
    due_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ModRevision(TypedDict, total=False):
    id: str
    policy_id: str
    source_work_order_id: str
    prior_mod_factor: float
    payroll_variance_ratio: float
    revised_mod_factor: float
    status: str
    created_at: str
    updated_at: str
    version: int
