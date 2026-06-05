"""Domain types: entity TypedDicts, status enums, role enum.

All field names are exactly as the PRD names them. Status enums mirror the
state dimensions the PRD describes for each lifecycle entity.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum (the three declared roles) ---
class UserRole(str, Enum):
    APPLICANT = "Applicant"
    CASE_WORKER = "CaseWorker"
    HEARING_OFFICER = "HearingOfficer"


# --- Status / enum value sets ---
class MemberStatus(str, Enum):
    COUNTED = "COUNTED"
    EXCLUDED = "EXCLUDED"


class Relationship(str, Enum):
    SELF = "SELF"
    SPOUSE = "SPOUSE"
    CHILD = "CHILD"
    DEPENDENT = "DEPENDENT"
    OTHER = "OTHER"


class IncomeType(str, Enum):
    WAGES = "WAGES"
    SELF_EMPLOYMENT = "SELF_EMPLOYMENT"
    SOCIAL_SECURITY = "SOCIAL_SECURITY"
    CHILD_SUPPORT = "CHILD_SUPPORT"
    TANF = "TANF"
    GIFT = "GIFT"


class AssetType(str, Enum):
    CASH = "CASH"
    BANK_ACCOUNT = "BANK_ACCOUNT"
    VEHICLE = "VEHICLE"
    HOME = "HOME"
    RETIREMENT = "RETIREMENT"
    BURIAL_FUND = "BURIAL_FUND"


class Pathway(str, Enum):
    MAGI = "MAGI"
    NON_MAGI = "NON_MAGI"


class MagiVariant(str, Enum):
    POINT_IN_TIME = "POINT_IN_TIME"
    PROJECTED_ANNUAL = "PROJECTED_ANNUAL"


class ReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    DOCS_REQUESTED = "DOCS_REQUESTED"
    VERIFIED = "VERIFIED"


class Decision(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class DecisionReason(str, Enum):
    INCOME_UNDER_THRESHOLD = "INCOME_UNDER_THRESHOLD"
    INCOME_OVER_THRESHOLD = "INCOME_OVER_THRESHOLD"
    ASSETS_UNDER_LIMIT = "ASSETS_UNDER_LIMIT"
    ASSETS_OVER_LIMIT = "ASSETS_OVER_LIMIT"


class CoverageStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    IN_REDETERMINATION = "IN_REDETERMINATION"
    TERMINATED = "TERMINATED"


class RedetStatus(str, Enum):
    INITIATED = "INITIATED"
    INFO_REQUESTED = "INFO_REQUESTED"
    RENEWED = "RENEWED"
    TERMINATED = "TERMINATED"
    PENDING_APPEAL = "PENDING_APPEAL"


class AppealStatus(str, Enum):
    FILED = "FILED"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    HEARD = "HEARD"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"
    WITHDRAWN = "WITHDRAWN"


# --- Entity TypedDicts ---
# StateRule — carries full common fields.
class StateRule(TypedDict):
    id: str
    state_code: str
    is_expansion_state: bool
    magi_adult_threshold_pct: int
    magi_child_threshold_pct: int
    abd_asset_limit_cents: int
    standard_asset_limit_cents: int
    continuous_coverage_active: bool
    created_at: str
    updated_at: str
    version: int


# FplSchedule — immutable after creation: ONLY id + created_at (no updated_at, no version).
class FplSchedule(TypedDict):
    id: str
    year: int
    base_annual_cents: int
    per_member_increment_cents: int
    created_at: str


class Household(TypedDict):
    id: str
    state_code: str
    fpl_year: int
    household_size: int
    primary_applicant_name: str
    covered_member_months: int
    active_enrollment_count: int
    created_at: str
    updated_at: str
    version: int


class HouseholdMember(TypedDict):
    id: str
    household_id: str
    full_name: str
    age: int
    relationship: str
    is_disabled: bool
    member_status: str
    created_at: str
    updated_at: str
    version: int


class IncomeSource(TypedDict):
    id: str
    member_id: str
    income_type: str
    monthly_amount_cents: int
    is_magi_countable: bool
    projected_annual_cents: int
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict):
    id: str
    household_id: str
    asset_type: str
    value_cents: int
    is_exempt: bool
    countable_value_cents: int
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    household_id: str
    pathway: str
    magi_variant: str
    review_status: str
    verification_status: str
    assigned_caseworker_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EligibilityDetermination(TypedDict):
    id: str
    application_id: str
    pathway: str
    magi_annual_cents: Optional[int]
    fpl_percentage: Optional[int]
    countable_assets_cents: Optional[int]
    applicable_threshold_pct: Optional[int]
    decision: str
    decision_reason: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    household_id: str
    application_id: str
    coverage_status: str
    coverage_start: str
    coverage_end: str
    redetermination_due: str
    member_months: int
    created_at: str
    updated_at: str
    version: int


class Redetermination(TypedDict):
    id: str
    enrollment_id: str
    redet_status: str
    window_open: str
    window_close: str
    info_request_count: int
    new_determination_id: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    enrollment_id: str
    redetermination_id: str
    appeal_status: str
    adjudicator_id: Optional[str]
    aid_paid_pending: bool
    created_at: str
    updated_at: str
    version: int
