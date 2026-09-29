"""Grievance, dispute, gender, compliance and capacity refusals."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.assertions import assert_instant_equals
from test_helpers.api_errors import (
    ERR_ACTOR_DISQUALIFIED,
    ERR_AGE_GROUP_NOT_MET,
    ERR_DISPUTE_WINDOW_EXPIRED,
    ERR_FORMAT_GENDER_MISMATCH,
    ERR_GRIEVANCE_SUBJECT_INVALID,
    ERR_GRIEVANCE_WINDOW_EXPIRED,
    ERR_LEAGUE_TEAM_CAPACITY_REACHED,
    ERR_MATCH_RESULT_STATE_INVALID,
    ERR_MATCH_SCHEDULE_STATE_INVALID,
    ERR_NOT_TEAM_CAPTAIN,
    ERR_OUTSIDE_REGISTRATION_WINDOW,
    ERR_RATING_LEVEL_EXCEEDS_LEAGUE,
    ERR_ROSTER_QUOTA_NOT_MET,
    ERR_SCORECARD_WINDOW_EXPIRED,
    ERR_TEAM_ROSTER_NONCOMPLIANT,
)
from test_helpers.constants import (
    AGE_18_OVER,
    CLOCK_DEFAULT,
    FORMAT_MENS_DOUBLES,
    GENDER_F,
    GRIEVANCE_FILED,
    GRIEVANCE_SCORE_FALSIFICATION,
    RESULT_REPORTED,
    REVIEW_DISPUTE,
    REVIEW_VERIFY,
    SCHED_CONFIRMED,
    SCHED_SCHEDULED,
    SCORECARD_SUBMITTED,
    SCORECARD_VERIFIED,
    SPOT_ACTIVE,
    SPOT_PENDING,
    STRIKE_SCORECARD_FALSIFICATION,
    TEAM_DRAFT,
    TEAM_REGISTERED,
    TIER_SECTION,
)
from test_helpers.fixtures import (
    Scenario,
    played_match,
    six_a_side_league,
    standard_three_lines,
    two_team_league,
)
from test_helpers.test_users import LEAGUE_COORDINATOR, SECTION_ADMIN


def _verified_match_then_clock(api, clock):
    """One verified match starting 2026-08-15T18:00:00Z, then the clock moves."""
    s = six_a_side_league(api)
    played_match(s, standard_three_lines(s), match_key="m1")
    s.set_clock(clock)
    return s


def _score_falsification_grievance(s):
    return f.grievance_payload(
        s.league["id"],
        s.teams["th"]["id"],
        GRIEVANCE_SCORE_FALSIFICATION,
        subject_match_id=s.matches["m1"]["id"],
        statement="Line 3 games were reported in the wrong order.",
    )


def test_a_grievance_one_second_past_the_anchor_window_is_refused(api):
    """The anchor is the subject match's start instant, not its end or its card.

    PRD 3.8: "Temporally, a grievance must be filed within the section's
    `grievance_window_hours` - three days by default - of its subject anchor: the
    subject match's start instant for the three match-based kinds, or the appeal
    decision it contests for a `RATING_VIOLATION`; later is refused with
    `ERR_GRIEVANCE_WINDOW_EXPIRED`."

    Design: Corner/errors/grievance_filed_one_second_late_returns_422_grievance_window_expired
    """
    s = _verified_match_then_clock(api, "2026-08-18T18:00:01Z")
    response = api.create_grievance(
        _score_falsification_grievance(s), s.captain_headers("ta")
    )
    validate_error(response, ERR_GRIEVANCE_WINDOW_EXPIRED, 422)
    reported = response.json()["data"]["error_id"]
    # The payload is coherent: the match belongs to the league and names the accused.
    assert reported != ERR_GRIEVANCE_SUBJECT_INVALID
    # And the filer captains the other side of that very match.
    assert reported != ERR_NOT_TEAM_CAPTAIN

    _filed, meta = validate_paginated(
        api.list_grievances(
            SECTION_ADMIN, {"league_id": s.league["id"], "limit": 100, "offset": 0}
        )
    )
    assert meta["total_count"] == 0


def test_the_same_grievance_on_the_last_admissible_instant_is_accepted(api):
    """72 hours after the start instant is inside the window because it is inclusive.

    PRD 3.8: "The grievance arrives at `status` `FILED` with `remedy` null, both
    vote counts 0, and `decided_by_chair_player_id`, `decided_at` and
    `decision_note` null."

    Design: Corner/errors/grievance_filed_one_second_late_returns_422_grievance_window_expired
    """
    s = _verified_match_then_clock(api, "2026-08-18T18:00:00Z")
    filed = get_success_data(
        api.create_grievance(
            _score_falsification_grievance(s), s.captain_headers("ta")
        ),
        201,
    )
    assert filed["status"] == GRIEVANCE_FILED
    assert filed["filed_by_captain_player_id"] == s.player_id("pa1")
    assert filed["against_team_id"] == s.teams["th"]["id"]
    assert filed["subject_match_id"] == s.matches["m1"]["id"]
    assert filed["remedy"] is None
    assert filed["support_vote_count"] == 0
    assert filed["oppose_vote_count"] == 0
    assert filed["decided_by_chair_player_id"] is None
    assert filed["decided_at"] is None
    assert filed["decision_note"] is None


# ---------------------------------------------------------------------------
def _mens_league_with_a_pending_female_spot(api):
    """A MENS_DOUBLES 3.5 league whose DRAFT team staged a female player."""
    s = Scenario(api)
    s.set_clock(CLOCK_DEFAULT)
    s.create_section(min_matches_for_playoff_eligibility=1)
    s.create_facility()
    s.create_league(
        tier=TIER_SECTION,
        ntrp_level=3.5,
        age_group=AGE_18_OVER,
        format=FORMAT_MENS_DOUBLES,
        min_active_roster_size=2,
    )
    s.open_registration()
    s.add_player("ph1", level=3.5, full_name="Hank Halfvolley")
    s.add_player(
        "pf1", level=3.5, gender=GENDER_F, birth_year=1975, full_name="Fay Forehand"
    )
    s.create_team("th", "ph1", "Balboa Aces")
    return s


def test_a_female_player_may_be_staged_but_not_activated_in_a_mens_league(api):
    """The add is accepted because the gender gate lives at activation.

    PRD 3.3: "A `MENS_DOUBLES` league admits only players whose gender is `M`; a
    `WOMENS_DOUBLES` league admits only players whose gender is `F`; a
    `MIXED_DOUBLES` league admits both. Inadmissibility is refused with
    `ERR_FORMAT_GENDER_MISMATCH`."

    Design: Corner/errors/activating_a_female_player_in_a_mens_doubles_league_returns_422_format_gender_mismatch
    """
    s = _mens_league_with_a_pending_female_spot(api)
    staged = s.add_spot("th", "pf1")
    assert staged["status"] == SPOT_PENDING

    response = api.activate_roster_spot(staged["id"], s.captain_headers("th"))
    validate_error(response, ERR_FORMAT_GENDER_MISMATCH, 422)
    reported = response.json()["data"]["error_id"]
    # 3.5 sits inside a 3.5 league's band and birth year 1975 clears AGE_18_OVER.
    assert reported != ERR_RATING_LEVEL_EXCEEDS_LEAGUE
    assert reported != ERR_AGE_GROUP_NOT_MET

    unchanged = s.refresh_spot("pf1")
    assert unchanged["status"] == SPOT_PENDING
    assert unchanged["level_at_add"] is None

    team = s.refresh_team("th")
    assert team["active_roster_size"] == 0
    assert team["roster_compliant"] is False

    # The refusal is specific to the mismatched player, not to team or endpoint.
    male = s.add_spot("th", "ph1")
    activated = get_success_data(
        api.activate_roster_spot(male["id"], s.captain_headers("th"))
    )
    assert activated["status"] == SPOT_ACTIVE
    assert activated["level_at_add"] == 3.5


# ---------------------------------------------------------------------------
def test_a_dispute_one_second_late_is_refused_while_verify_still_succeeds(api):
    """Only the DISPUTE branch is time-boxed, and its anchor is the card itself.

    PRD 3.6: "It must land while the current instant is at or before the
    scorecard's `updated_at` advanced by the section's
    `scorecard_dispute_window_hours` - one day by default; later is refused with
    `ERR_DISPUTE_WINDOW_EXPIRED`."

    Design: Corner/errors/disputing_a_card_one_second_past_the_dispute_window_returns_422_dispute_window_expired
    """
    s = six_a_side_league(api)
    played_match(s, standard_three_lines(s), match_key="m1", verify=False)
    s.set_clock("2026-08-16T21:00:01Z")
    card_id = s.scorecards["sc1"]["id"]

    response = api.review_scorecard(
        card_id,
        {
            "decision": REVIEW_DISPUTE,
            "dispute_reason": "Line 3 set scores were transposed",
            "disputed_line_numbers": [3],
        },
        s.captain_headers("ta"),
    )
    validate_error(response, ERR_DISPUTE_WINDOW_EXPIRED, 422)
    reported = response.json()["data"]["error_id"]
    # The submission window runs to 2026-08-17T21:00:00Z and has not closed.
    assert reported != ERR_SCORECARD_WINDOW_EXPIRED
    # And the match is still REPORTED, the state a review requires.
    assert reported != ERR_MATCH_RESULT_STATE_INVALID

    still_open = get_success_data(api.get_scorecard(card_id, SECTION_ADMIN))
    assert still_open["status"] == SCORECARD_SUBMITTED
    assert still_open["dispute_reason"] is None
    assert still_open["disputed_line_numbers"] == []
    assert still_open["verified_at"] is None
    assert s.refresh_match("m1")["result_status"] == RESULT_REPORTED

    verified = get_success_data(
        api.review_scorecard(
            card_id, {"decision": REVIEW_VERIFY}, s.captain_headers("ta")
        )
    )
    assert verified["status"] == SCORECARD_VERIFIED
    assert_instant_equals(verified["verified_at"], "2026-08-16T21:00:01Z")


# ---------------------------------------------------------------------------
def _scheduled_fixture_with_a_struck_home_player(api):
    """A mid-season strike drops the home side below its minimum active roster."""
    s = two_team_league(api, roster_size=2, with_committee=True)
    s.create_match("m1", "th", "ta")
    s.schedule_match("m1", "2026-08-15T18:00:00Z", 3)
    strike = get_success_data(
        api.create_strike(
            f.strike_payload(
                s.player_id("ph2"),
                STRIKE_SCORECARD_FALSIFICATION,
                reason="Falsified a set score in a prior season",
            ),
            LEAGUE_COORDINATOR,
        ),
        201,
    )
    return s, strike


def test_confirmation_re_evaluates_compliance_instead_of_trusting_roster_lock(api):
    """Both sides were compliant at start of play; one has silently fallen below.

    PRD 3.5: "Both teams must have `roster_compliant` true, failing which the
    refusal is `ERR_TEAM_ROSTER_NONCOMPLIANT` - this is the check that strands a
    team whose roster has fallen below its league's `min_active_roster_size`,
    whether through removals or through a cascade of ineligibility."

    Design: Corner/errors/confirming_a_match_with_a_noncompliant_side_returns_409_team_roster_noncompliant
    """
    s, strike = _scheduled_fixture_with_a_struck_home_player(api)
    version_before = s.matches["m1"]["version"]

    response = api.confirm_match(s.matches["m1"]["id"], s.captain_headers("th"))
    validate_error(response, ERR_TEAM_ROSTER_NONCOMPLIANT, 409)
    reported = response.json()["data"]["error_id"]
    # SCHEDULED to CONFIRMED is the transition this endpoint exists for.
    assert reported != ERR_MATCH_SCHEDULE_STATE_INVALID
    # And the strike landed on a teammate, not on the confirming captain.
    assert reported != ERR_ACTOR_DISQUALIFIED

    unchanged = s.refresh_match("m1")
    assert unchanged["schedule_status"] == SCHED_SCHEDULED
    assert unchanged["version"] == version_before

    assert s.refresh_team("th")["roster_compliant"] is False
    assert s.refresh_team("ta")["roster_compliant"] is True

    get_success_data(
        api.rescind_strike(
            strike["id"],
            {"rescinded_reason": "The prior-season report was mis-attributed"},
            s.chair_headers(),
        )
    )
    restored = s.refresh_team("th")
    assert restored["active_roster_size"] == 2
    assert restored["roster_compliant"] is True

    confirmed = get_success_data(
        api.confirm_match(s.matches["m1"]["id"], s.captain_headers("th"))
    )
    assert confirmed["schedule_status"] == SCHED_CONFIRMED


# ---------------------------------------------------------------------------
def _one_team_league_with_a_ready_second_team(api):
    """A league capped at one team: one REGISTERED squad and one compliant DRAFT."""
    s = Scenario(api)
    s.set_clock(CLOCK_DEFAULT)
    s.create_section(min_matches_for_playoff_eligibility=1)
    s.create_facility()
    s.create_league(
        tier=TIER_SECTION,
        ntrp_level=4.0,
        age_group=AGE_18_OVER,
        format=FORMAT_MENS_DOUBLES,
        min_active_roster_size=2,
        max_roster_size=4,
        max_teams=1,
    )
    s.open_registration()
    for key, name in (
        ("ph1", "Hank Halfvolley"),
        ("ph2", "Ned Netcord"),
        ("pb1", "Vic Volley"),
        ("pb2", "Sam Slice"),
    ):
        s.add_player(key, level=4.0, full_name=name)
    s.create_team("th", "ph1", "Ace Alone")
    s.fill_roster("th", ["ph1", "ph2"])
    s.register_team("th")
    s.create_team("tb", "pb1", "Second Serve")
    s.fill_roster("tb", ["pb1", "pb2"])
    return s


def test_the_team_quota_counts_registered_rows_and_bites_at_registration(api):
    """A capped league still holds a DRAFT team; it simply cannot register it.

    PRD 3.4: "The league's `registered_team_count` must be strictly below its
    `max_teams`, and a league already at quota refuses the registration with
    `ERR_LEAGUE_TEAM_CAPACITY_REACHED`."

    Design: Corner/errors/registering_a_second_team_in_a_one_team_league_returns_409_league_team_capacity_reached
    """
    s = _one_team_league_with_a_ready_second_team(api)
    version_before = s.refresh_team("tb")["version"]

    response = api.register_team(s.teams["tb"]["id"], s.captain_headers("tb"))
    validate_error(response, ERR_LEAGUE_TEAM_CAPACITY_REACHED, 409)
    reported = response.json()["data"]["error_id"]
    # The second team holds two ACTIVE spots and meets min_active_roster_size 2.
    assert reported != ERR_TEAM_ROSTER_NONCOMPLIANT
    assert reported != ERR_ROSTER_QUOTA_NOT_MET
    # And the clock still reads 2026-08-01T00:00:00Z, inside the window.
    assert reported != ERR_OUTSIDE_REGISTRATION_WINDOW

    stranded = s.refresh_team("tb")
    assert stranded["status"] == TEAM_DRAFT
    assert stranded["version"] == version_before
    assert stranded["active_roster_size"] == 2

    _all_teams, all_meta = validate_paginated(
        api.list_teams(
            SECTION_ADMIN, {"league_id": s.league["id"], "limit": 100, "offset": 0}
        )
    )
    assert all_meta["total_count"] == 2

    registered, registered_meta = validate_paginated(
        api.list_teams(
            SECTION_ADMIN,
            {
                "league_id": s.league["id"],
                "status": TEAM_REGISTERED,
                "limit": 100,
                "offset": 0,
            },
        )
    )
    assert registered_meta["total_count"] == 1
    assert registered[0]["id"] == s.teams["th"]["id"]
    assert s.refresh_league()["registered_team_count"] == 1
