"""Readiness decay, the competition readiness gate and the computed progress report."""
import pytest

from test_helpers import (
    advance_clock,
    api_client,
    assert_one_decimal,
    drive_no_show_ladder,
    enroll_athlete,
    fetch_athlete,
    fetch_group_session,
    fetch_progress_report,
    finalize_performance_battery,
    setup_athlete_at_competition_readiness,
    setup_cleared_athlete,
    setup_session_with_coach,
    validate_error,
    validate_paginated,
    validate_success,
)

# A composite of exactly 60.0 for a BASKETBALL GUARD in the 15-16 band.
BATTERY_AT_SIXTY = {"CMJ_CM": 42.5, "SPRINT_10M_S": 1.74, "IMTP_N": 1850}
# A stronger retest: 70.0 / 70.0 / 63.3 -> composite 68.3.
BATTERY_STRONGER = {"CMJ_CM": 45.0, "SPRINT_10M_S": 1.70, "IMTP_N": 1900}
NO_SHOW_WINDOWS = [("2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z"),
                   ("2026-08-11T10:00:00Z", "2026-08-11T11:00:00Z")]


def test_01_a_competition_session_refuses_an_athlete_below_the_readiness_minimum(
        api, front_desk_headers, performance_director_headers):
    """An athlete with no battery on file sits at the default base and is refused.

    "Enrollment in a session whose `phase_focus` is `COMPETITION` requires the
    athlete's live `readiness_index` to be at least 60.00 — the boundary is
    inclusive, so exactly 60.00 is admitted."

    Design: Corner/errors/competition_session_enrollment_below_readiness_minimum_is_rejected
    """
    athlete, staff, _coach = setup_cleared_athlete(
        athlete_overrides={"full_name": "Below Threshold Athlete"},
        coach_name="Coach Readiness Gate")
    assert athlete["training_clearance"] == "CLEARED"
    assert athlete["readiness_index"] == pytest.approx(50.00, abs=0.01)

    session = setup_session_with_coach(
        staff["id"], start_at="2026-08-20T16:00:00Z", end_at="2026-08-20T17:00:00Z",
        station_count=3, max_athletes=10, phase_focus="COMPETITION")

    validate_error(
        api.create_enrollment(
            {"athlete_id": athlete["id"], "group_session_id": session["id"]},
            front_desk_headers),
        "ERR_READINESS_BELOW_THRESHOLD", expected_status=422)

    _rows, meta = validate_paginated(api.list_enrollments(
        performance_director_headers, params={"athlete_id": athlete["id"]}))
    assert meta["total_count"] == 0, "the refused booking must not have created a row"
    assert fetch_group_session(session["id"])["reserved_count"] == 0


def test_02_a_battery_composite_of_exactly_sixty_sets_readiness_to_the_minimum(api):
    """The freshly finalized composite becomes the readiness base with no decay yet.

    "**Base.** The athlete's `last_composite_percentile`, or 50.0 when no battery
    has ever been finalized."

    Design: Difficulty/boundary_precision_check/readiness_index_exactly_at_competition_minimum_admits_enrollment
    """
    athlete, _staff, _coach, battery = setup_athlete_at_competition_readiness(
        athlete_overrides={"full_name": "Leo Kaur", "date_of_birth": "2010-01-15",
                           "maturity_offset_months": 0})

    assert battery["variant_applied"] == "RAW_NORM"
    assert battery["effective_age_years"] == 16
    assert_one_decimal(battery["composite_percentile"], "composite_percentile")
    assert battery["composite_percentile"] == pytest.approx(60.0, abs=0.05)

    assert athlete["last_composite_percentile"] == pytest.approx(60.0, abs=0.05)
    assert athlete["readiness_index"] == pytest.approx(60.00, abs=0.01)


