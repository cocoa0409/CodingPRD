"""
Dual-variant projection arithmetic.

Two calculations in the requirements accept a client-chosen variant and diverge
sharply on byte-identical inputs.  The first lives in the weight-descent
scheduling domain (§3.5): from one wrestler's certified figures the
``WEEKLY_STEP`` variant compounds the weekly allowable weight while the
``LINEAR_RATE`` variant subtracts one fixed pound delta, so the two schedules
disagree from the fourth week onward and arrive at the target class in a
different number of weeks.  The second lives in the assessor-credential domain
(§3.9): the same three remeasured samples score their largest deviation under
``WORST_CASE`` and their mean under ``SAMPLE_MEAN``, which straddles
``audit_fail_threshold_pct`` and therefore reaches opposite regulatory
consequences — one audit passes with no cascade at all, the other suspends the
assessor and voids every sampled assessment.

Everything here runs over HTTP through the shared client.  The server is
restarted before each test, so every precondition is built through the declared
endpoints.
"""

from typing import Any, Dict, List

import pytest

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories, fixtures
from test_helpers.assertions import (
    assert_all_null,
    assert_audit_score_equals,
    assert_milestone,
    assert_ordered_by,
    assert_row_count,
    assert_weight_equals,
    expected_deviation,
    expected_min_eligible_class,
    expected_sample_mean_score,
    expected_worst_case_score,
    plus_weeks,
    round_audit,
    round_weight,
)
from test_helpers.constants import (
    ASSESSMENT_VALIDATED,
    ASSESSMENT_VOIDED,
    ASSESSOR_CERTIFIED,
    ASSESSOR_SUSPENDED,
    AUDIT_FAIL,
    AUDIT_FINALIZED,
    AUDIT_OPEN,
    AUDIT_PASS,
    AUDIT_SAMPLE_DEVIATIONS,
    AUDIT_SAMPLE_MEAN_SCORE,
    AUDIT_TYPE_ASSESSOR_SAMPLE,
    AUDIT_WORST_CASE_SCORE,
    CANON_MINIMUM_CERTIFIED_WEIGHT_LBS,
    CANON_TARGET_CLASS_LBS,
    CANON_USG_PASS,
    DEFAULT_AUDIT_MIN_SAMPLE_COUNT,
    DEFAULT_MAX_WEEKLY_DESCENT_PCT,
    ELIGIBILITY_INELIGIBLE,
    HOLD_SOURCE_ASSESSMENT_VOIDED,
    LINEAR_RATE_MILESTONE_COUNT,
    LINEAR_RATE_MILESTONE_DATES,
    LINEAR_RATE_PROJECTED_DATE,
    LINEAR_RATE_SCHEDULE,
    LINEAR_RATE_TOTAL_WEEKS,
    LINEAR_RATE_WEEKLY_DELTA_LBS,
    MILESTONE_SCHEDULED,
    PLAN_CANCELLED,
    PLAN_CERTIFIED,
    PLAN_DRAFT,
    PLAN_START_DATE,
    CANCEL_REASON_SUPERSEDED,
    SCORING_SAMPLE_MEAN,
    SCORING_WORST_CASE,
    SEX_MALE,
    VARIANT_LINEAR_RATE,
    VARIANT_WEEKLY_STEP,
    VOID_REASON_AUDIT_FAIL_PREFIX,
    WEEKLY_STEP_MILESTONE_COUNT,
    WEEKLY_STEP_MILESTONE_DATES,
    WEEKLY_STEP_PROJECTED_DATE,
    WEEKLY_STEP_SCHEDULE,
    WEEKLY_STEP_TOTAL_WEEKS,
    WRESTLER_PROVISIONAL,
    WRESTLER_SUSPENDED,
)
from test_helpers.test_users import STATE_OFFICE

# The five certified figures §3.9 clears when a sampled assessment is voided.
_CERTIFIED_FIGURES = (
    "alpha_weight_lbs",
    "body_fat_pct",
    "minimum_certified_weight_lbs",
    "min_weight_class_lbs",
    "lowest_eligible_class_lbs",
)

