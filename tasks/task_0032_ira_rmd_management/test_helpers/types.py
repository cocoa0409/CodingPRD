"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── User Roles (PRD §2.1) ──────────────────────────────────────


class UserRole(str, Enum):
    PLAN_ADMINISTRATOR = "PlanAdministrator"
    ACCOUNT_OWNER = "AccountOwner"
    IRS_AUDITOR = "IRSAuditor"


# ─── Status enums for entities with state machines (PRD §3) ─────


class IRAAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CONVERSION_IN_PROGRESS = "CONVERSION_IN_PROGRESS"
    INHERITED = "INHERITED"
    CLOSED = "CLOSED"


class ContributionStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    REVERSED = "REVERSED"


class DistributionStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REVERSED = "REVERSED"


class ConversionStatus(str, Enum):
    INITIATED = "INITIATED"
    COMPLETED = "COMPLETED"
    REVERSED = "REVERSED"


class BeneficiaryDesignationStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    INHERITED = "INHERITED"


class RMDScheduleStatus(str, Enum):
    OPEN = "OPEN"
    SATISFIED = "SATISFIED"
    DELINQUENT = "DELINQUENT"


class RMDPosture(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    REQUIRED_PENDING = "REQUIRED_PENDING"
    REQUIRED_MET = "REQUIRED_MET"
    REQUIRED_DELINQUENT = "REQUIRED_DELINQUENT"


class FilingStatus(str, Enum):
    SINGLE = "SINGLE"
    MARRIED_JOINT = "MARRIED_JOINT"
    MARRIED_SEPARATE = "MARRIED_SEPARATE"
    HEAD_OF_HOUSEHOLD = "HEAD_OF_HOUSEHOLD"


class AccountType(str, Enum):
    TRADITIONAL = "TRADITIONAL"
    ROTH = "ROTH"


class ContributionKind(str, Enum):
    PRETAX = "PRETAX"
    AFTERTAX = "AFTERTAX"
    ROTH = "ROTH"


class DistributionReason(str, Enum):
    NORMAL = "NORMAL"
    EARLY = "EARLY"
    RMD = "RMD"
    INHERITED = "INHERITED"
    ROLLOVER = "ROLLOVER"
    RETURN_OF_CONTRIBUTION = "RETURN_OF_CONTRIBUTION"


class Relationship(str, Enum):
    SPOUSE = "SPOUSE"
    MINOR_CHILD = "MINOR_CHILD"
    DISABLED = "DISABLED"
    CHRONIC_ILL = "CHRONIC_ILL"
    ELIGIBLE_TRUST = "ELIGIBLE_TRUST"
    NON_ELIGIBLE_INDIVIDUAL = "NON_ELIGIBLE_INDIVIDUAL"


# ─── Entity TypedDicts (PRD §3) ─────────────────────────────────


class AccountOwner(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    tax_id_last4: str
    filing_status: str
    modified_agi_cents: int
    deceased_at: Optional[str]
    rmd_posture: str
    created_at: str
    updated_at: str
    version: int


class IRAAccount(TypedDict, total=False):
    id: str
    owner_id: str
    account_type: str
    status: str
    cash_balance_cents: int
    pretax_basis_cents: int
    aftertax_basis_cents: int
    ytd_contribution_cents: int
    tax_year_marker: int
    opened_at: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BeneficiaryDesignation(TypedDict, total=False):
    id: str
    account_id: str
    beneficiary_full_name: str
    relationship: str
    percentage_bps: int
    status: str
    secure_deadline_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Contribution(TypedDict, total=False):
    id: str
    account_id: str
    tax_year: int
    amount_cents: int
    contribution_kind: str
    status: str
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Conversion(TypedDict, total=False):
    id: str
    source_account_id: str
    target_account_id: str
    gross_amount_cents: int
    taxable_amount_cents: int
    nontaxable_amount_cents: int
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Distribution(TypedDict, total=False):
    id: str
    account_id: str
    amount_cents: int
    distribution_reason: str
    tax_year: int
    federal_withholding_cents: int
    status: str
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RMDSchedule(TypedDict, total=False):
    id: str
    owner_id: str
    tax_year: int
    required_amount_cents: int
    satisfied_amount_cents: int
    deadline_at: str
    status: str
    is_first_rmd_year: bool
    created_at: str
    updated_at: str
    version: int


# Append-only entities (PRD §2.4 — only id + created_at)
class Form1099R(TypedDict, total=False):
    id: str
    distribution_id: Optional[str]
    conversion_id: Optional[str]
    tax_year: int
    gross_distribution_cents: int
    taxable_amount_cents: int
    federal_withholding_cents: int
    distribution_code: str
    ira_sep_simple_flag: bool
    created_at: str


class AuditEvent(TypedDict, total=False):
    id: str
    owner_id: str
    account_id: Optional[str]
    event_kind: str
    tax_year: int
    amount_cents: int
    occurred_at: str
    created_at: str


class SystemClock(TypedDict, total=False):
    current_utc: str
    current_tax_year: int
