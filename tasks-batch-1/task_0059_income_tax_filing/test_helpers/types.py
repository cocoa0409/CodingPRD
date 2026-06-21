"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    TAXPAYER = "Taxpayer"
    PREPARER = "Preparer"
    IRS_GATEWAY = "IrsGateway"


class FilingStatus(str, Enum):
    SINGLE = "SINGLE"
    MARRIED_JOINT = "MARRIED_JOINT"
    MARRIED_SEPARATE = "MARRIED_SEPARATE"
    HEAD_OF_HOUSEHOLD = "HEAD_OF_HOUSEHOLD"


class DeductionMethod(str, Enum):
    STANDARD = "STANDARD"
    ITEMIZED = "ITEMIZED"


class TaxReturnStatus(str, Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    FILED = "FILED"
    REJECTED = "REJECTED"
    AMENDED = "AMENDED"
    SUPERSEDED = "SUPERSEDED"


class DocType(str, Enum):
    W2 = "W2"
    NEC = "1099_NEC"
    INT = "1099_INT"
    DIV = "1099_DIV"
    B = "1099_B"


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


class Quarter(str, Enum):
    Q1 = "Q1"
    Q2 = "Q2"
    Q3 = "Q3"
    Q4 = "Q4"


class EFilingStatus(str, Enum):
    TRANSMITTED = "TRANSMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class AmendedReturnStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"


# --- Entity TypedDicts (all entities carry common_fields: true) ---

class Taxpayer(TypedDict):
    id: str
    email: str
    full_name: str
    filing_status: str
    prior_year_agi_cents: int
    prior_year_total_tax_cents: int
    created_at: str
    updated_at: str
    version: int


class TaxReturn(TypedDict):
    id: str
    taxpayer_id: str
    tax_year: int
    filing_status: str
    status: str
    deduction_method: str
    total_income_cents: int
    agi_cents: int
    taxable_income_cents: int
    tax_before_credits_cents: int
    total_credits_cents: int
    tax_after_credits_cents: int
    total_payments_cents: int
    balance_due_cents: int
    computed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncomeDocument(TypedDict):
    id: str
    return_id: str
    doc_type: str
    payer_name: str
    box_amount_cents: int
    federal_withholding_cents: int
    qualified_dividends_cents: int
    proceeds_cents: int
    cost_basis_cents: int
    holding_long_term: bool
    created_at: str
    updated_at: str
    version: int


class Schedule(TypedDict):
    id: str
    return_id: str
    schedule_type: str
    gross_amount_cents: int
    expense_amount_cents: int
    net_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Dependent(TypedDict):
    id: str
    return_id: str
    full_name: str
    age_years: int
    is_student: bool
    qualifies_ctc: bool
    created_at: str
    updated_at: str
    version: int


class CreditClaim(TypedDict):
    id: str
    return_id: str
    credit_type: str
    claimed_amount_cents: int
    allowed_amount_cents: int
    refundable_cents: int
    created_at: str
    updated_at: str
    version: int


class EstimatedTaxPayment(TypedDict):
    id: str
    return_id: str
    quarter: str
    amount_cents: int
    paid_on: str
    period_start: str
    period_end: str
    on_time: bool
    created_at: str
    updated_at: str
    version: int


class EFilingSubmission(TypedDict):
    id: str
    return_id: str
    status: str
    signature_pin: str
    ack_code: Optional[str]
    snapshot_balance_due_cents: int
    superseded_by_amendment: bool
    created_at: str
    updated_at: str
    version: int


class AmendedReturn(TypedDict):
    id: str
    original_return_id: str
    taxpayer_id: str
    status: str
    corrected_balance_due_cents: int
    correction_period_start: str
    correction_period_end: str
    delta_cents: int
    created_at: str
    updated_at: str
    version: int
