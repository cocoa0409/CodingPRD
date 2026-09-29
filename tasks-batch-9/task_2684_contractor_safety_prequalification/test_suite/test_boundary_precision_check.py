"""Difficulty rule: boundary_precision_check.

Values sitting exactly on a boundary: a metric equal to its effective ceiling,
and an audit draw whose ceiling rounds a fractional row up — including the
degenerate pool of zero rows.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prd_bench_local_runner.testing import validate_success  # noqa: E402

from test_helpers.assertions import (  # noqa: E402
    assert_contractor_posture,
    assert_effective_thresholds,
    assert_instant_equals,
    assert_prequalification_state,
    assert_score_equals,
)
from test_helpers.constants import INITIAL_CLOCK  # noqa: E402

_EMR_AT_CEILING = {"emr": 1.00}


def test_emr_exactly_at_its_ceiling_scores_fifty_and_composites_to_78_01(build, api):
    """The EMR sub-score is exactly 50.00, so the composite lands on 78.01.

    PRD Section 3.4: "When a value is at or below its threshold, the sub-score
    is one hundred minus fifty times the ratio of value to threshold, rounded
    half-up to two decimal places — so a value exactly equal to its threshold
    scores exactly 50.00 and a value of zero scores 100.00."

    Design: Difficulty/boundary_precision_check/emr_exactly_at_effective_threshold_is_not_a_breach_and_grades_approved
    """
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing(statistic_overrides=_EMR_AT_CEILING)

    graded = scenario["prequalification"]
    assert_score_equals(graded["final_composite_score"], 78.01)
    assert_effective_thresholds(
        graded["effective_thresholds"],
        max_trir=3.0000,
        max_dart_rate=1.5000,
        max_emr=1.0000,
        max_citation_points=6.0000,
        tightening=1.00,
        hazard_tier=1,
    )

    scorecard = validate_success(
        api.get_scorecard(scenario["prequalification_id"], scenario["manager_headers"])
    )
    assert scorecard["normalized_metrics"]["emr"] == 1.00, (
        f"expected the governing emr 1.00, got {scorecard['normalized_metrics']['emr']}"
    )
    assert_score_equals(scorecard["final_composite_score"], 78.01)


def test_value_equal_to_its_effective_ceiling_is_not_a_breach(build, api):
    """No soft breach is recorded, so the row is approved with no codes.

    PRD Section 3.6: "Both comparisons against the effective ceiling itself are
    strict: a value exactly equal to its effective ceiling is not a breach at
    all."

    Design: Difficulty/boundary_precision_check/emr_exactly_at_effective_threshold_is_not_a_breach_and_grades_approved
    """
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing(statistic_overrides=_EMR_AT_CEILING)

    graded = scenario["prequalification"]
    assert_prequalification_state(
        graded,
        status="APPROVED",
        grade="B",
        deficiency_codes=[],
        final_composite_score=78.01,
    )
    assert graded["conditional_expires_at"] is None
    assert_instant_equals(graded["expires_at"], "2027-08-01T00:00:00Z")

    contractor = build.read_contractor(scenario["contractor_id"])
    assert_contractor_posture(contractor, open_deficiency_count=0)


def test_audit_sampling_run_draws_nothing_from_an_empty_eligible_pool(build, api):
    """A DRAFT row is not eligible, and an empty pool is a 200 with zero draws.

    PRD Section 3.11: "An empty eligible pool is a perfectly normal result: the
    run reports a `selected_count` of 0 and an empty array with a 200 response,
    never an error."

    Design: Difficulty/boundary_precision_check/audit_sampling_ceiling_draws_zero_from_an_empty_pool_and_one_from_a_single_row_pool
    """
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing(submit=False, grade=False)

    result = validate_success(
        api.run_audit_sampling(scenario["client_id"], {}, scenario["manager_headers"]),
        200,
    )
    assert result["selected_count"] == 0, (
        f"expected selected_count 0 from an empty pool, got {result['selected_count']}"
    )
    assert result["selected_prequalification_ids"] == []

    row = build.read_prequalification(scenario["prequalification_id"])
    assert_prequalification_state(row, status="DRAFT", audit_state="NOT_SELECTED")
    assert row["audit_selected_at"] is None


def test_audit_sampling_ceiling_draws_one_row_from_a_single_row_pool(build, api):
    """25 percent of one eligible row rounds up to exactly one draw.

    PRD Section 3.11: "The draw size is the client's `audit_sample_rate_pct`
    expressed as a fraction, multiplied by the number of eligible rows, rounded
    **up** to the next whole row: at the default rate of 25 percent, a pool of
    five rows yields two draws, and a pool of one row yields one."

    Design: Difficulty/boundary_precision_check/audit_sampling_ceiling_draws_zero_from_an_empty_pool_and_one_from_a_single_row_pool
    """
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing()
    pq_id = scenario["prequalification_id"]

    assert_prequalification_state(
        scenario["prequalification"],
        status="APPROVED",
        grade="B",
        final_composite_score=80.51,
        audit_state="NOT_SELECTED",
    )

    result = validate_success(
        api.run_audit_sampling(scenario["client_id"], {}, scenario["manager_headers"]),
        200,
    )
    assert result["selected_count"] == 1, (
        f"expected selected_count 1 from a one-row pool, got {result['selected_count']}"
    )
    assert result["selected_prequalification_ids"] == [pq_id]

    row = build.read_prequalification(pq_id)
    assert_prequalification_state(row, status="APPROVED", audit_state="SELECTED")
    assert_instant_equals(row["audit_selected_at"], INITIAL_CLOCK)
