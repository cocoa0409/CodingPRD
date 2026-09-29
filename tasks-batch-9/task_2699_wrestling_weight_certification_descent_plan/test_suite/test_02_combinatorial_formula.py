"""
Multi-step derived arithmetic whose evaluation order is load-bearing.

Two families of the requirements' formulas are exercised here.  The first is the
``WEEKLY_STEP`` descent projection of §3.5, where each week's allowable weight is
rounded to one decimal place *before* it becomes the base of the next week, so
that the schedule diverges from the closed-form single-shot compounding value.
The second is the four-step eligibility-floor derivation of §3.7, where the
weight class decides which growth allowance applies, the descent milestone
decides the floor and the floor decides the class — a dependency that looks
circular but whose evaluation order the specification pins so that it never
iterates and never folds the growth allowance back into the hard-floor class.

Every precondition is built through the declared endpoints: the logical clock
starts at its default instant and the database starts empty before each test.
"""

from decimal import ROUND_HALF_UP, Decimal

import pytest

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories, fixtures
from test_helpers.api_errors import ERR_CLASS_BELOW_CERTIFIED_MINIMUM
from test_helpers.assertions import (
    assert_weight_equals,
    expected_lowest_eligible_class,
    plus_weeks,
    round_weight,
    weekly_step_allowable_weights,
)
from test_helpers.constants import (
    ASSESSMENT_DAY_INSTANT,
    CANON_ALPHA_WEIGHT_LBS,
    CANON_MINIMUM_CERTIFIED_WEIGHT_LBS,
    CANON_MIN_WEIGHT_CLASS_LBS,
    CANON_TARGET_CLASS_LBS,
    DEFAULT_MAX_WEEKLY_DESCENT_PCT,
    DEFAULT_TEAM_NAME,
    DEFAULT_WEIGHT_CLASSES,
    EVENT_TYPE_DUAL,
    EVENT_TYPE_TOURNAMENT,
    MILESTONE_SCHEDULED,
    OUTCOME_BLOCKED_CLASS_BELOW_MINIMUM,
    OUTCOME_CLEARED,
    PLAN_START_DATE,
    VARIANT_WEEKLY_STEP,
    WEEKLY_STEP_MILESTONE_COUNT,
    WEEKLY_STEP_MILESTONE_DATES,
    WEEKLY_STEP_PROJECTED_DATE,
    WEEKLY_STEP_SCHEDULE,
    WEEKLY_STEP_TOTAL_WEEKS,
)
from test_helpers.test_users import STATE_OFFICE

# The two growth-allowance dates the December reckoning totals, and the events
# whose ``event_date`` becomes the ``as_of_date`` of a logged check.
FIRST_GROWTH_DATE = "2026-12-01"
FIRST_GROWTH_LBS = 1.0
SECOND_GROWTH_DATE = "2026-12-12"
SECOND_GROWTH_LBS = 3.0
DECEMBER_GROWTH_TOTAL_LBS = 4.0

EARLY_EVENT_DATE = "2026-11-10"
DECEMBER_EVENT_DATE = "2026-12-12"


# ── Private computation helpers ──────────────────────────────────────

