"""Fines, penalty points, the posture gate, and the cascades they drive.

Covers difficulty queue: non_linear_state_machine (posture OPEN→RESTRICTED→OPEN cycle),
transitive_cascade (fine assess → points → posture), boundary_precision_check (penalty
threshold ≥ flips at exactly threshold), cross_entity_state_dependency (waive needs
posture OPEN), compensating_invariant (assess then waive conserves points); and corner
consistency cases.
"""
from test_helpers import (
    validate_success, validate_error,
    setup_team_with_signed_player, setup_restricted_team,
    assess_fine, team_version,
    make_team_gm_headers, TEST_USERS,
)

COMMISH = TEST_USERS["commissioner_headers"]


def test_fine_assess_flips_posture_to_restricted(api):
    """PRD §3.8: "A team's posture is OPEN normally and flips to RESTRICTED the moment
    its accumulated penalty_points, after the assessing fine is applied, reaches or
    exceeds the season's penalty_threshold".

    Design: Difficulty/transitive_cascade/fine_assess_cascade_points_then_posture_depth3
    """
    season, team, player, contract = setup_team_with_signed_player(
        season_overrides={"penalty_threshold": 3})
    assess_fine(team["id"], player["id"], penalty_points=4)
    t = validate_success(api.get_team(team["id"], COMMISH), 200)
    assert t["penalty_points"] == 4
    assert t["posture"] == "RESTRICTED"


def test_fine_assess_accumulates_penalty_points(api):
    """PRD §3.8: "On assessment, the fine's penalty_points are added to the team's
    cumulative penalty_points and the team's version is incremented by 1."

    Design: Difficulty/transitive_cascade/fine_assess_cascade_points_then_posture_depth3
    """
    season, team, player, contract = setup_team_with_signed_player(
        season_overrides={"penalty_threshold": 3})
    assess_fine(team["id"], player["id"], penalty_points=4)
    t = validate_success(api.get_team(team["id"], COMMISH), 200)
    assert t["penalty_points"] == 4


def test_posture_cycle_restricted_then_open_after_waive(api):
    """PRD §3.8: "If this reversal drops the team's penalty_points below the season's
    penalty_threshold while the team is RESTRICTED, the team's posture returns to OPEN,
    lifting the lockout".

    Design: Difficulty/non_linear_state_machine/team_posture_cycle_open_restricted_open
    """
    season, team, player, contract, fine = setup_restricted_team(threshold=3, fine_points=3)
    before = validate_success(api.get_team(team["id"], COMMISH), 200)
    assert before["posture"] == "RESTRICTED"
    validate_success(api.waive_fine(fine["id"], COMMISH), 200)
    after = validate_success(api.get_team(team["id"], COMMISH), 200)
    assert after["posture"] == "OPEN"
    assert after["penalty_points"] == 0


def test_fine_waive_reverses_points(api):
    """PRD §3.8: "On a waive, the fine's penalty_points are subtracted back from the
    team's cumulative penalty_points, and both the fine's version and the team's version
    are incremented by 1."

    Design: Difficulty/non_linear_state_machine/team_posture_cycle_open_restricted_open
    """
    season, team, player, contract, fine = setup_restricted_team(threshold=3, fine_points=3)
    validate_success(api.waive_fine(fine["id"], COMMISH), 200)
    after = validate_success(api.get_team(team["id"], COMMISH), 200)
    assert after["penalty_points"] == 0


def test_penalty_below_threshold_stays_open(api):
    """PRD §3.8: "A team's posture is OPEN normally and flips to RESTRICTED the moment
    its accumulated penalty_points, after the assessing fine is applied, reaches or
    exceeds the season's penalty_threshold".

    With threshold 3, two points leaves the team OPEN.

    Design: Difficulty/boundary_precision_check/penalty_threshold_ge_flips_posture_at_exactly_threshold
    """
    season, team, player, contract = setup_team_with_signed_player(
        season_overrides={"penalty_threshold": 3})
    assess_fine(team["id"], player["id"], penalty_points=2)
    t = validate_success(api.get_team(team["id"], COMMISH), 200)
    assert t["posture"] == "OPEN"


