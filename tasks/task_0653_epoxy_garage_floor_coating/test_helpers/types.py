"""Domain types: entity TypedDicts, status enums, role enum.

All money is integer cents. Statuses are plain strings on the wire; the enums
below capture the legal value sets the PRD defines.
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------
# Status / enum value sets
# --------------------------------------------------------------------------
class ProjectSalesStatus(str, Enum):
    LEAD = "LEAD"
    ASSESSED = "ASSESSED"
    QUOTED = "QUOTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class ProjectBuildStatus(str, Enum):
    PRE_BUILD = "PRE_BUILD"
    SCHEDULED = "SCHEDULED"
    INSTALLED = "INSTALLED"
    CURING = "CURING"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class AssessmentStatus(str, Enum):
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class PrepTier(str, Enum):
    LIGHT = "LIGHT"
    MODERATE = "MODERATE"
    HEAVY = "HEAVY"


class QuoteVariant(str, Enum):
    ESTIMATE = "ESTIMATE"
    FINAL = "FINAL"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    SUPERSEDED = "SUPERSEDED"


class InstallJobStatus(str, Enum):
    BOOKED = "BOOKED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CURED = "CURED"
    CANCELLED = "CANCELLED"


class WarrantyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLAIM_OPEN = "CLAIM_OPEN"
    VOID = "VOID"


class WarrantyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    NEEDS_INFO = "NEEDS_INFO"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CALLBACK_SCHEDULED = "CALLBACK_SCHEDULED"
    CLOSED = "CLOSED"


class ReferralStatus(str, Enum):
    PENDING = "PENDING"
    CONVERTED = "CONVERTED"
    CLAWED_BACK = "CLAWED_BACK"
    EXPIRED = "EXPIRED"


class CoatingFamily(str, Enum):
    FLAKE = "FLAKE"
    METALLIC = "METALLIC"


class CoatingSku(str, Enum):
    FLAKE_STANDARD = "FLAKE_STANDARD"
    FLAKE_PREMIUM = "FLAKE_PREMIUM"
    METALLIC = "METALLIC"


class DefectType(str, Enum):
    HOT_TIRE = "HOT_TIRE"
    PEEL = "PEEL"
    OTHER = "OTHER"


class InstallSeason(str, Enum):
    PEAK = "PEAK"
    STANDARD = "STANDARD"
    OFF = "OFF"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SALES_REP = "SalesRep"
    SCHEDULER = "Scheduler"
    CREW = "Crew"
    WARRANTY_AGENT = "WarrantyAgent"
    CUSTOMER = "Customer"


# --------------------------------------------------------------------------
# Entity TypedDicts.  Every entity carries common_fields (id, created_at,
# updated_at, version) per the PRD's common-resource rule.
# --------------------------------------------------------------------------
class CoatingSystem(TypedDict):
    id: str
    name: str
    family: str
    sku: str
    requires_metallic_certified_crew: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class ColorOption(TypedDict):
    id: str
    coating_system_id: str
    name: str
    flake_blend_code: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class FinancingPlan(TypedDict):
    id: str
    name: str
    apr_bps: int
    term_months: int
    min_principal_cents: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict):
    id: str
    name: str
    metallic_certified: bool
    max_sqft_per_day: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    referral_code: str
    account_credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict):
    id: str
    customer_id: str
    site_zip: str
    sales_status: str
    build_status: str
    accepted_quote_id: Optional[str]
    referral_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict):
    id: str
    project_id: str
    measured_sqft: int
    oil_stain_pct: int
    crack_density: int
    crack_linear_ft: int
    spalling: bool
    moisture_pct: int
    condition_score: int
    prep_tier: str
    billable_crack_ft: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    project_id: str
    assessment_id: str
    coating_system_id: str
    color_option_id: str
    financing_plan_id: Optional[str]
    install_season: str
    variant: str
    priced_sqft: int
    system_material_cents: int
    prep_labor_cents: int
    volume_discount_pct_bps: int
    discount_cents: int
    mobilization_cents: int
    grand_total_cents: int
    monthly_payment_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InstallJob(TypedDict):
    id: str
    project_id: str
    crew_id: str
    install_date: str
    install_end: str
    foot_traffic_ok_at: str
    vehicle_traffic_ok_at: str
    as_measured_sqft: Optional[int]
    as_measured_crack_ft: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Warranty(TypedDict):
    id: str
    project_id: str
    install_job_id: str
    covered_install_price_cents: int
    term_months: int
    coverage_start_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    warranty_id: str
    defect_type: str
    reported_at: str
    months_elapsed: int
    prorated_credit_cents: int
    revision_rounds: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    referrer_customer_id: str
    referred_customer_id: str
    project_id: str
    credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