def test_03_readiness_of_exactly_sixty_is_admitted_to_a_competition_session(api):
    """The inclusive boundary lets the athlete through and the booking is charged drop-in.

    "Enrollment in a session whose `phase_focus` is `COMPETITION` requires the
    athlete's live `readiness_index` to be at least 60.00 — the boundary is
    inclusive, so exactly 60.00 is admitted."

    Design: Difficulty/boundary_precision_check/readiness_index_exactly_at_competition_minimum_admits_enrollment
    """
    athlete, staff, _coach, _battery = setup_athlete_at_competition_readiness(
        athlete_overrides={"full_name": "Leo Kaur", "date_of_birth": "2010-01-15",
                           "maturity_offset_months": 0})
    session = setup_session_with_coach(
        staff["id"], start_at="2026-08-10T10:00:00Z", end_at="2026-08-10T11:00:00Z",
        station_count=3, max_athletes=10, phase_focus="COMPETITION")

    enrollment = enroll_athlete(athlete["id"], session["id"])

    assert enrollment["status"] == "RESERVED"
    assert enrollment["funding_source"] == "DROP_IN"
    assert enrollment["charge_cents"] == 4500

    reread = fetch_group_session(session["id"])
    assert reread["reserved_count"] == 1
    assert reread["athlete_units"] == pytest.approx(1.0, abs=0.05)


def test_04_readiness_is_undecayed_on_the_thirtieth_day_after_the_test(api):
    """Day thirty is still inside the grace period, so nothing is subtracted.

    "The first 30 days are a grace period and cost nothing; each day beyond the
    thirtieth costs 0.5 points, and the total decay is capped at 20.0 points, which
    the ladder reaches after 70 days beyond grace."

    Design: Difficulty/boundary_precision_check/readiness_decay_grace_boundary_at_day_30_versus_day_31_on_progress_report
    """
    athlete, _staff, coach = setup_cleared_athlete(
        athlete_overrides={"full_name": "Dev Anand", "date_of_birth": "2010-01-15",
                           "maturity_offset_months": 0},
        coach_name="Mona Reid")
    finalize_performance_battery(athlete["id"], coach, BATTERY_AT_SIXTY)

    advance_clock("2026-08-31T00:00:00Z")
    report = fetch_progress_report(athlete["id"])

    assert report["readiness_index"] == pytest.approx(60.00, abs=0.01)
    assert report["composite_percentile_current"] == pytest.approx(60.0, abs=0.05)
    assert report["composite_percentile_previous"] is None
    assert report["delta_percentile_points"] is None
    assert report["tests_included_count"] == 1
    assert report["attendance_rate_pct"] is None
    assert report["no_show_fee_total_cents"] == 0
    assert report["next_test_due_on"] == "2026-09-26"
    assert report["test_overdue"] is False


def test_05_readiness_loses_half_a_point_on_the_thirty_first_day(api):
    """The first day beyond grace costs exactly 0.5 points.

    "**Decay.** The number of whole days elapsed between `last_performance_test_at`
    and the current logical clock — computed by dividing the elapsed seconds by
    86,400 and discarding the fraction, and taken as zero when
    `last_performance_test_at` is null."

    Design: Difficulty/boundary_precision_check/readiness_decay_grace_boundary_at_day_30_versus_day_31_on_progress_report
    """
    athlete, _staff, coach = setup_cleared_athlete(
        athlete_overrides={"full_name": "Dev Anand", "date_of_birth": "2010-01-15",
                           "maturity_offset_months": 0},
        coach_name="Mona Reid")
    finalize_performance_battery(athlete["id"], coach, BATTERY_AT_SIXTY)

    advance_clock("2026-08-31T00:00:00Z")
    at_grace = fetch_progress_report(athlete["id"])
    advance_clock("2026-09-01T00:00:00Z")
    past_grace = fetch_progress_report(athlete["id"])

    assert at_grace["readiness_index"] == pytest.approx(60.00, abs=0.01)
    assert past_grace["readiness_index"] == pytest.approx(59.50, abs=0.01)
    assert past_grace["readiness_index"] != pytest.approx(60.00, abs=0.01)
    assert past_grace["composite_percentile_current"] == pytest.approx(60.0, abs=0.05)
    assert past_grace["next_test_due_on"] == "2026-09-26"
    assert past_grace["test_overdue"] is False, \
        "the logical date has not yet passed the due date"