# The audit's sample window opens on the day all three assessments were taken,
# so every one of them is inside the failure cascade's reach.
_AUDIT_WINDOW_START = "2026-11-01"

# One roster of three wrestlers, each measured once by the same assessor on the
# same UTC calendar day — exactly the assessor's daily capacity of three.  The
# last figure of each row is the auditor's remeasured body-fat percentage, which
# produces the deviations 1.20, 2.40 and 0.60 the requirements work through.
_AUDIT_SUBJECTS = (
    ("Alex Mercer", 11, 159.6, 14.0, "2026-11-01T09:00:00Z", 15.2),
    ("Blake Ito", 12, 165.0, 16.0, "2026-11-01T10:00:00Z", 18.4),
    ("Casey Nolan", 10, 175.0, 20.0, "2026-11-01T11:00:00Z", 20.6),
)


def _milestone_rows(api, plan_id: str, expected_count: int) -> List[Dict[str, Any]]:
    """The plan's milestones, week-index ascending, checked for row count.

    Milestones are the only discovery channel for a generated schedule (§2.10),
    and §2.3 pins their listing order.
    """
    response = api.list_plan_milestones(plan_id, STATE_OFFICE, {"limit": 100})
    rows = assert_row_count(response, expected_count, "milestone listing")
    assert_ordered_by(rows, "week_index", "milestone listing")
    return rows


def _sampled_assessor_scenario(api) -> fixtures.Scenario:
    """An open season whose single assessor has three validated assessments.

    The three measurements are the ones the requirements score: recorded
    body-fat percentages of 14.0, 16.0 and 20.0 against remeasured values of
    15.2, 18.4 and 20.6.
    """
    scenario = fixtures.open_season_with_team(api)
    assessor = fixtures.create_certified_assessor(api)
    wrestler_ids: List[str] = []
    assessments: List[Dict[str, Any]] = []
    pairs: List[List[Any]] = []
    for full_name, grade, weight, body_fat_pct, assessed_at, remeasured in _AUDIT_SUBJECTS:
        wrestler = fixtures.create_wrestler(api, scenario.team_id, full_name, SEX_MALE, grade)
        assessment = fixtures.create_validated_assessment(
            api,
            wrestler["id"],
            assessor["id"],
            assessed_at=assessed_at,
            measured_weight_lbs=weight,
            body_fat_pct=body_fat_pct,
            urine_specific_gravity=CANON_USG_PASS,
        )
        wrestler_ids.append(wrestler["id"])
        assessments.append(assessment)
        pairs.append([assessment["id"], remeasured])
    scenario.update(
        assessor=assessor,
        assessor_id=assessor["id"],
        wrestler_ids=wrestler_ids,
        assessments=assessments,
        samples=factories.audit_samples(pairs),
    )
    return scenario


def _sample_deviations(scenario: fixtures.Scenario) -> List[float]:
    """Each sample's deviation, rounded half up to two decimal places (§3.9)."""
    deviations = [
        expected_deviation(remeasured, assessment["body_fat_pct"])
        for assessment, (_, _, _, _, _, remeasured) in zip(
            scenario.assessments, _AUDIT_SUBJECTS
        )
    ]
    assert deviations == [round_audit(d) for d in AUDIT_SAMPLE_DEVIATIONS], (
        f"the sampled measurements must produce the worked deviations, got {deviations}"
    )
    return deviations


def _open_and_finalize_audit(api, scenario: fixtures.Scenario, scoring_variant: str) -> Dict[str, Any]:
    """Open a sampled assessor audit under one scoring variant and score it."""
    audit = fixtures.open_audit(
        api,
        scenario.season_id,
        AUDIT_TYPE_ASSESSOR_SAMPLE,
        scoring_variant,
        _AUDIT_WINDOW_START,
        assessor_id=scenario.assessor_id,
        samples=scenario.samples,
    )
    assert audit["scoring_variant"] == scoring_variant
    assert audit["status"] == AUDIT_OPEN
    assert audit["sample_count"] == len(_AUDIT_SUBJECTS)
    assert audit["discrepancy_score"] is None
    assert audit["outcome"] is None
    assert audit["voided_assessment_count"] == 0
    return fixtures.finalize_audit(api, audit["id"])


