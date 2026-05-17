"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 distinguishes two common-fields shapes:

- Top-level mutable resources (Employee, W4Profile, PayPeriod,
  PayrollItem, Paycheck, GarnishmentOrder, RemittancePeriod) carry
  id + created_at + updated_at + version.
- Append-only / immutable records (YTDLedgerEntry, TaxBracketTable)
  carry ONLY id + created_at. They have no updated_at and no
  version.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PAYROLL_SPECIALIST = "PayrollSpecialist"
    PAYROLL_MANAGER = "PayrollManager"
    TREASURER = "Treasurer"


# ---------------------------------------------------------------------------
# Employee — PRD §3.1
# ---------------------------------------------------------------------------
class EmployeeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class WorkState(str, Enum):
    CA = "CA"
    NY = "NY"
    TX = "TX"
    IL = "IL"
    PA = "PA"


class WorkLocality(str, Enum):
    NYC = "NYC"
    PHL = "PHL"
    NONE = "NONE"


# ---------------------------------------------------------------------------
# W4Profile — PRD §3.1
# ---------------------------------------------------------------------------
class FilingStatus(str, Enum):
    SINGLE = "SINGLE"
    MARRIED_JOINT = "MARRIED_JOINT"
    HEAD_OF_HOUSEHOLD = "HEAD_OF_HOUSEHOLD"


# ---------------------------------------------------------------------------
# PayPeriod — PRD §3.2
# ---------------------------------------------------------------------------
class PayPeriodStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# Paycheck — PRD §3.4, §3.6
# ---------------------------------------------------------------------------
class PaycheckStatus(str, Enum):
    DRAFT = "DRAFT"
    CALCULATED = "CALCULATED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    VOIDED = "VOIDED"


# ---------------------------------------------------------------------------
# GarnishmentOrder — PRD §3.5
# ---------------------------------------------------------------------------
class GarnishmentOrderType(str, Enum):
    CHILD_SUPPORT = "CHILD_SUPPORT"
    FEDERAL_TAX_LEVY = "FEDERAL_TAX_LEVY"
    STUDENT_LOAN = "STUDENT_LOAN"
    CREDITOR = "CREDITOR"


class GarnishmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SATISFIED = "SATISFIED"
    RELEASED = "RELEASED"


# ---------------------------------------------------------------------------
# RemittancePeriod — PRD §3.10
# ---------------------------------------------------------------------------
class RemittanceStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    REMITTED = "REMITTED"
    AMENDED = "AMENDED"


# ---------------------------------------------------------------------------
# YTDLedgerEntry — PRD §2.11
# ---------------------------------------------------------------------------
class LedgerEntryKind(str, Enum):
    ACCRUAL = "ACCRUAL"
    REVERSAL = "REVERSAL"


# ---------------------------------------------------------------------------
# TaxBracketTable — PRD §3.9
# ---------------------------------------------------------------------------
class Jurisdiction(str, Enum):
    FEDERAL = "FEDERAL"
    CA = "CA"
    NY = "NY"
    TX = "TX"
    IL = "IL"
    PA = "PA"
    NYC = "NYC"
    PHL = "PHL"


class FilingStatusOrAny(str, Enum):
    SINGLE = "SINGLE"
    MARRIED_JOINT = "MARRIED_JOINT"
    HEAD_OF_HOUSEHOLD = "HEAD_OF_HOUSEHOLD"
    ANY = "ANY"


# ===========================================================================
# Top-level mutable resources (common_fields: true) — PRD §2.4
# Carry id + created_at + updated_at + version.
# ===========================================================================
class Employee(TypedDict, total=False):
    id: str
    full_name: str
    hire_date: str
    work_state: str
    work_locality: str
    hourly_rate_cents: int
    ytd_gross_wages_cents: int
    ytd_social_security_wages_cents: int
    ytd_medicare_wages_cents: int
    status: str
    termination_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class W4Profile(TypedDict, total=False):
    id: str
    employee_id: str
    filing_status: str
    dependents_amount_cents: int
    other_income_cents: int
    additional_withholding_cents: int
    state_allowances: int
    prefilled_from_prior_year: bool
    effective_pay_period_id: str
    created_at: str
    updated_at: str
    version: int


class PayPeriod(TypedDict, total=False):
    id: str
    period_start: str
    period_end: str
    pay_date: str
    status: str
    paycheck_count: int
    created_at: str
    updated_at: str
    version: int


class PayrollItem(TypedDict, total=False):
    id: str
    pay_period_id: str
    employee_id: str
    regular_hours: float
    overtime_hours: float
    double_hours: float
    retro_adjustment_cents: int
    locked: bool
    created_at: str
    updated_at: str
    version: int


class Paycheck(TypedDict, total=False):
    id: str
    pay_period_id: str
    payroll_item_id: str
    employee_id: str
    w4_profile_id: Optional[str]
    gross_wages_cents: Optional[int]
    federal_withholding_cents: Optional[int]
    state_withholding_cents: Optional[int]
    local_withholding_cents: Optional[int]
    social_security_cents: Optional[int]
    medicare_base_cents: Optional[int]
    medicare_additional_cents: Optional[int]
    garnishment_total_cents: Optional[int]
    net_pay_cents: Optional[int]
    is_retro_correction: bool
    correction_of_paycheck_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class GarnishmentOrder(TypedDict, total=False):
    id: str
    employee_id: str
    order_type: str
    priority_rank: int
    total_owed_cents: int
    amount_collected_cents: int
    cap_pct_of_disposable: int
    effective_pay_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RemittanceStateBreakdownEntry(TypedDict, total=False):
    state: str
    amount_cents: int


class RemittancePeriod(TypedDict, total=False):
    id: str
    tax_year: int
    tax_month: int
    total_federal_withholding_cents: int
    total_state_withholding_cents: int
    total_local_withholding_cents: int
    total_social_security_cents: int
    total_medicare_cents: int
    total_medicare_additional_cents: int
    state_breakdown: List[RemittanceStateBreakdownEntry]
    status: str
    created_at: str
    updated_at: str
    version: int


# ===========================================================================
# Append-only / immutable records (common_fields: false) — PRD §2.4
# Carry ONLY id + created_at. No updated_at, no version.
# ===========================================================================
class YTDLedgerEntry(TypedDict, total=False):
    id: str
    employee_id: str
    paycheck_id: str
    tax_year: int
    gross_wages_delta_cents: int
    social_security_wages_delta_cents: int
    medicare_wages_delta_cents: int
    entry_kind: str
    created_at: str


class TaxBracketEntry(TypedDict, total=False):
    lower_cents: int
    upper_cents_or_null: Optional[int]
    rate_bps: int


class TaxBracketTable(TypedDict, total=False):
    id: str
    jurisdiction: str
    filing_status: str
    tax_year: int
    brackets: List[TaxBracketEntry]
    created_at: str


__all__ = [
    "UserRole",
    "EmployeeStatus",
    "WorkState",
    "WorkLocality",
    "FilingStatus",
    "PayPeriodStatus",
    "PaycheckStatus",
    "GarnishmentOrderType",
    "GarnishmentStatus",
    "RemittanceStatus",
    "LedgerEntryKind",
    "Jurisdiction",
    "FilingStatusOrAny",
    "Employee",
    "W4Profile",
    "PayPeriod",
    "PayrollItem",
    "Paycheck",
    "GarnishmentOrder",
    "RemittanceStateBreakdownEntry",
    "RemittancePeriod",
    "YTDLedgerEntry",
    "TaxBracketEntry",
    "TaxBracketTable",
]
