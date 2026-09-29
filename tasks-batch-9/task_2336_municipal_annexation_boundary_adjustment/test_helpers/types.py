"""Domain types for the Municipal Annexation And Boundary Adjustment API.

Entity shapes, status enumerations and the role enumeration, all named exactly
as the PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Role enumeration (PRD §2.1 — seven recognized roles)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    STATE_LAW_ADMIN = "StateLawAdmin"
    MUNICIPAL_PLANNER = "MunicipalPlanner"
    CITY_CLERK = "CityClerk"
    PROPERTY_OWNER = "PropertyOwner"
    FISCAL_ANALYST = "FiscalAnalyst"
    BOUNDARY_COMMISSIONER = "BoundaryCommissioner"
    COUNTY_ASSESSOR = "CountyAssessor"


# --------------------------------------------------------------------------
# Enumerated value sets
# --------------------------------------------------------------------------
class AnnexationMethod(str, Enum):
    PETITION_100 = "PETITION_100"
    PETITION_MAJORITY = "PETITION_MAJORITY"
    REFERENDUM = "REFERENDUM"
    INVOLUNTARY_ORDINANCE = "INVOLUNTARY_ORDINANCE"


class SignatureBasis(str, Enum):
    ASSESSED_VALUE = "ASSESSED_VALUE"
    OWNER_COUNT = "OWNER_COUNT"


class ProtestBasis(str, Enum):
    ASSESSED_VALUE = "ASSESSED_VALUE"
    OWNER_COUNT = "OWNER_COUNT"


class FiscalMethod(str, Enum):
    AVERAGE_COST = "AVERAGE_COST"
    MARGINAL_COST = "MARGINAL_COST"


class DeAnnexationRefundBasis(str, Enum):
    DAILY_PRORATION = "DAILY_PRORATION"
    WHOLE_QUARTER = "WHOLE_QUARTER"


class EffectiveDateRule(str, Enum):
    IMMEDIATE = "IMMEDIATE"
    NEXT_QUARTER_START = "NEXT_QUARTER_START"
    NEXT_FISCAL_YEAR = "NEXT_FISCAL_YEAR"


class ServiceType(str, Enum):
    POLICE = "POLICE"
    FIRE = "FIRE"
    WATER = "WATER"
    SEWER = "SEWER"


class CaseType(str, Enum):
    ANNEXATION = "ANNEXATION"
    DE_ANNEXATION = "DE_ANNEXATION"


class CaseStatus(str, Enum):
    DRAFT = "DRAFT"
    TERRITORY_CERTIFIED = "TERRITORY_CERTIFIED"
    PETITION_CIRCULATING = "PETITION_CIRCULATING"
    SUFFICIENCY_REVIEW = "SUFFICIENCY_REVIEW"
    HEARING_NOTICED = "HEARING_NOTICED"
    HEARING_HELD = "HEARING_HELD"
    PROTEST_SUSTAINED = "PROTEST_SUSTAINED"
    ORDINANCE_ADOPTED = "ORDINANCE_ADOPTED"
    REFERENDUM_PENDING = "REFERENDUM_PENDING"
    REFERENDUM_APPROVED = "REFERENDUM_APPROVED"
    COMMISSION_REVIEW = "COMMISSION_REVIEW"
    COMMISSION_APPROVED = "COMMISSION_APPROVED"
    EFFECTIVE = "EFFECTIVE"
    DENIED = "DENIED"
    MSD_ALTERNATIVE_ADOPTED = "MSD_ALTERNATIVE_ADOPTED"
    DE_ANNEXED = "DE_ANNEXED"


CASE_TERMINAL_STATUSES = ["DENIED", "MSD_ALTERNATIVE_ADOPTED", "DE_ANNEXED"]


class TaxRollStatus(str, Enum):
    NOT_TRANSFERRED = "NOT_TRANSFERRED"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class ProtestOutcomeCase(str, Enum):
    NOT_EVALUATED = "NOT_EVALUATED"
    FAILED = "FAILED"
    SUSTAINED = "SUSTAINED"


class ReferendumResult(str, Enum):
    NOT_HELD = "NOT_HELD"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CommissionReviewStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ParcelStatus(str, Enum):
    PROPOSED = "PROPOSED"
    PENDING_ANNEX = "PENDING_ANNEX"
    INCORPORATED = "INCORPORATED"
    EXCLUDED = "EXCLUDED"
    DE_ANNEXED = "DE_ANNEXED"


class PetitionType(str, Enum):
    OWNER_100 = "OWNER_100"
    OWNER_MAJORITY = "OWNER_MAJORITY"


class SufficiencyStatus(str, Enum):
    CIRCULATING = "CIRCULATING"
    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"
    EXPIRED = "EXPIRED"


class ConsentStatus(str, Enum):
    SIGNED = "SIGNED"
    WITHDRAWN = "WITHDRAWN"


class AnalysisStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class AdoptionStatus(str, Enum):
    DRAFT = "DRAFT"
    ADOPTED = "ADOPTED"
    RESCINDED = "RESCINDED"


class ServiceReadiness(str, Enum):
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    READY = "READY"


class CommitmentStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    FULFILLED = "FULFILLED"
    VOIDED = "VOIDED"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    VACATED = "VACATED"


class HearingProtestOutcome(str, Enum):
    OPEN = "OPEN"
    FAILED = "FAILED"
    SUSTAINED = "SUSTAINED"


class PublicationType(str, Enum):
    NEWSPAPER = "NEWSPAPER"
    MAILED = "MAILED"
    POSTED = "POSTED"


class NoticeStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class FilingStatus(str, Enum):
    FILED = "FILED"
    WITHDRAWN = "WITHDRAWN"


class RateSchedule(str, Enum):
    OUTSIDE_CITY_SURCHARGE = "OUTSIDE_CITY_SURCHARGE"
    INSIDE_CITY = "INSIDE_CITY"


class AccountStatus(str, Enum):
    OUTSIDE_CITY = "OUTSIDE_CITY"
    INSIDE_CITY_PENDING_TRANSITION = "INSIDE_CITY_PENDING_TRANSITION"
    INSIDE_CITY_ACTIVE = "INSIDE_CITY_ACTIVE"
    DISCONNECTED = "DISCONNECTED"


# --------------------------------------------------------------------------
# Entity shapes. Every resource carries `id` and `created_at`; all but
# NoticePublication additionally carry `updated_at` and `version` (PRD §2.5).
# --------------------------------------------------------------------------
class StatuteProfile(TypedDict):
    id: str
    state_code: str
    authorized_methods: List[str]
    signature_basis: str
    signature_threshold_pct: float
    protest_basis: str
    protest_threshold_pct: float
    contiguity_min_ratio: float
    urban_density_min_units_per_acre: float
    subdivision_test_min_developed_ratio: float
    min_qualification_index: float
    notice_min_days: int
    hearing_to_ordinance_min_days: int
    required_service_types: List[str]
    police_fire_timeline_max_days: int
    water_sewer_timeline_max_days: int
    fiscal_method: str
    per_capita_shared_revenue_cents: int
    referendum_required_methods: List[str]
    boundary_commission_required: bool
    de_annexation_allowed: bool
    de_annexation_refund_basis: str
    msd_alternative_allowed: bool
    msd_cost_recovery_pct: float
    effective_date_rule: str
    fiscal_year_end_month_day: str
    created_at: str
    updated_at: str
    version: int


class Municipality(TypedDict):
    id: str
    statute_profile_id: str
    name: str
    state_code: str
    population: int
    citywide_annual_service_cost_cents: int
    citywide_population: int
    general_fund_millage_rate: float
    taxable_assessed_value_cents: int
    corporate_boundary_perimeter_feet: float
    fiscal_deficit_tolerance_pct: float
    hearing_changeover_buffer_minutes: int
    utility_outside_surcharge_pct: float
    created_at: str
    updated_at: str
    version: int


class ServiceProvider(TypedDict):
    id: str
    municipality_id: str
    provider_name: str
    service_types: List[str]
    concurrent_project_capacity: int
    encumbered_capacity_days: int
    created_at: str
    updated_at: str
    version: int


class PropertyOwner(TypedDict):
    id: str
    owner_name: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class AnnexationCase(TypedDict):
    id: str
    municipality_id: str
    predecessor_case_id: Optional[str]
    case_type: str
    method: str
    status: str
    tax_roll_status: str
    shared_boundary_feet: float
    total_lot_count: int
    developed_lot_count: int
    dwelling_units: int
    max_service_distance_miles: float
    parcel_count: int
    territory_acreage: float
    territory_assessed_value_cents: int
    contiguity_ratio: float
    urban_development_qualified: bool
    qualification_index: float
    effective_date: Optional[str]
    protest_pct: float
    protest_outcome: str
    referendum_result: str
    commission_review_status: str
    fiscal_finalized_by_user_id: Optional[str]
    hearing_held_at: Optional[str]
    ordinance_adopted_at: Optional[str]
    tax_roll_transferred_assessed_value_cents: int
    tax_roll_transferred_tax_cents: int
    de_annexation_refund_cents: int
    msd_annual_assessment_cents: int
    created_at: str
    updated_at: str
    version: int


class Parcel(TypedDict):
    id: str
    annexation_case_id: str
    primary_owner_id: str
    parcel_apn: str
    assessed_value_cents: int
    acreage: float
    is_developed: bool
    dwelling_units: int
    parcel_status: str
    annual_tax_cents: int
    prorated_tax_cents: int
    created_at: str
    updated_at: str
    version: int


class Petition(TypedDict):
    id: str
    annexation_case_id: str
    petition_type: str
    circulation_days: int
    circulation_started_at: str
    circulation_deadline_at: str
    sufficiency_status: str
    qualified_signature_assessed_value_cents: int
    qualified_signature_owner_count: int
    signature_value_pct: float
    signature_owner_pct: float
    created_at: str
    updated_at: str
    version: int


class ParcelOwnerConsent(TypedDict):
    id: str
    petition_id: str
    parcel_id: str
    property_owner_id: str
    ownership_share_pct: float
    consent_status: str
    signed_at: str
    withdrawn_at: Optional[str]
    qualified_value_cents: int
    created_at: str
    updated_at: str
    version: int


class FiscalImpactAnalysis(TypedDict):
    id: str
    annexation_case_id: str
    analysis_method: str
    projected_population: int
    horizon_years: int
    marginal_police_cost_cents: int
    marginal_fire_cost_cents: int
    marginal_water_cost_cents: int
    marginal_sewer_cost_cents: int
    property_tax_revenue_cents: int
    projected_utility_revenue_cents: int
    shared_revenue_cents: int
    gross_annual_revenue_cents: int
    base_service_cost_cents: int
    overhead_tier_pct: float
    administrative_overhead_cents: int
    projected_annual_service_cost_cents: int
    net_annual_impact_cents: int
    deficit_ratio_pct: float
    status: str
    finalized_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlanOfServices(TypedDict):
    id: str
    annexation_case_id: str
    adoption_status: str
    service_readiness: str
    adopted_at: Optional[str]
    committed_cost_cents: int
    covered_service_types: List[str]
    created_at: str
    updated_at: str
    version: int


class ServiceCommitment(TypedDict):
    id: str
    plan_of_services_id: str
    service_provider_id: str
    service_type: str
    window_start_date: str
    window_end_date: str
    timeline_days: int
    committed_account_count: int
    activated_account_count: int
    cost_cents: int
    commitment_status: str
    created_at: str
    updated_at: str
    version: int


class PublicHearing(TypedDict):
    id: str
    annexation_case_id: str
    municipality_id: str
    scheduled_start_at: str
    scheduled_end_at: str
    protest_window_days: int
    hearing_status: str
    held_at: Optional[str]
    notice_published_at: Optional[str]
    protest_opens_at: Optional[str]
    protest_closes_at: Optional[str]
    protest_pct: float
    protest_outcome: str
    created_at: str
    updated_at: str
    version: int


class NoticePublication(TypedDict):
    """Immutable statutory artifact — carries only `id` and `created_at`
    beyond its own fields; no `updated_at` and no `version` (PRD §2.5)."""
    id: str
    public_hearing_id: str
    publication_type: str
    published_at: str
    notice_status: str
    created_at: str


class ProtestFiling(TypedDict):
    id: str
    public_hearing_id: str
    parcel_id: str
    property_owner_id: str
    ownership_share_pct: float
    filing_status: str
    filed_at: str
    protest_value_cents: int
    created_at: str
    updated_at: str
    version: int


class UtilityAccount(TypedDict):
    id: str
    parcel_id: str
    service_provider_id: str
    service_type: str
    monthly_base_cents: int
    rate_schedule: str
    account_status: str
    effective_monthly_cents: int
    created_at: str
    updated_at: str
    version: int
