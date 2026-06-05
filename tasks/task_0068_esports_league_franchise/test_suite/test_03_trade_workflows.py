"""Trade negotiation: the PROPOSED fork, acceptance cascade, window/posture gates,
validation ordering, and stale-version rejection.

Covers difficulty queue: non_linear_state_machine (trade fork), cross_entity_state_dependency
(trade needs window open), priority_pair_validation_conflict (window vs restricted,
invalid_state vs window), optimistic_concurrency (stale to_team version); and corner
queue trade/state cases.
"""
from test_helpers import (
    validate_success, validate_error,
    setup_proposed_trade, team_version,
    create_player, sign_contract,
    make_team_gm_headers, TEST_USERS,
)

COMMISH = TEST_USERS["commissioner_headers"]


def test_accept_reassigns_contracts_and_sets_accepted(api):
    """PRD §3.7: "Each contract in contract_ids_out has its team_id reassigned to the
    to_team_id, and each contract in contract_ids_in has its team_id reassigned to the
    from_team_id; the reassigned contracts stay ACTIVE". PRD §3.7: "The trade's status
    becomes ACCEPTED and its version is incremented by 1."

    Design: Difficulty/non_linear_state_machine/trade_branching_fork_accept_vs_reject_divergent_side_effects
    """
    s = setup_proposed_trade(window_open=True)
    g_v = team_version(s["g"]["id"])
    res = api.accept_trade(s["trade"]["id"], {"expected_to_team_version": g_v},
                           make_team_gm_headers(s["g"]["id"]))
    trade = validate_success(res, 200)
    assert trade["status"] == "ACCEPTED"
    c1 = validate_success(api.get_contract(s["c1"]["id"], COMMISH), 200)
    c2 = validate_success(api.get_contract(s["c2"]["id"], COMMISH), 200)
    assert c1["team_id"] == s["g"]["id"]
    assert c2["team_id"] == s["f"]["id"]


def test_reject_does_not_reassign_contracts(api):
    """PRD §3.6: "Rejecting moves the trade from PROPOSED to REJECTED. It requires only
    that the trade is PROPOSED and that the acting GM owns the to_team_id. No contracts
    are reassigned and no payroll changes; the trade's version is incremented by 1."

    Design: Difficulty/non_linear_state_machine/trade_branching_fork_accept_vs_reject_divergent_side_effects
    """
    s = setup_proposed_trade(window_open=True)
    res = api.reject_trade(s["trade"]["id"], make_team_gm_headers(s["g"]["id"]))
    trade = validate_success(res, 200)
    assert trade["status"] == "REJECTED"
    c1 = validate_success(api.get_contract(s["c1"]["id"], COMMISH), 200)
    c2 = validate_success(api.get_contract(s["c2"]["id"], COMMISH), 200)
    assert c1["team_id"] == s["f"]["id"]
    assert c2["team_id"] == s["g"]["id"]


def test_accept_requires_window_open(api):
    """PRD §3.7: "The season's trade_window_state must be OPEN, else
    ERR_TRADE_WINDOW_CLOSED (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/trade_accept_requires_season_window_open
    """
    s = setup_proposed_trade(window_open=False)
    g_v = team_version(s["g"]["id"])
    res = api.accept_trade(s["trade"]["id"], {"expected_to_team_version": g_v},
                           make_team_gm_headers(s["g"]["id"]))
    validate_error(res, "ERR_TRADE_WINDOW_CLOSED")


def test_accept_window_closed_blocks_transition(api):
    """PRD §3.7: "The season's trade_window_state must be OPEN, else
    ERR_TRADE_WINDOW_CLOSED (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/trade_branching_fork_accept_vs_reject_divergent_side_effects
    """
    s = setup_proposed_trade(window_open=False)
    g_v = team_version(s["g"]["id"])
    res = api.accept_trade(s["trade"]["id"], {"expected_to_team_version": g_v},
                           make_team_gm_headers(s["g"]["id"]))
    validate_error(res, "ERR_TRADE_WINDOW_CLOSED")
    trade = validate_success(api.get_trade(s["trade"]["id"], COMMISH), 200)
    assert trade["status"] == "PROPOSED"


