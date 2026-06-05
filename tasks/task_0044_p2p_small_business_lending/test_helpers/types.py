"""Domain types: entity TypedDicts, status enums, role enum.

All field names match the PRD exactly. Entities with the full common-field set
carry id/created_at/updated_at/version; RepaymentAllocation is append-only and
carries only id and created_at (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Status enums ---

class BorrowerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LoanApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SCORED = "SCORED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RiskGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    F = "F"


class LoanStatus(str, Enum):
    FUNDING = "FUNDING"
    ACTIVE = "ACTIVE"
    REPAYMENT = "REPAYMENT"
    PAID_OFF = "PAID_OFF"
    DEFAULTED = "DEFAULTED"
    CHARGED_OFF = "CHARGED_OFF"


class InvestorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class InvestmentStatus(str, Enum):
    COMMITTED = "COMMITTED"
    WRITTEN_OFF = "WRITTEN_OFF"


class RepaymentKind(str, Enum):
    SCHEDULED = "SCHEDULED"
    RECOVERY = "RECOVERY"


class DocumentType(str, Enum):
    SERIES_NOTE_PROSPECTUS = "SERIES_NOTE_PROSPECTUS"
    RISK_FACTORS = "RISK_FACTORS"
    ANNUAL_REPORT = "ANNUAL_REPORT"


class DisclosureStatus(str, Enum):
    FILED = "FILED"
    SUPERSEDED = "SUPERSEDED"


# --- Role enum ---

class UserRole(str, Enum):
    BORROWER = "Borrower"
    INVESTOR = "Investor"
    UNDERWRITER = "Underwriter"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


# --- Entity TypedDicts (common_fields: true -> id/created_at/updated_at/version) ---

class Borrower(TypedDict):
    id: str
    business_name: str
    ein: str
    state_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LoanApplication(TypedDict):
    id: str
    borrower_id: str
    requested_principal_cents: int
    term_months: int
    plaid_avg_monthly_revenue_cents: int
    plaid_monthly_debt_payment_cents: int
    plaid_nsf_count_90d: int
    plaid_account_age_months: int
    credit_score: Optional[float]
    risk_grade: Optional[str]
    offered_apr: Optional[float]
    scored_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict):
    id: str
    application_id: str
    borrower_id: str
    principal_cents: int
    apr: float
    term_months: int
    committed_cents: int
    outstanding_principal_cents: int
    late_fee_outstanding_cents: int
    current_period_index: int
    missed_payment_count: int
    last_assessed_period_index: int
    status: str
    funded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Investor(TypedDict):
    id: str
    display_name: str
    capital_base_cents: int
    committed_capital_cents: int
    max_single_loan_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Investment(TypedDict):
    id: str
    investor_id: str
    loan_id: str
    amount_cents: int
    outstanding_principal_cents: int
    charged_off_basis_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Repayment(TypedDict):
    id: str
    loan_id: str
    amount_cents: int
    kind: str
    late_fee_paid_cents: int
    interest_paid_cents: int
    principal_paid_cents: int
    platform_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class ComplianceDisclosure(TypedDict):
    id: str
    loan_id: str
    document_type: str
    filed_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only entity (common_fields: false -> only id + created_at) ---

class RepaymentAllocation(TypedDict):
    id: str
    repayment_id: str
    investment_id: str
    principal_amount_cents: int
    interest_amount_cents: int
    created_at: str
