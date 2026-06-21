"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Status / enum dimensions ---

class AccountFundingStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"
    CLOSED = "CLOSED"


class AccountComplianceHold(str, Enum):
    CLEAR = "CLEAR"
    HELD = "HELD"


class AccountType(str, Enum):
    HSA = "HSA"
    HEALTH_FSA = "HEALTH_FSA"
    DCFSA = "DCFSA"


class CoverageTier(str, Enum):
    SELF_ONLY = "SELF_ONLY"
    FAMILY = "FAMILY"


class MaritalStatus(str, Enum):
    SINGLE = "SINGLE"
    MARRIED_JOINT = "MARRIED_JOINT"
    MARRIED_SEPARATE = "MARRIED_SEPARATE"


class FsaReliefMode(str, Enum):
    NONE = "NONE"
    GRACE_PERIOD = "GRACE_PERIOD"
    CARRYOVER = "CARRYOVER"


class PlanYearLifecycle(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"


class ContributionSource(str, Enum):
    PAYROLL = "PAYROLL"
    EMPLOYER = "EMPLOYER"
    INDIVIDUAL = "INDIVIDUAL"


class ContributionStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class ExpenseCategory(str, Enum):
    MEDICAL = "MEDICAL"
    DENTAL = "DENTAL"
    VISION = "VISION"
    PRESCRIPTION = "PRESCRIPTION"
    DEPENDENT_CARE = "DEPENDENT_CARE"
    OTC = "OTC"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PENDING_SUBSTANTIATION = "PENDING_SUBSTANTIATION"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REIMBURSED = "REIMBURSED"
    VOIDED = "VOIDED"


class DenialReason(str, Enum):
    NOT_QUALIFIED = "NOT_QUALIFIED"
    OUTSIDE_WINDOW = "OUTSIDE_WINDOW"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"
    DUPLICATE = "DUPLICATE"


class BatchStatus(str, Enum):
    DRAFT = "DRAFT"
    SETTLED = "SETTLED"
    PARTIAL = "PARTIAL"


class LedgerEntryType(str, Enum):
    CONTRIBUTION = "CONTRIBUTION"
    CONTRIBUTION_REVERSAL = "CONTRIBUTION_REVERSAL"
    REIMBURSEMENT = "REIMBURSEMENT"
    REIMBURSEMENT_REVERSAL = "REIMBURSEMENT_REVERSAL"
    FORFEITURE = "FORFEITURE"
    CARRYOVER_OUT = "CARRYOVER_OUT"
    CARRYOVER_IN = "CARRYOVER_IN"


class UserRole(str, Enum):
    PLAN_ADMIN = "PlanAdmin"
    PARTICIPANT = "Participant"
    ADJUDICATOR = "Adjudicator"
    FUND_DISBURSER = "FundDisburser"


# --- Entity TypedDicts ---

# common_fields: true -> id, created_at, updated_at, version
class Participant(TypedDict):
    id: str
    email: str
    full_name: str
    birth_date: str
    marital_status: str
    hdhp_covered: bool
    created_at: str
    updated_at: str
    version: int


class PlanYear(TypedDict):
    id: str
    label: str
    coverage_start: str
    coverage_end: str
    run_out_end: str
    fsa_relief_mode: str
    grace_period_end: Optional[str]
    carryover_cap_cents: int
    hsa_individual_cap_cents: int
    hsa_family_cap_cents: int
    hsa_catchup_cents: int
    health_fsa_cap_cents: int
    dcfsa_cap_joint_cents: int
    dcfsa_cap_separate_cents: int
    lifecycle: str
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    participant_id: str
    plan_year_id: str
    account_type: str
    coverage_tier: str
    elected_amount_cents: int
    auto_adjudication_threshold_cents: int
    funding_status: str
    compliance_hold: str
    contributed_cents: int
    reimbursed_cents: int
    available_balance_cents: int
    forfeited_cents: int
    carried_in_cents: int
    carryover_source_account_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Contribution(TypedDict):
    id: str
    account_id: str
    amount_cents: int
    source: str
    posted_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    account_id: str
    service_date: str
    expense_category: str
    claimed_amount_cents: int
    substantiated: bool
    reimbursable_amount_cents: int
    status: str
    denial_reason: Optional[str]
    adjudicated_by: Optional[str]
    reimbursed_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReimbursementBatch(TypedDict):
    id: str
    participant_id: str
    claim_ids: List[str]
    total_reimbursed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> append-only, only id + created_at (no updated_at, no version)
class LedgerEntry(TypedDict):
    id: str
    account_id: str
    claim_id: Optional[str]
    entry_type: str
    amount_cents: int
    memo: str
    created_at: str


class ClockState(TypedDict):
    current_utc: str