def test_accept_window_closed_leaves_trade_proposed(api):
    """PRD §3.7: "The season's trade_window_state must be OPEN, else
    ERR_TRADE_WINDOW_CLOSED (HTTP 409)."
    PRD §3.6: "A trade is created in status PROPOSED."

    A blocked accept does not advance the trade out of PROPOSED.

    Design: Difficulty/cross_entity_state_dependency/trade_accept_requires_season_window_open
    """
    s = setup_proposed_trade(window_open=False)
    g_v = team_version(s["g"]["id"])
    res = api.accept_trade(s["trade"]["id"], {"expected_to_team_version": g_v},
                           make_team_gm_headers(s["g"]["id"]))
    validate_error(res, "ERR_TRADE_WINDOW_CLOSED")
    trade = validate_success(api.get_trade(s["trade"]["id"], COMMISH), 200)
    assert trade["status"] == "PROPOSED"
    # Contracts unchanged.
    c1 = validate_success(api.get_contract(s["c1"]["id"], COMMISH), 200)
    assert c1["team_id"] == s["f"]["id"]


def test_stale_accept_leaves_contracts_unmoved(api):
    """PRD §2.7: "If another roster mutation — a previously accepted trade, a waive, or
    a promotion — has advanced that team's version since the GM read it, the accept is
    rejected with ERR_STALE_VERSION (HTTP 412)".
    PRD §3.7: "each contract in contract_ids_in has its team_id reassigned to the
    from_team_id".

    A stale-rejected accept performs no contract reassignment.

    Design: Difficulty/optimistic_concurrency/trade_accept_stale_to_team_version_rejected
    """
    s = setup_proposed_trade(window_open=True)
    pg3 = create_player(s["season"]["id"], handle="pg3")
    c3 = sign_contract(s["g"]["id"], pg3["id"], base_salary_cents=3_000_000,
                       contract_type="STANDARD")
    g_v_stale = team_version(s["g"]["id"])
    validate_success(
        api.waive_contract(c3["id"], {"expected_team_version": g_v_stale},
                           make_team_gm_headers(s["g"]["id"])), 200)
    res = api.accept_trade(s["trade"]["id"], {"expected_to_team_version": g_v_stale},
                           make_team_gm_headers(s["g"]["id"]))
    validate_error(res, "ERR_STALE_VERSION")
    c2 = validate_success(api.get_contract(s["c2"]["id"], COMMISH), 200)
    assert c2["team_id"] == s["g"]["id"]


def test_window_closed_beats_team_restricted_on_accept(api):
    """PRD §3.11: "The trade-window gate follows, yielding ERR_TRADE_WINDOW_CLOSED.
    Then the posture gate, yielding ERR_TEAM_RESTRICTED."
    PRD §3.11: "Earlier checks take precedence: a request failing multiple checks
    surfaces the highest-priority failure".

    With the window CLOSED and to_team G RESTRICTED, the window check (earlier) wins.

    Design: Difficulty/priority_pair_validation_conflict/window_closed_beats_team_restricted_on_accept
    """
    s = setup_proposed_trade(window_open=True, season_overrides={"penalty_threshold": 3})
    # Make G RESTRICTED via a 3-point fine on its signed player.
    pg = validate_success(api.get_contract(s["c2"]["id"], COMMISH), 200)["player_id"]
    api.create_fine(
        {"team_id": s["g"]["id"], "player_id": pg, "amount_cents": 100000, "penalty_points": 3},
        COMMISH)
    # Close the window.
    api.set_trade_window(s["season"]["id"], {"trade_window_state": "CLOSED"}, COMMISH)
    g_v = team_version(s["g"]["id"])
    res = api.accept_trade(s["trade"]["id"], {"expected_to_team_version": g_v},
                           make_team_gm_headers(s["g"]["id"]))
    validate_error(res, "ERR_TRADE_WINDOW_CLOSED")


