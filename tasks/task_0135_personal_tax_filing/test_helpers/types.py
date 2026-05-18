"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 distinguishes two common-fields shapes:

- Persisted resources carrying id + created_at + updated_at + version:
  Taxpayer, TaxReturn, IncomeDocument, Schedule, TaxCredit,
  AmendedReturn, EstimatedTaxPayment.
- Append-style records carrying ONLY id + created_at: EFiling and
  AuditLog. PRD §2.4: "The EFiling and AuditLog records are the
  exceptions. Both are append-style records that carry an id and a
  created_at timestamp; neither exposes updated_at, and neither
  exposes a version field."
"""
from __future__ import annotations

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    TAXPAYER = "Taxpayer"
    IRS_ADJUDICATOR = "IRSAdjudicator"


# ---------------------------------------------------------------------------
# Status enums — PRD §3
# ---------------------------------------------------------------------------
class TaxpayerAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"


class TaxReturnStatus(str, Enum):
    DRAFT = "DRAFT"
    READY_TO_FILE = "READY_TO_FILE"
    FILED = "FILED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    AMENDED = "AMENDED"
    SUPERSEDED = "SUPERSEDED"


class FilingStatus(str, Enum):
    SINGLE = "SINGLE"
    MARRIED_JOINT = "MARRIED_JOINT"
    MARRIED_SEPARATE = "MARRIED_SEPARATE"
    HEAD_OF_HOUSEHOLD = "HEAD_OF_HOUSEHOLD"
    QUALIFYING_SURVIVING_SPOUSE = "QUALIFYING_SURVIVING_SPOUSE"


class DeductionMethod(str, Enum):
    STANDARD = "STANDARD"
    ITEMIZED = "ITEMIZED"


class DocType(str, Enum):
    W2 = "W2"
    NEC_1099 = "1099_NEC"
    INT_1099 = "1099_INT"
    DIV_1099 = "1099_DIV"
    B_1099 = "1099_B"


class HoldingPeriod(str, Enum):
    NONE = "NONE"
    SHORT_TERM = "SHORT_TERM"
    LONG_TERM = "LONG_TERM"


class ScheduleType(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"


class CreditType(str, Enum):
    EITC = "EITC"
    CTC = "CTC"
    AOTC = "AOTC"


class EligibilityStatus(str, Enum):
    PENDING = "PENDING"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class EFilingOutcome(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class AmendedReturnStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class EstimatedPaymentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class Quarter(str, Enum):
    Q1 = "Q1"
    Q2 = "Q2"
    Q3 = "Q3"
    Q4 = "Q4"


# ---------------------------------------------------------------------------
# Entity TypedDicts — PRD §2.4 (common fields) + §3 (per-entity fields)
# ---------------------------------------------------------------------------
class FilingAddress(TypedDict):
    street: str
    city: str
    state: str
    zip: str


class Taxpayer(TypedDict, total=False):
    id: str
    ssn_last4: str
    full_name: str
    date_of_birth: str
    filing_address: FilingAddress
    is_blind: bool
    account_status: str
    created_at: str
    updated_at: str
    version: int


class TaxReturn(TypedDict, total=False):
    id: str
    taxpayer_id: str
    tax_year: int
    filing_status: str
    dependents_count: int
    qualifying_children_under_17: int
    status: str
    deduction_method: str
    total_income_cents: int
    agi_cents: int
    taxable_income_cents: int
    regular_tax_cents: int
    amt_cents: int
    total_credits_cents: int
    total_withholding_cents: int
    estimated_payments_applied_cents: int
    balance_due_or_refund_cents: int
    filed_at: Optional[str]
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncomeDocument(TypedDict, total=False):
    id: str
    tax_return_id: str
    doc_type: str
    payer_ein: str
    payer_name: str
    wages_cents: int
    federal_withholding_cents: int
    nonemployee_comp_cents: int
    interest_income_cents: int
    ordinary_dividends_cents: int
    qualified_dividends_cents: int
    proceeds_cents: int
    cost_basis_cents: int
    holding_period: str
    imported_at: str
    created_at: str
    updated_at: str
    version: int


class Schedule(TypedDict, total=False):
    id: str
    tax_return_id: str
    schedule_type: str
    itemized_medical_cents: int
    itemized_salt_cents: int
    itemized_mortgage_interest_cents: int
    itemized_charity_cents: int
    schedule_b_interest_cents: int
    schedule_b_dividends_cents: int
    schedule_c_gross_receipts_cents: int
    schedule_c_expenses_cents: int
    schedule_c_net_profit_cents: int
    schedule_d_short_term_gain_cents: int
    schedule_d_long_term_gain_cents: int
    schedule_e_rental_income_cents: int
    schedule_e_rental_expenses_cents: int
    total_itemized_deduction_cents: int
    created_at: str
    updated_at: str
    version: int


class TaxCredit(TypedDict, total=False):
    id: str
    tax_return_id: str
    credit_type: str
    requested_amount_cents: int
    eligibility_status: str
    approved_amount_cents: int
    refundable_portion_cents: int
    aotc_student_count: int
    aotc_qualified_expenses_cents: int
    ineligibility_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# EFiling — append-style. PRD §2.4: id + created_at only.
class EFiling(TypedDict, total=False):
    id: str
    tax_return_id: str
    submission_id: str
    outcome: str
    rejection_code: Optional[str]
    rejection_message: Optional[str]
    filed_at: str
    processed_at: Optional[str]
    created_at: str


class AmendedReturn(TypedDict, total=False):
    id: str
    original_return_id: str
    form_code: str
    reason_summary: str
    status: str
    delta_agi_cents: int
    delta_tax_cents: int
    delta_balance_due_or_refund_cents: int
    restated_return_snapshot: Optional[dict]
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EstimatedTaxPayment(TypedDict, total=False):
    id: str
    taxpayer_id: str
    tax_year: int
    quarter: str
    amount_cents: int
    scheduled_pay_date: str
    status: str
    confirmed_at: Optional[str]
    cancelled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# AuditLog — append-style. PRD §2.4: id + created_at only.
class AuditLog(TypedDict, total=False):
    id: str
    actor_role: str
    actor_id: str
    action: str
    target_entity: str
    target_id: str
    payload: dict
    created_at: str


__all__ = [
    "UserRole",
    "TaxpayerAccountStatus",
    "TaxReturnStatus",
    "FilingStatus",
    "DeductionMethod",
    "DocType",
    "HoldingPeriod",
    "ScheduleType",
    "CreditType",
    "EligibilityStatus",
    "EFilingOutcome",
    "AmendedReturnStatus",
    "EstimatedPaymentStatus",
    "Quarter",
    "FilingAddress",
    "Taxpayer",
    "TaxReturn",
    "IncomeDocument",
    "Schedule",
    "TaxCredit",
    "EFiling",
    "AmendedReturn",
    "EstimatedTaxPayment",
    "AuditLog",
]
