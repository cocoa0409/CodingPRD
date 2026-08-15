"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    TRUST_OFFICER = "TrustOfficer"
    TRUST_EXECUTIVE = "TrustExecutive"
    INVESTMENT_MANAGER = "InvestmentManager"
    TRUST_OPERATIONS_OFFICER = "TrustOperationsOfficer"
    TAX_SPECIALIST = "TaxSpecialist"
    COMMITTEE_MEMBER = "CommitteeMember"
    BENEFICIARY = "Beneficiary"


class TrustAccountStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_ACCEPTANCE_REVIEW = "UNDER_ACCEPTANCE_REVIEW"
    ACCEPTANCE_DECLINED = "ACCEPTANCE_DECLINED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATING = "TERMINATING"
    TERMINATED = "TERMINATED"
    CLOSED = "CLOSED"


class TrustType(str, Enum):
    REVOCABLE = "REVOCABLE"
    IRREVOCABLE = "IRREVOCABLE"
    TESTAMENTARY = "TESTAMENTARY"
    CHARITABLE = "CHARITABLE"


class DistributionStandard(str, Enum):
    HEMS = "HEMS"
    SUPPORT = "SUPPORT"
    DISCRETIONARY = "DISCRETIONARY"


class TrustDocumentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    INTERPRETED = "INTERPRETED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class BeneficiaryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECEASED = "DECEASED"


class BeneficiaryClass(str, Enum):
    INCOME = "INCOME"
    REMAINDER = "REMAINDER"


class CommitteeMemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class DistributionRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFORMATION_REQUESTED = "INFORMATION_REQUESTED"
    VOTING = "VOTING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    DISBURSED = "DISBURSED"
    WITHDRAWN = "WITHDRAWN"
    CANCELLED = "CANCELLED"


class AllocationSource(str, Enum):
    INCOME_ONLY = "INCOME_ONLY"
    PRINCIPAL_ONLY = "PRINCIPAL_ONLY"
    INCOME_FIRST = "INCOME_FIRST"
    PRINCIPAL_FIRST = "PRINCIPAL_FIRST"


class PurposeCategory(str, Enum):
    HEALTH = "HEALTH"
    EDUCATION = "EDUCATION"
    MAINTENANCE = "MAINTENANCE"
    SUPPORT = "SUPPORT"
    TRAVEL = "TRAVEL"
    LUXURY = "LUXURY"
    OTHER = "OTHER"


class VoteValue(str, Enum):
    APPROVE = "APPROVE"
    DECLINE = "DECLINE"
    ABSTAIN = "ABSTAIN"


class IpsStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class AssetClass(str, Enum):
    EQUITY = "EQUITY"
    FIXED_INCOME = "FIXED_INCOME"
    CASH_EQUIVALENT = "CASH_EQUIVALENT"
    ALTERNATIVE = "ALTERNATIVE"


class HoldingStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ReviewStatus(str, Enum):
    OPEN = "OPEN"
    REMEDIATION_PLANNED = "REMEDIATION_PLANNED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class ReviewDirection(str, Enum):
    OVERWEIGHT = "OVERWEIGHT"
    UNDERWEIGHT = "UNDERWEIGHT"


class ReviewSeverity(str, Enum):
    STANDARD = "STANDARD"
    CRITICAL = "CRITICAL"


class EntryKind(str, Enum):
    RECEIPT = "RECEIPT"
    DISBURSEMENT = "DISBURSEMENT"
    FEE = "FEE"
    DISTRIBUTION = "DISTRIBUTION"
    TAX_PAYMENT = "TAX_PAYMENT"
    INVESTMENT_PURCHASE = "INVESTMENT_PURCHASE"
    INVESTMENT_SALE = "INVESTMENT_SALE"
    ADJUSTMENT = "ADJUSTMENT"


class Bucket(str, Enum):
    INCOME = "INCOME"
    PRINCIPAL = "PRINCIPAL"


class ReceiptType(str, Enum):
    INITIAL_FUNDING = "INITIAL_FUNDING"
    INTEREST = "INTEREST"
    ORDINARY_DIVIDEND = "ORDINARY_DIVIDEND"
    RENTAL_INCOME = "RENTAL_INCOME"
    MINERAL_ROYALTY = "MINERAL_ROYALTY"
    CAPITAL_GAIN_DISTRIBUTION = "CAPITAL_GAIN_DISTRIBUTION"
    SALE_PROCEEDS = "SALE_PROCEEDS"


class FeeVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class FeeStatus(str, Enum):
    CALCULATED = "CALCULATED"
    DISCLOSED = "DISCLOSED"
    DISPUTED = "DISPUTED"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    DELIVERED = "DELIVERED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISPUTED = "DISPUTED"
    SUPERSEDED = "SUPERSEDED"


class FilingStatus(str, Enum):
    DATA_COLLECTION = "DATA_COLLECTION"
    PREPARED = "PREPARED"
    UNDER_REVIEW = "UNDER_REVIEW"
    FILED = "FILED"
    ACCEPTED = "ACCEPTED"
    AMENDMENT_REQUIRED = "AMENDMENT_REQUIRED"