def test_invalid_state_beats_window_closed_on_accept(api):
    """PRD §3.11: "Then the target's state legality for the requested transition is
    checked, yielding ERR_INVALID_STATE. ... The trade-window gate follows, yielding
    ERR_TRADE_WINDOW_CLOSED."
    PRD §3.6: "All three transitions require the trade to still be PROPOSED, else
    ERR_INVALID_STATE (HTTP 409)".

    Re-accepting an already-REJECTED trade while the window is CLOSED surfaces the
    earlier state check.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_window_closed_on_accept
    """
    s = setup_proposed_trade(window_open=True)
    validate_success(api.reject_trade(s["trade"]["id"], make_team_gm_headers(s["g"]["id"])), 200)
    api.set_trade_window(s["season"]["id"], {"trade_window_state": "CLOSED"}, COMMISH)
    g_v = team_version(s["g"]["id"])
    res = api.accept_trade(s["trade"]["id"], {"expected_to_team_version": g_v},
                           make_team_gm_headers(s["g"]["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_window_closed_priority_leaves_restricted_team_trade_proposed(api):
    """PRD §3.11: "The trade-window gate follows, yielding ERR_TRADE_WINDOW_CLOSED.
    Then the posture gate, yielding ERR_TEAM_RESTRICTED."
    PRD §3.6: "A trade is created in status PROPOSED."

    Window-closed wins over the posture gate and the trade stays PROPOSED.

    Design: Difficulty/priority_pair_validation_conflict/window_closed_beats_team_restricted_on_accept
    """
    s = setup_proposed_trade(window_open=True, season_overrides={"penalty_threshold": 3})
    pg = validate_success(api.get_contract(s["c2"]["id"], COMMISH), 200)["player_id"]
    api.create_fine(
        {"team_id": s["g"]["id"], "player_id": pg, "amount_cents": 100000, "penalty_points": 3},
        COMMISH)
    api.set_trade_window(s["season"]["id"], {"trade_window_state": "CLOSED"}, COMMISH)
    g_v = team_version(s["g"]["id"])
    res = api.accept_trade(s["trade"]["id"], {"expected_to_team_version": g_v},
                           make_team_gm_headers(s["g"]["id"]))
    validate_error(res, "ERR_TRADE_WINDOW_CLOSED")
    trade = validate_success(api.get_trade(s["trade"]["id"], COMMISH), 200)
    assert trade["status"] == "PROPOSED"


def test_invalid_state_priority_does_not_resurrect_rejected_trade(api):
    """PRD §3.11: "Then the target's state legality for the requested transition is
    checked, yielding ERR_INVALID_STATE. ... The trade-window gate follows, yielding
    ERR_TRADE_WINDOW_CLOSED."
    PRD §3.6: "Rejecting moves the trade from PROPOSED to REJECTED."

    The state check pre-empts the window check, and the trade remains REJECTED.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_window_closed_on_accept
    """
    s = setup_proposed_trade(window_open=True)
    validate_success(api.reject_trade(s["trade"]["id"], make_team_gm_headers(s["g"]["id"])), 200)
    api.set_trade_window(s["season"]["id"], {"trade_window_state": "CLOSED"}, COMMISH)
    g_v = team_version(s["g"]["id"])
    res = api.accept_trade(s["trade"]["id"], {"expected_to_team_version": g_v},
                           make_team_gm_headers(s["g"]["id"]))
    validate_error(res, "ERR_INVALID_STATE")
    trade = validate_success(api.get_trade(s["trade"]["id"], COMMISH), 200)
    assert trade["status"] == "REJECTED"


def test_accept_stale_to_team_version_rejected(api):
    """PRD §2.7: "If another roster mutation — a previously accepted trade, a waive, or
    a promotion — has advanced that team's version since the GM read it, the accept is
    rejected with ERR_STALE_VERSION (HTTP 412)".

    Capture G's version, then waive a G contract to advance G.version, then accept
    carrying the stale version.

    Design: Difficulty/optimistic_concurrency/trade_accept_stale_to_team_version_rejected
    """
    s = setup_proposed_trade(window_open=True)
    # G signs a third player so it has a contract to waive.
    pg3 = create_player(s["season"]["id"], handle="pg3")
    c3 = sign_contract(s["g"]["id"], pg3["id"], base_salary_cents=3_000_000,
                       contract_type="STANDARD")
    g_v_stale = team_version(s["g"]["id"])
    # Waive c3 to advance G.version past g_v_stale.
    validate_success(
        api.waive_contract(c3["id"], {"expected_team_version": g_v_stale},
                           make_team_gm_headers(s["g"]["id"])), 200)
    res = api.accept_trade(s["trade"]["id"], {"expected_to_team_version": g_v_stale},
                           make_team_gm_headers(s["g"]["id"]))
    validate_error(res, "ERR_STALE_VERSION")


def test_accept_correct_version_succeeds(api):
    """PRD §2.7: "The accept request must include expected_to_team_version carrying the
    version of the to_team (the accepting team) that the GM last read."
    PRD §3.7: "Both teams' payroll_active_cents are recomputed. The version of the
    from-team and the version of the to-team are each incremented by 1."

    Design: Corner/cross_cutting_complexity_layers/trade_accept_correct_version_succeeds
    """
    s = setup_proposed_trade(window_open=True)
    g_v = team_version(s["g"]["id"])
    res = api.accept_trade(s["trade"]["id"], {"expected_to_team_version": g_v},
                           make_team_gm_headers(s["g"]["id"]))
    trade = validate_success(res, 200)
    assert trade["status"] == "ACCEPTED"
    c1 = validate_success(api.get_contract(s["c1"]["id"], COMMISH), 200)
    assert c1["team_id"] == s["g"]["id"]


def test_reject_already_rejected_trade_returns_invalid_state(api):
    """PRD §3.6: "All three transitions require the trade to still be PROPOSED, else
    ERR_INVALID_STATE (HTTP 409)".

    Design: Corner/state_machines/cancel_already_rejected_trade_via_reject_returns_invalid_state
    """
    s = setup_proposed_trade(window_open=True)
    validate_success(api.reject_trade(s["trade"]["id"], make_team_gm_headers(s["g"]["id"])), 200)
    res = api.reject_trade(s["trade"]["id"], make_team_gm_headers(s["g"]["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_propose_trade_empty_both_lists_returns_invalid_trade_assets(api):
    """PRD §3.6: "the two lists may not both be empty — contract_ids_out may be empty
    only if contract_ids_in is non-empty, and vice versa. Any violation of these asset
    rules is rejected with ERR_INVALID_TRADE_ASSETS (HTTP 422)."

    Design: Corner/validations/propose_trade_with_empty_both_lists_returns_invalid_trade_assets
    """
    from test_helpers import create_season, create_team, create_trade_payload
    season = create_season()
    api.start_regular(season["id"], COMMISH)
    api.set_trade_window(season["id"], {"trade_window_state": "OPEN"}, COMMISH)
    f = create_team(season["id"], name="F", market_size_weight=1)
    g = create_team(season["id"], name="G", market_size_weight=1)
    res = api.create_trade(
        create_trade_payload(season["id"], f["id"], g["id"],
                             contract_ids_out=[], contract_ids_in=[]),
        make_team_gm_headers(f["id"]))
    validate_error(res, "ERR_INVALID_TRADE_ASSETS")


def test_propose_trade_window_closed_returns_window_closed(api):
    """PRD §3.6: "Proposing a trade requires that the season's trade_window_state is
    OPEN; a proposal while the window is CLOSED is rejected with ERR_TRADE_WINDOW_CLOSED
    (HTTP 409)."

    Design: Corner/validations/propose_trade_window_closed_returns_window_closed
    """
    from test_helpers import create_season, create_team, create_player, sign_contract, create_trade_payload
    season = create_season()
    api.start_regular(season["id"], COMMISH)
    f = create_team(season["id"], name="F", market_size_weight=1)
    g = create_team(season["id"], name="G", market_size_weight=1)
    pf = create_player(season["id"], handle="pf")
    pg = create_player(season["id"], handle="pg")
    c1 = sign_contract(f["id"], pf["id"], base_salary_cents=10_000_000, contract_type="STANDARD")
    c2 = sign_contract(g["id"], pg["id"], base_salary_cents=12_000_000, contract_type="STANDARD")
    res = api.create_trade(
        create_trade_payload(season["id"], f["id"], g["id"],
                             contract_ids_out=[c1["id"]], contract_ids_in=[c2["id"]]),
        make_team_gm_headers(f["id"]))
    validate_error(res, "ERR_TRADE_WINDOW_CLOSED")