def _single_shot_compounded(baseline: float, rate_pct: float, week_index: int) -> float:
    """The closed form the requirements explicitly reject.

    One single rounding applied to the baseline multiplied by the rate factor
    raised to the week index, instead of the per-week rounding §3.5 pins.
    """
    factor = (Decimal("1") - Decimal(str(rate_pct)) / Decimal("100")) ** week_index
    product = Decimal(str(baseline)) * factor
    return float(product.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _milestones(api, plan_id):
    """Every milestone row of a plan, in week-index ascending order."""
    rows, _meta = validate_paginated(
        api.list_plan_milestones(plan_id, STATE_OFFICE, {"limit": 100})
    )
    return rows


def _run_check(api, wrestler_id, event_id, requested_class_lbs):
    """Run and log the certification-database check, which always returns 201."""
    response = api.create_eligibility_check(
        wrestler_id,
        factories.eligibility_check_payload(event_id, requested_class_lbs),
        STATE_OFFICE,
    )
    return validate_success(response, 201)


# ── Composite preconditions ──────────────────────────────────────────

def _certified_weekly_step_plan(api):
    """A wrestler whose compounding descent plan has just been certified.

    The canonical measurement of 159.6 pounds at 14.0 percent body fat yields a
    147.6 pound minimum certified weight, a 150 pound minimum weight class and a
    159.6 pound descent baseline, and the plan targets the 150 pound class from a
    2026-11-02 start at the season's default 1.5 percent weekly rate.
    """
    scenario = fixtures.certified_wrestler(
        api,
        target_class_lbs=CANON_TARGET_CLASS_LBS,
        plan_start_date=PLAN_START_DATE,
        plan_variant=VARIANT_WEEKLY_STEP,
    )
    return scenario, _milestones(api, scenario.plan_id)


def _certified_plan_with_growth_dates_and_events(api):
    """The same certified plan, plus two growth dates and two competitions.

    The season publishes 1.0 pound effective 2026-12-01 and 3.0 pounds effective
    2026-12-12, and carries an early dual on 2026-11-10 and a December
    tournament on 2026-12-12.
    """
    season = fixtures.create_open_season(api)
    fixtures.publish_growth_allowance(
        api, season["id"], FIRST_GROWTH_DATE, FIRST_GROWTH_LBS, "December growth date"
    )
    fixtures.publish_growth_allowance(
        api,
        season["id"],
        SECOND_GROWTH_DATE,
        SECOND_GROWTH_LBS,
        "Mid-December growth date",
    )
    team = fixtures.create_team(api, season["id"], DEFAULT_TEAM_NAME)
    assessor = fixtures.create_certified_assessor(api)
    wrestler = fixtures.create_wrestler(api, team["id"])
    fixtures.move_clock(api, ASSESSMENT_DAY_INSTANT)
    assessment = fixtures.create_validated_assessment(
        api, wrestler["id"], assessor["id"]
    )
    plan = fixtures.create_certified_plan(
        api,
        wrestler["id"],
        team["id"],
        assessment["id"],
        target_class_lbs=CANON_TARGET_CLASS_LBS,
        plan_start_date=PLAN_START_DATE,
        plan_variant=VARIANT_WEEKLY_STEP,
    )
    early_event = fixtures.create_event(
        api,
        season["id"],
        "Early Dual",
        EARLY_EVENT_DATE,
        EVENT_TYPE_DUAL,
        competition_days=1,
        weigh_in_days=1,
        consecutive_day_allowance_lbs=1.0,
    )
    december_event = fixtures.create_event(
        api,
        season["id"],
        "December Invitational",
        DECEMBER_EVENT_DATE,
        EVENT_TYPE_TOURNAMENT,
        competition_days=2,
        weigh_in_days=2,
        consecutive_day_allowance_lbs=1.0,
    )
    return fixtures.Scenario(
        season_id=season["id"],
        team_id=team["id"],
        wrestler_id=wrestler["id"],
        assessment_id=assessment["id"],
        plan_id=plan["id"],
        early_event_id=early_event["id"],
        december_event_id=december_event["id"],
    )


# ── The compounding descent schedule ─────────────────────────────────

def test_weekly_step_rounds_each_week_before_it_becomes_the_next_base(api):
    """Each week's allowable weight is the previous week's *rounded* value.

    §3.5 fixes the compounding schedule for a 159.6 pound baseline, a 1.5
    percent rate and a 150 pound target at 159.6, 157.2, 154.8, 152.5, 150.2 and
    147.9 pounds, one milestone row per week index from zero through
    ``total_weeks`` inclusive, each dated seven days after the last.

    Design: Difficulty/combinatorial_formula/weekly_step_per_week_rounding_order_pinned
    """
    _scenario, milestones = _certified_weekly_step_plan(api)

    assert len(milestones) == WEEKLY_STEP_MILESTONE_COUNT, (
        f"expected {WEEKLY_STEP_MILESTONE_COUNT} milestone rows, got {len(milestones)}"
    )
    # The per-week recomputation of the same figures the requirements state.
    recomputed = weekly_step_allowable_weights(
        CANON_ALPHA_WEIGHT_LBS, DEFAULT_MAX_WEEKLY_DESCENT_PCT, CANON_TARGET_CLASS_LBS
    )
    assert recomputed == WEEKLY_STEP_SCHEDULE

    for week_index, expected_weight in enumerate(WEEKLY_STEP_SCHEDULE):
        milestone = milestones[week_index]
        assert milestone["week_index"] == week_index, (
            f"milestones are ordered by week_index ascending; row {week_index} "
            f"carries week_index {milestone['week_index']!r}"
        )
        assert_weight_equals(
            milestone["allowable_weight_lbs"],
            expected_weight,
            f"week {week_index} allowable_weight_lbs",
        )
        assert milestone["effective_date"] == plus_weeks(PLAN_START_DATE, week_index), (
            f"week {week_index}: expected effective_date "
            f"{plus_weeks(PLAN_START_DATE, week_index)}, "
            f"got {milestone['effective_date']!r}"
        )
        assert milestone["effective_date"] == WEEKLY_STEP_MILESTONE_DATES[week_index]
        assert milestone["status"] == MILESTONE_SCHEDULED


def test_weekly_step_week_five_is_not_the_single_shot_compounding_value(api):
    """The fifth week is where the two arithmetic forms part company.

    §3.5 states the per-step schedule reaches 147.9 pounds at week five and that
    computing the baseline multiplied by the rate factor raised to the week index
    in a single shot is incorrect; that closed form yields 148.0, a tenth of a
    pound apart.

    Design: Difficulty/combinatorial_formula/weekly_step_per_week_rounding_order_pinned
    """
    _scenario, milestones = _certified_weekly_step_plan(api)

    week_five = next(m for m in milestones if m["week_index"] == 5)
    assert_weight_equals(
        week_five["allowable_weight_lbs"], 147.9, "week 5 allowable_weight_lbs"
    )

    single_shot = _single_shot_compounded(
        CANON_ALPHA_WEIGHT_LBS, DEFAULT_MAX_WEEKLY_DESCENT_PCT, 5
    )
    assert single_shot == 148.0, (
        f"the closed form under test is 148.0, computed {single_shot}"
    )
    assert round_weight(week_five["allowable_weight_lbs"]) != single_shot, (
        "week 5 carries the single-shot compounding value "
        f"{single_shot}; the requirements pin per-week rounding, which gives 147.9"
    )
    assert week_five["effective_date"] == "2026-12-07", (
        "week 5 falls seven days times five after the 2026-11-02 start; got "
        f"{week_five['effective_date']!r}"
    )


def test_weekly_step_total_weeks_is_the_first_week_at_or_below_the_target(api):
    """``total_weeks`` counts from zero and the count follows from the schedule.

    §3.5 makes ``total_weeks`` the smallest week index whose allowable weight is
    less than or equal to the target class, sets ``milestone_count`` to that
    figure plus one and dates ``projected_certification_date`` seven days times
    ``total_weeks`` after the start.  Week four is still 150.2 pounds, above the
    150 pound target, so the plan arrives at week five.

    Design: Difficulty/combinatorial_formula/weekly_step_per_week_rounding_order_pinned
    """
    scenario, milestones = _certified_weekly_step_plan(api)
    plan = fixtures.read_plan(api, scenario.plan_id)

    assert plan["total_weeks"] == WEEKLY_STEP_TOTAL_WEEKS, (
        f"expected total_weeks {WEEKLY_STEP_TOTAL_WEEKS}, got {plan['total_weeks']!r}"
    )
    assert plan["milestone_count"] == WEEKLY_STEP_TOTAL_WEEKS + 1
    assert plan["projected_certification_date"] == WEEKLY_STEP_PROJECTED_DATE, (
        f"expected projected_certification_date {WEEKLY_STEP_PROJECTED_DATE}, "
        f"got {plan['projected_certification_date']!r}"
    )
    # A compounding plan leaves the fixed pound delta unset.
    assert plan["weekly_delta_lbs"] is None
    # The rate is pinned onto the plan at creation time.
    assert_weight_equals(
        plan["weekly_rate_pct"], DEFAULT_MAX_WEEKLY_DESCENT_PCT, "weekly_rate_pct"
    )

    # Week four is above the target and week five is the first week at or below
    # it, which is exactly what makes total_weeks five rather than four.
    by_week = {m["week_index"]: m["allowable_weight_lbs"] for m in milestones}
    assert round_weight(by_week[4]) > CANON_TARGET_CLASS_LBS
    assert round_weight(by_week[5]) <= CANON_TARGET_CLASS_LBS


# ── The four-step eligibility floor ──────────────────────────────────

def test_december_check_totals_growth_and_picks_the_governing_milestone(api):
    """Steps one and two of §3.7, evaluated as of the event's own date.

    ``as_of_date`` is copied from the referenced event, the growth total is the
    sum over every allowance whose ``effective_date`` is on or before that date —
    inclusive of the date itself, so both the 1.0 pound 2026-12-01 date and the
    3.0 pound 2026-12-12 date count, for 4.0 pounds — and the governing schedule
    value is the due milestone with the greatest ``effective_date``, which on
    2026-12-12 is the 2026-12-07 week-five row at 147.9 pounds.

    Design: Difficulty/combinatorial_formula/eligibility_floor_circular_evaluation_order_pinned
    """
    scenario = _certified_plan_with_growth_dates_and_events(api)

    check = _run_check(
        api,
        scenario.wrestler_id,
        scenario.december_event_id,
        CANON_TARGET_CLASS_LBS,
    )

    assert check["as_of_date"] == DECEMBER_EVENT_DATE, (
        f"expected as_of_date {DECEMBER_EVENT_DATE}, got {check['as_of_date']!r}"
    )
    assert_weight_equals(
        check["growth_allowance_lbs"],
        DECEMBER_GROWTH_TOTAL_LBS,
        "growth_allowance_lbs",
    )
    assert_weight_equals(
        check["schedule_allowable_weight_lbs"],
        WEEKLY_STEP_SCHEDULE[-1],
        "schedule_allowable_weight_lbs",
    )


def test_december_floor_keeps_the_hard_floor_class_over_the_relaxed_candidate(api):
    """Step four never folds the growth allowance back into the hard floor.

    With a 4.0 pound growth total and a 147.9 pound schedule value the floor is
    147.9 pounds, so the smallest candidate class whose limit plus the allowance
    reaches it is 144.  §3.7 clamps the report to the larger of that candidate
    and the wrestler's ``min_weight_class_lbs``, which was computed at
    validation time from the unadjusted minimum, so the answer is 150 and a
    150 pound request clears.

    Design: Difficulty/combinatorial_formula/eligibility_floor_circular_evaluation_order_pinned
    """
    scenario = _certified_plan_with_growth_dates_and_events(api)

    check = _run_check(
        api,
        scenario.wrestler_id,
        scenario.december_event_id,
        CANON_TARGET_CLASS_LBS,
    )

    # The growth-relaxed candidate on its own would be 144 pounds.
    relaxed_candidate = min(
        c
        for c in DEFAULT_WEIGHT_CLASSES
        if c + DECEMBER_GROWTH_TOTAL_LBS >= WEEKLY_STEP_SCHEDULE[-1]
    )
    assert relaxed_candidate == 144

    assert check["lowest_eligible_class_lbs"] == CANON_MIN_WEIGHT_CLASS_LBS, (
        "expected the report to clamp up to the hard-floor class "
        f"{CANON_MIN_WEIGHT_CLASS_LBS}, got {check['lowest_eligible_class_lbs']!r}"
    )
    assert check["lowest_eligible_class_lbs"] != relaxed_candidate, (
        "the growth allowance was folded back into min_weight_class_lbs, "
        f"reporting {relaxed_candidate}"
    )
    assert check["lowest_eligible_class_lbs"] == expected_lowest_eligible_class(
        CANON_MINIMUM_CERTIFIED_WEIGHT_LBS,
        WEEKLY_STEP_SCHEDULE[-1],
        DECEMBER_GROWTH_TOTAL_LBS,
        CANON_MIN_WEIGHT_CLASS_LBS,
    )

    assert check["outcome"] == OUTCOME_CLEARED, (
        f"expected outcome {OUTCOME_CLEARED}, got {check['outcome']!r}"
    )
    assert check["blocking_error_id"] is None, (
        "a cleared check reports no blocking error, got "
        f"{check['blocking_error_id']!r}"
    )


def test_early_event_floor_is_governed_by_the_week_one_milestone(api):
    """The same four steps return a different class earlier in the season.

    On 2026-11-10 no growth allowance has taken effect yet, so the total is 0.0,
    and the latest milestone due is the 2026-11-09 week-one row at 157.2 pounds.
    The floor is therefore 157.2, and with no allowance to relax the ladder the
    smallest qualifying class is 165 rather than 157.

    Design: Difficulty/combinatorial_formula/eligibility_floor_circular_evaluation_order_pinned
    """
    scenario = _certified_plan_with_growth_dates_and_events(api)

    check = _run_check(api, scenario.wrestler_id, scenario.early_event_id, 157)

    assert check["as_of_date"] == EARLY_EVENT_DATE, (
        f"expected as_of_date {EARLY_EVENT_DATE}, got {check['as_of_date']!r}"
    )
    assert_weight_equals(
        check["growth_allowance_lbs"], 0.0, "growth_allowance_lbs"
    )
    assert_weight_equals(
        check["schedule_allowable_weight_lbs"],
        WEEKLY_STEP_SCHEDULE[1],
        "schedule_allowable_weight_lbs",
    )
    assert check["lowest_eligible_class_lbs"] == 165, (
        "a 157.2 pound floor with no growth allowance selects the 165 pound "
        f"class, got {check['lowest_eligible_class_lbs']!r}"
    )
    assert check["lowest_eligible_class_lbs"] == expected_lowest_eligible_class(
        CANON_MINIMUM_CERTIFIED_WEIGHT_LBS,
        WEEKLY_STEP_SCHEDULE[1],
        0.0,
        CANON_MIN_WEIGHT_CLASS_LBS,
    )


@pytest.mark.parametrize(
    "event_key, requested_class_lbs, reported_floor_lbs",
    [
        ("december_event_id", 144, CANON_MIN_WEIGHT_CLASS_LBS),
        ("early_event_id", 157, 165),
    ],
    ids=["december-144-under-the-150-hard-floor", "early-dual-157-under-the-165-floor"],
)
def test_request_below_the_reported_floor_is_blocked(
    api, event_key, requested_class_lbs, reported_floor_lbs
):
    """A class beneath the computed floor blocks, and names the entry error.

    §3.7 makes the outcome ``BLOCKED_CLASS_BELOW_MINIMUM`` when the requested
    class is below the computed ``lowest_eligible_class_lbs`` and the governing
    plan is not breached, carrying ``ERR_CLASS_BELOW_CERTIFIED_MINIMUM`` as the
    error a real entry attempt would return.  The check itself still succeeds and
    is logged.

    Design: Difficulty/combinatorial_formula/eligibility_floor_circular_evaluation_order_pinned
    """
    scenario = _certified_plan_with_growth_dates_and_events(api)

    check = _run_check(
        api, scenario.wrestler_id, scenario[event_key], requested_class_lbs
    )

    assert check["requested_class_lbs"] == requested_class_lbs
    assert check["lowest_eligible_class_lbs"] == reported_floor_lbs, (
        f"expected lowest_eligible_class_lbs {reported_floor_lbs}, "
        f"got {check['lowest_eligible_class_lbs']!r}"
    )
    assert check["outcome"] == OUTCOME_BLOCKED_CLASS_BELOW_MINIMUM, (
        f"expected outcome {OUTCOME_BLOCKED_CLASS_BELOW_MINIMUM}, "
        f"got {check['outcome']!r}"
    )
    assert check["blocking_error_id"] == ERR_CLASS_BELOW_CERTIFIED_MINIMUM, (
        f"expected blocking_error_id {ERR_CLASS_BELOW_CERTIFIED_MINIMUM}, "
        f"got {check['blocking_error_id']!r}"
    )
