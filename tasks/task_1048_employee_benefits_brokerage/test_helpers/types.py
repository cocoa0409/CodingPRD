"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this system carry the common fields id, created_at, updated_at,
and version (see PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    BENEFITS_CONSULTANT = "BenefitsConsultant"
    CARRIER_REP = "CarrierRep"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CLIENT_CONTACT = "ClientContact"
    PLATFORM_ADMIN = "PlatformAdmin"


# --- Status enums ---
class CensusMemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class QuoteStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SELECTED = "SELECTED"
    DECLINED = "DECLINED"


class PolicyLifecycleStatus(str, Enum):
    BOUND = "BOUND"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class PolicyCommissionStatus(str, Enum):
    PENDING = "PENDING"
    FINALIZED = "FINALIZED"


class PolicyRenewalStatus(str, Enum):
    NONE = "NONE"
    RENEWING = "RENEWING"
    RENEWED = "RENEWED"


class RenewalStatus(str, Enum):
    OPEN = "OPEN"
    NEGOTIATING = "NEGOTIATING"
    AGREED = "AGREED"
    DECLINED = "DECLINED"


class ProposingSide(str, Enum):
    CARRIER = "CARRIER"
    BROKER = "BROKER"


class EnrollmentWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"


class ElectionStatus(str, Enum):
    SELECTED = "SELECTED"
    CONFIRMED = "CONFIRMED"
    WAIVED = "WAIVED"
    WITHDRAWN = "WITHDRAWN"


class FilingStatus(str, Enum):
    DRAFT = "DRAFT"
    PREPARED = "PREPARED"
    CERTIFIED = "CERTIFIED"
    FILED = "FILED"
    LATE = "LATE"


class CoverageLine(str, Enum):
    MEDICAL = "MEDICAL"
    DENTAL = "DENTAL"
    VISION = "VISION"
    LIFE = "LIFE"


class CoverageTier(str, Enum):
    EMPLOYEE_ONLY = "EMPLOYEE_ONLY"
    EMPLOYEE_SPOUSE = "EMPLOYEE_SPOUSE"
    EMPLOYEE_CHILD = "EMPLOYEE_CHILD"
    FAMILY = "FAMILY"


class FilingType(str, Enum):
    ACA_1094C = "ACA_1094C"
    FORM_5500 = "FORM_5500"
    ERISA_SPD = "ERISA_SPD"


class Industry(str, Enum):
    RETAIL = "RETAIL"
    MANUFACTURING = "MANUFACTURING"
    TECH = "TECH"
    HEALTHCARE = "HEALTHCARE"
    OTHER = "OTHER"


class EmploymentType(str, Enum):
    FULL_TIME = "FULL_TIME"
    PART_TIME = "PART_TIME"


# --- Entity TypedDicts (all carry id/created_at/updated_at/version) ---
class Client(TypedDict):
    id: str
    legal_name: str
    ein: str
    industry: str
    fiscal_year_end_month: int
    full_time_equivalent_count: int
    employee_count: int
    is_ale: bool
    enrolled_headcount: int
    active_premium_total_cents: int
    ytd_commission_cents: int
    created_at: str
    updated_at: str
    version: int


class CensusMember(TypedDict):
    id: str
    client_id: str
    full_name: str
    birth_date: str
    annual_salary_cents: int
    monthly_contribution_cents: int
    employment_type: str
    affordable_rate_of_pay: bool
    affordable_fpl: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class MarketingCampaign(TypedDict):
    id: str
    client_id: str
    coverage_line: str
    target_effective_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CarrierQuote(TypedDict):
    id: str
    campaign_id: str
    carrier_name: str
    monthly_premium_cents: int
    commission_rate_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict):
    id: str
    client_id: str
    quote_id: str
    coverage_line: str
    carrier_name: str
    effective_date: str
    expiration_date: str
    original_premium_cents: int
    monthly_premium_cents: int
    commission_rate_pct: float
    estimated_commission_cents: int
    finalized_commission_cents: int
    commission_status: str
    renewal_status: str
    lifecycle_status: str
    created_at: str
    updated_at: str
    version: int


class Renewal(TypedDict):
    id: str
    policy_id: str
    initial_offer_premium_cents: int
    current_offer_premium_cents: int
    proposing_side: str
    round_count: int
    agreed_premium_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EnrollmentWindow(TypedDict):
    id: str
    client_id: str
    plan_year: int
    opens_at: str
    closes_at: str
    total_confirmed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Election(TypedDict):
    id: str
    window_id: str
    census_member_id: str
    policy_id: str
    coverage_tier: str
    monthly_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceFiling(TypedDict):
    id: str
    client_id: str
    filing_type: str
    plan_year: int
    due_date: str
    prepared_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StopLossPolicy(TypedDict):
    id: str
    client_id: str
    attachment_point_cents: int
    aggregate_limit_cents: int
    wellness_credit_pct: float
    cumulative_claims_cents: int
    reimbursed_cents: int
    wellness_credit_cents: int
    total_recovery_cents: int
    created_at: str
    updated_at: str
    version: int
