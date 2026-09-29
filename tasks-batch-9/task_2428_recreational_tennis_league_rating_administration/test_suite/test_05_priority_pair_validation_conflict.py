"""Requests that trip two or three ladder ranks at once, testing which is reported."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_FACILITY_SECTION_MISMATCH,
    ERR_MATCH_RESULT_STATE_INVALID,
    ERR_PLAYER_NOT_PLAYABLE,
    ERR_RATING_PERIOD_CLOSED,
    ERR_SCORECARD_ALREADY_OPEN,
    ERR_SCORECARD_WINDOW_EXPIRED,
    ERR_TEAM_DATE_CONFLICT,
)
from test_helpers.constants import (
    AGE_18_OVER,
    CLOCK_DEFAULT,
    FORMAT_MENS_DOUBLES,
    PLAYER_STRIKE_SUSPENDED,
    RATING_PERIOD_RECALC_IN_PROGRESS,
    RESULT_REPORTED,
    SCHED_PLAYED,
    SCHED_SCHEDULED,
    SCHED_UNSCHEDULED,
    SCORECARD_SUBMITTED,
    SPOT_PENDING,
    STRIKE_SCORECARD_FALSIFICATION,
    TEAM_DRAFT,
    TIER_SECTION,
)
from test_helpers.fixtures import Scenario, six_a_side_league, two_team_league
from test_helpers.test_users import LEAGUE_COORDINATOR, SECTION_ADMIN


# ---------------------------------------------------------------------------
# Instance: pair_a_result_state_409_outranks_expired_submission_window_422_rejected
# ---------------------------------------------------------------------------
def _reported_match_past_its_submission_deadline(api):
    """M1 is REPORTED with an open card and the clock is 3h past the 48h deadline."""
    s = six_a_side_league(api)
    s.create_match("m1", "th", "ta")
    s.schedule_match("m1", "2026-08-15T18:00:00Z", 3)
    s.confirm_match("m1")
    s.set_clock("2026-08-15T21:00:00Z")
    s.mark_played("m1")
    s.submit_scorecard("m1", _home_sweepish_lines(s))
    s.set_clock("2026-08-18T00:00:00Z")
    return s


def _home_sweepish_lines(s):
    return [
        f.scorecard_line(
            1,
            [s.player_id("ph1"), s.player_id("ph2")],
            [s.player_id("pa1"), s.player_id("pa2")],
            [f.set_score(6, 4), f.set_score(6, 0)],
        ),
        f.scorecard_line(
            2,
            [s.player_id("ph3"), s.player_id("ph4")],
            [s.player_id("pa3"), s.player_id("pa4")],
            [f.set_score(6, 4), f.set_score(6, 3)],
        ),
        f.scorecard_line(
            3,
            [s.player_id("ph5"), s.player_id("ph6")],
            [s.player_id("pa5"), s.player_id("pa6")],
            [f.set_score(4, 6), f.set_score(4, 6)],
        ),
    ]


def _away_sweepish_lines(s):
    return [
        f.scorecard_line(
            1,
            [s.player_id("ph1"), s.player_id("ph2")],
            [s.player_id("pa1"), s.player_id("pa2")],
            [f.set_score(4, 6), f.set_score(0, 6)],
        ),
        f.scorecard_line(
            2,
            [s.player_id("ph3"), s.player_id("ph4")],
            [s.player_id("pa3"), s.player_id("pa4")],
            [f.set_score(4, 6), f.set_score(3, 6)],
        ),
        f.scorecard_line(
            3,
            [s.player_id("ph5"), s.player_id("ph6")],
            [s.player_id("pa5"), s.player_id("pa6")],
            [f.set_score(6, 4), f.set_score(6, 4)],
        ),
    ]


def test_the_result_state_check_is_reported_ahead_of_the_expired_window(api):
    """Three checks fail together and only rank 25 is allowed to answer.

    PRD 2.9: "Submitting a scorecard against a match whose `result_status` forbids
    reporting *and* doing so after the submission window has closed reports
    `ERR_MATCH_RESULT_STATE_INVALID`, not `ERR_SCORECARD_WINDOW_EXPIRED`, because
    the state check at rank 25 outranks the temporal check at rank 62."

    Design: Difficulty/priority_pair_validation_conflict/pair_a_result_state_409_outranks_expired_submission_window_422_rejected
    """
    s = _reported_match_past_its_submission_deadline(api)
    response = api.create_scorecard(
        f.scorecard_payload(s.matches["m1"]["id"], _away_sweepish_lines(s)),
        s.captain_headers("ta"),
    )
    validate_error(response, ERR_MATCH_RESULT_STATE_INVALID, 409)

    reported_error = response.json()["data"]["error_id"]
    assert reported_error != ERR_SCORECARD_WINDOW_EXPIRED
    assert reported_error != ERR_SCORECARD_ALREADY_OPEN
    assert response.status_code != 422


def test_the_refused_second_submission_changes_nothing_about_the_first(api):
    """One scorecard remains on file and no standings credit appears.

    PRD 3.6: "A match may have at most one scorecard in the `SUBMITTED`,
    `DISPUTED` or `AMENDED` states at any time, and a second attempt while one is
    open is refused with `ERR_SCORECARD_ALREADY_OPEN`."

    Design: Difficulty/priority_pair_validation_conflict/pair_a_result_state_409_outranks_expired_submission_window_422_rejected
    """
    s = _reported_match_past_its_submission_deadline(api)
    validate_error(
        api.create_scorecard(
            f.scorecard_payload(s.matches["m1"]["id"], _away_sweepish_lines(s)),
            s.captain_headers("ta"),
        ),
        ERR_MATCH_RESULT_STATE_INVALID,
        409,
    )

    match = s.refresh_match("m1")
    assert match["result_status"] == RESULT_REPORTED
    assert match["schedule_status"] == SCHED_PLAYED

    card = get_success_data(
        api.get_scorecard(s.scorecards["sc1"]["id"], SECTION_ADMIN)
    )
    assert card["status"] == SCORECARD_SUBMITTED
    assert card["amendment_count"] == 0

    cards, _meta = validate_paginated(
        api.list_scorecards(
            SECTION_ADMIN, {"match_id": s.matches["m1"]["id"], "limit": 100, "offset": 0}
        )
    )
    assert len(cards) == 1
    assert s.refresh_team("th")["standings_points"] == 0
    assert s.refresh_team("ta")["standings_points"] == 0


# ---------------------------------------------------------------------------
# Instance: pair_c_facility_section_mismatch_422_outranks_team_date_conflict_409_rejected
# ---------------------------------------------------------------------------
def _foreign_facility_and_a_busy_calendar_date(api):
    """M1 fills 2026-08-15 for both teams; a foreign-section facility awaits M2."""
    s = two_team_league(api, roster_size=2, facility_kwargs={"court_count": 4})
    other_section = get_success_data(
        api.create_section(
            f.section_payload(code="NORCAL-2026", name="Northern California"),
            SECTION_ADMIN,
        ),
        201,
    )
    foreign_facility = get_success_data(
        api.create_facility(
            f.facility_payload(other_section["id"], name="Bay Area Courts", court_count=4),
            SECTION_ADMIN,
        ),
        201,
    )

    s.create_match("m1", "th", "ta")
    s.schedule_match("m1", "2026-08-15T18:00:00Z", 2)
    s.create_match("m2", "ta", "th", round_number=2)
    return s, foreign_facility


def test_the_referential_facility_check_answers_before_the_calendar_check(api):
    """A foreign facility on an already-busy date reports the 422, not the 409.

    PRD 2.9: "And scheduling a match at a facility belonging to another section on
    a date where the team already plays reports `ERR_FACILITY_SECTION_MISMATCH`,
    not `ERR_TEAM_DATE_CONFLICT`, because the referential check at rank 42
    outranks the calendar check at rank 54."

    Design: Difficulty/priority_pair_validation_conflict/pair_c_facility_section_mismatch_422_outranks_team_date_conflict_409_rejected
    """
    s, foreign_facility = _foreign_facility_and_a_busy_calendar_date(api)
    m2 = s.refresh_match("m2")
    response = api.schedule_match(
        m2["id"],
        f.schedule_payload(
            foreign_facility["id"], "2026-08-15T20:00:00Z", m2["version"], 2
        ),
        LEAGUE_COORDINATOR,
    )
    validate_error(response, ERR_FACILITY_SECTION_MISMATCH, 422)
    assert response.json()["data"]["error_id"] != ERR_TEAM_DATE_CONFLICT
    assert response.status_code != 409


def test_the_refused_schedule_leaves_the_fixture_unscheduled_and_unversioned(api):
    """No slot is written and the OCC version is untouched by the rejection.

    PRD 3.5: "On success `facility_id`, `scheduled_start_at` and `courts_required`
    are written (overwritten, on a reschedule), `scheduled_end_at` is derived as
    `scheduled_start_at` advanced by the league's `match_duration_minutes`"

    Design: Difficulty/priority_pair_validation_conflict/pair_c_facility_section_mismatch_422_outranks_team_date_conflict_409_rejected
    """
    s, foreign_facility = _foreign_facility_and_a_busy_calendar_date(api)
    before = s.refresh_match("m2")
    validate_error(
        api.schedule_match(
            before["id"],
            f.schedule_payload(
                foreign_facility["id"], "2026-08-15T20:00:00Z", before["version"], 2
            ),
            LEAGUE_COORDINATOR,
        ),
        ERR_FACILITY_SECTION_MISMATCH,
        422,
    )

    after = s.refresh_match("m2")
    assert after["schedule_status"] == SCHED_UNSCHEDULED
    assert after["facility_id"] is None
    assert after["scheduled_start_at"] is None
    assert after["scheduled_end_at"] is None
    assert after["version"] == before["version"]

    first = s.refresh_match("m1")
    assert first["schedule_status"] == SCHED_SCHEDULED
    assert first["facility_id"] == s.facility["id"]


# ---------------------------------------------------------------------------
# Instance: rating_period_closed_409_outranks_player_not_playable_422_rejected
# ---------------------------------------------------------------------------
def _closed_rating_epoch_and_a_suspended_pending_spot(api):
    """A DRAFT team holds two PENDING spots; h2 is suspended, the epoch is closed."""
    s = Scenario(api)
    s.set_clock(CLOCK_DEFAULT)
    s.create_section(
        min_matches_for_playoff_eligibility=1,
        strike_limit=3,
        disqualification_strike_limit=6,
    )
    s.create_facility()
    s.create_league(
        tier=TIER_SECTION,
        ntrp_level=4.0,
        age_group=AGE_18_OVER,
        format=FORMAT_MENS_DOUBLES,
        min_active_roster_size=2,
    )
    s.open_registration()
    s.add_player("ph1", level=4.0)
    s.add_player("ph2", level=4.0)
    s.create_team("th", "ph1")
    s.add_spot("th", "ph1")
    s.add_spot("th", "ph2")

    get_success_data(
        api.create_strike(
            f.strike_payload(
                s.player_id("ph2"),
                STRIKE_SCORECARD_FALSIFICATION,
                reason="Fabricated line scores in a prior season",
            ),
            LEAGUE_COORDINATOR,
        ),
        201,
    )
    get_success_data(api.year_end_recalc(s.section["id"], SECTION_ADMIN))
    return s


def test_the_closed_rating_epoch_answers_before_the_unplayable_player(api):
    """Rank 33 beats rank 34 even though the player is genuinely suspended.

    PRD 2.9: "it reports the failure with the **lowest priority number** in the
    ordering below, and the priority ordering is a fixed part of the contract."

    Design: Difficulty/priority_pair_validation_conflict/rating_period_closed_409_outranks_player_not_playable_422_rejected
    """
    s = _closed_rating_epoch_and_a_suspended_pending_spot(api)
    assert s.refresh_player("ph2")["status"] == PLAYER_STRIKE_SUSPENDED
    assert s.refresh_player("ph2")["strike_count"] == 3

    response = api.activate_roster_spot(
        s.spots["ph2"]["id"], s.captain_headers("th")
    )
    validate_error(response, ERR_RATING_PERIOD_CLOSED, 409)
    assert response.json()["data"]["error_id"] != ERR_PLAYER_NOT_PLAYABLE
    assert response.status_code != 422


def test_the_phase_flag_alone_blocks_activation_with_zero_players_recalculated(api):
    """The recalculation touched nobody, so only the epoch posture can be at fault.

    PRD 3.9: "The section's `recalculated_player_count` is set to the number of
    players in scope, `rating_period_status` becomes `RECALC_IN_PROGRESS`, and the
    section's `version` increases by 1."

    Design: Difficulty/priority_pair_validation_conflict/rating_period_closed_409_outranks_player_not_playable_422_rejected
    """
    s = _closed_rating_epoch_and_a_suspended_pending_spot(api)
    section = get_success_data(api.get_section(s.section["id"], SECTION_ADMIN))
    assert section["rating_period_status"] == RATING_PERIOD_RECALC_IN_PROGRESS
    assert section["recalculated_player_count"] == 0

    validate_error(
        api.activate_roster_spot(s.spots["ph2"]["id"], s.captain_headers("th")),
        ERR_RATING_PERIOD_CLOSED,
        409,
    )

    spot = s.refresh_spot("ph2")
    assert spot["status"] == SPOT_PENDING
    assert spot["ineligible_reason"] is None

    team = s.refresh_team("th")
    assert team["active_roster_size"] == 0
    assert team["status"] == TEAM_DRAFT
