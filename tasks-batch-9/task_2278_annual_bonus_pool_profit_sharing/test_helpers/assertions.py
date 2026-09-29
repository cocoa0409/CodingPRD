"""Entity assertions and the domain's conserved-quantity checks."""

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import THRESHOLDS, burden_rate_pct_for
from .types import (
    AccrualPeriodStatus,
    AdjustmentStatus,
    AllocationStatus,
    DisputeStatus,
    EligibilityStatus,
    EmploymentStatus,
    EventType,
    GovernancePosture,
    MetricStatus,
    PaymentStatus,
    PayoutRunStatus,
    PlanStatus,
    PoolCalibrationStatus,
    PoolDistributionStatus,
    TerminationTreatmentPolicy,
)

MONEY_TOLERANCE = 0  # money is integer cents and compares exactly
PCT_TOLERANCE = 0.005  # two-decimal percentage fields
RATIO_TOLERANCE = 0.00005  # four-decimal multiplier and ratio fields


def _members(enum_cls):
    return [member.value for member in enum_cls]


def assert_cents(value, expected: int, label: str = "money field"):
    """Money is held as an integer number of cents; no monetary field is a decimal."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )
    assert value == expected, f"{label}: expected {expected} cents, got {value}"


def assert_is_cents(value, label: str = "money field"):
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )


def assert_pct(value, expected: float, label: str = "percentage field"):
    """Two-decimal percentage comparison."""
    assert value == pytest.approx(expected, abs=PCT_TOLERANCE), (
        f"{label}: expected {expected}, got {value}"
    )


def assert_ratio(value, expected: float, label: str = "ratio field"):
    """Four-decimal multiplier / allocation-ratio comparison."""
    assert value == pytest.approx(expected, abs=RATIO_TOLERANCE), (
        f"{label}: expected {expected}, got {value}"
    )


def assert_audit_fields(data: dict, label: str = "resource"):
    """id, created_at, updated_at and version, the four fields every resource but
    an eligibility event carries."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version starts at 1"


# ─── Bonus plan ───────────────────────────────────────────────────────────
def assert_bonus_plan(data: dict):
    assert_audit_fields(data, "BonusPlan")
    assert data["status"] in _members(PlanStatus)
    assert data["governance_posture"] in _members(GovernancePosture)
    assert data["termination_treatment_policy"] in _members(TerminationTreatmentPolicy)
    assert isinstance(data["plan_year"], int)
    assert 1900 <= data["plan_year"] <= 2999
    for field in (
        "total_target_cents",
        "funded_pool_cents",
        "aggregate_rounding_delta_cents",
        "discretionary_budget_cents",
        "discretionary_used_cents",
        "accrued_base_cents",
        "accrued_total_cents",
        "locked_total_cents",
        "paid_total_cents",
        "forfeited_total_cents",
        "dispute_adjustment_cents",
        "settlement_burden_cents",
        "true_up_cents",
    ):
        assert_is_cents(data[field], f"BonusPlan.{field}")
    assert isinstance(data["over_allocated_pool_count"], int)
    assert isinstance(data["under_utilized_pool_count"], int)
    assert data["company_weight_pct"] + data["business_unit_weight_pct"] + data[
        "individual_weight_pct"
    ] == pytest.approx(100.00, abs=PCT_TOLERANCE)


def assert_company_metric(data: dict):
    assert_audit_fields(data, "CompanyMetric")
    assert data["status"] in _members(MetricStatus)
    assert 0.01 <= data["weight_pct"] <= 100.00
    assert data["threshold_value"] < data["target_value"] < data["max_value"]
    assert 0.00 <= data["achievement_pct"] <= THRESHOLDS["METRIC_ACHIEVEMENT_CAP"]


def assert_business_unit(data: dict):
    assert_audit_fields(data, "BusinessUnit")
    assert isinstance(data["unit_code"], str) and data["unit_code"]
    assert isinstance(data["name"], str) and data["name"]