# ── The descent schedule: WEEKLY_STEP against LINEAR_RATE ────────────


@pytest.mark.parametrize(
    "plan_variant,total_weeks,milestone_count,projected_date,weekly_delta_lbs",
    [
        (
            VARIANT_WEEKLY_STEP,
            WEEKLY_STEP_TOTAL_WEEKS,
            WEEKLY_STEP_MILESTONE_COUNT,
            WEEKLY_STEP_PROJECTED_DATE,
            None,
        ),
        (
            VARIANT_LINEAR_RATE,
            LINEAR_RATE_TOTAL_WEEKS,
            LINEAR_RATE_MILESTONE_COUNT,
            LINEAR_RATE_PROJECTED_DATE,
            LINEAR_RATE_WEEKLY_DELTA_LBS,
        ),
    ],
    ids=["weekly_step", "linear_rate"],
)
def test_certified_plan_header_figures_follow_the_chosen_variant(
    api,
    plan_variant,
    total_weeks,
    milestone_count,
    projected_date,
    weekly_delta_lbs,
):
    """Certification derives total_weeks, milestone_count and the projected date.

    From a baseline alpha weight of 159.6 pounds, the pinned rate of 1.5 percent
    and a target class of 150, §3.5 has the compounding variant arrive in five
    weeks and the linear variant in four; milestone_count is total_weeks plus
    one and projected_certification_date is the start advanced by seven days
    times total_weeks.  weekly_delta_lbs is the fixed pound delta of a linear
    plan and stays null for a compounding one.

    Design: Difficulty/dual_variant_calc/descent_schedule_variant_divergence_on_plan
    """
    scenario = fixtures.certified_wrestler(api, plan_variant=plan_variant)

    plan = validate_success(api.get_descent_plan(scenario.plan_id, STATE_OFFICE))

    assert plan["plan_variant"] == plan_variant
    assert plan["status"] == PLAN_CERTIFIED
    assert plan["target_class_lbs"] == CANON_TARGET_CLASS_LBS
    assert plan["plan_start_date"] == PLAN_START_DATE
    # The rate is copied from the season constant at creation and pinned there.
    assert_weight_equals(
        plan["weekly_rate_pct"], DEFAULT_MAX_WEEKLY_DESCENT_PCT, "weekly_rate_pct"
    )
    assert plan["total_weeks"] == total_weeks
    assert plan["milestone_count"] == milestone_count
    assert plan["milestone_count"] == plan["total_weeks"] + 1
    assert plan["projected_certification_date"] == projected_date
    assert plan["projected_certification_date"] == plus_weeks(
        PLAN_START_DATE, total_weeks
    )
    if weekly_delta_lbs is None:
        assert plan["weekly_delta_lbs"] is None, (
            "weekly_delta_lbs remains null for a compounding plan, got "
            f"{plan['weekly_delta_lbs']!r}"
        )
    else:
        assert_weight_equals(
            plan["weekly_delta_lbs"], weekly_delta_lbs, "weekly_delta_lbs"
        )
    assert plan["missed_milestone_count"] == 0
    assert plan["breach_count"] == 0
    assert plan["revision_count"] == 0
    assert plan["cancel_reason"] is None


