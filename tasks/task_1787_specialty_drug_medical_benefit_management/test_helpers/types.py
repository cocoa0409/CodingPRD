"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLAN_ADMIN = "PlanAdmin"
    MEDICAL_POLICY_OFFICER = "MedicalPolicyOfficer"
    PROVIDER_REP = "ProviderRep"
    CASE_MANAGER = "CaseManager"
    PHARMACY_ANALYST = "PharmacyAnalyst"


class SourcingRule(str, Enum):
    BUY_AND_BILL_ONLY = "BUY_AND_BILL_ONLY"
    SPECIALTY_PHARMACY_ONLY = "SPECIALTY_PHARMACY_ONLY"
    EITHER = "EITHER"


class SourcingPath(str, Enum):
    BUY_AND_BILL = "BUY_AND_BILL"
    WHITE_BAG = "WHITE_BAG"


class SiteOfCare(str, Enum):
    HOPD = "HOPD"
    OFFICE = "OFFICE"
    HOME = "HOME"
    AMBULATORY = "AMBULATORY"


class DoseRoundingMode(str, Enum):
    VIAL = "VIAL"
    INCREMENT = "INCREMENT"


class BiosimilarSubstitution(str, Enum):
    DISABLED = "DISABLED"
    PREFERRED = "PREFERRED"
    MANDATORY = "MANDATORY"


class AspScheduleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"


class PolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ProviderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RECOUPMENT_HOLD = "RECOUPMENT_HOLD"


class AuthStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    EXHAUSTED = "EXHAUSTED"


class ClaimStatus(str, Enum):
    APPROVED_FOR_PAYMENT = "APPROVED_FOR_PAYMENT"
    PENDED = "PENDED"
    PAID = "PAID"
    ADJUSTED = "ADJUSTED"
    DENIED = "DENIED"


class PendReason(str, Enum):
    DOSE_REVIEW = "DOSE_REVIEW"
    AUTH_SUSPENDED = "AUTH_SUSPENDED"


class RedirectionStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class BiosimilarPolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class ForecastVariant(str, Enum):
    BASELINE = "BASELINE"
    POLICY_ADJUSTED = "POLICY_ADJUSTED"


# --- Entities carrying id + created_at + updated_at + version (PRD §2.5) ---


class DrugCatalogEntry(TypedDict, total=False):
    id: str
    j_code: str
    drug_name: str
    billing_unit_mg: int
    vial_size_mg: int
    single_dose_vial: bool
    sourcing_rule: str
    weight_based_dosing: bool
    mg_per_kg: Optional[float]
    dose_rounding_mode: str
    rounding_increment_mg: Optional[int]
    max_single_dose_mg: int
    site_of_care_eligible: bool
    created_at: str
    updated_at: str
    version: int


class AspRateSchedule(TypedDict, total=False):
    id: str
    drug_id: str
    effective_start: str
    asp_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClinicalPolicy(TypedDict, total=False):
    id: str
    drug_id: str
    covered_diagnoses: List[str]
    step_therapy_required: bool
    requires_site_of_care_redirection: bool
    biosimilar_substitution: str
    version_no: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProviderAccount(TypedDict, total=False):
    id: str
    name: str
    status: str
    cumulative_paid_cents: int
    recoupment_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class PriorAuthorization(TypedDict, total=False):
    id: str
    drug_id: str
    member_id: str
    provider_account_id: str
    diagnosis_code: str
    requested_dose_mg: Optional[float]
    weight_kg: Optional[float]
    requested_start_date: str
    step_therapy_completed: bool
    status: str
    approved_dose_mg: Optional[float]
    validity_start: Optional[str]
    validity_end: Optional[str]
    max_administrations: Optional[int]
    administrations_used: int
    policy_id: Optional[str]
    policy_version_no: Optional[int]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InfusionClaim(TypedDict, total=False):
    id: str
    auth_id: str
    drug_id: str
    provider_account_id: str
    service_date: str
    site_of_care: str
    sourcing_path: str
    j_code_billed: str
    billed_units: int
    waste_units: int
    jw_modifier: bool
    status: str
    pend_reason: Optional[str]
    administered_mg: float
    payable_waste_units: int
    asp_schedule_id_used: Optional[str]
    asp_rate_cents: float
    addon_pct_applied: float
    allowed_amount_cents: int
    member_cost_share_cents: int
    override_by: Optional[str]
    denial_reason: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SiteOfCareRedirection(TypedDict, total=False):
    id: str
    auth_id: str
    from_site: str
    candidate_sites: List[str]
    accepted_site: Optional[str]
    member_incentive_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BiosimilarPolicy(TypedDict, total=False):
    id: str
    reference_drug_id: str
    biosimilar_drug_id: str
    provider_incentive_addon_pct: float
    member_copay_waiver_pct: float
    effective_start: str
    effective_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PipelineDrug(TypedDict, total=False):
    id: str
    drug_name: str
    expected_approval_date: str
    prevalence_per_100k: float
    projected_annual_cost_cents: int
    year1_uptake_pct: float
    steady_state_uptake_pct: float
    biosimilar_erosion_pct: float
    created_at: str
    updated_at: str
    version: int


# --- Immutable records: id + created_at ONLY (PRD §2.5) ---


class ClaimAdjustment(TypedDict, total=False):
    id: str
    claim_id: str
    asp_schedule_id: str
    old_allowed_cents: int
    new_allowed_cents: int
    delta_cents: int
    reason: str
    created_at: str


class PerDrugProjection(TypedDict, total=False):
    pipeline_drug_id: str
    projected_cents: int


class SpendForecastRun(TypedDict, total=False):
    id: str
    variant: str
    horizon_years: int
    enrollment_projection: int
    as_of_date: str
    pipeline_total_cents: int
    inline_annualized_cents: int
    total_projected_cents: int
    per_drug_projections: List[PerDrugProjection]
    created_at: str