def assert_job_level_target(data: dict):
    assert_audit_fields(data, "JobLevelTarget")
    assert isinstance(data["job_level"], str) and data["job_level"]
    assert 0.01 <= data["target_bonus_pct"] <= 200.00
    assert data["guideline_max_ratio"] > data["guideline_min_ratio"]


def assert_participant(data: dict):
    assert_audit_fields(data, "Participant")
    assert data["employment_status"] in _members(EmploymentStatus)
    assert_is_cents(data["base_salary_cents"], "Participant.base_salary_cents")
    assert data["base_salary_cents"] >= 1
    assert_is_cents(
        data["current_base_salary_cents"], "Participant.current_base_salary_cents"
    )


def assert_eligibility_event(data: dict):
    """Eligibility events are the one exception: only ``id`` and ``created_at``."""
    assert is_valid_uuid(data.get("id", "")), "EligibilityEvent.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "EligibilityEvent.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, (
        "an eligibility event has neither updated_at nor version"
    )
    assert "version" not in data, (
        "an eligibility event has neither updated_at nor version"
    )
    assert data["event_type"] in _members(EventType)
    assert isinstance(data["superseded"], bool)


def assert_bu_pool(data: dict):
    assert_audit_fields(data, "BusinessUnitPool")
    assert data["calibration_status"] in _members(PoolCalibrationStatus)
    assert data["distribution_status"] in _members(PoolDistributionStatus)
    for field in (
        "eligible_target_cents",
        "funded_cents",
        "allocated_cents",
        "available_cents",
        "min_utilization_cents",
    ):
        assert_is_cents(data[field], f"BusinessUnitPool.{field}")
    assert isinstance(data["eligible_headcount"], int)
    assert isinstance(data["top_tier_award_count"], int)
    assert isinstance(data["max_top_tier_count"], int)
    assert isinstance(data["calibration_returned_count"], int)
    assert_pool_conservation(data)


def assert_participant_award(data: dict):
    assert_audit_fields(data, "ParticipantAward")
    assert data["allocation_status"] in _members(AllocationStatus)
    assert data["payment_status"] in _members(PaymentStatus)
    assert data["eligibility_status"] in _members(EligibilityStatus)
    for field in (
        "prorated_target_cents",
        "proposed_allocation_cents",
        "adjustment_total_cents",
        "final_award_cents",
        "payout_amount_cents",
    ):
        assert_is_cents(data[field], f"ParticipantAward.{field}")
    assert isinstance(data["credited_days"], int)
    assert isinstance(data["segment_count"], int)
    assert isinstance(data["retraction_count"], int)


def assert_discretionary_adjustment(data: dict):
    assert_audit_fields(data, "DiscretionaryAdjustment")
    assert data["status"] in _members(AdjustmentStatus)
    assert_is_cents(data["adjustment_cents"], "DiscretionaryAdjustment.adjustment_cents")
    assert data["adjustment_cents"] != 0, "adjustment_cents is signed and non-zero"
    assert_is_cents(
        data["per_award_cap_cents"], "DiscretionaryAdjustment.per_award_cap_cents"
    )
    assert isinstance(data["justification"], str) and len(data["justification"]) >= 1
    assert isinstance(data["submitted_by_user_id"], str)


def assert_accrual_period(data: dict):
    assert_audit_fields(data, "AccrualPeriod")
    assert data["status"] in _members(AccrualPeriodStatus)
    assert data["period_end"] >= data["period_start"]


def assert_payout_run(data: dict):
    assert_audit_fields(data, "PayoutRun")
    assert data["status"] in _members(PayoutRunStatus)
    for field in (
        "total_paid_cents",
        "total_forfeited_cents",
        "settlement_burden_cents",
        "true_up_cents",
    ):
        assert_is_cents(data[field], f"PayoutRun.{field}")


def assert_dispute(data: dict):
    assert_audit_fields(data, "Dispute")
    assert data["status"] in _members(DisputeStatus)
    assert isinstance(data["dispute_reason"], str) and data["dispute_reason"]