def test_06_the_progress_report_reports_the_delta_between_two_finalized_batteries(api):
    """Two finalized batteries give a current, a previous and their difference.

    "From that ordering the report exposes `composite_percentile_current` (the
    newest session's composite, or null when there is none),
    `composite_percentile_previous` (the second newest, or null when fewer than two
    exist), and `delta_percentile_points` — the previous subtracted from the
    current, rounded half up to one decimal place, and null whenever either side is
    null."

    Design: Corner/calculations/progress_report_delta_between_two_finalized_batteries
    """
    athlete, _staff, coach = setup_cleared_athlete(
        athlete_overrides={"full_name": "Delta Athlete", "date_of_birth": "2010-01-15",
                           "sport": "BASKETBALL", "position": "GUARD"},
        coach_name="Coach Delta")

    first = finalize_performance_battery(athlete["id"], coach, BATTERY_AT_SIXTY)
    assert first["composite_percentile"] == pytest.approx(60.0, abs=0.05)

    advance_clock("2026-08-15T09:00:00Z")
    second = finalize_performance_battery(athlete["id"], coach, BATTERY_STRONGER)
    assert second["composite_percentile"] == pytest.approx(68.3, abs=0.05)

    report = fetch_progress_report(athlete["id"])

    assert report["athlete_id"] == athlete["id"]
    assert report["composite_percentile_current"] == pytest.approx(68.3, abs=0.05)
    assert report["composite_percentile_previous"] == pytest.approx(60.0, abs=0.05)
    assert report["delta_percentile_points"] == pytest.approx(8.3, abs=0.05)
    assert report["tests_included_count"] == 2
    assert report["normative_cohort"] == "BASKETBALL/GUARD/15-16"
    assert report["next_test_due_on"] == "2026-10-10"
    assert report["test_overdue"] is False
    assert report["readiness_index"] == pytest.approx(68.30, abs=0.01)


def test_07_each_no_show_fee_is_rounded_to_whole_cents_as_it_is_assessed(api):
    """A base-multiplier no-show line is 1,237.5 cents and is persisted as 1,238.

    "The product of the list price, the fee percentage and the multiplier is
    rounded half up to whole cents and stored as `no_show_fee_cents`."

    Design: Difficulty/combinatorial_formula/no_show_statement_rounds_each_line_before_summing_to_2476_not_2475
    """
    athlete, staff, coach = setup_cleared_athlete(
        athlete_overrides={"full_name": "Noor Haddad", "date_of_birth": "2010-01-15"},
        coach_name="Cleo Marsh")

    _sessions, no_shows = drive_no_show_ladder(
        athlete["id"], staff["id"], coach, NO_SHOW_WINDOWS)

    assert [row["status"] for row in no_shows] == ["NO_SHOW", "NO_SHOW"]
    assert [row["strike_index_at_no_show"] for row in no_shows] == [1, 2]
    for row in no_shows:
        assert row["no_show_fee_cents"] == 1238, \
            "4,500 x 27.5 per cent x 1.0 is 1,237.5 cents and rounds half up"

    reread = fetch_athlete(athlete["id"])
    assert reread["no_show_strikes"] == 2
    assert reread["membership_status"] == "ACTIVE", "the third strike is what suspends"


def test_08_the_fee_statement_sums_the_persisted_rounded_lines(api):
    """Two base-multiplier lines total 2,476 cents, not the 2,475 of a late rounding.

    "The rejected alternative — recomputing each line unrounded, summing the
    unrounded lines, and rounding once at the end — is explicitly not the contract,
    and the two disagree: two lines at the base multiplier are 1,237.5 cents each,
    so per-line rounding totals 2,476 cents while sum-then-round totals 2,475."

    Design: Difficulty/combinatorial_formula/no_show_statement_rounds_each_line_before_summing_to_2476_not_2475
    """
    athlete, staff, coach = setup_cleared_athlete(
        athlete_overrides={"full_name": "Noor Haddad", "date_of_birth": "2010-01-15"},
        coach_name="Cleo Marsh")
    _sessions, no_shows = drive_no_show_ladder(
        athlete["id"], staff["id"], coach, NO_SHOW_WINDOWS)
    assert sum(row["no_show_fee_cents"] for row in no_shows) == 2476

    report = fetch_progress_report(athlete["id"])

    assert report["no_show_fee_total_cents"] == 2476
    assert report["no_show_fee_total_cents"] != 2475
    assert report["attendance_rate_pct"] == pytest.approx(0.0, abs=0.05)
