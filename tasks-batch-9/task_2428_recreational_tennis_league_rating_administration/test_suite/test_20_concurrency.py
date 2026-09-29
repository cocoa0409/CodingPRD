"""Optimistic concurrency on the two guarded writes, and version-bump discipline."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.assertions import assert_instant_equals
from test_helpers.api_errors import (
    ERR_DUPLICATE_ROSTER_SPOT,
    ERR_FACILITY_COURTS_EXCEEDED,
    ERR_MATCH_SCHEDULE_STATE_INVALID,
    ERR_MISSING_EXPECTED_VERSION,
    ERR_ROSTER_SIZE_EXCEEDED,
    ERR_STALE_MATCH_VERSION,
    ERR_STALE_TEAM_VERSION,
    ERR_VALIDATION,
)
from test_helpers.constants import (
    CLOCK_DEFAULT,
    SCHED_SCHEDULED,
    SPOT_ACTIVE,
    SPOT_PENDING,
    SPOT_REMOVED,
    TIER_SECTION,
)
from test_helpers.fixtures import Scenario, two_team_league
from test_helpers.test_users import LEAGUE_COORDINATOR, SECTION_ADMIN


def _draft_team_with_one_active_spot(api):
    """Team A holds one ACTIVE spot; pa2 is rated and holds no spot anywhere."""
    s = Scenario(api)
    s.set_clock(CLOCK_DEFAULT)
    s.create_section()
    s.create_facility()
    s.create_league(tier=TIER_SECTION, ntrp_level=4.0, min_active_roster_size=2)
    s.open_registration()
    s.add_player("pa1", level=4.0, full_name="Adam Ace")
    s.add_player("pa2", level=4.0, full_name="Bea Backhand")
    s.create_team("ta", "pa1", "Ace Attack")
    creation_version = s.teams["ta"]["version"]
    s.add_spot("ta", "pa1")
    s.activate_spot("ta", "pa1")
    return s, creation_version


def test_a_roster_add_replaying_the_creation_version_of_the_team_is_rejected(api):
    """Two accepted child writes have moved the parent since the client last read it.

    PRD 2.7: "A request whose `expected_team_version` does not equal the target
    team's current `version` is therefore deciding against a roster that no longer
    exists, and is rejected with `ERR_STALE_TEAM_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/roster_spot_write_with_the_pre_activation_team_version_returns_412_stale_team_version
    """
    s, creation_version = _draft_team_with_one_active_spot(api)
    team_id = s.teams["ta"]["id"]

    response = api.create_roster_spot(
        f.roster_spot_payload(team_id, s.player_id("pa2"), creation_version),
        s.captain_headers("ta"),
    )
    validate_error(response, ERR_STALE_TEAM_VERSION, 412)
    reported = response.json()["data"]["error_id"]
    # pa2 holds no spot in this league.
    assert reported != ERR_DUPLICATE_ROSTER_SPOT
    # And one spot is a long way short of the league's maximum roster size.
    assert reported != ERR_ROSTER_SIZE_EXCEEDED

    _spots, meta = validate_paginated(
        api.list_roster_spots(
            SECTION_ADMIN, {"team_id": team_id, "limit": 100, "offset": 0}
        )
    )
    assert meta["total_count"] == 1

    team = get_success_data(api.get_team(team_id, SECTION_ADMIN))
    assert team["version"] == creation_version + 2
    assert team["active_roster_size"] == 1

    accepted = get_success_data(
        api.create_roster_spot(
            f.roster_spot_payload(team_id, s.player_id("pa2"), team["version"]),
            s.captain_headers("ta"),
        ),
        201,
    )
    assert accepted["status"] == SPOT_PENDING
    assert accepted["version"] == 1


def test_a_roster_add_that_omits_the_version_field_is_malformed_not_stale(api):
    """Absence and inequality are different failures, and absence is checked first.

    PRD 2.7: "If either of those two operations omits its version field entirely, the
    request is refused earlier, with `ERR_MISSING_EXPECTED_VERSION` (HTTP 400) - a
    missing declaration is a malformed request, not a stale one."

    Design: Corner/cross_cutting_complexity_layers/roster_spot_write_omitting_the_version_field_returns_400_missing_expected_version
    """
    s, creation_version = _draft_team_with_one_active_spot(api)
    team_id = s.teams["ta"]["id"]

    response = api.create_roster_spot(
        {"team_id": team_id, "player_id": s.player_id("pa2")},
        s.captain_headers("ta"),
    )
    validate_error(response, ERR_MISSING_EXPECTED_VERSION, 400)
    reported = response.json()["data"]["error_id"]
    assert reported != ERR_STALE_TEAM_VERSION
    assert response.status_code != 412
    # The concurrency rules own this field, not the generic body validation.
    assert reported != ERR_VALIDATION

    _spots, meta = validate_paginated(
        api.list_roster_spots(
            SECTION_ADMIN, {"team_id": team_id, "limit": 100, "offset": 0}
        )
    )
    assert meta["total_count"] == 1
    team = get_success_data(api.get_team(team_id, SECTION_ADMIN))
    assert team["version"] == creation_version + 2
    assert team["active_roster_size"] == 1


def test_the_team_version_moves_on_every_accepted_write_and_on_no_read(api):
    """Child endpoints mutate the aggregate, so the parent counter must follow them.

    PRD 3.3: "The new spot arrives at `status` `PENDING`, with `level_at_add` null,
    `verified_match_count` 0 and `playoff_eligible` false, and the parent team's
    `version` increases by 1 as a consequence."

    Design: Corner/cross_cutting_complexity_layers/every_accepted_write_advances_the_team_version_while_reads_leave_it_alone
    """
    s, creation_version = _draft_team_with_one_active_spot(api)
    team_id = s.teams["ta"]["id"]
    live = get_success_data(api.get_team(team_id, SECTION_ADMIN))["version"]
    assert live == creation_version + 2

    staged = get_success_data(
        api.create_roster_spot(
            f.roster_spot_payload(team_id, s.player_id("pa2"), live),
            s.captain_headers("ta"),
        ),
        201,
    )
    assert staged["status"] == SPOT_PENDING
    assert staged["version"] == 1

    after_add = get_success_data(api.get_team(team_id, SECTION_ADMIN))
    assert after_add["version"] == live + 1
    # A PENDING spot moves the version without counting toward the active roster.
    assert after_add["active_roster_size"] == 1

    for _ in range(3):
        assert (
            get_success_data(api.get_team(team_id, SECTION_ADMIN))["version"]
            == live + 1
        )
    validate_paginated(
        api.list_roster_spots(
            SECTION_ADMIN, {"team_id": team_id, "limit": 100, "offset": 0}
        )
    )
    assert (
        get_success_data(api.get_team(team_id, SECTION_ADMIN))["version"] == live + 1
    )

    activated = get_success_data(
        api.activate_roster_spot(staged["id"], s.captain_headers("ta"))
    )
    assert activated["status"] == SPOT_ACTIVE
    after_activation = get_success_data(api.get_team(team_id, SECTION_ADMIN))
    assert after_activation["version"] == live + 2
    assert after_activation["active_roster_size"] == 2
    assert after_activation["roster_compliant"] is True

    removal = api.delete_roster_spot(staged["id"], s.captain_headers("ta"))
    assert removal.status_code == 204
    after_removal = get_success_data(api.get_team(team_id, SECTION_ADMIN))
    assert after_removal["version"] == live + 3
    assert after_removal["active_roster_size"] == 1
    assert get_success_data(
        api.get_roster_spot(staged["id"], SECTION_ADMIN)
    )["status"] == SPOT_REMOVED


# ---------------------------------------------------------------------------
def test_a_reschedule_replaying_the_fixture_creation_version_is_rejected(api):
    """The slot write is a self-loop, so only the declaration can catch a lost update.

    PRD 2.7: "A request whose `expected_match_version` does not equal the match's
    current `version` is rejected with `ERR_STALE_MATCH_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/match_reschedule_with_the_creation_version_returns_412_stale_match_version
    """
    s = two_team_league(api, roster_size=2)
    s.create_match("m1", "th", "ta")
    creation_version = s.matches["m1"]["version"]
    s.schedule_match("m1", "2026-08-15T18:00:00Z", 3)
    match_id = s.matches["m1"]["id"]

    response = api.schedule_match(
        match_id,
        f.schedule_payload(
            s.facility["id"], "2026-08-16T18:00:00Z", creation_version, 3
        ),
        LEAGUE_COORDINATOR,
    )
    validate_error(response, ERR_STALE_MATCH_VERSION, 412)
    reported = response.json()["data"]["error_id"]
    # SCHEDULED to SCHEDULED is a permitted self-loop.
    assert reported != ERR_MATCH_SCHEDULE_STATE_INVALID
    # And the slot being superseded is this same match's, so no court is contested.
    assert reported != ERR_FACILITY_COURTS_EXCEEDED

    untouched = s.refresh_match("m1")
    assert_instant_equals(untouched["scheduled_start_at"], "2026-08-15T18:00:00Z")
    assert untouched["schedule_status"] == SCHED_SCHEDULED
    assert untouched["version"] == creation_version + 1

    moved = get_success_data(
        api.schedule_match(
            match_id,
            f.schedule_payload(
                s.facility["id"], "2026-08-16T18:00:00Z", creation_version + 1, 3
            ),
            LEAGUE_COORDINATOR,
        )
    )
    assert_instant_equals(moved["scheduled_start_at"], "2026-08-16T18:00:00Z")
    assert_instant_equals(moved["scheduled_end_at"], "2026-08-16T21:00:00Z")
    assert moved["schedule_status"] == SCHED_SCHEDULED
    assert moved["version"] == creation_version + 2