class TerminationCaseStatus(str, Enum):
    INITIATED = "INITIATED"
    LIABILITIES_RESERVED = "LIABILITIES_RESERVED"
    TAX_CLEARANCE_RECEIVED = "TAX_CLEARANCE_RECEIVED"
    FINAL_ACCOUNTING_APPROVED = "FINAL_ACCOUNTING_APPROVED"
    DISTRIBUTED = "DISTRIBUTED"
    CLOSED = "CLOSED"


# --- Entity TypedDicts ---
# Primary resources carry id + created_at + updated_at + version (PRD §2.4).
# CommitteeVote and LedgerEntry are leaner: only id + created_at (PRD §2.4).


class TrustAccount(TypedDict, total=False):
    id: str
    trust_name: str
    trust_type: str
    grantor_name: str
    governing_state: str
    ein: str
    fiscal_year_end_month: int
    distribution_standard: str
    status: str
    accepted_at: Optional[str]
    income_balance_cents: int
    principal_balance_cents: int
    reserved_income_cents: int
    reserved_principal_cents: int
    available_income_cents: int
    available_principal_cents: int
    total_market_value_cents: int
    pending_distribution_count: int
    created_at: str
    updated_at: str
    version: int


class TrustDocument(TypedDict, total=False):
    id: str
    trust_id: str
    version_number: int
    prior_document_id: Optional[str]
    summary: Optional[str]
    per_stirpes: bool
    interpretation_notes: str
    status: str
    submitted_at: Optional[str]
    approved_at: Optional[str]
    rejected_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Beneficiary(TypedDict, total=False):
    id: str
    trust_id: str
    full_name: str
    beneficiary_class: str
    share_bps: int
    date_of_birth: str
    status: str
    deceased_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommitteeMember(TypedDict, total=False):
    id: str
    full_name: str
    term_start: str
    term_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DistributionRequest(TypedDict, total=False):
    id: str
    trust_id: str
    beneficiary_id: str
    amount_cents: int
    allocation_source: str
    purpose_category: str
    purpose_note: Optional[str]
    status: str
    income_portion_cents: int
    principal_portion_cents: int
    approve_count: int
    decline_count: int
    abstain_count: int
    committee_size_snapshot: int
    opened_by_user_id: Optional[str]
    decision_at: Optional[str]
    disbursed_at: Optional[str]
    cancelled_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommitteeVote(TypedDict, total=False):
    id: str
    distribution_request_id: str
    committee_member_id: str
    vote: str
    created_at: str


class InvestmentPolicyStatement(TypedDict, total=False):
    id: str
    trust_id: str
    effective_from: str
    effective_to: str
    equity_target_pct: float
    equity_band_pct: float
    fixed_income_target_pct: float
    fixed_income_band_pct: float
    alternatives_allowed: bool
    status: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InvestmentHolding(TypedDict, total=False):
    id: str
    trust_id: str
    asset_class: str
    ticker: str
    units: int
    unit_price_cents: int
    market_value_cents: int
    cost_basis_cents: int
    priced_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceReview(TypedDict, total=False):
    id: str
    trust_id: str
    investment_policy_statement_id: str
    asset_class: str
    direction: str
    measured_weight_pct: float
    band_limit_pct: float
    severity: str
    status: str
    remediation_note: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LedgerEntry(TypedDict, total=False):
    id: str
    trust_id: str
    entry_kind: str
    bucket: str
    amount_cents: int
    receipt_type: Optional[str]
    value_date: str
    description: Optional[str]
    source_entity_type: str
    source_entity_id: Optional[str]
    created_at: str


class FeeAssessment(TypedDict, total=False):
    id: str
    trust_id: str
    period_start: str
    period_end: str
    variant: str
    base_market_value_cents: int
    annual_fee_cents: int
    assessed_fee_cents: int
    income_portion_cents: int
    principal_portion_cents: int
    status: str
    calculated_by_user_id: str
    disclosed_by_user_id: Optional[str]
    posted_by_user_id: Optional[str]
    disclosed_at: Optional[str]
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AnnualStatement(TypedDict, total=False):
    id: str
    trust_id: str
    fiscal_year: int
    opening_income_cents: int
    opening_principal_cents: int
    receipts_income_cents: int
    receipts_principal_cents: int
    disbursements_cents: int
    fees_cents: int
    distributions_cents: int
    closing_income_cents: int
    closing_principal_cents: int
    status: str
    delivered_at: Optional[str]
    acknowledged_at: Optional[str]
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TaxReturnFiling(TypedDict, total=False):
    id: str
    trust_id: str
    tax_year: int
    tentative_dni_cents: int
    dni_cents: int
    elected_65day_amount_cents: int
    distribution_deduction_cents: int
    exemption_cents: int
    trust_taxable_income_cents: int
    status: str
    prepared_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    amendment_number: int
    filed_at: Optional[str]
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DistributionLine(TypedDict, total=False):
    beneficiary_id: str
    beneficiary_class: str
    amount_cents: int


class TerminationCase(TypedDict, total=False):
    id: str
    trust_id: str
    status: str
    reason: str
    initiated_by_user_id: str
    reserve_taxes_cents: int
    reserve_fees_cents: int
    distributable_income_cents: int
    distributable_principal_cents: int
    distribution_lines: List[DistributionLine]
    approved_by_user_id: Optional[str]
    distributed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
