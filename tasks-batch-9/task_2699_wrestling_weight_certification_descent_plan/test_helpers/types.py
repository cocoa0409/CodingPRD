"""
Response shapes.

Most stored resources carry ``id``, ``created_at``, ``updated_at`` and an
integer ``version``.  Three resource types are deliberately append-only and
therefore carry only ``id`` and ``created_at`` — ``WeighIn``,
``EligibilityCheck`` and ``GrowthAllowance`` have no ``updated_at`` and no
``version`` in any response, which is why they inherit from ``AppendOnlyRow``
rather than from ``MutableRow``.
"""

from typing import Any, Dict, List, Optional

try:  # pragma: no cover - the fallback only matters on very old interpreters
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict


class AppendOnlyRow(TypedDict):
    """The identity fields every stored resource carries."""

    id: str
    created_at: str


class MutableRow(AppendOnlyRow, total=False):
    """Adds the mutation bookkeeping most resources also carry."""

    updated_at: str
    version: int


# ── Season ───────────────────────────────────────────────────────────
class Season(MutableRow, total=False):
    name: str
    start_date: str
    weight_classes: List[int]
    min_body_fat_pct_male: float
    min_body_fat_pct_female: float
    hydration_max_specific_gravity: float
    max_weekly_descent_pct: float
    assessor_min_training_hours: int
    audit_fail_threshold_pct: float
    audit_min_sample_count: int
    max_consecutive_day_allowance_lbs: float
    appeal_filing_window_days: int
    max_appeal_retest_rounds: int
    assessor_daily_assessment_capacity: int
    plan_breach_limit: int
    status: str
    team_count: int
    certified_wrestler_count: int


# ── Team ─────────────────────────────────────────────────────────────
class Team(MutableRow, total=False):
    season_id: str
    school_name: str
    roster_count: int
    open_flag_severity_total: int
    compliance_status: str


# ── Assessor ─────────────────────────────────────────────────────────
class Assessor(MutableRow, total=False):
    full_name: str
    credential_number: str
    certified_methods: List[str]
    certification_expires_on: str
    training_hours_completed: float
    status: str
    validated_assessment_count: int
    voided_assessment_count: int
    last_audit_outcome: Optional[str]
    suspension_reason: Optional[str]


# ── Wrestler ─────────────────────────────────────────────────────────
class Wrestler(MutableRow, total=False):
    team_id: str
    source_assessment_id: Optional[str]
    full_name: str
    sex: str
    grade: int
    certification_status: str
    eligibility_status: str
    alpha_weight_lbs: Optional[float]
    body_fat_pct: Optional[float]
    minimum_certified_weight_lbs: Optional[float]
    min_weight_class_lbs: Optional[int]
    lowest_eligible_class_lbs: Optional[int]
    open_health_flag_count: int
    disqualified_at: Optional[str]
    certification_hold_reason: Optional[str]


# ── Assessment ───────────────────────────────────────────────────────
class Assessment(MutableRow, total=False):
    wrestler_id: str
    assessor_id: str
    retest_of_assessment_id: Optional[str]
    appeal_id: Optional[str]
    method: str
    assessed_at: str
    measured_weight_lbs: float
    body_fat_pct: float
    urine_specific_gravity: float
    status: str
    hydration_passed: Optional[bool]
    lean_body_weight_lbs: Optional[float]
    minimum_certified_weight_lbs: Optional[float]
    min_weight_class_lbs: Optional[int]
    alpha_weight_lbs: Optional[float]
    void_reason: Optional[str]


# ── Appeal ───────────────────────────────────────────────────────────
class Appeal(MutableRow, total=False):
    assessment_id: str
    team_id: str
    reviewing_assessor_id: Optional[str]
    retest_assessment_id: Optional[str]
    reason: str
    filed_at: str
    status: str
    retest_round_count: int
    decision_note: Optional[str]


# ── Descent plan ─────────────────────────────────────────────────────
class DescentPlan(MutableRow, total=False):
    wrestler_id: str
    source_assessment_id: str
    supersedes_plan_id: Optional[str]
    plan_variant: str
    target_class_lbs: int
    plan_start_date: str
    weekly_rate_pct: float
    weekly_delta_lbs: Optional[float]
    status: str
    total_weeks: Optional[int]
    milestone_count: int
    projected_certification_date: Optional[str]
    missed_milestone_count: int
    breach_count: int
    revision_count: int
    cancel_reason: Optional[str]


# ── Descent milestone ────────────────────────────────────────────────
class DescentMilestone(MutableRow, total=False):
    plan_id: str
    week_index: int
    effective_date: str
    allowable_weight_lbs: float
    min_eligible_class_lbs: int
    status: str
    evaluated_recorded_weight_lbs: Optional[float]


# ── Event ────────────────────────────────────────────────────────────
class Event(MutableRow, total=False):
    season_id: str
    name: str
    event_type: str
    event_date: str
    competition_days: int
    weigh_in_days: int
    consecutive_day_allowance_lbs: float
    status: str
    bracket_locked: bool
    reseed_required: bool
    entry_count: int
    weighed_in_count: int
    seeded_entry_count: int
    seed_integrity_sum: int


# ── Tournament entry ─────────────────────────────────────────────────
class TournamentEntry(MutableRow, total=False):
    event_id: str
    wrestler_id: str
    weight_class_lbs: int
    season_win_count: int
    status: str
    seed_number: Optional[int]
    latest_effective_weight_lbs: Optional[float]
    weight_class_change_count: int
    scratch_reason: Optional[str]


# ── Weigh-in (append-only) ───────────────────────────────────────────
class WeighIn(AppendOnlyRow, total=False):
    event_id: str
    wrestler_id: str
    entry_id: str
    day_index: int
    recorded_weight_lbs: float
    recorded_at: str
    official_user_id: str
    allowance_lbs: float
    effective_limit_lbs: float
    result: str
    below_minimum: bool


# ── Eligibility check (append-only) ──────────────────────────────────
class EligibilityCheck(AppendOnlyRow, total=False):
    wrestler_id: str
    event_id: str
    requested_class_lbs: int
    checked_at: str
    as_of_date: str
    growth_allowance_lbs: float
    schedule_allowable_weight_lbs: Optional[float]
    lowest_eligible_class_lbs: Optional[int]
    outcome: str
    blocking_error_id: Optional[str]


# ── Growth allowance (append-only) ───────────────────────────────────
class GrowthAllowance(AppendOnlyRow, total=False):
    season_id: str
    effective_date: str
    allowance_lbs: float
    note: Optional[str]


# ── Health flag ──────────────────────────────────────────────────────
class HealthFlag(MutableRow, total=False):
    wrestler_id: str
    weigh_in_id: Optional[str]
    source: str
    severity: int
    status: str
    raised_at: str
    review_note: Optional[str]
    reviewer_user_id: Optional[str]


# ── Program audit ────────────────────────────────────────────────────
class ProgramAudit(MutableRow, total=False):
    season_id: str
    assessor_id: Optional[str]
    audit_type: str
    scoring_variant: str
    sample_window_start: str
    samples: List[Dict[str, Any]]
    sample_count: int
    discrepancy_score: Optional[float]
    outcome: Optional[str]
    voided_assessment_count: int
    status: str


# Field sets used by the shared shape assertions.
COMMON_MUTABLE_FIELDS = ("id", "created_at", "updated_at", "version")
COMMON_APPEND_ONLY_FIELDS = ("id", "created_at")
APPEND_ONLY_ENTITIES = ("WeighIn", "EligibilityCheck", "GrowthAllowance")
