"""Domain types: entity TypedDicts, status enums, role enum.

All resources carry the common resource properties of PRD section 2.4:
server-minted UUID id, created_at, updated_at, and integer version.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    STARS_ADMIN = "StarsAdmin"
    STARS_ANALYST = "StarsAnalyst"
    QUALITY_OPS = "QualityOps"
    SURVEY_COORDINATOR = "SurveyCoordinator"
    INCENTIVE_MANAGER = "IncentiveManager"
    COMPLAINTS_AUDITOR = "ComplaintsAuditor"


class RatingCycleStatus(str, Enum):
    SETUP = "SETUP"
    DATA_COLLECTION = "DATA_COLLECTION"
    CUTPOINT_REVIEW = "CUTPOINT_REVIEW"
    OFFICIAL_PUBLISHED = "OFFICIAL_PUBLISHED"
    CLOSED = "CLOSED"


class MeasureStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class MeasureDomain(str, Enum):
    STAYING_HEALTHY = "STAYING_HEALTHY"
    CHRONIC_CARE = "CHRONIC_CARE"
    MEMBER_EXPERIENCE = "MEMBER_EXPERIENCE"
    MEMBER_COMPLAINTS = "MEMBER_COMPLAINTS"
    CUSTOMER_SERVICE = "CUSTOMER_SERVICE"
    DRUG_SAFETY = "DRUG_SAFETY"


class MeasureType(str, Enum):
    PROCESS = "PROCESS"
    OUTCOME = "OUTCOME"
    PATIENT_EXPERIENCE = "PATIENT_EXPERIENCE"


class MeasureDirection(str, Enum):
    HIGHER_BETTER = "HIGHER_BETTER"
    LOWER_BETTER = "LOWER_BETTER"


class MeasureDataSource(str, Enum):
    HEDIS = "HEDIS"
    CAHPS = "CAHPS"
    HOS = "HOS"
    PHARMACY_PDE = "PHARMACY_PDE"
    COMPLAINTS = "COMPLAINTS"
    APPEALS = "APPEALS"


class CutPointSetStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class PerformanceStatus(str, Enum):
    REPORTED = "REPORTED"
    VALIDATED = "VALIDATED"
    LOCKED = "LOCKED"


class MemberStatus(str, Enum):
    ENROLLED = "ENROLLED"
    DISENROLLED = "DISENROLLED"


class CareGapStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"
    EXCLUDED = "EXCLUDED"


class GapType(str, Enum):
    PHARMACY_ADHERENCE = "PHARMACY_ADHERENCE"
    SCREENING = "SCREENING"
    FOLLOW_UP = "FOLLOW_UP"
    IMMUNIZATION = "IMMUNIZATION"


class InterventionChannel(str, Enum):
    CALL = "CALL"
    MAIL = "MAIL"
    SMS = "SMS"
    PHARMACIST_CONSULT = "PHARMACIST_CONSULT"


class ProgramType(str, Enum):
    ATTAINMENT = "ATTAINMENT"
    GAP_CLOSURE = "GAP_CLOSURE"


class ProviderGroupStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class PayoutStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DENIED = "DENIED"


class SurveyType(str, Enum):
    CAHPS = "CAHPS"
    HOS = "HOS"


class SurveyWaveStatus(str, Enum):
    PLANNED = "PLANNED"
    FIELDING = "FIELDING"
    CLOSED_FIELD = "CLOSED_FIELD"
    SCORED = "SCORED"


class ComplaintCategory(str, Enum):
    APPEALS_TIMELINESS = "APPEALS_TIMELINESS"
    COVERAGE_DETERMINATION = "COVERAGE_DETERMINATION"
    BILLING = "BILLING"
    ENROLLMENT = "ENROLLMENT"
    SERVICE_QUALITY = "SERVICE_QUALITY"


class ComplaintStatus(str, Enum):
    FILED = "FILED"
    RESOLVED_VALID = "RESOLVED_VALID"
    RESOLVED_INVALID = "RESOLVED_INVALID"


class ForecastBasis(str, Enum):
    PUBLISHED_CUTPOINTS = "PUBLISHED_CUTPOINTS"
    DRAFT_CUTPOINTS = "DRAFT_CUTPOINTS"


class RatingCycle(TypedDict, total=False):
    id: str
    measurement_year: int
    rating_year: int
    benchmark_pmpm: float
    status: str
    published_cutpoint_set_id: Optional[str]
    live_weighted_stars: Optional[float]
    official_overall_stars: Optional[float]
    official_rebate_amount: Optional[float]
    official_improvement_star: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Measure(TypedDict, total=False):
    id: str
    rating_cycle_id: str
    code: str
    title: str
    domain: str
    measure_type: str
    weight: int
    direction: str
    data_source: str
    improvement_eligible: bool
    prior_cycle_star: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CutPointRow(TypedDict):
    measure_id: str
    band_2_floor: float
    band_3_floor: float
    band_4_floor: float
    band_5_floor: float


class CutPointSet(TypedDict, total=False):
    id: str
    rating_cycle_id: str
    label: str
    rows: List[Dict[str, Any]]
    status: str
    created_at: str
    updated_at: str
    version: int


class MeasurePerformance(TypedDict, total=False):
    id: str
    rating_cycle_id: str
    measure_id: str
    numerator: int
    denominator: int
    exclusion_count: int
    raw_value: Optional[float]
    published_star: Optional[int]
    draft_star: Optional[int]
    timeliness_alert: bool
    reported_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    member_ref: str
    plan_contract: str
    enrolled_months: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CareGap(TypedDict, total=False):
    id: str
    member_id: str
    measure_id: str
    gap_type: str
    intervention_count: int
    last_intervention_channel: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProviderGroup(TypedDict, total=False):
    id: str
    name: str
    program_type: str
    linked_measure_id: str
    target_star: int
    unit_reward_per_gap: float
    max_pool_amount: float
    paid_total: float
    reserved_total: float
    remaining_amount: float
    status: str
    created_at: str
    updated_at: str
    version: int


class IncentivePayout(TypedDict, total=False):
    id: str
    provider_group_id: str
    amount: float
    basis_snapshot: Dict[str, Any]
    proposed_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SurveyVendor(TypedDict, total=False):
    id: str
    name: str
    max_concurrent_waves: int
    created_at: str
    updated_at: str
    version: int


class SurveyWave(TypedDict, total=False):
    id: str
    rating_cycle_id: str
    survey_type: str
    vendor_id: str
    window_start: str
    window_end: str
    sample_size: int
    response_count: Optional[int]
    response_rate: Optional[float]
    sufficient: Optional[bool]
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplaintCase(TypedDict, total=False):
    id: str
    rating_cycle_id: str
    member_id: str
    category: str
    filed_at: str
    resolved_at: Optional[str]
    late_resolution: Optional[bool]
    status: str
    created_at: str
    updated_at: str
    version: int


class RatingForecast(TypedDict, total=False):
    id: str
    rating_cycle_id: str
    basis: str
    measures_included: int
    measures_improved: int
    measures_declined: int
    measures_eligible: int
    improvement_score: Optional[float]
    improvement_star: Optional[int]
    projected_overall_stars: Optional[float]
    member_months_used: int
    rebate_tier_rate: float
    projected_rebate_amount: float
    created_at: str
    updated_at: str
    version: int
