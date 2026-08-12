"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Any, List, Optional, TypedDict


class UserRole(str, Enum):
    PARTICIPANT = "Participant"
    PLAN_SPONSOR_ADMIN = "PlanSponsorAdmin"
    ROLLOVER_PROCESSOR = "RolloverProcessor"
    TAX_REPORTING_OFFICER = "TaxReportingOfficer"
    OPERATIONS_AGENT = "OperationsAgent"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    TERMINATED = "TERMINATED"


class PlanType(str, Enum):
    PLAN_401K = "PLAN_401K"
    PLAN_403B = "PLAN_403B"
    PLAN_457B = "PLAN_457B"
    IRA = "IRA"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SEPARATED = "SEPARATED"
    RETIRED = "RETIRED"
    DISABLED = "DISABLED"


class MaritalStatus(str, Enum):
    SINGLE = "SINGLE"
    MARRIED = "MARRIED"
    WIDOWED = "WIDOWED"
    DIVORCED = "DIVORCED"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class SourceType(str, Enum):
    PRE_TAX = "PRE_TAX"
    EMPLOYER_PRETAX = "EMPLOYER_PRETAX"
    ROTH = "ROTH"
    AFTER_TAX = "AFTER_TAX"


class LoanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TRANSFERRED = "TRANSFERRED"
    OFFSET = "OFFSET"


class CaseType(str, Enum):
    DIRECT_ROLLOVER_OUT = "DIRECT_ROLLOVER_OUT"
    INDIRECT_ROLLOVER_OUT = "INDIRECT_ROLLOVER_OUT"
    PLAN_TRANSFER = "PLAN_TRANSFER"
    IN_PLAN_ROTH_CONVERSION = "IN_PLAN_ROTH_CONVERSION"
    ROLLOVER_IN = "ROLLOVER_IN"


class CaseStatus(str, Enum):
    DRAFT = "DRAFT"
    DOCS_PENDING = "DOCS_PENDING"
    ELIGIBILITY_REVIEW = "ELIGIBILITY_REVIEW"
    ELIGIBLE = "ELIGIBLE"
    DENIED = "DENIED"
    DISBURSED = "DISBURSED"
    AWAITING_REDEPOSIT = "AWAITING_REDEPOSIT"
    ACCEPTANCE_PENDING = "ACCEPTANCE_PENDING"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    INCOMPLETE = "INCOMPLETE"
    CANCELLED = "CANCELLED"


class QualifyingEvent(str, Enum):
    PLAN_TERMINATION = "PLAN_TERMINATION"
    SEPARATION = "SEPARATION"
    DISABILITY = "DISABILITY"
    AGE_59_HALF = "AGE_59_HALF"
    NONE = "NONE"


class DocType(str, Enum):
    SPOUSAL_CONSENT = "SPOUSAL_CONSENT"
    SEPARATION_VERIFICATION = "SEPARATION_VERIFICATION"
    DISABILITY_PROOF = "DISABILITY_PROOF"
    IDENTITY_PROOF = "IDENTITY_PROOF"
    RECEIVING_PLAN_ACCEPTANCE = "RECEIVING_PLAN_ACCEPTANCE"
    SOURCE_PLAN_STATEMENT = "SOURCE_PLAN_STATEMENT"


class DocumentStatus(str, Enum):
    REQUIRED = "REQUIRED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class VerificationDirection(str, Enum):
    OUTBOUND = "OUTBOUND"
    INBOUND = "INBOUND"


class VerificationMethod(str, Enum):
    PLAN_LETTER = "PLAN_LETTER"
    IRS_FORM_LOOKUP = "IRS_FORM_LOOKUP"
    THIRD_PARTY_REGISTRY = "THIRD_PARTY_REGISTRY"


class VerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class DisbursementMethod(str, Enum):
    CHECK = "CHECK"
    ACH = "ACH"
    WIRE = "WIRE"
    INTERNAL_BOOK_ENTRY = "INTERNAL_BOOK_ENTRY"


class DisbursementStatus(str, Enum):
    PENDING = "PENDING"
    ISSUED = "ISSUED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class RedepositStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    CREDITED = "CREDITED"
    REJECTED = "REJECTED"


class NoticeStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SENT = "SENT"
    SKIPPED = "SKIPPED"


class TaxFormType(str, Enum):
    FORM_1099_R = "FORM_1099_R"
    FORM_5498 = "FORM_5498"


class TaxFormStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"


class DistributionCode(str, Enum):
    CODE_1 = "CODE_1"
    CODE_7 = "CODE_7"
    CODE_G = "CODE_G"


# All entities carry the standard system-managed fields of PRD §2.5:
# id, created_at, updated_at, version.


class Plan(TypedDict, total=False):
    id: str
    plan_name: str
    plan_type: str
    status: str
    accepts_incoming_rollovers: bool
    accepts_incoming_transfers: bool
    accepts_loan_transfers: bool
    accepts_after_tax_basis: bool
    allows_in_plan_roth_conversion: bool
    requires_spousal_consent: bool
    spousal_consent_threshold_cents: int
    created_at: str
    updated_at: str
    version: int


class PlanFreezeWindow(TypedDict, total=False):
    id: str
    plan_id: str
    start_date: str
    end_date: str
    reason: str
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    employment_status: str
    separation_date: Optional[str]
    marital_status: str
    age_months: int
    current_age_years: float
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict, total=False):
    id: str
    participant_id: str
    plan_id: str
    status: str
    total_balance_cents: int
    vested_balance_cents: int
    basis_cents: int
    created_at: str
    updated_at: str
    version: int


class MoneySourceBalance(TypedDict, total=False):
    id: str
    account_id: str
    source_type: str
    balance_cents: int
    basis_cents: int
    vested_pct: int
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict, total=False):
    id: str
    account_id: str
    outstanding_balance_cents: int
    interest_rate_bp: int
    term_months: int
    status: str
    offset_at: Optional[str]
    offset_qualified: Optional[bool]
    offset_rollover_deadline: Optional[str]
    offset_repaid_cents: int
    created_at: str
    updated_at: str
    version: int


class RolloverCase(TypedDict, total=False):
    id: str
    case_type: str
    source_account_id: Optional[str]
    receiving_account_id: Optional[str]
    receiving_plan_id: Optional[str]
    receiving_institution_name: Optional[str]
    requested_amount_cents: Optional[int]
    withholding_acknowledged: bool
    status: str
    prior_status: Optional[str]
    qualifying_event: Optional[str]
    gross_cents: Optional[int]
    basis_portion_cents: Optional[int]
    taxable_cents: Optional[int]
    withholding_cents: Optional[int]
    net_cents: Optional[int]
    forfeiture_cents: int
    disbursement_issued_date: Optional[str]
    rollover_deadline_date: Optional[str]
    credited_total_cents: int
    eligibility_decided_by: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RequiredDocument(TypedDict, total=False):
    id: str
    rollover_case_id: str
    doc_type: str
    status: str
    submitted_by: Optional[str]
    reviewed_by: Optional[str]
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SourcePlanVerification(TypedDict, total=False):
    id: str
    rollover_case_id: str
    direction: str
    method: str
    status: str
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict, total=False):
    id: str
    rollover_case_id: str
    method: str
    gross_cents: int
    withholding_cents: int
    net_cents: int
    issued_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Redeposit(TypedDict, total=False):
    id: str
    rollover_case_id: Optional[str]
    loan_id: Optional[str]
    receiving_account_id: str
    amount_cents: int
    received_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FollowUpNotice(TypedDict, total=False):
    id: str
    rollover_case_id: str
    notice_seq: int
    scheduled_date: str
    status: str
    days_remaining: Optional[int]
    outstanding_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class TaxForm(TypedDict, total=False):
    id: str
    form_type: str
    tax_year: int
    participant_id: str
    rollover_case_id: Optional[str]
    loan_id: Optional[str]
    gross_distribution_cents: Optional[int]
    taxable_amount_cents: Optional[int]
    federal_withholding_cents: Optional[int]
    distribution_code: Optional[str]
    rollover_contribution_cents: Optional[int]
    fair_market_value_cents: Optional[int]
    status: str
    supersedes_id: Optional[str]
    revision: int
    created_at: str
    updated_at: str
    version: int
