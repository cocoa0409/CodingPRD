"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class ClientStatus(str, Enum):
    INTAKE_REVIEW = "INTAKE_REVIEW"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class EntitlementStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    TERMINATED = "TERMINATED"


class ClaimType(str, Enum):
    SSI = "SSI"
    SSDI = "SSDI"


class AccountType(str, Enum):
    OPERATING = "OPERATING"
    RESTRICTED = "RESTRICTED"
    DEDICATED = "DEDICATED"


class AccountStatus(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class LedgerEntryType(str, Enum):
    DEPOSIT_POSTED = "DEPOSIT_POSTED"
    DEPOSIT_RETURNED = "DEPOSIT_RETURNED"
    DISBURSEMENT_RELEASED = "DISBURSEMENT_RELEASED"
    DISBURSEMENT_RETURNED = "DISBURSEMENT_RETURNED"


class BudgetPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class Category(str, Enum):
    HOUSING = "HOUSING"
    FOOD = "FOOD"
    CLOTHING = "CLOTHING"
    PERSONAL = "PERSONAL"
    MEDICAL = "MEDICAL"
    EDUCATION = "EDUCATION"
    SAVINGS = "SAVINGS"


class DisbursementStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PENDING_CONSERVATOR = "PENDING_CONSERVATOR"
    APPROVED = "APPROVED"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    RETURNED = "RETURNED"


class DepositSource(str, Enum):
    SSA_BENEFIT = "SSA_BENEFIT"
    PENSION = "PENSION"
    REFUND = "REFUND"
    OTHER = "OTHER"


class DepositStatus(str, Enum):
    RECEIVED = "RECEIVED"
    POSTED = "POSTED"
    RETURNED = "RETURNED"


class CourtOrderType(str, Enum):
    RESTRICTED_WITHDRAWAL = "RESTRICTED_WITHDRAWAL"
    REPORT_EXTENSION = "REPORT_EXTENSION"
    BOND_RELIEF = "BOND_RELIEF"


class CourtOrderStatus(str, Enum):
    PETITIONED = "PETITIONED"
    GRANTED = "GRANTED"
    EXECUTED = "EXECUTED"
    EXPIRED = "EXPIRED"


class BondStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"


class ReportType(str, Enum):
    SSA_6233 = "SSA_6233"
    COURT_ANNUAL = "COURT_ANNUAL"


class ReportBasis(str, Enum):
    CASH = "CASH"
    ACCRUAL = "ACCRUAL"


class ReportStatus(str, Enum):
    DRAFTING = "DRAFTING"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class SpendDownStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    MET = "MET"
    LAPSED = "LAPSED"


class AuditAuthority(str, Enum):
    SSA = "SSA"
    STATE_COURT = "STATE_COURT"
    BONDING_COMPANY = "BONDING_COMPANY"


class AuditScope(str, Enum):
    CLIENT_ACCOUNT = "CLIENT_ACCOUNT"
    ORG_WIDE = "ORG_WIDE"


class AuditStatus(str, Enum):
    OPENED = "OPENED"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    CLOSED_NO_ACTION = "CLOSED_NO_ACTION"
    MISUSE_CONFIRMED = "MISUSE_CONFIRMED"


class AuthorityScope(str, Enum):
    EXCLUSIVE = "EXCLUSIVE"
    SHARED = "SHARED"
    ADVISORY = "ADVISORY"


class ConservatorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DISCHARGED = "DISCHARGED"


class UserRole(str, Enum):
    FIDUCIARY_ADMIN = "FiduciaryAdmin"
    CASE_MANAGER = "CaseManager"
    FINANCIAL_OFFICER = "FinancialOfficer"
    CONSERVATOR_OFFICER = "ConservatorOfficer"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"


# --- Entity TypedDicts ---
# All entities except LedgerEntry carry common fields:
# id, created_at, updated_at, version.


class Client(TypedDict, total=False):
    id: str
    legal_name: str
    date_of_birth: str
    ssn_last4: str
    county_of_residence: str
    medicaid_enrolled: bool
    medicaid_resource_limit_cents: int
    status: str
    total_funds_cents: int
    countable_resources_cents: int
    medicaid_at_risk: bool
    created_at: str
    updated_at: str
    version: int


class BenefitEntitlement(TypedDict, total=False):
    id: str
    client_id: str
    claim_type: str
    monthly_benefit_cents: int
    effective_start_date: str
    effective_end_date: Optional[str]
    status: str
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrustAccount(TypedDict, total=False):
    id: str
    client_id: str
    account_type: str
    bank_account_ref: str
    balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LedgerEntry(TypedDict, total=False):
    # Append-only: carries ONLY id + created_at (no updated_at, no version)
    id: str
    account_id: str
    entry_type: str
    amount_cents: int
    reference_id: str
    balance_after_cents: int
    created_at: str


class BudgetLine(TypedDict):
    category: str
    percent: int


class AllocatedLine(TypedDict):
    category: str
    amount_cents: int


class BudgetPlan(TypedDict, total=False):
    id: str
    client_id: str
    period_month: str
    source_benefit_cents: int
    lines: List[BudgetLine]
    allocated_lines: List[AllocatedLine]
    total_planned_cents: int
    status: str
    superseded_by_plan_id: Optional[str]
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict, total=False):
    id: str
    client_id: str
    account_id: str
    budget_plan_id: str
    court_order_id: Optional[str]
    spend_down_plan_id: Optional[str]
    payee_name: str
    category: str
    amount_cents: int
    scheduled_release_date: str
    requested_by_user_id: str
    approved_by_user_id: Optional[str]
    co_approved_by_conservator_id: Optional[str]
    fee_cents: int
    released_at: Optional[str]
    returned_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Deposit(TypedDict, total=False):
    id: str
    account_id: str
    entitlement_id: Optional[str]
    source: str
    amount_cents: int
    received_date: str
    posted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CourtOrder(TypedDict, total=False):
    id: str
    client_id: str
    order_type: str
    amount_limit_cents: Optional[int]
    petitioned_date: str
    granted_date: Optional[str]
    expiry_date: str
    executed_disbursement_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SuretyBond(TypedDict, total=False):
    id: str
    coverage_amount_cents: int
    coverage_start_date: str
    coverage_end_date: str
    premium_paid_through_date: str
    status: str
    funds_under_management_cents: int
    utilization_bps: int
    created_at: str
    updated_at: str
    version: int


class AccountingReport(TypedDict, total=False):
    id: str
    client_id: str
    report_type: str
    period_start_date: str
    period_end_date: str
    basis: str
    due_date: str
    receipts_total_cents: Optional[int]
    disbursements_total_cents: Optional[int]
    opening_balance_cents: Optional[int]
    ending_balance_cents: Optional[int]
    submitted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SpendDownEntry(TypedDict):
    category: str
    planned_amount_cents: int


class SpendDownPlan(TypedDict, total=False):
    id: str
    client_id: str
    target_month: str
    entries: List[SpendDownEntry]
    provisional_excess_cents: int
    final_excess_cents: Optional[int]
    auto_created: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditCase(TypedDict, total=False):
    id: str
    client_id: str
    authority: str
    scope: str
    period_start_date: str
    period_end_date: str
    misuse_amount_cents: Optional[int]
    findings_count: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Conservator(TypedDict, total=False):
    id: str
    client_id: str
    full_name: str
    court_case_number: str
    authority_scope: str
    appointed_date: str
    status: str
    created_at: str
    updated_at: str
    version: int
