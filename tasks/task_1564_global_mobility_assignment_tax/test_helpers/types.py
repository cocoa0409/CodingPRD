"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    MOBILITY_ADMIN = "MobilityAdmin"
    BUSINESS_UNIT_APPROVER = "BusinessUnitApprover"
    MOBILITY_APPROVER = "MobilityApprover"
    PAYROLL_SPECIALIST = "PayrollSpecialist"
    FINANCE_CONTROLLER = "FinanceController"
    VENDOR_COORDINATOR = "VendorCoordinator"
    TAX_VENDOR = "TaxVendor"
    ASSIGNEE = "Assignee"
    ANY = "Any"


class AssignmentStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_BU_APPROVAL = "PENDING_BU_APPROVAL"
    PENDING_MOBILITY_APPROVAL = "PENDING_MOBILITY_APPROVAL"
    ACTIVE = "ACTIVE"
    REPATRIATION_PENDING = "REPATRIATION_PENDING"
    REPATRIATED = "REPATRIATED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class CostPosture(str, Enum):
    NORMAL = "NORMAL"
    OVERRUN = "OVERRUN"


class AssignmentType(str, Enum):
    SHORT_TERM = "SHORT_TERM"
    LONG_TERM = "LONG_TERM"


class PackageStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"


class SplitStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class RecordStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class SettlementStatus(str, Enum):
    CALCULATED = "CALCULATED"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"


class SettlementDirection(str, Enum):
    EMPLOYEE_CREDIT = "EMPLOYEE_CREDIT"
    EMPLOYEE_DEBIT = "EMPLOYEE_DEBIT"
    ZERO = "ZERO"


class EngagementStatus(str, Enum):
    ENGAGED = "ENGAGED"
    DATA_SENT = "DATA_SENT"
    DRAFT_RETURNED = "DRAFT_RETURNED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    ACCEPTED = "ACCEPTED"
    FILED = "FILED"
    CLOSED = "CLOSED"


class EngagementScope(str, Enum):
    HOME_ONLY = "HOME_ONLY"
    HOST_ONLY = "HOST_ONLY"
    DUAL = "DUAL"


class CertificateStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SUBMITTED = "SUBMITTED"
    ISSUED = "ISSUED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ProjectionStatus(str, Enum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"


class ProjectionVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    ACTUALIZED = "ACTUALIZED"


class ExtensionStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    SUPERSEDED = "SUPERSEDED"


class ChargebackStatus(str, Enum):
    ACCRUED = "ACCRUED"
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class ChargebackEntryType(str, Enum):
    PERIOD_COST = "PERIOD_COST"
    SETTLEMENT = "SETTLEMENT"


class MobilityProgram(TypedDict, total=False):
    id: str
    name: str
    home_country_code: str
    functional_currency: str
    cost_overrun_threshold_pct: int
    max_assignment_duration_days: int
    per_diem_annual_day_cap: int
    status: str
    total_posted_chargeback_cents: int
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict, total=False):
    id: str
    employee_ref: str
    full_name: str
    home_country_code: str
    family_size: int
    annual_base_salary_cents: int
    created_at: str
    updated_at: str
    version: int


class AllowancePolicy(TypedDict, total=False):
    id: str
    policy_name: str
    host_country_code: str
    effective_from: str
    effective_to: str
    per_diem_daily_cents: int
    housing_monthly_cap_cents: int
    cola_pct: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    program_id: str
    employee_id: str
    policy_id: str
    host_country_code: str
    host_business_unit: str
    assignment_type: str
    totalization_applies: bool
    start_date: str
    planned_end_date: str
    actual_end_date: Optional[str]
    status: str
    cost_posture: str
    ytd_gross_cents: int
    ytd_hypo_withheld_cents: int
    ytd_per_diem_days: int
    ytd_chargeback_cents: int
    submitted_by_user_id: Optional[str]
    bu_approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CompensationPackage(TypedDict, total=False):
    id: str
    assignment_id: str
    letter_title: str
    home_base_annual_cents: int
    goods_services_differential_pct: int
    relocation_lump_sum_cents: int
    status: str
    revision_number: int
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayrollSplit(TypedDict, total=False):
    id: str
    assignment_id: str
    home_payroll_pct: int
    host_payroll_pct: int
    shadow_payroll_host: bool
    coc_exempt: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ShadowPayrollRecord(TypedDict, total=False):
    id: str
    assignment_id: str
    tax_year: int
    period_month: int
    total_gross_cents: int
    per_diem_days: int
    housing_receipts_cents: int
    home_gross_cents: int
    host_gross_cents: int
    per_diem_cents: int
    housing_cents: int
    hypothetical_tax_cents: int
    employer_host_tax_cents: int
    employer_socsec_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict, total=False):
    id: str
    assignment_id: str
    tax_year: int
    vendor_engagement_id: str
    total_hypo_withheld_cents: int
    final_hypo_tax_cents: int
    settlement_amount_cents: int
    direction: str
    status: str
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VendorEngagement(TypedDict, total=False):
    id: str
    assignment_id: str
    tax_year: int
    scope: str
    vendor_name: str
    fee_cents: int
    status: str
    revision_count: int
    filed_total_gross_cents: Optional[int]
    filed_home_tax_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CertificateOfCoverage(TypedDict, total=False):
    id: str
    assignment_id: str
    application_ref: str
    status: str
    valid_from: Optional[str]
    valid_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CostProjection(TypedDict, total=False):
    id: str
    assignment_id: str
    variant: str
    projected_months: int
    monthly_cost_cents: int
    total_projected_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExtensionRequest(TypedDict, total=False):
    id: str
    assignment_id: str
    requested_new_end_date: str
    reason: Optional[str]
    status: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChargebackEntry(TypedDict, total=False):
    id: str
    assignment_id: str
    business_unit: str
    entry_type: str
    source_record_id: Optional[str]
    source_settlement_id: Optional[str]
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
