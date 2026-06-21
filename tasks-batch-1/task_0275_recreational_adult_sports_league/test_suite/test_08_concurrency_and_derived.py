"""Optimistic concurrency on the two version-bearing write endpoints, plus
derived-field reconciliation and immediate consistency.

Covers the cross-cutting OCC corners and the free-agent / confirmed-count
derived-field corners.
"""
from test_helpers import (
    validate_success, validate_error,
    make_league_admin_headers, make_team_captain_headers, make_referee_headers,
    ApiErrorId,
)
import test_helpers.fixtures as fx
import test_helpers.factories as F

ADMIN = make_league_admin_headers()


def test_stale_division_version_on_team_register_rejected(api):
    """PRD §2.6: "If `expected_division_version` does not equal the division's current
    `version`, the registration is rejected with `ERR_STALE_VERSION` (HTTP 412),
    forcing the client to re-read the division before it competes for a capacity slot."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_division_version_on_team_register
    """
    base = fx.setup_open_division()
    division = base["division"]
    cap1 = fx.create_player()
    cap2 = fx.create_player()
    stale_v = fx.get_division_version(division["id"])
    # First registration bumps the division version.
    validate_success(
        api.create_team(division["id"], F.create_team_payload(cap1["id"], stale_v, name="OCC First"),
                        make_team_captain_headers(cap1["id"])),
        expected_status=201,
    )
    # Second register reusing the now-stale version -> 412.
    resp = api.create_team(division["id"], F.create_team_payload(cap2["id"], stale_v, name="OCC Second"),
                           make_team_captain_headers(cap2["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_stale_game_version_on_submit_score_rejected(api):
    """PRD §2.6: "If `expected_game_version` does not equal the game's current
    `version`, the submission is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing
    a re-read before the scoreline is overwritten."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_game_version_on_submit_score
    """
    s = fx.setup_in_play_game_pending()
    ref_headers = make_referee_headers(s["referee"]["id"])
    gv = validate_success(api.get_game(s["game"]["id"], ADMIN))["version"]
    # First submit bumps the game version.
    validate_success(api.submit_score(s["game"]["id"], F.submit_score_payload(2, 1, gv), ref_headers))
    # Reusing the pre-bump version -> 412.
    resp = api.submit_score(s["game"]["id"], F.submit_score_payload(3, 0, gv), ref_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_free_agent_flag_reconciles_after_roster_release(api):
    """PRD §3.3: "The `is_free_agent` flag is derived: it is true exactly when the
    player has no `ACTIVE` roster entries, and it is recomputed whenever a roster entry
    is created or released."

    Design: Corner/cross_cutting_complexity_layers/free_agent_invariant_after_roster_release
    """
    base = fx.setup_open_division()
    cap = fx.create_player()
    member = fx.create_player()
    team = fx.register_team(base["division"]["id"], cap["id"])
    entry = validate_success(
        api.add_roster(team["id"], F.roster_add_payload(member["id"]), make_team_captain_headers(cap["id"])),
        expected_status=201,
    )
    after_add = validate_success(api.get_player(member["id"], ADMIN))
    assert after_add["is_free_agent"] is False, "adding to a roster clears free-agent status"

    released = validate_success(
        api.release_roster(team["id"], entry["id"], make_team_captain_headers(cap["id"]))
    )
    assert released["state"] == "RELEASED"
    after_release = validate_success(api.get_player(member["id"], ADMIN))
    assert after_release["is_free_agent"] is True, "releasing the only entry restores free-agent"


def test_confirmed_count_visible_immediately_after_confirm(api):
    """PRD §3.2: "An administrator may confirm a `PENDING` team explicitly, moving it
    to `CONFIRMED` and incrementing the division's recomputed `confirmed_team_count` by
    one."

    Design: Corner/consistency_model/immediate_consistency_confirmed_count_visible_in_response
    """
    base = fx.setup_open_division()
    cap = fx.create_player()
    team = fx.register_team(base["division"]["id"], cap["id"])
    fx.confirm_team(team["id"])
    division = validate_success(api.get_division(base["division"]["id"], ADMIN))
    assert division["confirmed_team_count"] == 1, (
        f"confirmed_team_count must be 1 on the very next read, got {division['confirmed_team_count']}"
    )
