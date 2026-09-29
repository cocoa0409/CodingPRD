"""League and team lifecycle edges: initial states, refusals and the lock cascade."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers.api_errors import (
    ERR_INVALID_STATE,
    ERR_LEAGUE_ALREADY_TERMINAL,
    ERR_OUTSIDE_REGISTRATION_WINDOW,
    ERR_ROSTER_QUOTA_NOT_MET,
)
from test_helpers.constants import (
    AGE_18_OVER,
    CLOCK_DEFAULT,
    FORMAT_MENS_DOUBLES,
    LEAGUE_DRAFT,
    LEAGUE_REGISTRATION_OPEN,
    LEAGUE_ROSTERS_LOCKED,
    SPOT_ACTIVE,
    SPOT_PENDING,
    SPOT_REMOVED,
    TEAM_DRAFT,
    TEAM_REGISTERED,
    TEAM_ROSTER_LOCKED,
    TIER_DISTRICT,
    TIER_SECTION,
)
from test_helpers.fixtures import Scenario, six_a_side_league
from test_helpers.test_users import LEAGUE_COORDINATOR, SECTION_ADMIN

CHILD_LEAGUE_KWARGS = {
    "tier": TIER_DISTRICT,
    "ntrp_level": 4.0,
    "age_group": AGE_18_OVER,
    "format": FORMAT_MENS_DOUBLES,
    "lines_per_match": 3,
    "min_active_roster_size": 2,
    "max_teams": 4,
    "registration_opens_at": "2026-08-01T00:00:00Z",
    "registration_closes_at": "2026-08-10T00:00:00Z",
    "roster_lock_at": "2026-08-10T00:00:00Z",
    "season_end_at": "2026-09-30T00:00:00Z",
}


def _draft_child_league(api):
    """A DISTRICT league still at DRAFT under an opened SECTION parent."""
    s = Scenario(api)
    s.set_clock(CLOCK_DEFAULT)
    s.create_section()
    s.create_facility()
    parent = s.create_league(
        tier=TIER_SECTION,
        ntrp_level=4.0,
        registration_closes_at="2026-12-01T00:00:00Z",
        roster_lock_at="2026-12-01T00:00:00Z",
        season_end_at="2026-12-31T00:00:00Z",
    )
    s.open_registration(parent)
    child = s.create_league(**dict(CHILD_LEAGUE_KWARGS, parent_league_id=parent["id"]))
    return s, child


def test_a_league_is_born_at_draft_and_open_registration_is_its_only_first_edge(api):
    """DRAFT at version 1 becomes REGISTRATION_OPEN at version 2 in one call.

    PRD 3.4: "A league walks a seven-value lifecycle: it begins at `DRAFT` and may
    reach `REGISTRATION_OPEN`, `ROSTERS_LOCKED`, `IN_PLAY`, `PLAYOFFS`, and finally
    either `COMPLETED` or `CANCELLED`."

    Design: Corner/state_machines/league_created_in_draft_and_open_registration_moves_to_registration_open
    """
    s, child = _draft_child_league(api)
    before = get_success_data(api.get_league(child["id"], LEAGUE_COORDINATOR))
    assert before["status"] == LEAGUE_DRAFT
    assert before["version"] == 1

    opened = get_success_data(api.open_registration(child["id"], SECTION_ADMIN))
    assert opened["id"] == child["id"]
    assert opened["status"] == LEAGUE_REGISTRATION_OPEN
    assert opened["version"] == 2
    assert opened["registered_team_count"] == 0
    assert opened["noncompliant_team_count"] == 0


def test_opening_registration_a_second_time_is_refused_and_changes_nothing(api):
    """The edge is declared out of DRAFT only, so the replay has no transition.

    PRD 3.4: "Opening registration takes the league from `DRAFT` to
    `REGISTRATION_OPEN` and belongs to the section administrator."

    Design: Corner/state_machines/league_open_registration_twice_returns_invalid_state
    """
    s, child = _draft_child_league(api)
    s.open_registration(child)

    response = api.open_registration(child["id"], SECTION_ADMIN)
    validate_error(response, ERR_INVALID_STATE, 409)
    assert response.json()["data"]["error_id"] != ERR_LEAGUE_ALREADY_TERMINAL

    after = get_success_data(api.get_league(child["id"], LEAGUE_COORDINATOR))
    assert after["status"] == LEAGUE_REGISTRATION_OPEN
    assert after["version"] == 2


def _draft_team_with_one_active_and_one_pending_spot(api):
    """An open DISTRICT league holding a DRAFT team of one ACTIVE, one PENDING spot."""
    s, child = _draft_child_league(api)
    s.open_registration(child)
    s.league = child
    s.add_player("p1", level=4.0, full_name="Adam Ace")
    s.add_player("p2", level=4.0, full_name="Ben Baseline")
    s.create_team("tm", "p1", "Balboa Aces", league=child)
    s.add_spot("tm", "p1")
    s.activate_spot("tm", "p1")
    s.add_spot("tm", "p2")
    return s, child


def test_activating_the_second_spot_lets_the_team_register_and_moves_the_league(api):
    """One call flips the team to REGISTERED and recounts the league in the same breath.

    PRD 3.4: "On success the league recomputes `registered_team_count` and increases
    its own `version` by 1, and the team's `version` increases by 1."

    Design: Corner/state_machines/team_register_with_two_active_spots_moves_to_registered_and_bumps_league_counter
    """
    s, child = _draft_team_with_one_active_and_one_pending_spot(api)
    s.activate_spot("tm", "p2")

    registered = get_success_data(
        api.register_team(s.teams["tm"]["id"], s.captain_headers("tm"))
    )
    assert registered["status"] == TEAM_REGISTERED
    assert registered["active_roster_size"] == 2
    assert registered["roster_compliant"] is True

    league = s.refresh_league(child["id"])
    assert league["registered_team_count"] == 1
    assert league["noncompliant_team_count"] == 0

    _teams, meta = validate_paginated(
        api.list_teams(
            SECTION_ADMIN,
            {
                "league_id": child["id"],
                "status": TEAM_REGISTERED,
                "limit": 100,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 1


def test_a_team_that_never_registered_cannot_withdraw(api):
    """Withdrawal is declared from three states and DRAFT is not one of them.

    PRD 3.4: "A captain may withdraw its own team from `REGISTERED`, from
    `ROSTER_LOCKED` or from `IN_PLAY`, optionally supplying a `reason`, and the
    destination in all three cases is `WITHDRAWN`, which is terminal."

    Design: Corner/state_machines/team_withdraw_from_draft_returns_invalid_state
    """
    s, _child = _draft_team_with_one_active_and_one_pending_spot(api)
    validate_error(
        api.withdraw_team(
            s.teams["tm"]["id"],
            s.captain_headers("tm"),
            {"reason": "Captain changed their mind before registering"},
        ),
        ERR_INVALID_STATE,
        409,
    )

    team = s.refresh_team("tm")
    assert team["status"] == TEAM_DRAFT
    assert team["active_roster_size"] == 1
    assert s.refresh_spot("p1")["status"] == SPOT_ACTIVE
    assert s.refresh_spot("p2")["status"] == SPOT_PENDING


def _two_registered_teams_and_a_stray_pending_spot(api):
    """Two six-player REGISTERED teams; the home side carries a seventh PENDING spot."""
    s = six_a_side_league(api, start=False)
    s.add_player("ph7", level=4.0, full_name="Gus Grip")
    s.add_spot("th", "ph7")
    s.set_clock("2026-08-08T00:00:00Z")
    return s


def test_locking_rosters_walks_the_league_the_teams_and_the_pending_spots(api):
    """Three levels move in one request and the never-activated spot is dropped.

    PRD 3.4: "Every team of the league at `REGISTERED` transitions to
    `ROSTER_LOCKED`. For each of those teams, every roster spot still at `PENDING`
    transitions to `REMOVED` - pending spots that were never activated are simply
    dropped at lock time, and this is the moment where a captain's unfinished
    paperwork stops mattering."

    Design: Corner/state_machines/lock_rosters_cascades_every_registered_team_and_drops_pending_spots
    """
    s = _two_registered_teams_and_a_stray_pending_spot(api)
    locked = get_success_data(api.lock_rosters(s.league["id"], LEAGUE_COORDINATOR))
    assert locked["status"] == LEAGUE_ROSTERS_LOCKED
    assert locked["registered_team_count"] == 2
    assert locked["noncompliant_team_count"] == 0
    assert locked["version"] == 5

    for team_key in ("th", "ta"):
        team = s.refresh_team(team_key)
        assert team["status"] == TEAM_ROSTER_LOCKED
        assert team["active_roster_size"] == 6
        assert team["roster_compliant"] is True

    dropped = s.refresh_spot("ph7")
    assert dropped["status"] == SPOT_REMOVED
    assert dropped["ineligible_reason"] is None
    assert s.refresh_spot("ph1")["status"] == SPOT_ACTIVE


def test_the_lock_leaves_the_six_activated_spots_of_each_team_alone(api):
    """Only the PENDING spot is removed; the ACTIVE six survive untouched.

    PRD 3.4: "Each affected team then recomputes `active_roster_size`,
    `playoff_eligible_roster_size` and `roster_compliant` from the surviving active
    spots, the league recomputes `noncompliant_team_count`, and the league's
    `version` plus each affected team's `version` each increase by 1."

    Design: Corner/state_machines/lock_rosters_cascades_every_registered_team_and_drops_pending_spots
    """
    s = _two_registered_teams_and_a_stray_pending_spot(api)
    s.lock_rosters()
    home_id = s.teams["th"]["id"]

    _removed, removed_meta = validate_paginated(
        api.list_roster_spots(
            SECTION_ADMIN,
            {"team_id": home_id, "status": SPOT_REMOVED, "limit": 100, "offset": 0},
        )
    )
    assert removed_meta["total_count"] == 1

    _active, active_meta = validate_paginated(
        api.list_roster_spots(
            SECTION_ADMIN,
            {"team_id": home_id, "status": SPOT_ACTIVE, "limit": 100, "offset": 0},
        )
    )
    assert active_meta["total_count"] == 6

    _away_pending, away_meta = validate_paginated(
        api.list_roster_spots(
            SECTION_ADMIN,
            {
                "team_id": s.teams["ta"]["id"],
                "status": SPOT_PENDING,
                "limit": 100,
                "offset": 0,
            },
        )
    )
    assert away_meta["total_count"] == 0
