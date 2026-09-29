"""Domain types for the Annual Bonus Pool & Profit Sharing API.

Enum members mirror the exact literal values the API stores and returns.
TypedDicts describe the response shapes the tests assert against; note that
EligibilityEvent deliberately carries only ``id`` and ``created_at`` because
eligibility events are an append-only record with no ``updated_at`` and no
``version``.
"""

from enum import Enum
from typing import Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    PLAN_ADMIN = "PlanAdmin"
    COMPENSATION_COMMITTEE = "CompensationCommittee"
    BUSINESS_UNIT_MANAGER = "BusinessUnitManager"
    HR_BUSINESS_PARTNER = "HRBusinessPartner"
    FINANCE_CONTROLLER = "FinanceController"
    EMPLOYEE = "Employee"


# ─── Bonus plan ───────────────────────────────────────────────────────────
class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    TARGETS_SET = "TARGETS_SET"
    PENDING_CERTIFICATION = "PENDING_CERTIFICATION"
    CERTIFIED = "CERTIFIED"
    ALLOCATION_OPEN = "ALLOCATION_OPEN"
    CALIBRATION_REVIEW = "CALIBRATION_REVIEW"
    LOCKED = "LOCKED"
    PAID_OUT = "PAID_OUT"
    SETTLED = "SETTLED"


class GovernancePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    FLAGGED = "FLAGGED"
    BREACHED = "BREACHED"


class TerminationTreatmentPolicy(str, Enum):
    STRICT_PAYMENT_DATE = "STRICT_PAYMENT_DATE"
    GOOD_LEAVER_PRORATION = "GOOD_LEAVER_PRORATION"


# ─── Company metric ───────────────────────────────────────────────────────
class MetricStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTUAL_ENTERED = "ACTUAL_ENTERED"


# ─── Business unit pool ───────────────────────────────────────────────────
class PoolCalibrationStatus(str, Enum):
    DRAFT = "DRAFT"
    SCORECARD_SUBMITTED = "SCORECARD_SUBMITTED"
    SCORECARD_CERTIFIED = "SCORECARD_CERTIFIED"
    FUNDED = "FUNDED"
    ALLOCATING = "ALLOCATING"
    CALIBRATION_SUBMITTED = "CALIBRATION_SUBMITTED"
    CALIBRATED = "CALIBRATED"
    LOCKED = "LOCKED"


class PoolDistributionStatus(str, Enum):
    NO_ELIGIBLE_PARTICIPANTS = "NO_ELIGIBLE_PARTICIPANTS"
    OVER_ALLOCATED = "OVER_ALLOCATED"
    UNDER_UTILIZED = "UNDER_UTILIZED"
    WITHIN_GUIDELINES = "WITHIN_GUIDELINES"


# ─── Participant and eligibility events ───────────────────────────────────
class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    TERMINATED = "TERMINATED"


class EventType(str, Enum):
    TRANSFER = "TRANSFER"
    LEAVE = "LEAVE"
    TERMINATION = "TERMINATION"


class TerminationReason(str, Enum):
    VOLUNTARY_RESIGNATION = "VOLUNTARY_RESIGNATION"
    TERMINATED_FOR_CAUSE = "TERMINATED_FOR_CAUSE"
    REDUNDANCY = "REDUNDANCY"
    RETIREMENT = "RETIREMENT"
    DEATH = "DEATH"
    DISABILITY = "DISABILITY"


# ─── Participant award ────────────────────────────────────────────────────
class AllocationStatus(str, Enum):
    UNALLOCATED = "UNALLOCATED"
    PROPOSED = "PROPOSED"
    CALIBRATED = "CALIBRATED"
    LOCKED = "LOCKED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    DEFERRED = "DEFERRED"
    PAID = "PAID"
    FORFEITED = "FORFEITED"


class EligibilityStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    GOOD_LEAVER = "GOOD_LEAVER"
    BAD_LEAVER = "BAD_LEAVER"
    INELIGIBLE_MIN_SERVICE = "INELIGIBLE_MIN_SERVICE"


# ─── Discretionary adjustment ─────────────────────────────────────────────
class AdjustmentStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVERSED = "REVERSED"


# ─── Accrual period ───────────────────────────────────────────────────────
class AccrualPeriodStatus(str, Enum):
    OPEN = "OPEN"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class ProvisionalTargetBasis(str, Enum):
    AWARD_PRORATED = "AWARD_PRORATED"
    PARTICIPANT_UNPRORATED = "PARTICIPANT_UNPRORATED"


# ─── Payout run ───────────────────────────────────────────────────────────
class PayoutRunStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    SETTLED = "SETTLED"


# ─── Dispute ──────────────────────────────────────────────────────────────
class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_ADJUSTED = "RESOLVED_ADJUSTED"


# ─── Decision verbs ───────────────────────────────────────────────────────
class ReviewDecision(str, Enum):
    CERTIFY = "CERTIFY"
    RETURN = "RETURN"


class AdjustmentDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class DisputeResolution(str, Enum):
    UPHOLD = "UPHOLD"
    ADJUST = "ADJUST"


