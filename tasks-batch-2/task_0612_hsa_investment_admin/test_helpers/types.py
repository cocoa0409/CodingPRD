"""Domain types: entity TypedDicts, status enums, role enum.

All monetary amounts are integer cents. All timestamps are ISO 8601 UTC.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ────────────────────────────────────────────────────────────

class AccountLifecycleStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class ContributionPosture(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"


class PayrollPeriodStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class CoverageTier(str, Enum):
    SELF_ONLY = "SELF_ONLY"
    FAMILY = "FAMILY"


class CoveragePeriodStatus(str, Enum):
    ATTESTED = "ATTESTED"
    SUPERSEDED = "SUPERSEDED"


class ContributionChannel(str, Enum):
    PAYROLL = "PAYROLL"
    INDIVIDUAL = "INDIVIDUAL"


class ContributionKind(str, Enum):
    REGULAR = "REGULAR"
    CATCH_UP = "CATCH_UP"


class ContributionStatus(str, Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class InvestmentSweepStatus(str, Enum):
    EXECUTED = "EXECUTED"
    UNWOUND = "UNWOUND"


class DistributionMethod(str, Enum):
    DEBIT_CARD = "DEBIT_CARD"
    REIMBURSEMENT = "REIMBURSEMENT"


class DistributionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CLEARED = "CLEARED"
    DENIED = "DENIED"
    REVERSED = "REVERSED"


class SubstantiationStatus(str, Enum):
    UNSUBSTANTIATED = "UNSUBSTANTIATED"
    QUALIFIED = "QUALIFIED"
    NONQUALIFIED = "NONQUALIFIED"


class ReceiptStatus(str, Enum):
    VAULTED = "VAULTED"
    CONSUMED = "CONSUMED"


class DebitCardStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ExcessCorrectionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


class TaxFormType(str, Enum):
    FORM_1099_SA = "FORM_1099_SA"
    FORM_5498_SA = "FORM_5498_SA"


class UserRole(str, Enum):
    ACCOUNTHOLDER = "Accountholder"
    EMPLOYER = "Employer"
    ACCOUNT_ADMIN = "AccountAdmin"


# ─── Entity TypedDicts ───────────────────────────────────────────────────────
# Entities carrying the full common-field set: id, created_at, updated_at, version.

class Accountholder(TypedDict):
    id: str
    full_name: str
    email: str
    date_of_birth: str
    turns_55_or_older_in_plan_year: bool
    created_at: str
    updated_at: str
    version: int


class Employer(TypedDict):
    id: str
    name: str
    payroll_contributions_enabled: bool
    created_at: str
    updated_at: str
    version: int


class PayrollPeriod(TypedDict):
    id: str
    employer_id: str
    period_start_day: int
    period_end_day: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HsaAccount(TypedDict):
    id: str
    accountholder_id: str
    employer_id: Optional[str]
    plan_year: int
    lifecycle_status: str
    contribution_posture: str
    cash_balance_cents: int
    invested_balance_cents: int
    contributions_ytd_cents: int
    applicable_limit_cents: int
    excess_contribution_cents: int
    invest_threshold_cents: int
    sweep_increment_cents: int
    verification_token: str
    created_at: str
    updated_at: str
    version: int


class CoveragePeriod(TypedDict):
    id: str
    account_id: str
    coverage_tier: str
    effective_month: int
    end_month: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Contribution(TypedDict):
    id: str
    account_id: str
    channel: str
    amount_cents: int
    contribution_kind: str
    status: str
    posted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InvestmentSweep(TypedDict):
    id: str
    account_id: str
    requested_amount_cents: Optional[int]
    swept_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Distribution(TypedDict):
    id: str
    account_id: str
    method: str
    amount_cents: int
    card_id: Optional[str]
    substantiation_status: str
    status: str
    receipt_id: Optional[str]
    cleared_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Receipt(TypedDict):
    id: str
    account_id: str
    distribution_id: Optional[str]
    merchant: str
    service_date: str
    amount_cents: int
    is_qualified_medical: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class DebitCard(TypedDict):
    id: str
    account_id: str
    last_four: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ExcessCorrection(TypedDict):
    id: str
    account_id: str
    requested_amount_cents: int
    corrected_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Immutable snapshot: carries ONLY id + created_at (no updated_at, no version).
class TaxForm(TypedDict):
    id: str
    account_id: str
    form_type: str
    tax_year: int
    gross_amount_cents: int
    nonqualified_amount_cents: int
    fair_market_value_cents: int
    created_at: str
