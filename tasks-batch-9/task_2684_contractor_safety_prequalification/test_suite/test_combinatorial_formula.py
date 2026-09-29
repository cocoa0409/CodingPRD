"""Difficulty rule: combinatorial_formula.

Two multi-input formulas whose intermediate rounding order and whose input
resolution order both change the answer: the composite score's per-product
rounding, and the threshold resolution that reads a hazard tier out of the
incident record.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prd_bench_local_runner.testing import validate_success  # noqa: E402

from test_helpers.assertions import (  # noqa: E402
    assert_contractor_posture,
    assert_effective_thresholds,
    assert_exact_int,
    assert_grant_state,
    assert_instant_equals,
    assert_prequalification_state,
    assert_rate_equals,
    reconcile_open_deficiency_count,
)
from test_helpers.constants import INITIAL_CLOCK  # noqa: E402

# hours 1000000, 10 recordables, 5 DART cases, EMR 0.95 and two serious
# citations: trir 2.0000, dart_rate 1.0000, citation_points 4.
_HEAVY_STATISTIC = {
    "reporting_year": 2025,
    "hours_worked": 1000000,
    "recordable_incidents": 10,
    "dart_cases": 5,
    "fatalities": 0,
    "emr": 0.95,
    "citation_count_willful": 0,
    "citation_count_serious": 2,
    "citation_count_other": 0,
    "source_document_ref": "OSHA300A-2025",
}


def test_statistic_normalization_writes_four_decimal_rates_and_exact_points(build, api):
    """trir 2.0000, dart_rate 1.0000 and citation_points exactly 4.

    PRD Section 3.3: "Citation history is collapsed into a single integer
    `citation_points` by weighting severity: each willful citation contributes
    5 points, each serious citation contributes 2 points, and each
    other-than-serious citation contributes 1 point; the three products are
    added and the result is an exact integer with no rounding step at all."

    Design: Difficulty/combinatorial_formula/metric_normalization_rounds_each_weighted_product_before_summing
    """
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing(
        statistic_overrides=_HEAVY_STATISTIC, submit=False, grade=False
    )

    statistic = scenario["statistic"]
    assert_rate_equals(statistic["trir"], 2.0000)
    assert_rate_equals(statistic["dart_rate"], 1.0000)
    assert_exact_int(statistic["citation_points"], 4)
    assert statistic["verification_status"] == "VERIFIED"


def test_each_weighted_product_is_rounded_before_the_sum_yielding_63_14(build, api):
    """Per-product rounding lands on 63.14, not the single-rounding 63.13.

    PRD Section 3.4: "**Each weighted product is rounded half-up to two decimal
    places before it enters the sum**, the four rounded products are added in
    the fixed metric order TRIR, then DART, then EMR, then citation points, and
    the total is rounded half-up to two decimal places again."

    Design: Difficulty/combinatorial_formula/metric_normalization_rounds_each_weighted_product_before_summing
    """
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing(statistic_overrides=_HEAVY_STATISTIC)

    graded = scenario["prequalification"]
    assert_prequalification_state(
        graded,
        status="CONDITIONAL",
        grade="C",
        deficiency_codes=["COMPOSITE_C"],
        final_composite_score=63.14,
    )
    assert graded["final_composite_score"] != 63.13, (
        "63.13 is the forbidden single-rounding result of summing unrounded products"
    )
    assert_effective_thresholds(
        graded["effective_thresholds"],
        max_trir=3.0000,
        max_dart_rate=1.5000,
        max_emr=1.0000,
        max_citation_points=6.0000,
        tightening=1.00,
        hazard_tier=1,
    )
    assert_instant_equals(graded["conditional_expires_at"], "2026-10-30T00:00:00Z")
    assert_instant_equals(graded["expires_at"], "2027-08-01T00:00:00Z")

    contractor = build.read_contractor(scenario["contractor_id"])
    assert_contractor_posture(contractor, open_deficiency_count=1)
    assert (
        reconcile_open_deficiency_count(
            api, scenario["admin_headers"], scenario["contractor_id"]
        )
        == 1
    )


def _approved_then_lost_time_then_closed(build):
    """The canonical approval, a badge, a LOST_TIME report and its closure."""
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing()
    grant = build.grant_badge(
        scenario["worker_id"],
        scenario["site_id"],
        scenario["prequalification_id"],
        scenario["contractor_id"],
    )
    incident = build.file_incident(
        scenario["client_id"],
        scenario["contractor_id"],
        scenario["site_id"],
        severity="LOST_TIME",
        description="Fall from ladder, three lost work days",
    )
    closed = build.close_incident(incident["id"], scenario["client_id"])
    scenario["grant"] = grant
    scenario["incident"] = incident
    scenario["closed_incident"] = closed
    return scenario


def test_lost_time_report_suspends_the_standing_and_its_closure_reopens_review(build, api):
    """The first grading is untightened; the report freezes then thaws the row.

    PRD Section 3.9: "And `incident_review_flag` is recomputed: if no other
    open lost-time or fatal report remains and the flag therefore flips from
    true to false, every `SUSPENDED` prequalification of that contractor is
    carried back to `UNDER_REVIEW`, processed in ascending `created_at` order,
    with `grade`, `final_composite_score`, `effective_thresholds`,
    `deficiency_codes`, `conditional_expires_at` and `expires_at` all cleared,
    followed by a recomputation of `open_deficiency_count`."

    Design: Difficulty/combinatorial_formula/threshold_resolution_escalates_tier_from_closed_lost_time_at_badged_site
    """
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing()

    first_grading = scenario["prequalification"]
    assert_prequalification_state(
        first_grading, status="APPROVED", grade="B", final_composite_score=80.51
    )
    assert_effective_thresholds(
        first_grading["effective_thresholds"],
        max_trir=3.0000,
        max_dart_rate=1.5000,
        max_emr=1.0000,
        max_citation_points=6.0000,
        tightening=1.00,
        hazard_tier=1,
    )

    grant = build.grant_badge(
        scenario["worker_id"],
        scenario["site_id"],
        scenario["prequalification_id"],
        scenario["contractor_id"],
    )
    incident = build.file_incident(
        scenario["client_id"],
        scenario["contractor_id"],
        scenario["site_id"],
        severity="LOST_TIME",
        description="Fall from ladder, three lost work days",
    )

    suspended = build.read_prequalification(scenario["prequalification_id"])
    assert_prequalification_state(suspended, status="SUSPENDED", grade="B")
    revoked = validate_success(
        api.get_grant(grant["id"], scenario["manager_headers"])
    )
    assert_grant_state(revoked, status="REVOKED", revocation_reason="PREQUAL_SUSPENDED")

    build.close_incident(incident["id"], scenario["client_id"])

    reopened = build.read_prequalification(scenario["prequalification_id"])
    assert_prequalification_state(
        reopened,
        status="UNDER_REVIEW",
        grade=None,
        deficiency_codes=[],
        final_composite_score=None,
    )
    assert reopened["effective_thresholds"] is None
    assert reopened["conditional_expires_at"] is None
    assert reopened["expires_at"] is None


def test_closed_lost_time_still_escalates_the_tier_on_the_second_grading(build, api):
    """Re-grading resolves tier 2 from the closed report and scores 77.06.

    PRD Section 3.9: "Note also that a closed report keeps participating in the
    client-scoped severity snapshot of threshold resolution for the full 365
    days after it occurred, so closing a review does not erase the tier
    escalation it caused."

    Design: Difficulty/combinatorial_formula/threshold_resolution_escalates_tier_from_closed_lost_time_at_badged_site
    """
    scenario = _approved_then_lost_time_then_closed(build)

    regraded = build.grade_prequalification(
        scenario["prequalification_id"], scenario["client_id"]
    )

    assert_prequalification_state(
        regraded,
        status="APPROVED",
        grade="B",
        deficiency_codes=[],
        final_composite_score=77.06,
    )
    assert_effective_thresholds(
        regraded["effective_thresholds"],
        max_trir=2.5500,
        max_dart_rate=1.2750,
        max_emr=0.8500,
        max_citation_points=5.1000,
        tightening=0.85,
        hazard_tier=2,
    )
    assert_instant_equals(regraded["expires_at"], "2027-08-01T00:00:00Z")

    contractor = build.read_contractor(scenario["contractor_id"])
    assert_contractor_posture(
        contractor,
        base_hazard_tier=1,
        incident_review_flag=False,
        open_severe_incident_count=0,
    )