@pytest.mark.parametrize(
    "plan_variant,allowable_weights,effective_dates",
    [
        (VARIANT_WEEKLY_STEP, WEEKLY_STEP_SCHEDULE, WEEKLY_STEP_MILESTONE_DATES),
        (VARIANT_LINEAR_RATE, LINEAR_RATE_SCHEDULE, LINEAR_RATE_MILESTONE_DATES),
    ],
    ids=["weekly_step", "linear_rate"],
)
def test_generated_schedule_rows_follow_the_chosen_variant(
    api, plan_variant, allowable_weights, effective_dates
):
    """One milestone per week index, carrying the variant's allowable weight.

    §3.5 fixes the compounding schedule at 159.6, 157.2, 154.8, 152.5, 150.2 and
    147.9 and the linear schedule at 159.6, 157.2, 154.8, 152.4 and 150.0 for
    these inputs.  Each row's effective_date is the start advanced by seven days
    times its week index, its min_eligible_class_lbs is the smallest ladder
    member at or above the larger of that week's allowable weight and the
    wrestler's 147.6 pound certified minimum, and each row starts SCHEDULED with
    no evaluated weight.

    Design: Difficulty/dual_variant_calc/descent_schedule_variant_divergence_on_plan
    """
    scenario = fixtures.certified_wrestler(api, plan_variant=plan_variant)

    rows = _milestone_rows(api, scenario.plan_id, len(allowable_weights))

    for week_index, row in enumerate(rows):
        allowable = allowable_weights[week_index]
        assert_milestone(
            row,
            week_index,
            effective_dates[week_index],
            allowable,
            expected_min_eligible_class(allowable, CANON_MINIMUM_CERTIFIED_WEIGHT_LBS),
            MILESTONE_SCHEDULED,
            f"{plan_variant} week {week_index}",
        )
        assert row["plan_id"] == scenario.plan_id
        assert row["evaluated_recorded_weight_lbs"] is None

    # total_weeks is the smallest index at or below the target class, and no
    # earlier week reaches it.
    assert round_weight(rows[-1]["allowable_weight_lbs"]) <= CANON_TARGET_CLASS_LBS
    for row in rows[:-1]:
        assert round_weight(row["allowable_weight_lbs"]) > CANON_TARGET_CLASS_LBS


def test_the_two_variants_diverge_from_identical_certified_figures(api):
    """Same wrestler, same baseline, same rate, same target: two schedules.

    §3.5 pins per-step rounding on the compounding variant and a single fixed
    delta on the linear one, so from week three the two schedules disagree —
    152.5 against 152.4 — and the compounding plan needs a sixth milestone the
    linear plan does not.  The divergence is regulatory, not cosmetic: at week
    four the compounding plan's allowable weight of 150.2 puts the wrestler's
    smallest permissible class at 157 while the linear plan's 150.0 already
    reaches 150.

    Design: Difficulty/dual_variant_calc/descent_schedule_variant_divergence_on_plan
    """
    scenario = fixtures.certified_wrestler(api, plan_variant=VARIANT_WEEKLY_STEP)
    step_plan = validate_success(api.get_descent_plan(scenario.plan_id, STATE_OFFICE))
    step_rows = _milestone_rows(api, scenario.plan_id, WEEKLY_STEP_MILESTONE_COUNT)

    # The very same wrestler, source assessment, target class and start date,
    # differing only in the projection variant.
    linear = fixtures.create_plan(
        api,
        scenario.wrestler_id,
        scenario.team_id,
        scenario.assessment_id,
        target_class_lbs=CANON_TARGET_CLASS_LBS,
        plan_start_date=PLAN_START_DATE,
        plan_variant=VARIANT_LINEAR_RATE,
    )
    linear_plan = fixtures.certify_plan(api, linear["id"])
    linear_rows = _milestone_rows(api, linear["id"], LINEAR_RATE_MILESTONE_COUNT)

    assert step_plan["source_assessment_id"] == linear_plan["source_assessment_id"]
    assert step_plan["target_class_lbs"] == linear_plan["target_class_lbs"]
    assert step_plan["plan_start_date"] == linear_plan["plan_start_date"]
    assert round_weight(step_plan["weekly_rate_pct"]) == round_weight(
        linear_plan["weekly_rate_pct"]
    )

    # Weeks zero through two agree, week three is where they part.
    for week_index in (0, 1, 2):
        assert round_weight(step_rows[week_index]["allowable_weight_lbs"]) == round_weight(
            linear_rows[week_index]["allowable_weight_lbs"]
        )
    assert_weight_equals(
        step_rows[3]["allowable_weight_lbs"], WEEKLY_STEP_SCHEDULE[3], "step week 3"
    )
    assert_weight_equals(
        linear_rows[3]["allowable_weight_lbs"], LINEAR_RATE_SCHEDULE[3], "linear week 3"
    )
    assert round_weight(step_rows[3]["allowable_weight_lbs"]) != round_weight(
        linear_rows[3]["allowable_weight_lbs"]
    )

    # Week four carries the two plans to different permissible classes.
    assert_weight_equals(
        step_rows[4]["allowable_weight_lbs"], WEEKLY_STEP_SCHEDULE[4], "step week 4"
    )
    assert_weight_equals(
        linear_rows[4]["allowable_weight_lbs"], LINEAR_RATE_SCHEDULE[4], "linear week 4"
    )
    assert step_rows[4]["min_eligible_class_lbs"] == expected_min_eligible_class(
        WEEKLY_STEP_SCHEDULE[4], CANON_MINIMUM_CERTIFIED_WEIGHT_LBS
    )
    assert linear_rows[4]["min_eligible_class_lbs"] == expected_min_eligible_class(
        LINEAR_RATE_SCHEDULE[4], CANON_MINIMUM_CERTIFIED_WEIGHT_LBS
    )
    assert (
        step_rows[4]["min_eligible_class_lbs"]
        != linear_rows[4]["min_eligible_class_lbs"]
    )

    # The compounding plan needs one more week, and one more milestone row.
    assert step_plan["total_weeks"] == linear_plan["total_weeks"] + 1
    assert len(step_rows) == len(linear_rows) + 1
    assert step_plan["projected_certification_date"] == WEEKLY_STEP_PROJECTED_DATE
    assert linear_plan["projected_certification_date"] == LINEAR_RATE_PROJECTED_DATE
    assert step_plan["weekly_delta_lbs"] is None
    assert_weight_equals(
        linear_plan["weekly_delta_lbs"],
        LINEAR_RATE_WEEKLY_DELTA_LBS,
        "linear weekly_delta_lbs",
    )


