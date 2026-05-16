"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 distinguishes two common-fields shapes:

- Entities with the "four common properties" (id, created_at, updated_at,
  version): StatePolicy, Household, Applicant, Application,
  EligibilityDetermination, Enrollment, Redetermination, Appeal,
  FairHearing.
- Append-only entities carrying ONLY id and created_at (no updated_at,
  no version per PRD §2.4): IncomeRecord, AssetRecord,
  EmergencyDeclaration.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1 (exact spellings)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    INTAKE_WORKER = "IntakeWorker"
    ELIGIBILITY_CASEWORKER = "EligibilityCaseworker"
    APPEALS_OFFICER = "AppealsOfficer"
    POLICY_ADMIN = "PolicyAdmin"


# ---------------------------------------------------------------------------
# Status enums — PRD §2.9
# ---------------------------------------------------------------------------
class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    WITHDRAWN = "WITHDRAWN"


class EligibilityOutcome(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    OVERTURNED = "OVERTURNED"


class IneligibilityReason(str, Enum):
    INCOME_EXCEEDS_LIMIT = "INCOME_EXCEEDS_LIMIT"
    ASSETS_EXCEED_LIMIT = "ASSETS_EXCEED_LIMIT"
    NOT_RESIDENT = "NOT_RESIDENT"
    NON_QUALIFYING_PROGRAM = "NON_QUALIFYING_PROGRAM"


class CoverageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONTINUOUS_COVERAGE = "CONTINUOUS_COVERAGE"
    REDETERMINATION_DUE = "REDETERMINATION_DUE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class RedeterminationStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    RENEWED = "RENEWED"
    TERMINATED = "TERMINATED"
    WITHDRAWN = "WITHDRAWN"


class RedeterminationDecision(str, Enum):
    RENEWED = "RENEWED"
    TERMINATED = "TERMINATED"


class AppealStatus(str, Enum):
    FILED = "FILED"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    UNDER_REVIEW = "UNDER_REVIEW"
    GRANTED = "GRANTED"
    UPHELD = "UPHELD"
    WITHDRAWN = "WITHDRAWN"


class FairHearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"


class EmergencyDeclarationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class EmergencyScope(str, Enum):
    FEDERAL = "FEDERAL"
    STATE = "STATE"


class ApplicationProgram(str, Enum):
    MAGI_ADULT = "MAGI_ADULT"
    MAGI_CHILD = "MAGI_CHILD"
    MAGI_PREGNANT = "MAGI_PREGNANT"
    NON_MAGI_DISABILITY = "NON_MAGI_DISABILITY"
    NON_MAGI_AGED = "NON_MAGI_AGED"


class RuleVariant(str, Enum):
    FEDERAL = "FEDERAL"
    STATE = "STATE"


class FilingStatus(str, Enum):
    SINGLE = "SINGLE"
    MARRIED_JOINT = "MARRIED_JOINT"
    MARRIED_SEPARATE = "MARRIED_SEPARATE"
    HEAD_OF_HOUSEHOLD = "HEAD_OF_HOUSEHOLD"


class DependentStatus(str, Enum):
    PRIMARY = "PRIMARY"
    SPOUSE = "SPOUSE"
    DEPENDENT = "DEPENDENT"
    EXCLUDED = "EXCLUDED"


class IncomeSourceType(str, Enum):
    WAGES = "WAGES"
    SELF_EMPLOYMENT = "SELF_EMPLOYMENT"
    INTEREST = "INTEREST"
    DIVIDENDS = "DIVIDENDS"
    CAPITAL_GAINS = "CAPITAL_GAINS"
    SOCIAL_SECURITY = "SOCIAL_SECURITY"
    UNEMPLOYMENT = "UNEMPLOYMENT"
    CHILD_SUPPORT = "CHILD_SUPPORT"
    TANF = "TANF"
    SSI = "SSI"
    OTHER = "OTHER"


class IncomeFrequency(str, Enum):
    ANNUAL = "ANNUAL"
    MONTHLY = "MONTHLY"
    BIWEEKLY = "BIWEEKLY"
    WEEKLY = "WEEKLY"


class AssetType(str, Enum):
    PRIMARY_RESIDENCE = "PRIMARY_RESIDENCE"
    VEHICLE = "VEHICLE"
    CHECKING = "CHECKING"
    SAVINGS = "SAVINGS"
    RETIREMENT = "RETIREMENT"
    INVESTMENT = "INVESTMENT"
    LIFE_INSURANCE = "LIFE_INSURANCE"
    OTHER = "OTHER"


# ---------------------------------------------------------------------------
# Entities carrying the four common fields (id, created_at, updated_at, version)
# ---------------------------------------------------------------------------
class StatePolicy(TypedDict, total=False):
    id: str
    state_code: str
    fpl_year: int
    fpl_base_amount: float
    fpl_per_member_amount: float
    magi_income_limit_pct: float
    asset_limit_per_member: float
    asset_test_applies: bool
    state_disregard_amount: float
    state_exempt_asset_types: List[str]
    emergency_continuous_active: bool
    created_at: str
    updated_at: str
    version: int


class Household(TypedDict, total=False):
    id: str
    state_code: str
    head_applicant_id: Optional[str]
    address_line: str
    filing_status: str
    household_size: int
    total_magi: float
    fpl_threshold_amount: float
    fpl_percent: Optional[float]
    active_enrollment_count: int
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict, total=False):
    id: str
    household_id: str
    full_name: str
    date_of_birth: str
    dependent_status: str
    is_disabled: bool
    is_pregnant: bool
    magi_income: float
    countable_assets: float
    redetermination_count_this_year: int
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    household_id: str
    program: str
    rule_variant: str
    submitted_at: Optional[str]
    status: str
    snapshot_magi: Optional[float]
    snapshot_fpl_percent: Optional[float]
    snapshot_countable_assets: Optional[float]
    created_at: str
    updated_at: str
    version: int


