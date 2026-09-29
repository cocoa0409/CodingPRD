"""Metrics probed exactly on their thresholds: the O/E ratio and follow-up completeness."""
from test_helpers import (
    advance_clock,
    create_outcome_review,
    follow_up_by_interval,
    refresh_program,
    setup_donated_donor,
    setup_program_with_staff,
    shift_instant,
    submit_follow_up,
    validate_error,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId

TWO_YEAR_EIGHT_VALID_NAMES = [
    "blood_pressure",
    "serum_creatinine",
    "egfr",
    "proteinuria",
    "weight",
    "smoking_status",
    "insurance_status",
    "employment_status",
    "blood_pressure",
    "",
]
TWO_YEAR_SEVEN_VALID_NAMES = [
    "blood_pressure",
    "serum_creatinine",
    "egfr",
    "proteinuria",
    "weight",
    "smoking_status",
    "insurance_status",
]


def _due_instant(row, seconds=0):
    """The row's `due_on` as an instant the clock can be set to, optionally shifted."""
    raw = row["due_on"]
    base = raw if "T" in raw else f"{raw[:10]}T00:00:00Z"
    return shift_instant(base, seconds=seconds)


def test_oe_ratio_exactly_at_the_flag_threshold_is_watch_not_flagged():
    """PRD §3.8: "Otherwise `oe_ratio` is `observed_survivor_count` divided by
    `expected_survivor_count`, rounded half up to **four** decimal places, and
    `flag_level` is `FLAGGED` when `oe_ratio` is strictly below 0.85, `WATCH` when it
    is strictly below 0.95 but not below 0.85, and `NONE` otherwise. Both thresholds
    are strict, so an `oe_ratio` of exactly 0.8500 is `WATCH` and not `FLAGGED`, and
    exactly 0.9500 is `NONE` and not `WATCH`. `requires_improvement_plan` is true
    exactly when `flag_level` is `FLAGGED`."
    PRD §3.8: "Creation snapshots the program's `expected_one_year_survival_rate`
    into the review's own `expected_survival_rate_used`."
    PRD §3.8: "A new review's `status` is `DRAFT` and `finalized_at` is null; a draft
    review does not yet affect the program's posture at all."

    Design: Difficulty/boundary_precision_check/outcome_oe_ratio_flag_threshold_boundary
    """
    env = setup_program_with_staff()

    review = create_outcome_review(
        env,
        period_start_on="2025-01-01",
        period_end_on="2025-12-31",
        cohort_size=25,
        observed_survivor_count=17,
    )

    assert review["expected_survival_rate_used"] == 0.8
    assert review["expected_survivor_count"] == 20.0, "25 * 0.80 rounded to two places"
    assert review["oe_ratio"] == 0.85, "17 / 20.0 is exactly the strict threshold"
    assert review["flag_level"] == "WATCH", "at the threshold is not flagged"
    assert review["requires_improvement_plan"] is False
    assert review["status"] == "DRAFT"
    assert review["finalized_at"] is None
    assert refresh_program(env)["compliance_posture"] == "OPEN"


def test_oe_ratio_one_notch_below_the_threshold_is_flagged():
    """PRD §3.8: "`flag_level` is `FLAGGED` when `oe_ratio` is strictly below 0.85,
    `WATCH` when it is strictly below 0.95 but not below 0.85, and `NONE` otherwise."
    PRD §3.8: "`requires_improvement_plan` is true exactly when `flag_level` is
    `FLAGGED`."
    PRD §3.8: "`expected_survivor_count` is `cohort_size` multiplied by
    `expected_survival_rate_used`, rounded half up to two decimal places."

    Design: Difficulty/boundary_precision_check/outcome_oe_ratio_flag_threshold_boundary
    """
    env = setup_program_with_staff()

    review = create_outcome_review(
        env,
        period_start_on="2024-01-01",
        period_end_on="2024-12-31",
        cohort_size=25,
        observed_survivor_count=16,
    )

    assert review["expected_survivor_count"] == 20.0
    assert review["oe_ratio"] == 0.8, "16 / 20.0 falls strictly below 0.85"
    assert review["flag_level"] == "FLAGGED"
    assert review["requires_improvement_plan"] is True
    assert review["status"] == "DRAFT"
    assert refresh_program(env)["compliance_posture"] == "OPEN", (
        "a draft review does not yet affect the program's posture at all"
    )


def test_cohort_below_the_floor_suppresses_the_ratio_but_keeps_the_expectation():
    """PRD §3.8: "When `cohort_size` is below 10, the cohort is too small to rate at
    all: `oe_ratio` is null, `flag_level` is `NONE` and `requires_improvement_plan`
    is false, no matter how catastrophic the raw ratio would have looked."
    PRD §3.8: "`expected_survivor_count` is `cohort_size` multiplied by
    `expected_survival_rate_used`, rounded half up to two decimal places."

    Design: Difficulty/boundary_precision_check/outcome_oe_ratio_flag_threshold_boundary
    """
    env = setup_program_with_staff()

    review = create_outcome_review(
        env,
        period_start_on="2023-01-01",
        period_end_on="2023-12-31",
        cohort_size=9,
        observed_survivor_count=3,
    )

    assert review["expected_survivor_count"] == 7.2, "still computed and stored"
    assert review["oe_ratio"] is None
    assert review["flag_level"] == "NONE"
    assert review["requires_improvement_plan"] is False
    assert review["expected_survival_rate_used"] == 0.8


def test_eight_distinct_fields_of_ten_on_the_due_date_is_exactly_complete():
    """PRD §3.7: "The `submitted_field_count` is the number of *distinct* names in
    `submitted_fields` that belong to the interval's required set and carry a
    non-null, non-empty string value: duplicates collapse to one, and a null or empty
    value does not count."
    PRD §3.7: "The threshold comparison is inclusive: when `completeness_pct` is at
    or above the program's `follow_up_completeness_threshold_pct` the row becomes
    `SUBMITTED_COMPLETE`, and otherwise it becomes `INCOMPLETE`. Eight distinct valid
    fields out of a two-year interval's ten give exactly 80.00 and, against the
    default threshold, count as complete; seven of ten give 70.00 and do not."
    PRD §3.7: "Submission is refused before the interval's `due_on` with
    `ERR_FOLLOW_UP_NOT_DUE`, and is refused entirely against a row whose status is
    already `WAIVED` or `SUBMITTED_COMPLETE` with `ERR_FOLLOW_UP_TERMINAL`;
    submission is accepted while the row is `DUE`, `INCOMPLETE` or `DELINQUENT`."
    PRD §3.7: "Otherwise the figure is 100 multiplied by the numerator divided by the
    denominator, rounded half up to two decimal places."

    Design: Difficulty/boundary_precision_check/follow_up_completeness_threshold_and_due_on_boundary
    """
    env = setup_donated_donor()
    two_year = follow_up_by_interval(env, env["donor_one"]["id"], "TWO_YEAR")
    assert two_year["due_on"].startswith("2028-08-08"), "donated_at plus 730 days"
    assert two_year["required_fields_count"] == 10
    advance_clock(env, _due_instant(two_year))

    submitted = submit_follow_up(
        env, two_year["id"], submitted_fields=list(TWO_YEAR_EIGHT_VALID_NAMES)
    )

    assert submitted["submitted_field_count"] == 8, (
        "ten listed names yield eight: the duplicate collapses and the empty value "
        "does not count"
    )
    assert submitted["completeness_pct"] == 80.0
    assert submitted["status"] == "SUBMITTED_COMPLETE", "at the threshold is complete"
    assert submitted["submitted_at"].startswith("2028-08-08"), (
        "a submission exactly on due_on is accepted"
    )

    program = refresh_program(env)
    assert program["follow_up_compliance_pct"] == 33.33, (
        "one of three countable rows, 33.3333 rounded half up"
    )
    assert program["compliance_posture"] == "RESTRICTED", "33.33 is strictly below 75"


def test_seven_distinct_fields_of_ten_falls_short_of_the_threshold():
    """PRD §3.7: "Eight distinct valid fields out of a two-year interval's ten give
    exactly 80.00 and, against the default threshold, count as complete; seven of ten
    give 70.00 and do not."
    PRD §3.7: "`completeness_pct` is 100 multiplied by `submitted_field_count`
    divided by `required_fields_count`, rounded half up to two decimal places, so it
    never exceeds 100.00."

    Design: Difficulty/boundary_precision_check/follow_up_completeness_threshold_and_due_on_boundary
    """
    env = setup_donated_donor()
    two_year = follow_up_by_interval(env, env["donor_one"]["id"], "TWO_YEAR")
    advance_clock(env, _due_instant(two_year))

    submitted = submit_follow_up(
        env, two_year["id"], submitted_fields=list(TWO_YEAR_SEVEN_VALID_NAMES)
    )

    assert submitted["submitted_field_count"] == 7
    assert submitted["completeness_pct"] == 70.0
    assert submitted["status"] == "INCOMPLETE"
    assert refresh_program(env)["follow_up_compliance_pct"] == 0.0, (
        "an INCOMPLETE row counts in the denominator but never in the numerator"
    )


def test_submission_one_day_before_due_on_is_refused_as_not_due():
    """PRD §3.7: "Submission is refused before the interval's `due_on` with
    `ERR_FOLLOW_UP_NOT_DUE`, and is refused entirely against a row whose status is
    already `WAIVED` or `SUBMITTED_COMPLETE` with `ERR_FOLLOW_UP_TERMINAL`;
    submission is accepted while the row is `DUE`, `INCOMPLETE` or `DELINQUENT`."
    PRD §3.7: "three follow-up rows are created for that donor, each in `DUE` status,
    with `interval_code` values of `SIX_MONTH`, `ONE_YEAR` and `TWO_YEAR` and
    `due_on` values of `donated_at` plus 180, 365 and 730 days respectively"

    Design: Difficulty/boundary_precision_check/follow_up_completeness_threshold_and_due_on_boundary
    """
    env = setup_donated_donor()
    two_year = follow_up_by_interval(env, env["donor_one"]["id"], "TWO_YEAR")
    assert two_year["due_on"].startswith("2028-08-08")
    assert two_year["status"] == "DUE"
    advance_clock(env, _due_instant(two_year, seconds=-1))

    response = api_client.submit_follow_up(
        two_year["id"],
        {"submitted_fields": list(TWO_YEAR_EIGHT_VALID_NAMES)},
        env["coordinator_headers"],
    )
    validate_error(response, ApiErrorId.ERR_FOLLOW_UP_NOT_DUE.value)

    untouched = follow_up_by_interval(env, env["donor_one"]["id"], "TWO_YEAR")
    assert untouched["status"] == "DUE"
    assert untouched["submitted_at"] is None
    assert untouched["submitted_field_count"] == 0
