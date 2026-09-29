"""The weighted ledger against its two thresholds, and the compensating rescission."""

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from test_helpers import factories as f
from test_helpers.constants import (
    INELIGIBLE_PLAYER_SUSPENDED,
    PLAYER_ACTIVE,
    PLAYER_DISQUALIFIED,
    PLAYER_STRIKE_SUSPENDED,
    SPOT_ACTIVE,
    SPOT_INELIGIBLE,
    STRIKE_ACTIVE,
    STRIKE_INELIGIBLE_LINEUP,
    STRIKE_NO_SHOW_DEFAULT,
    STRIKE_RESCINDED,
    STRIKE_SCORECARD_FALSIFICATION,
)
from test_helpers.fixtures import two_team_league
from test_helpers.test_users import LEAGUE_COORDINATOR, SECTION_ADMIN


def _two_compliant_registered_teams(api):
    """Each squad holds exactly two ACTIVE spots, which is the compliance floor."""
    return two_team_league(api, roster_size=2, with_committee=True, start=False)


def _strike(api, s, player_key, kind, reason):
    return get_success_data(
        api.create_strike(
            f.strike_payload(s.player_id(player_key), kind, reason=reason),
            LEAGUE_COORDINATOR,
        ),
        201,
    )


def _only_spot_of(api, s, player_key):
    spots, meta = validate_paginated(
        api.list_roster_spots(
            SECTION_ADMIN,
            {"player_id": s.player_id(player_key), "limit": 100, "offset": 0},
        )
    )
    assert meta["total_count"] == 1
    return spots[0]


def test_two_light_strikes_summing_to_three_suspend_at_the_inclusive_boundary(api):
    """Neither strike is heavy; the weighted sum reaches the limit exactly.

    PRD 3.7: "Immediately after each recompute, three status thresholds are evaluated
    against the section's two limits, and they are all inclusive comparisons."

    Design: Corner/cross_cutting_complexity_layers/two_light_strikes_summing_to_exactly_three_suspend_the_player_at_the_boundary
    """
    s = _two_compliant_registered_teams(api)
    lineup = _strike(
        api, s, "ph2", STRIKE_INELIGIBLE_LINEUP, "Fielded on a line without a spot"
    )
    assert lineup["weight"] == 2

    before = s.refresh_player("ph2")
    assert before["strike_count"] == 2
    assert before["status"] == PLAYER_ACTIVE
    assert _only_spot_of(api, s, "ph2")["status"] == SPOT_ACTIVE
    assert s.refresh_team("th")["roster_compliant"] is True

    crossing = _strike(
        api, s, "ph2", STRIKE_NO_SHOW_DEFAULT, "Did not appear for a scheduled line"
    )
    assert crossing["weight"] == 1

    struck = s.refresh_player("ph2")
    assert struck["strike_count"] == 3
    assert struck["status"] == PLAYER_STRIKE_SUSPENDED

    spot = _only_spot_of(api, s, "ph2")
    assert spot["status"] == SPOT_INELIGIBLE
    assert spot["ineligible_reason"] == INELIGIBLE_PLAYER_SUSPENDED
    assert spot["source_strike_id"] == crossing["id"]

    team = s.refresh_team("th")
    assert team["active_roster_size"] == 1
    assert team["roster_compliant"] is False

    ledger, ledger_meta = validate_paginated(
        api.list_strikes(
            SECTION_ADMIN, {"player_id": s.player_id("ph2"), "limit": 100, "offset": 0}
        )
    )
    assert ledger_meta["total_count"] == 2
    for row in ledger:
        assert row["status"] == STRIKE_ACTIVE


