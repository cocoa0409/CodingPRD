"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    LENDER_ADMIN = "LenderAdmin"
    DRAW_PROCESSOR = "DrawProcessor"
    CREDIT_OFFICER = "CreditOfficer"
    LOAN_SERVICER = "LoanServicer"
    INSPECTOR = "Inspector"
    BORROWER = "Borrower"


class EntityType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    LLC = "LLC"
    CORPORATION = "CORPORATION"
    PARTNERSHIP = "PARTNERSHIP"


class LoanStatus(str, Enum):
    OPEN = "OPEN"
    CONVERTED = "CONVERTED"
    TERMINATED = "TERMINATED"


class DayCountConvention(str, Enum):
    ACTUAL_360 = "ACTUAL_360"
    THIRTY_360 = "THIRTY_360"


class BudgetLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class DrawStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    FUNDED = "FUNDED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class LineType(str, Enum):
    WORK_COMPLETED = "WORK_COMPLETED"
    STORED_MATERIALS = "STORED_MATERIALS"


class DocType(str, Enum):
    LIEN_WAIVER_CONDITIONAL = "LIEN_WAIVER_CONDITIONAL"
    LIEN_WAIVER_UNCONDITIONAL = "LIEN_WAIVER_UNCONDITIONAL"
    INVOICE = "INVOICE"
    INSURANCE_CERTIFICATE = "INSURANCE_CERTIFICATE"


class DocStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class InspectionStatus(str, Enum):
    ORDERED = "ORDERED"
    COMPLETED = "COMPLETED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class ReallocationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class ReleaseStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    REJECTED = "REJECTED"


class ConversionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    CONVERTED = "CONVERTED"
    DECLINED = "DECLINED"


class EntryType(str, Enum):
    INITIAL_DEPOSIT = "INITIAL_DEPOSIT"
    INTEREST_PAYMENT = "INTEREST_PAYMENT"
    CAPITALIZATION = "CAPITALIZATION"
    SWEEP = "SWEEP"


# --- Entity TypedDicts (common_fields: true) ---------------------------------

class Borrower(TypedDict, total=False):
    id: str
    legal_name: str
    contact_email: str
    entity_type: str
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict, total=False):
    id: str
    borrower_id: str
    commitment_amount_cents: int
    interest_rate_annual_bps: int
    day_count_convention: str
    interest_reserve_initial_cents: int
    maturity_date: str
    retainage_pct: float
    reduced_retainage_pct: float
    retainage_milestone_pct: float
    stored_materials_max_pct: float
    status: str
    total_original_budget_cents: int
    principal_disbursed_cents: int
    retained_cents: int
    interest_reserve_balance_cents: int
    interest_reserve_depleted: bool
    interest_reserve_swept_cents: int
    interest_capitalized_cents: int
    inspection_percent_complete: float
    cost_percent_complete: float
    milestone_reached: bool
    retainage_fully_released: bool
    permanent_interest_rate_annual_bps: Optional[int]
    permanent_term_months: Optional[int]
    created_at: str
    updated_at: str
    version: int


class BudgetLine(TypedDict, total=False):
    id: str
    loan_id: str
    cost_code: str
    description: str
    original_amount_cents: int
    is_contingency: bool
    status: str
    revised_amount_cents: int
    disbursed_cents: int
    retained_cents: int
    approved_unfunded_cents: int
    created_at: str
    updated_at: str
    version: int


class DrawRequest(TypedDict, total=False):
    id: str
    loan_id: str
    draw_number: int
    period_start_date: str
    period_end_date: str
    status: str
    revision_notes: Optional[str]
    rejection_reason: Optional[str]
    requested_total_cents: int
    approved_total_cents: int
    retainage_total_cents: int
    funded_total_cents: int
    effective_retainage_pct: Optional[float]
    milestone_applied: bool
    created_at: str
    updated_at: str
    version: int


class DrawLineItem(TypedDict, total=False):
    id: str
    draw_id: str
    budget_line_id: str
    line_type: str
    requested_cents: int
    stored_material_invoice_cents: Optional[int]
    insurance_certificate_ref: Optional[str]
    stored_location: Optional[str]
    installed_by_date: Optional[str]
    is_installed: bool
    installed_date: Optional[str]
    approved_cents: int
    retainage_cents: int
    net_fundable_cents: int
    funded_cents: int
    created_at: str
    updated_at: str
    version: int


class DrawDocument(TypedDict, total=False):
    id: str
    draw_id: str
    doc_type: str
    party_name: str
    reference_number: Optional[str]
    amount_cents: int
    doc_date: str
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    loan_id: str
    draw_id: Optional[str]
    scheduled_date: str
    status: str
    percent_complete_reported: Optional[float]
    completed_date: Optional[str]
    stored_materials_observed_cents: Optional[int]
    notes: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReallocationRequest(TypedDict, total=False):
    id: str
    loan_id: str
    from_budget_line_id: str
    to_budget_line_id: str
    amount_cents: int
    justification: str
    status: str
    review_reason: Optional[str]
    created_loan_version: int
    created_at: str
    updated_at: str
    version: int


class RetainageRelease(TypedDict, total=False):
    id: str
    loan_id: str
    budget_line_id: str
    amount_cents: int
    reason: str
    status: str
    review_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConversionReview(TypedDict, total=False):
    id: str
    loan_id: str
    status: str
    decline_reason: Optional[str]
    permanent_interest_rate_annual_bps: Optional[int]
    permanent_term_months: Optional[int]
    created_at: str
    updated_at: str
    version: int


# Append-only ledger entry: carries ONLY id + created_at (no updated_at/version)
class InterestReserveEntry(TypedDict, total=False):
    id: str
    created_at: str
    loan_id: str
    entry_index: int
    entry_type: str
    amount_cents: int
    period_start_date: Optional[str]
    period_end_date: Optional[str]
    days_counted: Optional[int]
    interest_due_cents: Optional[int]
    paid_from_reserve_cents: Optional[int]
    capitalized_cents: Optional[int]
    reserve_balance_after_cents: int