def test_opening_the_second_variant_supersedes_the_first_plan(api):
    """The second plan cancels the first and records the back reference.

    §3.5 has plan creation supersede whatever the wrestler had before: a prior
    plan in DRAFT, CERTIFIED or BREACHED becomes CANCELLED with cancel_reason
    SUPERSEDED, and the new plan's supersedes_plan_id points at it.  A new plan
    also starts in DRAFT with weekly_delta_lbs still null — the variant's
    arithmetic runs at certification, not at creation.

    Design: Difficulty/dual_variant_calc/descent_schedule_variant_divergence_on_plan
    """
    scenario = fixtures.certified_wrestler(api, plan_variant=VARIANT_WEEKLY_STEP)
    step_plan_id = scenario.plan_id

    linear = fixtures.create_plan(
        api,
        scenario.wrestler_id,
        scenario.team_id,
        scenario.assessment_id,
        target_class_lbs=CANON_TARGET_CLASS_LBS,
        plan_start_date=PLAN_START_DATE,
        plan_variant=VARIANT_LINEAR_RATE,
    )

    assert linear["status"] == PLAN_DRAFT
    assert linear["plan_variant"] == VARIANT_LINEAR_RATE
    assert linear["supersedes_plan_id"] == step_plan_id
    assert linear["weekly_delta_lbs"] is None
    assert linear["total_weeks"] is None
    assert linear["projected_certification_date"] is None
    assert linear["milestone_count"] == 0

    superseded = validate_success(api.get_descent_plan(step_plan_id, STATE_OFFICE))
    assert superseded["status"] == PLAN_CANCELLED
    assert superseded["cancel_reason"] == CANCEL_REASON_SUPERSEDED
    # The cancelled plan keeps the figures its own variant produced.
    assert superseded["total_weeks"] == WEEKLY_STEP_TOTAL_WEEKS
    assert superseded["milestone_count"] == WEEKLY_STEP_MILESTONE_COUNT
    assert superseded["weekly_delta_lbs"] is None

    # Certifying the replacement produces the linear variant's own schedule.
    linear_plan = fixtures.certify_plan(api, linear["id"])
    assert linear_plan["status"] == PLAN_CERTIFIED
    assert linear_plan["total_weeks"] == LINEAR_RATE_TOTAL_WEEKS
    assert linear_plan["milestone_count"] == LINEAR_RATE_MILESTONE_COUNT
    assert_weight_equals(
        linear_plan["weekly_delta_lbs"],
        LINEAR_RATE_WEEKLY_DELTA_LBS,
        "linear weekly_delta_lbs",
    )
    _milestone_rows(api, linear["id"], LINEAR_RATE_MILESTONE_COUNT)