def test_a_ledger_of_five_holds_the_band_between_the_two_limits(api):
    """Past the suspension limit and short of the disqualification limit.

    PRD 3.7: "Otherwise, if `strike_count` sits at or above the section's
    `strike_limit` but below the disqualification limit, the player's `status` becomes
    `STRIKE_SUSPENDED`."

    Design: Corner/cross_cutting_complexity_layers/a_ledger_of_five_stays_suspended_because_the_disqualification_limit_is_six
    """
    s = _two_compliant_registered_teams(api)
    falsification = _strike(
        api, s, "ph2", STRIKE_SCORECARD_FALSIFICATION, "Falsified a set score"
    )
    assert s.refresh_player("ph2")["status"] == PLAYER_STRIKE_SUSPENDED

    second = _strike(
        api, s, "ph2", STRIKE_INELIGIBLE_LINEUP, "Fielded without an active spot"
    )
    assert second["weight"] == 2

    struck = s.refresh_player("ph2")
    assert struck["strike_count"] == 5
    assert struck["status"] == PLAYER_STRIKE_SUSPENDED
    assert struck["status"] != PLAYER_DISQUALIFIED

    # The spot keeps the strike that demoted it, not the latest one.
    spot = _only_spot_of(api, s, "ph2")
    assert spot["source_strike_id"] == falsification["id"]
    assert spot["source_strike_id"] != second["id"]

    # PRD 3.7 moves a team's version when a strike crosses a threshold and demotes
    # a spot; this second strike crosses nothing, so no team-version claim is made.
    team = s.refresh_team("th")
    assert team["active_roster_size"] == 1
    assert team["roster_compliant"] is False

    _strike(api, s, "ph2", STRIKE_NO_SHOW_DEFAULT, "Missed a rescheduled line")
    at_the_limit = s.refresh_player("ph2")
    assert at_the_limit["strike_count"] == 6
    assert at_the_limit["status"] == PLAYER_DISQUALIFIED

    # Disqualification is terminal, so a further strike changes no status.
    _strike(api, s, "ph2", STRIKE_NO_SHOW_DEFAULT, "Missed another line")
    beyond = s.refresh_player("ph2")
    assert beyond["strike_count"] == 7
    assert beyond["status"] == PLAYER_DISQUALIFIED


def test_rescinding_the_crossing_strike_unwinds_the_whole_cascade(api):
    """The compensating action returns the ledger, the spot and the team together.

    PRD 3.7: "The roster restoration is deliberately **surgical**: only those roster
    spots at `INELIGIBLE` whose `ineligible_reason` is `PLAYER_SUSPENDED` *and* whose
    `source_strike_id` names the strike just rescinded return to `ACTIVE`, and on
    doing so both `ineligible_reason` and `source_strike_id` are cleared to null."

    Design: Corner/cross_cutting_complexity_layers/rescinding_the_crossing_strike_restores_the_ledger_the_spot_and_the_team
    """
    s = _two_compliant_registered_teams(api)
    pre_issue_team = s.refresh_team("th")
    assert pre_issue_team["active_roster_size"] == 2
    assert pre_issue_team["roster_compliant"] is True
    pre_issue_eligible = pre_issue_team["playoff_eligible_roster_size"]

    strike = _strike(
        api, s, "ph2", STRIKE_SCORECARD_FALSIFICATION, "Falsified a set score"
    )
    assert s.refresh_player("ph2")["status"] == PLAYER_STRIKE_SUSPENDED
    assert s.refresh_team("th")["roster_compliant"] is False

    rescinded = get_success_data(
        api.rescind_strike(
            strike["id"],
            {"rescinded_reason": "The finding was withdrawn on review"},
            s.chair_headers(),
        )
    )
    assert rescinded["status"] == STRIKE_RESCINDED
    assert rescinded["weight"] == 3

    restored_player = s.refresh_player("ph2")
    assert restored_player["strike_count"] == 0
    assert restored_player["status"] == PLAYER_ACTIVE

    spot = _only_spot_of(api, s, "ph2")
    assert spot["status"] == SPOT_ACTIVE
    assert spot["ineligible_reason"] is None
    assert spot["source_strike_id"] is None

    team = s.refresh_team("th")
    assert team["active_roster_size"] == 2
    assert team["roster_compliant"] is True
    assert team["playoff_eligible_roster_size"] == pre_issue_eligible

    league = get_success_data(api.get_league(s.league["id"], SECTION_ADMIN))
    assert league["noncompliant_team_count"] == 0

    history, history_meta = validate_paginated(
        api.list_strikes(
            SECTION_ADMIN, {"player_id": s.player_id("ph2"), "limit": 100, "offset": 0}
        )
    )
    assert history_meta["total_count"] == 1
    assert history[0]["id"] == strike["id"]

    _active, active_meta = validate_paginated(
        api.list_strikes(
            SECTION_ADMIN,
            {
                "player_id": s.player_id("ph2"),
                "status": STRIKE_ACTIVE,
                "limit": 100,
                "offset": 0,
            },
        )
    )
    assert active_meta["total_count"] == 0