# ─── Response shapes ──────────────────────────────────────────────────────
class BonusPlan(TypedDict, total=False):
    id: str
    plan_year: int
    plan_name: str
    plan_period_start: str
    plan_period_end: str
    payment_date: str
    company_weight_pct: float
    business_unit_weight_pct: float
    individual_weight_pct: float
    discretionary_budget_pct: float
    termination_treatment_policy: str
    status: str
    governance_posture: str
    company_achievement_pct: float
    bu_weighted_achievement_pct: float
    blended_achievement_pct: float
    funding_multiplier: float
    total_target_cents: int
    funded_pool_cents: int
    aggregate_rounding_delta_cents: int
    discretionary_budget_cents: int
    discretionary_used_cents: int
    accrued_base_cents: int
    accrued_total_cents: int
    locked_total_cents: int
    paid_total_cents: int
    forfeited_total_cents: int
    dispute_adjustment_cents: int
    settlement_burden_cents: int
    true_up_cents: int
    over_allocated_pool_count: int
    under_utilized_pool_count: int
    certified_by_user_id: Optional[str]
    locked_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CompanyMetric(TypedDict, total=False):
    id: str
    plan_id: str
    metric_code: str
    weight_pct: float
    threshold_value: float
    target_value: float
    max_value: float
    actual_value: Optional[float]
    source_note: Optional[str]
    achievement_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class BusinessUnit(TypedDict, total=False):
    id: str
    unit_code: str
    name: str
    created_at: str
    updated_at: str
    version: int


class JobLevelTarget(TypedDict, total=False):
    id: str
    plan_id: str
    job_level: str
    target_bonus_pct: float
    guideline_min_ratio: float
    guideline_max_ratio: float
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict, total=False):
    id: str
    plan_id: str
    business_unit_id: str
    employee_code: str
    full_name: str
    job_level: str
    base_salary_cents: int
    hire_date: str
    employment_status: str
    termination_date: Optional[str]
    termination_reason: Optional[str]
    current_job_level: str
    current_base_salary_cents: int
    current_business_unit_id: str
    created_at: str
    updated_at: str
    version: int


class EligibilityEvent(TypedDict, total=False):
    """Append-only record: carries only ``id`` and ``created_at`` as audit fields."""

    id: str
    participant_id: str
    event_type: str
    effective_date: str
    new_job_level: Optional[str]
    new_base_salary_cents: Optional[int]
    new_business_unit_id: Optional[str]
    leave_end_date: Optional[str]
    paid_leave: bool
    termination_reason: Optional[str]
    note: Optional[str]
    supersedes_event_id: Optional[str]
    superseded: bool
    created_at: str


class BusinessUnitPool(TypedDict, total=False):
    id: str
    plan_id: str
    business_unit_id: str
    bu_metric_achievement_pct: float
    scorecard_narrative: Optional[str]
    calibration_status: str
    distribution_status: str
    eligible_target_cents: int
    eligible_headcount: int
    funded_cents: int
    allocated_cents: int
    available_cents: int
    min_utilization_cents: int
    utilization_pct: float
    top_tier_award_count: int
    max_top_tier_count: int
    calibration_returned_count: int
    scorecard_certified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ParticipantAward(TypedDict, total=False):
    id: str
    plan_id: str
    participant_id: str
    business_unit_id: str
    bu_pool_id: str
    prorated_target_cents: int
    credited_days: int
    excluded_leave_days: int
    segment_count: int
    target_bonus_pct: float
    eligibility_status: str
    allocation_status: str
    payment_status: str
    proposed_allocation_cents: int
    allocation_ratio: float
    allocation_rationale: Optional[str]
    adjustment_total_cents: int
    final_award_cents: int
    payout_amount_cents: int
    retraction_count: int
    created_at: str
    updated_at: str
    version: int


class DiscretionaryAdjustment(TypedDict, total=False):
    id: str
    plan_id: str
    award_id: str
    adjustment_cents: int
    justification: str
    documentation_ref: Optional[str]
    per_award_cap_cents: int
    status: str
    submitted_by_user_id: str
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccrualPeriod(TypedDict, total=False):
    id: str
    plan_id: str
    period_start: str
    period_end: str
    forecast_company_achievement_pct: float
    status: str
    provisional_target_basis: Optional[str]
    provisional_pool_cents: int
    elapsed_days: int
    cumulative_accrual_target_cents: int
    period_accrual_cents: int
    burden_rate_pct: float
    burden_cents: int
    total_period_cents: int
    posting_note: Optional[str]
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayoutRun(TypedDict, total=False):
    id: str
    plan_id: str
    run_note: Optional[str]
    status: str
    payment_date_used: Optional[str]
    paid_award_count: int
    deferred_award_count: int
    forfeited_award_count: int
    total_paid_cents: int
    total_forfeited_cents: int
    settlement_burden_cents: int
    true_up_cents: int
    settlement_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict, total=False):
    id: str
    plan_id: str
    award_id: str
    participant_id: str
    dispute_reason: str
    claimed_amount_cents: Optional[int]
    status: str
    reviewer_note: Optional[str]
    assigned_by_user_id: Optional[str]
    resolution: Optional[str]
    resolution_note: Optional[str]
    adjusted_amount_cents: Optional[int]
    resolved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
