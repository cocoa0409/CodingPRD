"""Referential, temporal, aggregate and conditional validation of write payloads."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_AGE_GROUP_NOT_MET,
    ERR_DUPLICATE_ROSTER_SPOT,
    ERR_INVALID_STATE,
    ERR_LEAGUE_PHASE_FORBIDS_ROSTER_CHANGE,
    ERR_MATCH_RESULT_STATE_INVALID,
    ERR_MATCH_SCHEDULE_STATE_INVALID,
    ERR_NOT_FOUND,
    ERR_OUTSIDE_REGISTRATION_WINDOW,
    ERR_RATING_LEVEL_EXCEEDS_LEAGUE,
    ERR_REFERENCE_NOT_FOUND,
    ERR_ROSTER_QUOTA_NOT_MET,
    ERR_ROSTER_SIZE_EXCEEDED,
    ERR_SCORECARD_WINDOW_EXPIRED,
    ERR_SECTION_SCOPE_MISMATCH,
    ERR_SELF_RATING_LOCKED,
    ERR_STALE_TEAM_VERSION,
)
from test_helpers.constants import (
    AGE_18_OVER,
    CLOCK_DEFAULT,
    FORMAT_MENS_DOUBLES,
    LEAGUE_REGISTRATION_OPEN,
    LEAGUE_ROSTERS_LOCKED,
    PLAYER_STRIKE_SUSPENDED,
    RATING_COMPUTER_RATED,
    RATING_SOURCE_SELF,
    RESULT_PENDING,
    RESULT_REPORTED,
    SCHED_PLAYED,
    SCORECARD_SUBMITTED,
    SPOT_ACTIVE,
    SPOT_PENDING,
    STRIKE_SCORECARD_FALSIFICATION,
    TEAM_DRAFT,
    TEAM_ROSTER_LOCKED,
    TIER_SECTION,
)
from test_helpers.fixtures import (
    Scenario,
    six_a_side_league,
    standard_three_lines,
    two_team_league,
)
from test_helpers.test_users import (
    LEAGUE_COORDINATOR,
    SECTION_ADMIN,
    make_player_headers,
)


def _open_league_with_one_team(api, **league_overrides):
    """A REGISTRATION_OPEN league whose only team is Team H, captained by ph1."""
    s = Scenario(api)
    s.set_clock(CLOCK_DEFAULT)
    s.create_section(min_matches_for_playoff_eligibility=1)
    s.create_facility()
    s.create_league(
        **dict(
            {
                "tier": TIER_SECTION,
                "ntrp_level": 4.0,
                "age_group": AGE_18_OVER,
                "format": FORMAT_MENS_DOUBLES,
                "min_active_roster_size": 2,
            },
            **league_overrides,
        )
    )
    s.open_registration()
    s.add_player("ph1", level=4.0, full_name="Hank Halfvolley")
    s.create_team("th", "ph1", "Balboa Aces")
    return s


# ---------------------------------------------------------------------------
def test_a_player_may_not_be_signed_by_a_second_team_of_the_same_league(api):
    """The uniqueness scope of a live roster spot is the league, not the team.

    PRD 3.3: "A player may hold at most one roster spot in the `PENDING`, `ACTIVE`
    or `INELIGIBLE` states per league, counted across *every* team of that league
    - a second attempt anywhere in the same league is refused with
    `ERR_DUPLICATE_ROSTER_SPOT`."

    Design: Corner/validations/same_player_on_a_second_team_of_one_league_returns_409_duplicate_roster_spot
    """
    s = _open_league_with_one_team(api)
    s.fill_roster("th", ["ph1"])
    s.add_player("pb1", level=4.0, full_name="Vic Volley")
    s.create_team("tb", "pb1", "Volley Kings")
    assert s.teams["tb"]["version"] == 1

    validate_error(
        api.create_roster_spot(
            f.roster_spot_payload(
                s.teams["tb"]["id"], s.player_id("ph1"), s.team_version("tb")
            ),
            s.captain_headers("tb"),
        ),
        ERR_DUPLICATE_ROSTER_SPOT,
        409,
    )

    _spots, meta = validate_paginated(
        api.list_roster_spots(
            SECTION_ADMIN, {"team_id": s.teams["tb"]["id"], "limit": 100, "offset": 0}
        )
    )
    assert meta["total_count"] == 0

    second = s.refresh_team("tb")
    assert second["version"] == 1
    assert second["active_roster_size"] == 0

    _held, held_meta = validate_paginated(
        api.list_roster_spots(
            SECTION_ADMIN,
            {"player_id": s.player_id("ph1"), "limit": 100, "offset": 0},
        )
    )
    assert held_meta["total_count"] == 1


# ---------------------------------------------------------------------------
def test_an_unresolvable_player_reference_answers_before_the_stale_version(api):
    """Rank 11 speaks first even though the declared team version is two behind.

    PRD 2.10: "A foreign key carried in a request body that does not resolve to an
    existing row of the entity it names is refused with `ERR_REFERENCE_NOT_FOUND`
    (HTTP 404)."

    Design: Corner/validations/unresolvable_player_fk_beats_a_stale_team_version_and_returns_404_reference_not_found
    """
    s = _open_league_with_one_team(api)
    s.fill_roster("th", ["ph1"])
    assert s.team_version("th") == 3

    response = api.create_roster_spot(
        f.roster_spot_payload(s.teams["th"]["id"], NON_EXISTENT_UUID, 1),
        s.captain_headers("th"),
    )
    validate_error(response, ERR_REFERENCE_NOT_FOUND, 404)
    reported = response.json()["data"]["error_id"]
    assert reported != ERR_STALE_TEAM_VERSION
    assert reported != ERR_NOT_FOUND

    team = s.refresh_team("th")
    assert team["version"] == 3
    assert team["active_roster_size"] == 1


# ---------------------------------------------------------------------------
def test_a_player_of_another_section_is_out_of_scope_rather_than_missing(api):
    """The row resolves, so the refusal is the scoping code and not rank 11.

    PRD 2.10: "A payload foreign key that *does* resolve but belongs to a different
    `Section` than the target resource is refused with `ERR_SECTION_SCOPE_MISMATCH`
    (HTTP 404): players, leagues, facilities and teams never cross section
    boundaries."

    Design: Corner/validations/roster_spot_naming_a_player_of_another_section_returns_404_section_scope_mismatch
    """
    s = _open_league_with_one_team(api)
    s.fill_roster("th", ["ph1"])
    other = get_success_data(
        api.create_section(
            f.section_payload(code="NORCAL-2026", name="Northern California"),
            SECTION_ADMIN,
        ),
        201,
    )
    s.add_player(
        "px1", full_name="Rex Ringer", section_id=other["id"]
    )

    response = api.create_roster_spot(
        f.roster_spot_payload(
            s.teams["th"]["id"], s.player_id("px1"), s.team_version("th")
        ),
        s.captain_headers("th"),
    )
    validate_error(response, ERR_SECTION_SCOPE_MISMATCH, 404)
    assert response.json()["data"]["error_id"] != ERR_REFERENCE_NOT_FOUND

    # The referenced row exists; it is only out of scope.
    get_success_data(api.get_player(s.player_id("px1"), SECTION_ADMIN))

    _spots, meta = validate_paginated(
        api.list_roster_spots(
            SECTION_ADMIN, {"team_id": s.teams["th"]["id"], "limit": 100, "offset": 0}
        )
    )
    assert meta["total_count"] == 1
    assert s.refresh_team("th")["version"] == 3


# ---------------------------------------------------------------------------
def test_registering_exactly_on_the_close_instant_lands_outside_the_window(api):
    """The window is half-open at the top, so the close instant is already outside.

    PRD 3.4: "The current instant must lie at or after `registration_opens_at` and
    strictly before `registration_closes_at`, and a request landing outside that
    half-open window is refused with `ERR_OUTSIDE_REGISTRATION_WINDOW`."

    Design: Corner/validations/register_exactly_at_the_close_instant_returns_422_outside_registration_window
    """
    s = _open_league_with_one_team(
        api,
        registration_closes_at="2026-08-10T00:00:00Z",
        roster_lock_at="2026-08-10T00:00:00Z",
        season_end_at="2026-09-30T00:00:00Z",
    )
    s.add_player("ph2", level=4.0, full_name="Ned Netcord")
    s.fill_roster("th", ["ph1", "ph2"])
    s.set_clock("2026-08-10T00:00:00Z")

    response = api.register_team(s.teams["th"]["id"], s.captain_headers("th"))
    validate_error(response, ERR_OUTSIDE_REGISTRATION_WINDOW, 422)
    reported = response.json()["data"]["error_id"]
    assert reported != ERR_INVALID_STATE
    assert reported != ERR_LEAGUE_PHASE_FORBIDS_ROSTER_CHANGE

    team = s.refresh_team("th")
    assert team["status"] == TEAM_DRAFT
    assert team["active_roster_size"] == 2
    assert s.refresh_spot("ph1")["status"] == SPOT_ACTIVE

    league = s.refresh_league()
    assert league["status"] == LEAGUE_REGISTRATION_OPEN
    assert league["registered_team_count"] == 0


# ---------------------------------------------------------------------------
def _played_match_with_no_card_yet(api, clock):
    """M1 is PLAYED with nothing reported, and the clock reads ``clock``."""
    s = six_a_side_league(api)
    s.create_match("m1", "th", "ta")
    s.schedule_match("m1", "2026-08-15T18:00:00Z", 3)
    s.confirm_match("m1")
    s.set_clock("2026-08-15T21:00:00Z")
    s.mark_played("m1")
    s.set_clock(clock)
    return s


def test_a_scorecard_landing_on_the_deadline_instant_is_still_accepted(api):
    """21:00 plus 48 hours is the last admissible instant, and it is inclusive.

    PRD 3.6: "A submission landing exactly on that boundary instant is still
    accepted; anything later is refused with `ERR_SCORECARD_WINDOW_EXPIRED`."

    Design: Corner/validations/scorecard_submitted_exactly_on_the_window_boundary_is_accepted
    """
    s = _played_match_with_no_card_yet(api, "2026-08-17T21:00:00Z")
    card = get_success_data(
        api.create_scorecard(
            f.scorecard_payload(s.matches["m1"]["id"], standard_three_lines(s)),
            s.captain_headers("th"),
        ),
        201,
    )
    assert card["status"] == SCORECARD_SUBMITTED
    assert card["submitted_by_captain_player_id"] == s.player_id("ph1")
    assert card["submitted_by_team_id"] == s.teams["th"]["id"]
    assert card["amendment_count"] == 0
    assert card["verified_at"] is None
    assert is_iso8601_timestamp(card["created_at"])
    assert card["created_at"].startswith("2026-08-17T21:00:00")

    match = s.refresh_match("m1")
    assert match["result_status"] == RESULT_REPORTED
    assert match["schedule_status"] == SCHED_PLAYED


def test_one_second_past_the_deadline_the_same_card_is_refused(api):
    """The temporal code answers while both status dimensions are still legal.

    PRD 3.6: "Temporally, the submission must land while the current instant is at
    or before the match's `scheduled_end_at` advanced by the section's
    `scorecard_submission_window_hours` - two days by default."

    Design: Corner/validations/scorecard_submitted_one_second_late_returns_422_scorecard_window_expired
    """
    s = _played_match_with_no_card_yet(api, "2026-08-17T21:00:01Z")
    response = api.create_scorecard(
        f.scorecard_payload(s.matches["m1"]["id"], standard_three_lines(s)),
        s.captain_headers("th"),
    )
    validate_error(response, ERR_SCORECARD_WINDOW_EXPIRED, 422)
    reported = response.json()["data"]["error_id"]
    assert reported != ERR_MATCH_SCHEDULE_STATE_INVALID
    assert reported != ERR_MATCH_RESULT_STATE_INVALID

    _cards, meta = validate_paginated(
        api.list_scorecards(
            SECTION_ADMIN,
            {"match_id": s.matches["m1"]["id"], "limit": 100, "offset": 0},
        )
    )
    assert meta["total_count"] == 0

    match = s.refresh_match("m1")
    assert match["result_status"] == RESULT_PENDING
    assert match["schedule_status"] == SCHED_PLAYED


# ---------------------------------------------------------------------------
def test_the_roster_cap_counts_pending_and_active_spots_together(api):
    """One activated and one still-pending spot already fill a cap of two.

    PRD 3.3: "And the team may not exceed its league's `max_roster_size`, counting
    spots in `PENDING` and `ACTIVE` together; an add that would push the combined
    count past that maximum is refused with `ERR_ROSTER_SIZE_EXCEEDED`, and the
    same cap is re-checked at activation."

    Design: Corner/validations/third_roster_add_counting_one_active_and_one_pending_returns_409_roster_size_exceeded
    """
    s = _open_league_with_one_team(api, max_roster_size=2)
    s.add_player("ph2", level=4.0, full_name="Ned Netcord")
    s.add_player("ph3", level=4.0, full_name="Sam Slice")
    s.add_spot("th", "ph1")
    s.activate_spot("th", "ph1")
    s.add_spot("th", "ph2")
    live_version = s.team_version("th")

    response = api.create_roster_spot(
        f.roster_spot_payload(
            s.teams["th"]["id"], s.player_id("ph3"), live_version
        ),
        s.captain_headers("th"),
    )
    validate_error(response, ERR_ROSTER_SIZE_EXCEEDED, 409)
    # The declared version is the live one, so the OCC check cannot be the cause.
    assert response.json()["data"]["error_id"] != ERR_STALE_TEAM_VERSION

    _spots, meta = validate_paginated(
        api.list_roster_spots(
            SECTION_ADMIN, {"team_id": s.teams["th"]["id"], "limit": 100, "offset": 0}
        )
    )
    assert meta["total_count"] == 2

    _rejected, rejected_meta = validate_paginated(
        api.list_roster_spots(
            SECTION_ADMIN,
            {
                "team_id": s.teams["th"]["id"],
                "player_id": s.player_id("ph3"),
                "limit": 100,
                "offset": 0,
            },
        )
    )
    assert rejected_meta["total_count"] == 0

    team = s.refresh_team("th")
    assert team["active_roster_size"] == 1
    assert team["version"] == live_version
    assert s.refresh_spot("ph2")["status"] == SPOT_PENDING


# ---------------------------------------------------------------------------
def test_a_computer_rated_record_no_longer_admits_a_self_rating(api):
    """Admissibility of the same payload shape turns on the target's provenance.

    PRD 3.2: "Once a player has become `COMPUTER_RATED`, `APPEAL_GRANTED` or
    `COMMITTEE_ASSIGNED`, a self-rating attempt is refused with
    `ERR_SELF_RATING_LOCKED`; from that point only a coordinator-sourced computer
    rating may overwrite the level."

    Design: Corner/validations/self_rating_a_computer_rated_player_returns_422_self_rating_locked
    """
    s = _open_league_with_one_team(api)
    player_id = s.player_id("ph1")
    assert s.refresh_player("ph1")["rating_type"] == RATING_COMPUTER_RATED

    validate_error(
        api.assign_rating(
            player_id,
            f.rating_payload(4.5, RATING_SOURCE_SELF),
            make_player_headers(player_id),
        ),
        ERR_SELF_RATING_LOCKED,
        422,
    )

    unchanged = s.refresh_player("ph1")
    assert unchanged["rating_type"] == RATING_COMPUTER_RATED
    assert unchanged["rating_level"] == 4.0
    assert unchanged["self_rated_level"] is None

    # The block is conditional on the source, not on the endpoint.
    overwritten = get_success_data(
        api.assign_rating(player_id, f.rating_payload(4.5), LEAGUE_COORDINATOR)
    )
    assert overwritten["rating_level"] == 4.5
    assert overwritten["rating_type"] == RATING_COMPUTER_RATED
    assert overwritten["self_rated_level"] is None


# ---------------------------------------------------------------------------
def test_an_underage_and_under_rated_activation_reports_the_age_failure(api):
    """Two adjacent activation gates fail together and rank 35 answers.

    PRD 2.9: "it reports the failure with the **lowest priority number** in the
    ordering below, and the priority ordering is a fixed part of the contract."

    Design: Corner/validations/underage_and_below_band_activation_returns_the_age_error_not_the_rating_error
    """
    s = _open_league_with_one_team(api)
    # League age 2026 - 2010 is 16, short of the 18 the age group demands, and the
    # 2.5 rating sits below the 3.0 floor of a 4.0 league's band.
    s.add_player("pz1", level=2.5, birth_year=2010, full_name="Zane Junior")
    s.add_spot("th", "pz1")

    response = api.activate_roster_spot(
        s.spots["pz1"]["id"], s.captain_headers("th")
    )
    validate_error(response, ERR_AGE_GROUP_NOT_MET, 422)
    assert response.json()["data"]["error_id"] != ERR_RATING_LEVEL_EXCEEDS_LEAGUE

    spot = s.refresh_spot("pz1")
    assert spot["status"] == SPOT_PENDING
    assert spot["level_at_add"] is None
    assert s.refresh_team("th")["active_roster_size"] == 0


# ---------------------------------------------------------------------------
def test_start_play_is_refused_when_only_one_team_is_still_compliant(api):
    """The quota is re-derived through player, spot and team, not read off a flag.

    PRD 3.4: "The precondition is that at least two teams of the league are
    simultaneously at `ROSTER_LOCKED` and have `roster_compliant` true; if fewer
    than two teams satisfy both, the request is refused with
    `ERR_ROSTER_QUOTA_NOT_MET`."

    Design: Corner/validations/start_play_with_only_one_compliant_team_returns_409_roster_quota_not_met
    """
    s = two_team_league(
        api,
        roster_size=2,
        start=False,
        section_kwargs={
            "min_matches_for_playoff_eligibility": 1,
            "strike_limit": 3,
            "disqualification_strike_limit": 6,
        },
    )
    s.set_clock("2026-08-08T00:00:00Z")
    s.lock_rosters()
    get_success_data(
        api.create_strike(
            f.strike_payload(
                s.player_id("pa2"),
                STRIKE_SCORECARD_FALSIFICATION,
                reason="Falsified line scores on a prior scorecard",
            ),
            LEAGUE_COORDINATOR,
        ),
        201,
    )

    response = api.start_play(s.league["id"], LEAGUE_COORDINATOR)
    validate_error(response, ERR_ROSTER_QUOTA_NOT_MET, 409)
    # ROSTERS_LOCKED is the only admissible from-state, so the state check passed.
    assert response.json()["data"]["error_id"] != ERR_INVALID_STATE

    league = s.refresh_league()
    assert league["status"] == LEAGUE_ROSTERS_LOCKED
    assert league["noncompliant_team_count"] == 1

    compliant = s.refresh_team("th")
    assert compliant["status"] == TEAM_ROSTER_LOCKED
    assert compliant["roster_compliant"] is True

    stranded = s.refresh_team("ta")
    assert stranded["status"] == TEAM_ROSTER_LOCKED
    assert stranded["active_roster_size"] == 1
    assert stranded["roster_compliant"] is False

    suspended = s.refresh_player("pa2")
    assert suspended["status"] == PLAYER_STRIKE_SUSPENDED
    assert suspended["strike_count"] == 3
