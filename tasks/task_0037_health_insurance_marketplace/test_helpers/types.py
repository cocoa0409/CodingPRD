"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    APPLICANT = "Applicant"
    NAVIGATOR = "Navigator"
    MARKETPLACE_ADMIN = "MarketplaceAdmin"


class Relationship(str, Enum):
    PRIMARY = "PRIMARY"
    SPOUSE = "SPOUSE"
    DEPENDENT = "DEPENDENT"


class TaxFilingStatus(str, Enum):
    FILER = "FILER"
    JOINT_FILER = "JOINT_FILER"
    DEPENDENT_FILER = "DEPENDENT_FILER"
    DEPENDENT_NONFILER = "DEPENDENT_NONFILER"


class MetalTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DETERMINED = "DETERMINED"
    ENROLLED = "ENROLLED"
    CANCELLED = "CANCELLED"


class EnrollmentWindow(str, Enum):
    OEP = "OEP"
    SEP = "SEP"


class CsrTier(str, Enum):
    CSR94 = "CSR94"
    CSR87 = "CSR87"
    CSR73 = "CSR73"
    NONE = "NONE"


class QualifyingEventType(str, Enum):
    BIRTH = "BIRTH"
    ADOPTION = "ADOPTION"
    MARRIAGE = "MARRIAGE"
    LOSS_OF_COVERAGE = "LOSS_OF_COVERAGE"
    PERMANENT_MOVE = "PERMANENT_MOVE"


class SepStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class LifecycleStatus(str, Enum):
    PENDING_EFFECTUATION = "PENDING_EFFECTUATION"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class PaymentStatus(str, Enum):
    AWAITING_BINDER = "AWAITING_BINDER"
    PAID = "PAID"
    DELINQUENT = "DELINQUENT"


# common_fields: true — id + created_at + updated_at + version
class Household(TypedDict):
    id: str
    applicant_user_id: str
    coverage_year: int
    rating_area: str
    household_magi_cents: int
    fpl_percent: float
    countable_size: int
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class HouseholdMember(TypedDict):
    id: str
    household_id: str
    full_name: str
    relationship: str
    tax_filing_status: str
    annual_income_cents: int
    applies_for_coverage: bool
    is_countable_income: bool
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only/config: ONLY id + created_at
class HealthPlan(TypedDict):
    id: str
    rating_area: str
    coverage_year: int
    metal_tier: str
    gross_premium_cents: int
    is_slcsp_benchmark: bool
    csr_eligible: bool
    created_at: str


# common_fields: true
class Application(TypedDict):
    id: str
    household_id: str
    status: str
    enrollment_window: str
    sep_request_id: Optional[str]
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class EligibilityDetermination(TypedDict):
    id: str
    application_id: str
    fpl_percent_snapshot: float
    applicable_pct: float
    max_aptc_monthly_cents: int
    csr_tier: str
    is_subsidy_eligible: bool
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Enrollment(TypedDict):
    id: str
    application_id: str
    plan_id: str
    elected_aptc_monthly_cents: int
    applied_aptc_monthly_cents: int
    net_premium_monthly_cents: int
    effective_date: str
    first_month_premium_cents: int
    lifecycle_status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class SepRequest(TypedDict):
    id: str
    application_id: str
    qualifying_event_type: str
    event_date: str
    status: str
    window_close_date: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class ReconciliationRecord(TypedDict):
    id: str
    enrollment_id: str
    actual_annual_magi_cents: int
    months_enrolled: int
    advanced_aptc_total_cents: int
    allowed_aptc_total_cents: int
    settlement_cents: int
    created_at: str
    updated_at: str
    version: int