# ── Audit discrepancy scoring: WORST_CASE against SAMPLE_MEAN ────────


@pytest.mark.parametrize(
    "scoring_variant,expected_score,expected_outcome,expected_voided_count",
    [
        (SCORING_SAMPLE_MEAN, AUDIT_SAMPLE_MEAN_SCORE, AUDIT_PASS, 0),
        (SCORING_WORST_CASE, AUDIT_WORST_CASE_SCORE, AUDIT_FAIL, len(_AUDIT_SUBJECTS)),
    ],
    ids=["sample_mean", "worst_case"],
)
def test_audit_score_and_outcome_follow_the_chosen_scoring_variant(
    api, scoring_variant, expected_score, expected_outcome, expected_voided_count
):
    """Finalizing scores the sampled deviations under the audit's own variant.

    §3.9 has WORST_CASE take the single largest per-sample deviation and
    SAMPLE_MEAN take their sum divided by sample_count, both to two decimal
    places, with the outcome FAIL when the score reaches
    audit_fail_threshold_pct and PASS otherwise.  Deviations of 1.20, 2.40 and
    0.60 therefore score 2.40 and fail under one variant and 1.40 and pass under
    the other.  A FAIL on a sampled assessor audit voids the sampled work; a
    PASS voids nothing.

    Design: Difficulty/dual_variant_calc/audit_discrepancy_scoring_variant_divergence_on_assessor
    """
    scenario = _sampled_assessor_scenario(api)
    deviations = _sample_deviations(scenario)
    threshold = scenario.season["audit_fail_threshold_pct"]

    # The audit is scoreable: it carries at least audit_min_sample_count samples.
    assert len(deviations) >= DEFAULT_AUDIT_MIN_SAMPLE_COUNT
    assert scenario.season["audit_min_sample_count"] == DEFAULT_AUDIT_MIN_SAMPLE_COUNT

    if scoring_variant == SCORING_WORST_CASE:
        assert round_audit(expected_score) == expected_worst_case_score(deviations)
    else:
        assert round_audit(expected_score) == expected_sample_mean_score(deviations)

    audit = _open_and_finalize_audit(api, scenario, scoring_variant)

    assert audit["status"] == AUDIT_FINALIZED
    assert audit["sample_count"] == len(_AUDIT_SUBJECTS)
    assert_audit_score_equals(
        audit["discrepancy_score"], expected_score, f"{scoring_variant} discrepancy_score"
    )
    assert audit["outcome"] == expected_outcome
    assert audit["voided_assessment_count"] == expected_voided_count
    # The verdict is exactly the threshold comparison, inclusive at the limit.
    if round_audit(audit["discrepancy_score"]) >= round_audit(threshold):
        assert audit["outcome"] == AUDIT_FAIL
    else:
        assert audit["outcome"] == AUDIT_PASS