def test_penalty_at_exactly_threshold_flips_restricted(api):
    """PRD §3.8: "A team's posture is OPEN normally and flips to RESTRICTED the moment
    its accumulated penalty_points, after the assessing fine is applied, reaches or
    exceeds the season's penalty_threshold".

    With threshold 3, accumulating exactly 3 points (2 then 1) flips RESTRICTED.

    Design: Difficulty/boundary_precision_check/penalty_threshold_ge_flips_posture_at_exactly_threshold
    """
    season, team, player, contract = setup_team_with_signed_player(
        season_overrides={"penalty_threshold": 3})
    assess_fine(team["id"], player["id"], penalty_points=2)
    mid = validate_success(api.get_team(team["id"], COMMISH), 200)
    assert mid["posture"] == "OPEN"
    assess_fine(team["id"], player["id"], penalty_points=1)
    t = validate_success(api.get_team(team["id"], COMMISH), 200)
    assert t["posture"] == "RESTRICTED"
    assert t["penalty_points"] == 3


def test_waive_contract_blocked_when_team_restricted(api):
    """PRD §3.8: "A RESTRICTED posture is a lockout: it blocks that team from accepting
    trades, waiving contracts, and promoting contracts — the three roster mutations
    guarded by the posture gate — each rejected with ERR_TEAM_RESTRICTED (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/contract_waive_requires_team_posture_open
    """
    season, team, player, contract, fine = setup_restricted_team(threshold=3, fine_points=3)
    t_v = team_version(team["id"])
    res = api.waive_contract(contract["id"], {"expected_team_version": t_v},
                             make_team_gm_headers(team["id"]))
    validate_error(res, "ERR_TEAM_RESTRICTED")


def test_restricted_posture_blocks_waive_specifically(api):
    """PRD §3.8: "A RESTRICTED posture is a lockout: it blocks that team from accepting
    trades, waiving contracts, and promoting contracts ... each rejected with
    ERR_TEAM_RESTRICTED (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/contract_waive_requires_team_posture_open
    """
    season, team, player, contract, fine = setup_restricted_team(threshold=3, fine_points=5)
    t_v = team_version(team["id"])
    res = api.waive_contract(contract["id"], {"expected_team_version": t_v},
                             make_team_gm_headers(team["id"]))
    validate_error(res, "ERR_TEAM_RESTRICTED")
    c = validate_success(api.get_contract(contract["id"], COMMISH), 200)
    assert c["status"] == "ACTIVE"


def test_assess_then_waive_conserves_penalty_points(api):
    """PRD §3.8: "On a waive, the fine's penalty_points are subtracted back from the
    team's cumulative penalty_points".

    Assess +2 then waive −2 returns penalty_points to 0.

    Design: Difficulty/compensating_invariant/fine_assess_then_waive_conserves_penalty_points
    """
    season, team, player, contract = setup_team_with_signed_player(
        season_overrides={"penalty_threshold": 3})
    fine = assess_fine(team["id"], player["id"], penalty_points=2)
    validate_success(api.waive_fine(fine["id"], COMMISH), 200)
    t = validate_success(api.get_team(team["id"], COMMISH), 200)
    assert t["penalty_points"] == 0
    assert t["posture"] == "OPEN"


def test_assess_then_waive_posture_stays_open(api):
    """PRD §3.8: "On a waive, the fine's penalty_points are subtracted back from the
    team's cumulative penalty_points".

    Design: Difficulty/compensating_invariant/fine_assess_then_waive_conserves_penalty_points
    """
    season, team, player, contract = setup_team_with_signed_player(
        season_overrides={"penalty_threshold": 3})
    fine = assess_fine(team["id"], player["id"], penalty_points=2)
    validate_success(api.waive_fine(fine["id"], COMMISH), 200)
    t = validate_success(api.get_team(team["id"], COMMISH), 200)
    assert t["posture"] == "OPEN"


def test_fine_assess_visible_immediately(api):
    """PRD §2.8: "The league runs on immediate consistency: every cap recomputation and
    every cross-entity cascade triggered by a request completes inside that same request
    before the response is returned."

    Design: Corner/consistency_model/fine_assess_visible_in_same_request_response
    """
    season, team, player, contract = setup_team_with_signed_player(
        season_overrides={"penalty_threshold": 10})
    assess_fine(team["id"], player["id"], penalty_points=2)
    t = validate_success(api.get_team(team["id"], COMMISH), 200)
    assert t["penalty_points"] == 2
    assert t["posture"] == "OPEN"
