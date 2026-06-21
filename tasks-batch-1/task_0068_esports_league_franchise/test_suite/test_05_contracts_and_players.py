"""Contract signing, waiving, two-way promotion, and the player free-agent cascade.

Covers difficulty queue: transitive_cascade (waive → contract WAIVED → player
FREE_AGENT), compensating_invariant (sign then waive conserves cap payroll),
resource_temporal_overlap (contract closed-interval touching endpoints); and corner
queue contract/validation cases.
"""
from test_helpers import (
    validate_success, validate_error,
    setup_team_with_signed_player, setup_team_with_two_contracts,
    create_season, create_team, create_player, sign_contract, team_version,
    create_contract_payload,
    make_team_gm_headers, TEST_USERS,
)

COMMISH = TEST_USERS["commissioner_headers"]


def test_waive_frees_player_to_free_agent(api):
    """PRD §3.4: "When, after the waive, no other ACTIVE contract references the
    contract's player_id, that player's status is set back to FREE_AGENT."
    PRD §3.4: "the player becomes free precisely when their last ACTIVE contract is
    waived."

    Design: Difficulty/transitive_cascade/contract_waive_cascade_status_then_player_free_agent_depth3
    """
    season, team, player, contract = setup_team_with_signed_player()
    t_v = team_version(team["id"])
    res = api.waive_contract(contract["id"], {"expected_team_version": t_v},
                             make_team_gm_headers(team["id"]))
    waived = validate_success(res, 200)
    assert waived["status"] == "WAIVED"
    p = validate_success(api.get_player(player["id"], COMMISH), 200)
    assert p["status"] == "FREE_AGENT"


def test_waive_sets_contract_waived(api):
    """PRD §3.4: "A GM may waive any ACTIVE contract their team holds, moving the
    contract from ACTIVE to the terminal WAIVED status."

    Design: Difficulty/transitive_cascade/contract_waive_cascade_status_then_player_free_agent_depth3
    """
    season, team, player, contract = setup_team_with_signed_player()
    t_v = team_version(team["id"])
    res = api.waive_contract(contract["id"], {"expected_team_version": t_v},
                             make_team_gm_headers(team["id"]))
    waived = validate_success(res, 200)
    assert waived["status"] == "WAIVED"


def test_sign_then_waive_conserves_cap_payroll(api):
    """PRD §3.4: "the team's payroll_active_cents is recomputed (the waived contract no
    longer contributes)".
    PRD §3.3: "A team's cap-counting payroll, payroll_active_cents, is the sum of
    base_salary_cents over every contract on the team whose status is ACTIVE and which
    counts toward the cap."

    Sign STANDARD +7,000,000 then waive −7,000,000 returns payroll to 0.

    Design: Difficulty/compensating_invariant/contract_sign_then_waive_conserves_cap_payroll
    """
    season, team, player, contract = setup_team_with_signed_player(
        contract_overrides={"base_salary_cents": 7_000_000})
    before = validate_success(api.get_team_payroll(team["id"], COMMISH), 200)
    assert before["payroll_active_cents"] == 7_000_000
    t_v = team_version(team["id"])
    validate_success(
        api.waive_contract(contract["id"], {"expected_team_version": t_v},
                           make_team_gm_headers(team["id"])), 200)
    after = validate_success(api.get_team_payroll(team["id"], COMMISH), 200)
    assert after["payroll_active_cents"] == 0


def test_sign_standard_sets_payroll(api):
    """PRD §3.2: "A successful sign creates a contract in status ACTIVE ... recomputes
    the signing team's payroll_active_cents".

    Design: Difficulty/compensating_invariant/contract_sign_then_waive_conserves_cap_payroll
    """
    season, team, player, contract = setup_team_with_signed_player(
        contract_overrides={"base_salary_cents": 7_000_000})
    payroll = validate_success(api.get_team_payroll(team["id"], COMMISH), 200)
    assert payroll["payroll_active_cents"] == 7_000_000