def test_a_passing_sample_mean_audit_leaves_every_row_untouched(api):
    """A PASS outcome triggers no cascade whatsoever.

    §3.9: on PASS the assessor keeps their credential, every assessment stands,
    and no wrestler, plan or entry is touched — only last_audit_outcome moves,
    which §3.2 has report the verdict of the most recently created finalized
    audit naming that assessor.

    Design: Difficulty/dual_variant_calc/audit_discrepancy_scoring_variant_divergence_on_assessor
    """
    scenario = _sampled_assessor_scenario(api)

    audit = _open_and_finalize_audit(api, scenario, SCORING_SAMPLE_MEAN)

    assert_audit_score_equals(
        audit["discrepancy_score"], AUDIT_SAMPLE_MEAN_SCORE, "discrepancy_score"
    )
    assert audit["outcome"] == AUDIT_PASS
    assert audit["voided_assessment_count"] == 0

    assessor = validate_success(api.get_assessor(scenario.assessor_id, STATE_OFFICE))
    assert assessor["status"] == ASSESSOR_CERTIFIED
    assert assessor["suspension_reason"] is None
    assert assessor["last_audit_outcome"] == AUDIT_PASS
    assert assessor["voided_assessment_count"] == 0
    assert assessor["validated_assessment_count"] == len(_AUDIT_SUBJECTS)

    for assessment, wrestler_id in zip(scenario.assessments, scenario.wrestler_ids):
        stored = validate_success(api.get_assessment(assessment["id"], STATE_OFFICE))
        assert stored["status"] == ASSESSMENT_VALIDATED
        assert stored["void_reason"] is None

        wrestler = validate_success(api.get_wrestler(wrestler_id, STATE_OFFICE))
        assert wrestler["certification_status"] == WRESTLER_PROVISIONAL
        assert wrestler["source_assessment_id"] == assessment["id"]
        assert wrestler["certification_hold_reason"] is None
        assert_weight_equals(
            wrestler["minimum_certified_weight_lbs"],
            assessment["minimum_certified_weight_lbs"],
            "minimum_certified_weight_lbs",
        )
        assert wrestler["min_weight_class_lbs"] == assessment["min_weight_class_lbs"]


def test_a_failing_worst_case_audit_suspends_the_assessor_and_voids_the_samples(api):
    """A FAIL outcome launches the credential cascade the PASS never triggers.

    §3.9 hop one moves the assessor CERTIFIED to SUSPENDED with
    suspension_reason ``AUDIT_FAIL:`` followed by the audit's id and
    last_audit_outcome FAIL.  Hop two voids every assessment of that assessor
    still VALIDATED whose assessed_at date is on or after sample_window_start,
    stamping the same ``AUDIT_FAIL:`` reason and incrementing both void counters
    per row.  Hop three moves each affected wrestler's certification dimension to
    SUSPENDED, clears source_assessment_id and all five certified figures, sets
    certification_hold_reason to SOURCE_ASSESSMENT_VOIDED and drops eligibility
    to INELIGIBLE.

    Design: Difficulty/dual_variant_calc/audit_discrepancy_scoring_variant_divergence_on_assessor
    """
    scenario = _sampled_assessor_scenario(api)

    audit = _open_and_finalize_audit(api, scenario, SCORING_WORST_CASE)

    assert_audit_score_equals(
        audit["discrepancy_score"], AUDIT_WORST_CASE_SCORE, "discrepancy_score"
    )
    assert audit["outcome"] == AUDIT_FAIL
    assert audit["voided_assessment_count"] == len(_AUDIT_SUBJECTS)

    expected_reason = VOID_REASON_AUDIT_FAIL_PREFIX + audit["id"]

    assessor = validate_success(api.get_assessor(scenario.assessor_id, STATE_OFFICE))
    assert assessor["status"] == ASSESSOR_SUSPENDED
    assert assessor["suspension_reason"] == expected_reason
    assert assessor["last_audit_outcome"] == AUDIT_FAIL
    assert assessor["voided_assessment_count"] == len(_AUDIT_SUBJECTS)
    assert assessor["validated_assessment_count"] == 0

    for assessment, wrestler_id in zip(scenario.assessments, scenario.wrestler_ids):
        stored = validate_success(api.get_assessment(assessment["id"], STATE_OFFICE))
        assert stored["status"] == ASSESSMENT_VOIDED
        assert stored["void_reason"] == expected_reason

        wrestler = validate_success(api.get_wrestler(wrestler_id, STATE_OFFICE))
        assert wrestler["certification_status"] == WRESTLER_SUSPENDED
        assert wrestler["eligibility_status"] == ELIGIBILITY_INELIGIBLE
        assert wrestler["source_assessment_id"] is None
        assert wrestler["certification_hold_reason"] == HOLD_SOURCE_ASSESSMENT_VOIDED
        assert_all_null(wrestler, _CERTIFIED_FIGURES, "suspended wrestler")


