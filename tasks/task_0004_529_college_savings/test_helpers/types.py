"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    ACCOUNT_OWNER = "AccountOwner"
    CUSTODIAN_AGENT = "CustodianAgent"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    SYSTEM_TAX_AUTHORITY = "SystemTaxAuthority"


class AccountStatus(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class ScheduledContributionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class ContributionKind(str, Enum):
    LUMP_SUM = "LUMP_SUM"
    RECURRING = "RECURRING"


class ContributionStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class ScheduleCadence(str, Enum):
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"


class WithdrawalStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
    DISBURSED = "DISBURSED"


class ExpenseClass(str, Enum):
    HIGHER_ED_TUITION = "HIGHER_ED_TUITION"
    ROOM_BOARD = "ROOM_BOARD"
    BOOKS_SUPPLIES = "BOOKS_SUPPLIES"
    K_12_TUITION = "K_12_TUITION"
    APPRENTICESHIP = "APPRENTICESHIP"
    NON_QUALIFIED = "NON_QUALIFIED"


class BeneficiaryChangeStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RelationshipClass(str, Enum):
    SELF = "SELF"
    CHILD = "CHILD"
    SIBLING = "SIBLING"
    FIRST_COUSIN = "FIRST_COUSIN"
    OTHER = "OTHER"


class StateTaxIncentiveStatus(str, Enum):
    DRAFT = "DRAFT"
    CALCULATED = "CALCULATED"
    FINALIZED = "FINALIZED"


class Form1099QStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    CORRECTED = "CORRECTED"
    REISSUED = "REISSUED"


class Form1099QRecipientKind(str, Enum):
    ACCOUNT_OWNER = "ACCOUNT_OWNER"
    BENEFICIARY = "BENEFICIARY"


class StateCode(str, Enum):
    CA = "CA"
    NY = "NY"
    IL = "IL"
    TX = "TX"
    FL = "FL"
    OH = "OH"


# --- Entity TypedDicts (common_fields: true) ---

class Donor(TypedDict):
    id: str
    full_name: str
    state_code: str
    federal_tax_id_last4: str
    email: str
    created_at: str
    updated_at: str
    version: int


class Beneficiary(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    relationship_class: str
    federal_tax_id_last4: str
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    donor_id: str
    beneficiary_id: str
    status: str
    total_basis_cents: int
    total_earnings_cents: int
    account_balance_cents: int
    ytd_qualified_k12_cents: int
    tax_year: int
    created_at: str
    updated_at: str
    version: int


class ScheduledContribution(TypedDict):
    id: str
    account_id: str
    amount_cents: int
    cadence: str
    next_run_utc: str
    status: str
    posted_runs: int
    created_at: str
    updated_at: str
    version: int


class Contribution(TypedDict):
    id: str
    account_id: str
    amount_cents: int
    contribution_kind: str
    scheduled_contribution_id: Optional[str]
    status: str
    posted_at_utc: Optional[str]
    tax_year: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Withdrawal(TypedDict):
    id: str
    account_id: str
    amount_cents: int
    expense_class: str
    status: str
    basis_portion_cents: Optional[int]
    earnings_portion_cents: Optional[int]
    penalty_cents: int
    k12_excess_cents: int
    tax_year: Optional[int]
    approved_at_utc: Optional[str]
    disbursed_at_utc: Optional[str]
    rejection_count: int
    created_at: str
    updated_at: str
    version: int


class BeneficiaryChange(TypedDict):
    id: str
    account_id: str
    from_beneficiary_id: str
    to_beneficiary_id: str
    from_relationship_class: str
    to_relationship_class: str
    status: str
    decided_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StateTaxIncentive(TypedDict):
    id: str
    donor_id: str
    tax_year: int
    contributions_eligible_cents: int
    match_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Form1099Q(TypedDict):
    id: str
    account_id: str
    tax_year: int
    gross_distribution_cents: int
    earnings_cents: int
    basis_cents: int
    penalty_cents: int
    recipient_kind: str
    recipient_tax_id_last4: Optional[str]
    status: str
    issued_at_utc: Optional[str]
    supersedes_form_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — only id and created_at-equivalent (ClockState only carries current_utc)
class ClockState(TypedDict):
    current_utc: str