def test_promote_two_way_counts_toward_cap(api):
    """PRD §3.3: "Promotion is a self-loop that keeps the contract ACTIVE while flipping
    two_way_promoted to true so that the contract's base_salary_cents joins the
    cap-counting payroll." PRD §3.3: "On success a promotion sets two_way_promoted to
    true, recomputes the team's payroll_active_cents to include this contract's
    base_salary_cents".

    Design: Corner/state_machines/two_way_promote_counts_toward_cap_after_promotion
    """
    season, team, std, tw = setup_team_with_two_contracts(
        std_salary=3_000_000, two_way_salary=4_000_000)
    t_v = team_version(team["id"])
    res = api.promote_contract(tw["id"], {"expected_team_version": t_v},
                               make_team_gm_headers(team["id"]))
    promoted = validate_success(res, 200)
    assert promoted["two_way_promoted"] is True
    payroll = validate_success(api.get_team_payroll(team["id"], COMMISH), 200)
    assert payroll["payroll_active_cents"] == 7_000_000


def test_sign_already_signed_player_returns_duplicate(api):
    """PRD §3.2: "The player must currently be a FREE_AGENT with no other ACTIVE
    contract; signing a player who already holds an ACTIVE contract is rejected with
    ERR_DUPLICATE_RESOURCE (HTTP 409)."

    Design: Corner/validations/sign_player_already_signed_returns_duplicate
    """
    season, team, player, contract = setup_team_with_signed_player(
        contract_overrides={"term_start": "2026-01-01T00:00:00.000Z",
                            "term_end": "2026-06-30T00:00:00.000Z"})
    res = api.create_contract(
        create_contract_payload(team["id"], player["id"], base_salary_cents=4_000_000,
                                contract_type="STANDARD",
                                term_start="2026-08-01T00:00:00.000Z",
                                term_end="2026-12-31T00:00:00.000Z"),
        make_team_gm_headers(team["id"]))
    validate_error(res, "ERR_DUPLICATE_RESOURCE")


def test_roster_max_exceeded_on_sign_returns_roster_limit(api):
    """PRD §3.3: "The count of ACTIVE STANDARD contracts — which, for the purpose of
    this count, includes promoted two-way contracts — may not exceed the season's
    roster_max." PRD §3.3: "A move that would push either count past its limit is
    rejected with ERR_ROSTER_LIMIT_EXCEEDED (HTTP 409)."

    Design: Corner/validations/roster_max_exceeded_on_sign_returns_roster_limit
    """
    season = create_season(roster_min=1, roster_max=1)
    team = create_team(season["id"], name="T", market_size_weight=1)
    p1 = create_player(season["id"], handle="p1")
    p2 = create_player(season["id"], handle="p2")
    sign_contract(team["id"], p1["id"], base_salary_cents=5_000_000, contract_type="STANDARD")
    res = api.create_contract(
        create_contract_payload(team["id"], p2["id"], base_salary_cents=4_000_000,
                                contract_type="STANDARD"),
        make_team_gm_headers(team["id"]))
    validate_error(res, "ERR_ROSTER_LIMIT_EXCEEDED")


def test_contract_create_increments_team_version(api):
    """PRD §2.4: "The version begins at 1 on creation and increments by exactly 1 on
    each successful mutation of that resource". PRD §3.2: "A successful sign creates a
    contract in status ACTIVE ... and increments the team's version by 1."

    Design: Corner/cross_cutting_complexity_layers/contract_create_increments_team_version
    """
    season = create_season()
    team = create_team(season["id"], name="T", market_size_weight=1)
    assert team["version"] == 1
    player = create_player(season["id"], handle="p")
    sign_contract(team["id"], player["id"], base_salary_cents=5_000_000, contract_type="STANDARD")
    t = validate_success(api.get_team(team["id"], COMMISH), 200)
    assert t["version"] == 2