def test_identical_samples_reach_opposite_verdicts_on_the_variant_alone(api):
    """Two audits over the same three samples, differing only in the variant.

    §3.9 works this case through explicitly: with the shipped threshold of 2.0
    percent, deviations of 1.20, 2.40 and 0.60 score 1.40 under SAMPLE_MEAN and
    pass, but 2.40 under WORST_CASE and fail — identical audit inputs, opposite
    regulatory consequence.  The passing audit keeps its own zero void count even
    after the failing one has voided all three assessments.

    Design: Difficulty/dual_variant_calc/audit_discrepancy_scoring_variant_divergence_on_assessor
    """
    scenario = _sampled_assessor_scenario(api)
    _sample_deviations(scenario)

    mean_audit = _open_and_finalize_audit(api, scenario, SCORING_SAMPLE_MEAN)
    assert mean_audit["outcome"] == AUDIT_PASS

    worst_audit = _open_and_finalize_audit(api, scenario, SCORING_WORST_CASE)
    assert worst_audit["outcome"] == AUDIT_FAIL

    # Same season, same assessor, same samples, same window.
    assert mean_audit["assessor_id"] == worst_audit["assessor_id"]
    assert mean_audit["sample_window_start"] == worst_audit["sample_window_start"]
    assert mean_audit["audit_type"] == worst_audit["audit_type"]
    assert mean_audit["sample_count"] == worst_audit["sample_count"]
    assert mean_audit["scoring_variant"] != worst_audit["scoring_variant"]

    assert_audit_score_equals(
        mean_audit["discrepancy_score"], AUDIT_SAMPLE_MEAN_SCORE, "mean discrepancy_score"
    )
    assert_audit_score_equals(
        worst_audit["discrepancy_score"], AUDIT_WORST_CASE_SCORE, "worst discrepancy_score"
    )
    assert mean_audit["outcome"] != worst_audit["outcome"]
    assert round_audit(
        worst_audit["discrepancy_score"] - mean_audit["discrepancy_score"]
    ) == pytest.approx(round_audit(AUDIT_WORST_CASE_SCORE - AUDIT_SAMPLE_MEAN_SCORE), abs=0.01)

    # Only the failing audit carries a void count, and only it moved the roster.
    assert worst_audit["voided_assessment_count"] == len(_AUDIT_SUBJECTS)
    reread_mean = validate_success(api.get_audit(mean_audit["id"], STATE_OFFICE))
    assert reread_mean["outcome"] == AUDIT_PASS
    assert reread_mean["voided_assessment_count"] == 0

    assessor = validate_success(api.get_assessor(scenario.assessor_id, STATE_OFFICE))
    assert assessor["status"] == ASSESSOR_SUSPENDED
    assert assessor["last_audit_outcome"] == AUDIT_FAIL
    assert assessor["suspension_reason"] == (
        VOID_REASON_AUDIT_FAIL_PREFIX + worst_audit["id"]
    )

    first_assessment = scenario.assessments[0]
    stored = validate_success(api.get_assessment(first_assessment["id"], STATE_OFFICE))
    assert stored["status"] == ASSESSMENT_VOIDED
    assert stored["void_reason"] == VOID_REASON_AUDIT_FAIL_PREFIX + worst_audit["id"]

    wrestler = validate_success(api.get_wrestler(scenario.wrestler_ids[0], STATE_OFFICE))
    assert wrestler["certification_status"] == WRESTLER_SUSPENDED
    assert wrestler["minimum_certified_weight_lbs"] is None