class EligibilityDetermination(TypedDict, total=False):
    id: str
    application_id: str
    decided_at: str
    outcome: str
    ineligibility_reason: Optional[str]
    computed_magi: float
    computed_fpl_percent: float
    applied_rule_variant: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    applicant_id: str
    determination_id: str
    coverage_start: str
    coverage_end: str
    coverage_status: str
    continuous_coverage_flag: bool
    redetermination_due_at: str
    created_at: str
    updated_at: str
    version: int


class Redetermination(TypedDict, total=False):
    id: str
    enrollment_id: str
    due_date: str
    status: str
    new_snapshot_magi: Optional[float]
    new_snapshot_fpl_percent: Optional[float]
    decision: Optional[str]
    enrollment_redetermination_premium: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    determination_id: str
    filed_at: str
    deadline_at: str
    status: str
    officer_id: Optional[str]
    outcome_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FairHearing(TypedDict, total=False):
    id: str
    appeal_id: str
    officer_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities — id + created_at ONLY (no updated_at, no version
# per PRD §2.4)
# ---------------------------------------------------------------------------
class IncomeRecord(TypedDict, total=False):
    id: str
    applicant_id: str
    source_type: str
    gross_amount: float
    frequency: str
    created_at: str


class AssetRecord(TypedDict, total=False):
    id: str
    applicant_id: str
    asset_type: str
    market_value: float
    exempt_under_federal: bool
    exempt_under_state: bool
    countable_value: float
    created_at: str


class EmergencyDeclaration(TypedDict, total=False):
    id: str
    scope: str
    state_code: Optional[str]
    declared_at: str
    expires_at: str
    status: str
    created_at: str


__all__ = [
    "UserRole",
    "ApplicationStatus",
    "EligibilityOutcome",
    "IneligibilityReason",
    "CoverageStatus",
    "RedeterminationStatus",
    "RedeterminationDecision",
    "AppealStatus",
    "FairHearingStatus",
    "EmergencyDeclarationStatus",
    "EmergencyScope",
    "ApplicationProgram",
    "RuleVariant",
    "FilingStatus",
    "DependentStatus",
    "IncomeSourceType",
    "IncomeFrequency",
    "AssetType",
    "StatePolicy",
    "Household",
    "Applicant",
    "Application",
    "EligibilityDetermination",
    "Enrollment",
    "Redetermination",
    "Appeal",
    "FairHearing",
    "IncomeRecord",
    "AssetRecord",
    "EmergencyDeclaration",
]
