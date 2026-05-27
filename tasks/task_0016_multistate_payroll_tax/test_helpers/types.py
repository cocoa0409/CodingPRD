"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD entity model. Entities carrying `id`, `created_at`,
`updated_at`, and `version` are full common-fields entities. GarnishmentDeduction
and TaxRateTable carry only `id` + `created_at` (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status Enums ─────────────────────────────────────────────────────────

class EmployeeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    TERMINATED = "TERMINATED"


class W4FormStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    SUPERSEDED = "SUPERSEDED"


class PaycheckRunStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    PAID = "PAID"
    VOID = "VOID"


class PaycheckStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    VOID = "VOID"


class GarnishmentOrderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SATISFIED = "SATISFIED"
    RELEASED = "RELEASED"
    SUSPENDED = "SUSPENDED"


class RemittanceStatus(str, Enum):
    ACCRUING = "ACCRUING"
    RECONCILED = "RECONCILED"
    REMITTED = "REMITTED"


class FilingStatus(str, Enum):
    SINGLE = "SINGLE"
    MARRIED_JOINT = "MARRIED_JOINT"
    HEAD_OF_HOUSEHOLD = "HEAD_OF_HOUSEHOLD"


class PayType(str, Enum):
    REGULAR = "REGULAR"
    OVERTIME = "OVERTIME"
    DOUBLE = "DOUBLE"
    RETRO = "RETRO"


class OrderType(str, Enum):
    CHILD_SUPPORT = "CHILD_SUPPORT"
    IRS_LEVY = "IRS_LEVY"
    STUDENT_LOAN = "STUDENT_LOAN"
    CREDITOR = "CREDITOR"


class TaxType(str, Enum):
    FED_INCOME = "FED_INCOME"
    FICA_EMPLOYEE = "FICA_EMPLOYEE"
    STATE_INCOME = "STATE_INCOME"
    LOCAL_INCOME = "LOCAL_INCOME"


class UserRole(str, Enum):
    HR_CLERK = "HRClerk"
    PAYROLL_PREPARER = "PayrollPreparer"
    PAYROLL_APPROVER = "PayrollApprover"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Entity TypedDicts (common_fields=true) ───────────────────────────────

class Employee(TypedDict, total=False):
    id: str
    full_name: str
    work_state_code: str
    residence_state_code: str
    locality_code: str
    status: str
    ytd_wages_cents: int
    ytd_fed_withheld_cents: int
    ytd_ss_wages_cents: int
    ytd_medicare_wages_cents: int
    created_at: str
    updated_at: str
    version: int


class W4Form(TypedDict, total=False):
    id: str
    employee_id: str
    tax_year: int
    filing_status: str
    dependents_amount_cents: int
    other_income_cents: int
    deductions_cents: int
    extra_withholding_cents: int
    supersedes_w4_id: Optional[str]
    status: str
    filed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PaycheckRun(TypedDict, total=False):
    id: str
    pay_period_start: str
    pay_period_end: str
    pay_date: str
    prepared_by_user_id: str
    approved_by_user_id: Optional[str]
    status: str
    total_gross_cents: int
    created_at: str
    updated_at: str
    version: int


class Paycheck(TypedDict, total=False):
    id: str
    paycheck_run_id: str
    employee_id: str
    pay_type: str
    regular_hours_e2: int
    overtime_hours_e2: int
    double_hours_e2: int
    retro_amount_cents: int
    hourly_rate_cents: int
    gross_wages_cents: int
    fed_withheld_cents: int
    state_withheld_cents: int
    local_withheld_cents: int
    ss_withheld_cents: int
    medicare_withheld_cents: int
    addl_medicare_cents: int
    garnishment_total_cents: int
    net_pay_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GarnishmentOrder(TypedDict, total=False):
    id: str
    employee_id: str
    order_type: str
    priority_rank: int
    weekly_cap_cents: int
    original_balance_cents: int
    balance_remaining_cents: int
    status: str
    served_on: str
    created_at: str
    updated_at: str
    version: int


class Remittance(TypedDict, total=False):
    id: str
    period_month: str
    jurisdiction: str
    tax_type: str
    accrued_cents: int
    reconciled_cents: int
    paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Entity TypedDicts (common_fields=false) ──────────────────────────────

class GarnishmentDeduction(TypedDict, total=False):
    id: str
    paycheck_id: str
    garnishment_order_id: str
    amount_cents: int
    applied_at: Optional[str]
    created_at: str


class TaxRateTable(TypedDict, total=False):
    id: str
    jurisdiction: str
    tax_year: int
    filing_status: str
    brackets_json: list
    supplemental_flat_basis_points: int
    created_at: str