# ─── Conserved quantities ─────────────────────────────────────────────────
def assert_pool_conservation(pool: dict):
    """For every pool, funded_cents always equals allocated_cents plus available_cents."""
    assert pool["funded_cents"] == pool["allocated_cents"] + pool["available_cents"], (
        "funded_cents must equal allocated_cents plus available_cents: "
        f"{pool['funded_cents']} != {pool['allocated_cents']} + {pool['available_cents']}"
    )


def assert_accrual_ledger_conservation(plan: dict, periods: list):
    """accrued_base_cents is the sum of period_accrual_cents over POSTED periods, and
    accrued_total_cents the sum of total_period_cents over the same set."""
    posted = [p for p in periods if p["status"] == AccrualPeriodStatus.POSTED.value]
    assert plan["accrued_base_cents"] == sum(p["period_accrual_cents"] for p in posted)
    assert plan["accrued_total_cents"] == sum(p["total_period_cents"] for p in posted)


def assert_discretionary_ledger_conservation(plan: dict, adjustments: list):
    """discretionary_used_cents is the sum of the absolute values of adjustment_cents
    over the plan's APPROVED adjustments."""
    approved = [
        a for a in adjustments if a["status"] == AdjustmentStatus.APPROVED.value
    ]
    assert plan["discretionary_used_cents"] == sum(
        abs(a["adjustment_cents"]) for a in approved
    )


def assert_settlement_closure(plan: dict):
    """accrued_total_cents plus true_up_cents equals paid_total_cents plus
    settlement_burden_cents."""
    assert plan["accrued_total_cents"] + plan["true_up_cents"] == (
        plan["paid_total_cents"] + plan["settlement_burden_cents"]
    ), "the settlement closure must hold exactly"


def assert_burden_band(cents: int, burden_rate_pct: float):
    """The burden rate is selected from the three-band table keyed on ``cents``."""
    assert_pct(burden_rate_pct, burden_rate_pct_for(cents), "burden_rate_pct")


def assert_distribution_status(pool: dict):
    """Recompute distribution_status from the pool's own integer cents figures."""
    if pool["eligible_headcount"] == 0:
        expected = PoolDistributionStatus.NO_ELIGIBLE_PARTICIPANTS.value
    elif pool["allocated_cents"] > pool["funded_cents"]:
        expected = PoolDistributionStatus.OVER_ALLOCATED.value
    elif pool["allocated_cents"] < pool["min_utilization_cents"]:
        expected = PoolDistributionStatus.UNDER_UTILIZED.value
    else:
        expected = PoolDistributionStatus.WITHIN_GUIDELINES.value
    assert pool["distribution_status"] == expected, (
        f"expected distribution_status {expected}, got {pool['distribution_status']}"
    )


def assert_max_top_tier_count(pool: dict):
    """max_top_tier_count is the greater of 1 and a quarter of eligible_headcount
    truncated downward."""
    expected = max(
        THRESHOLDS["TOP_TIER_MINIMUM_CAP"],
        pool["eligible_headcount"] // THRESHOLDS["TOP_TIER_HEADCOUNT_DIVISOR"],
    )
    assert pool["max_top_tier_count"] == expected


def assert_min_utilization_floor(pool: dict):
    """min_utilization_cents is funded_cents * 9950 / 10000 with the fraction discarded."""
    expected = (
        pool["funded_cents"] * THRESHOLDS["MIN_UTILIZATION_NUMERATOR"]
    ) // THRESHOLDS["MIN_UTILIZATION_DENOMINATOR"]
    assert pool["min_utilization_cents"] == expected


def assert_governance_posture(plan: dict):
    """BREACHED when two or more pools are over-allocated, otherwise FLAGGED when
    exactly one is over-allocated or at least one is under-utilized, otherwise
    COMPLIANT."""
    if plan["over_allocated_pool_count"] >= 2:
        expected = GovernancePosture.BREACHED.value
    elif plan["over_allocated_pool_count"] == 1 or plan["under_utilized_pool_count"] >= 1:
        expected = GovernancePosture.FLAGGED.value
    else:
        expected = GovernancePosture.COMPLIANT.value
    assert plan["governance_posture"] == expected, (
        f"expected governance_posture {expected}, got {plan['governance_posture']}"
    )
