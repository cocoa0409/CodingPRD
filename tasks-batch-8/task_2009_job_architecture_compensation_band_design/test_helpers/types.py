"""Domain types: entity TypedDicts, status enums, role enum for the
job architecture and compensation band design API.

All entities carry common fields (id, created_at, updated_at, version).
"""
from enum import Enum
from typing import Optional, TypedDict


class CompProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    FRAMEWORK_LOCKED = "FRAMEWORK_LOCKED"
    PRICING = "PRICING"
    MAPPING_OPEN = "MAPPING_OPEN"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class JobFamilyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class JobProfileStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    RETIRED = "RETIRED"


class FlsaClassification(str, Enum):
    PENDING = "PENDING"
    EXEMPT = "EXEMPT"
    NON_EXEMPT = "NON_EXEMPT"


class MarketSurveyStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class TargetPercentile(str, Enum):
    P50 = "P50"
    P62_5 = "P62_5"
    P75 = "P75"


class PricingVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    OFFICIAL = "OFFICIAL"


class PayBandStatus(str, Enum):
    DRAFT = "DRAFT"
    PRICED = "PRICED"
    COMP_APPROVED = "COMP_APPROVED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class EmployeeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class RangePosition(str, Enum):
    BELOW_MIN = "BELOW_MIN"
    IN_RANGE = "IN_RANGE"
    ABOVE_MAX = "ABOVE_MAX"
    UNBANDED = "UNBANDED"


class MappingDecisionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    HRBP_REVIEWED = "HRBP_REVIEWED"
    COMP_TRIAGED = "COMP_TRIAGED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RETURNED = "RETURNED"
    WITHDRAWN = "WITHDRAWN"
    REVERSED = "REVERSED"


class MappingKind(str, Enum):
    UPSLOT = "UPSLOT"
    DOWNSLOT = "DOWNSLOT"
    LATERAL = "LATERAL"


class ExceptionRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    HRBP_PASSED = "HRBP_PASSED"
    FINANCE_REVIEW = "FINANCE_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    RETURNED = "RETURNED"
    RESCINDED = "RESCINDED"


class ExceptionType(str, Enum):
    ABOVE_MAX_HIRE = "ABOVE_MAX_HIRE"
    BELOW_MIN_RETENTION = "BELOW_MIN_RETENTION"
    OFF_CYCLE_INCREASE = "OFF_CYCLE_INCREASE"
    GEO_MISMATCH = "GEO_MISMATCH"


class RefreshCycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IMPACT_COMPUTED = "IMPACT_COMPUTED"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    COMP_ADMIN = "CompAdmin"
    COMP_ANALYST = "CompAnalyst"
    COMP_MANAGER = "CompManager"
    HRBP = "HRBP"
    FINANCE_PARTNER = "FinancePartner"
    DEPARTMENT_MANAGER = "DepartmentManager"


class CompProgram(TypedDict, total=False):
    id: str
    fiscal_year: int
    refresh_cadence_months: int
    pricing_as_of_date: str
    merit_budget_cents: int
    refresh_budget_cents: int
    status: str
    total_payroll_projection_cents: int
    refresh_budget_spent_cents: int
    created_at: str
    updated_at: str
    version: int


class JobFamily(TypedDict, total=False):
    id: str
    code: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class JobLevel(TypedDict, total=False):
    id: str
    level_code: str
    title: str
    rank_order: int
    scope_criteria: Optional[str]
    min_years_experience: int
    created_at: str
    updated_at: str
    version: int


class GeoZone(TypedDict, total=False):
    id: str
    zone_code: str
    name: str
    parent_zone_id: Optional[str]
    differential_ratio: float
    effective_ratio: float
    created_at: str
    updated_at: str
    version: int


class JobProfile(TypedDict, total=False):
    id: str
    job_family_id: str
    job_level_id: str
    title: str
    summary: str
    salary_basis_weekly_cents: int
    duties_test_passed: bool
    flsa_classification: str
    flsa_determined_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MarketSurvey(TypedDict, total=False):
    id: str
    name: str
    publisher: str
    survey_year: int
    effective_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MarketCut(TypedDict, total=False):
    id: str
    market_survey_id: str
    job_profile_id: str
    geo_zone_id: str
    p25_cents: Optional[int]
    p50_cents: int
    p75_cents: Optional[int]
    sample_size: int
    effective_date: str
    excluded_from_composite: bool
    created_at: str
    updated_at: str
    version: int


class ProgressionPolicy(TypedDict, total=False):
    id: str
    job_family_id: str
    from_level_id: str
    to_level_id: str
    min_midpoint_progression_pct: float
    max_overlap_pct: float
    created_at: str
    updated_at: str
    version: int


class PayBand(TypedDict, total=False):
    id: str
    comp_program_id: str
    job_family_id: str
    job_level_id: str
    geo_zone_id: str
    target_percentile: str
    spread_pct: float
    policy_adjustment_factor: float
    pricing_variant: Optional[str]
    market_composite_cents: Optional[int]
    composite_cut_count: Optional[int]
    midpoint_cents: Optional[int]
    min_cents: Optional[int]
    max_cents: Optional[int]
    geo_ratio_snapshot: Optional[float]
    priced_at: Optional[str]
    status: str
    superseded_by_band_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Department(TypedDict, total=False):
    id: str
    name: str
    code: str
    adjustment_pool_cents: int
    committed_pool_cents: int
    projected_payroll_cents: int
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict, total=False):
    id: str
    employee_ref: str
    department_id: str
    job_profile_id: str
    geo_zone_id: str
    base_salary_cents: int
    hire_date: str
    status: str
    compa_ratio: Optional[float]
    range_position: str
    red_circled: bool
    created_at: str
    updated_at: str
    version: int


class MappingDecision(TypedDict, total=False):
    id: str
    employee_id: str
    from_job_profile_id: str
    to_job_profile_id: str
    justification: Optional[str]
    kind: Optional[str]
    provisional_adjustment_cents: Optional[int]
    final_adjustment_cents: Optional[int]
    pre_salary_cents: Optional[int]
    status: str
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExceptionRequest(TypedDict, total=False):
    id: str
    employee_id: str
    pay_band_id: str
    type: str
    requested_salary_cents: int
    justification: str
    status: str
    finance_required: bool
    pre_exception_salary_cents: Optional[int]
    applied_delta_cents: Optional[int]
    created_by_user_id: str
    comp_gate_by_user_id: Optional[str]
    applied_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RefreshCycle(TypedDict, total=False):
    id: str
    comp_program_id: str
    planned_window_start: str
    planned_window_end: str
    effective_date: str
    status: str
    budget_impact_cents: Optional[int]
    affected_employee_count: Optional[int]
    applied_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
