"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 distinguishes two common-fields shapes:

- Every persisted resource — Beneficiary, Plan, EnrollmentPeriod,
  Enrollment, MedigapPolicy, DrugPhaseLedger — carries id, created_at,
  updated_at, and version (PRD §2.4).
- LateEnrollmentPenalty, DrugClaim, and StarRatingSnapshot are lean and
  carry only id and created_at — no updated_at, no version (PRD §2.4).
"""
from __future__ import annotations

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLAN_ADMIN = "PlanAdmin"
    BENEFITS_COUNSELOR = "BenefitsCounselor"
    BENEFICIARY = "Beneficiary"
    AUDITOR = "Auditor"


# ---------------------------------------------------------------------------
# Status enums — PRD §3
# ---------------------------------------------------------------------------
class BeneficiaryLifecycleStatus(str, Enum):
    PRE_ELIGIBLE = "PRE_ELIGIBLE"
    IEP_OPEN = "IEP_OPEN"
    IEP_CLOSED = "IEP_CLOSED"
    ENROLLED = "ENROLLED"
    COVERAGE_GAP = "COVERAGE_GAP"
    DECEASED = "DECEASED"


class PlanType(str, Enum):
    PART_A = "PART_A"
    PART_B = "PART_B"
    PART_C = "PART_C"
    PART_D = "PART_D"
    MEDIGAP = "MEDIGAP"


class PartCovered(str, Enum):
    PART_A = "PART_A"
    PART_B = "PART_B"
    PART_C = "PART_C"
    PART_D = "PART_D"


class EnrollmentPeriodType(str, Enum):
    IEP = "IEP"
    AEP = "AEP"
    GEP = "GEP"
    SEP_MOVE = "SEP_MOVE"
    SEP_LOSS_OF_COVERAGE = "SEP_LOSS_OF_COVERAGE"
    MEDIGAP_GI = "MEDIGAP_GI"


class EnrollmentPeriodStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CONSUMED = "CONSUMED"


class EnrollmentStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    REJECTED = "REJECTED"


class MedigapPolicyStatus(str, Enum):
    APPLIED = "APPLIED"
    GUARANTEED_ISSUED = "GUARANTEED_ISSUED"
    UNDERWRITING = "UNDERWRITING"
    ISSUED = "ISSUED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class DrugClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ADJUDICATED = "ADJUDICATED"
    REVERSED = "REVERSED"


class DrugTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"
    TIER_4 = "TIER_4"
    TIER_5 = "TIER_5"


class DrugPhase(str, Enum):
    DEDUCTIBLE = "DEDUCTIBLE"
    INITIAL_COVERAGE = "INITIAL_COVERAGE"
    COVERAGE_GAP = "COVERAGE_GAP"
    CATASTROPHIC = "CATASTROPHIC"


class LateEnrollmentPenaltyPart(str, Enum):
    PART_B = "PART_B"
    PART_D = "PART_D"


# ---------------------------------------------------------------------------
# Entities carrying id, created_at, updated_at, version — PRD §2.4
# ---------------------------------------------------------------------------
class Beneficiary(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    medicare_id: str
    has_esrd: bool
    has_disability: bool
    ssdi_start_date: Optional[str]
    state_code: str
    lifecycle_status: str
    iep_start_date: str
    iep_end_date: str
    medicare_eligibility_date: str
    deceased_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Plan(TypedDict, total=False):
    id: str
    plan_code: str
    plan_type: str
    plan_year: int
    state_code: Optional[str]
    monthly_premium_cents: int
    annual_deductible_cents: int
    initial_coverage_limit_cents: int
    catastrophic_threshold_cents: int
    star_rating: float
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class EnrollmentPeriod(TypedDict, total=False):
    id: str
    beneficiary_id: str
    period_type: str
    window_start: str
    window_end: str
    status: str
    consumed_by_enrollment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    beneficiary_id: str
    plan_id: str
    enrollment_period_id: str
    part_covered: str
    status: str
    effective_date: str
    termination_date: Optional[str]
    months_late: int
    created_at: str
    updated_at: str
    version: int


class MedigapPolicy(TypedDict, total=False):
    id: str
    beneficiary_id: str
    plan_id: str
    status: str
    gi_window_id: Optional[str]
    applied_at: str
    issued_at: Optional[str]
    premium_locked_cents: int
    underwriting_uplift_decimal: float
    created_at: str
    updated_at: str
    version: int


class DrugPhaseLedger(TypedDict, total=False):
    id: str
    beneficiary_id: str
    plan_year: int
    enrollment_id: str
    deductible_paid_cents: int
    total_drug_spend_cents: int
    troop_cents: int
    current_phase: str
    last_adjudicated_claim_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Lean entities — id + created_at ONLY (no updated_at, no version)
# PRD §2.4: "LateEnrollmentPenalty and DrugClaim carry only id and
# created_at — they have no updated_at and no version".
# PRD §2.4: "The StarRatingSnapshot is likewise lean: only id and
# created_at accompany its measurement fields."
# ---------------------------------------------------------------------------
class LateEnrollmentPenalty(TypedDict, total=False):
    id: str
    beneficiary_id: str
    enrollment_id: str
    part: str
    months_late: int
    penalty_rate_decimal: float
    monthly_penalty_cents: int
    snapshot_base_premium_cents: int
    created_at: str


class DrugClaim(TypedDict, total=False):
    id: str
    beneficiary_id: str
    enrollment_id: str
    ndc_code: str
    tier: str
    fill_date: str
    gross_cost_cents: int
    status: str
    phase_at_adjudication: Optional[str]
    beneficiary_cost_cents: Optional[int]
    plan_cost_cents: Optional[int]
    adjudicated_at: Optional[str]
    created_at: str


class StarRatingSnapshot(TypedDict, total=False):
    id: str
    plan_id: str
    measurement_year: int
    clinical_quality_score: float
    member_experience_score: float
    customer_service_score: float
    weighted_star_rating: float
    published_at: str
    created_at: str


__all__ = [
    "UserRole",
    "BeneficiaryLifecycleStatus",
    "PlanType",
    "PartCovered",
    "EnrollmentPeriodType",
    "EnrollmentPeriodStatus",
    "EnrollmentStatus",
    "MedigapPolicyStatus",
    "DrugClaimStatus",
    "DrugTier",
    "DrugPhase",
    "LateEnrollmentPenaltyPart",
    "Beneficiary",
    "Plan",
    "EnrollmentPeriod",
    "Enrollment",
    "MedigapPolicy",
    "DrugPhaseLedger",
    "LateEnrollmentPenalty",
    "DrugClaim",
    "StarRatingSnapshot",
]
