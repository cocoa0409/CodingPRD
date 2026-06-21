"""
Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear errors rather than confusing assertion failures. Every fixture builds its
preconditions from scratch using only PRD-declared endpoints — the test harness
restarts the server (empty DB) before each test.

Identity threading: TeamGM is entity_backed:Team. Any ownership-gated call uses
make_team_gm_headers(team["id"]); the commissioner uses the opaque shared headers.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_season_payload, create_team_payload, create_player_payload,
    create_contract_payload, create_sponsorship_payload, create_fine_payload,
    create_trade_payload, create_stint_payload,
)
from .test_users import TEST_USERS, make_team_gm_headers

COMMISH = TEST_USERS["commissioner_headers"]


# ─── Tier 1: Primitive creators ──────────────────────────────────────────────

def create_season(**overrides) -> dict:
    """Create a season in SETUP. Returns the season object."""
    res = api_client.create_season(create_season_payload(**overrides), COMMISH)
    return get_success_data(res)


def create_team(season_id: str, **overrides) -> dict:
    """Create a team (posture OPEN). Returns the team object."""
    res = api_client.create_team(create_team_payload(season_id, **overrides), COMMISH)
    return get_success_data(res)


def create_player(season_id: str, **overrides) -> dict:
    """Register a free-agent player. Returns the player object."""
    res = api_client.create_player(create_player_payload(season_id, **overrides), COMMISH)
    return get_success_data(res)


def sign_contract(team_id: str, player_id: str, **overrides) -> dict:
    """Sign a free agent to a team (own-team GM). Returns the contract object."""
    res = api_client.create_contract(
        create_contract_payload(team_id, player_id, **overrides),
        make_team_gm_headers(team_id),
    )
    return get_success_data(res)


def create_sponsorship(season_id: str, **overrides) -> dict:
    """Create a PENDING sponsorship pool. Returns the sponsorship object."""
    res = api_client.create_sponsorship(create_sponsorship_payload(season_id, **overrides), COMMISH)
    return get_success_data(res)


def assess_fine(team_id: str, player_id: str, **overrides) -> dict:
    """Assess a fine against a team/player. Returns the fine object."""
    res = api_client.create_fine(create_fine_payload(team_id, player_id, **overrides), COMMISH)
    return get_success_data(res)


def get_team(team_id: str) -> dict:
    return get_success_data(api_client.get_team(team_id, COMMISH))


def team_version(team_id: str) -> int:
    return get_team(team_id)["version"]


# ─── Tier 2: Roster building ─────────────────────────────────────────────────

def setup_team_with_signed_player(season_overrides=None, contract_overrides=None,
                                  handle="p", team_name="T", weight=1):
    """
    Season + one team + one player signed on an ACTIVE contract.
    Returns (season, team, player, contract).
    """
    season = create_season(**(season_overrides or {}))
    team = create_team(season["id"], name=team_name, market_size_weight=weight)
    player = create_player(season["id"], handle=handle)
    contract = sign_contract(team["id"], player["id"], **(contract_overrides or {}))
    return season, team, player, contract


def setup_team_with_two_contracts(std_salary, two_way_salary,
                                  season_overrides=None, weight=1):
    """
    Season + one team holding one ACTIVE STANDARD contract (std_salary) and one
    ACTIVE unpromoted TWO_WAY contract (two_way_salary).
    Returns (season, team, std_contract, two_way_contract).
    """
    season = create_season(**(season_overrides or {}))
    team = create_team(season["id"], name="T1", market_size_weight=weight)
    p_std = create_player(season["id"], handle="p_std")
    p_tw = create_player(season["id"], handle="p_tw")
    std = sign_contract(team["id"], p_std["id"], base_salary_cents=std_salary,
                        contract_type="STANDARD")
    tw = sign_contract(team["id"], p_tw["id"], base_salary_cents=two_way_salary,
                       contract_type="TWO_WAY")
    return season, team, std, tw


def setup_team_with_two_standard_contracts(salary_a, salary_b, season_overrides=None):
    """
    Season + one team holding two ACTIVE STANDARD contracts (salary_a, salary_b).
    Returns (season, team).
    """
    season = create_season(**(season_overrides or {}))
    team = create_team(season["id"], name="T", market_size_weight=1)
    p1 = create_player(season["id"], handle="p1")
    p2 = create_player(season["id"], handle="p2")
    sign_contract(team["id"], p1["id"], base_salary_cents=salary_a, contract_type="STANDARD")
    sign_contract(team["id"], p2["id"], base_salary_cents=salary_b, contract_type="STANDARD")
    return season, team


def setup_team_single_standard(salary, cap=50_000_000, season_overrides=None):
    """
    Season (cap) + one team holding a single ACTIVE STANDARD contract (salary).
    Returns (season, team).
    """
    ov = {"salary_cap_cents": cap}
    ov.update(season_overrides or {})
    season = create_season(**ov)
    team = create_team(season["id"], name="T", market_size_weight=1)
    p = create_player(season["id"], handle="p")
    sign_contract(team["id"], p["id"], base_salary_cents=salary, contract_type="STANDARD")
    return season, team


# ─── Tier 3: Sponsorship / revenue waterfall ────────────────────────────────

def setup_three_team_sponsorship(weights=(3, 3, 1), names=("A", "B", "C"),
                                 pool_cents=10_000_000, league_share_pct=0.40):
    """
    Season + three teams (created in `names` order with `weights`) + one PENDING
    sponsorship. Returns (season, [team_a, team_b, team_c], sponsorship).
    """
    season = create_season()
    teams = [create_team(season["id"], name=n, market_size_weight=w)
             for n, w in zip(names, weights)]
    spo = create_sponsorship(season["id"], pool_cents=pool_cents,
                             league_share_pct=league_share_pct)
    return season, teams, spo


def setup_single_team_sponsorship(weight=5, pool_cents=10_000_000, league_share_pct=0.40):
    """
    Season + one team + one PENDING sponsorship. Returns (season, team, sponsorship).
    """
    season = create_season()
    team = create_team(season["id"], name="A", market_size_weight=weight)
    spo = create_sponsorship(season["id"], pool_cents=pool_cents,
                             league_share_pct=league_share_pct)
    return season, team, spo


def distribute_sponsorship(sponsorship: dict):
    """Distribute a PENDING sponsorship carrying its current version. Returns response."""
    return api_client.distribute_sponsorship(
        sponsorship["id"],
        {"expected_sponsorship_version": sponsorship["version"]},
        COMMISH,
    )


# ─── Tier 4: Trades — REGULAR season, open window, two teams each with a contract

def setup_regular_season_open_window():
    """
    Season advanced to REGULAR with the trade window OPEN. Returns the season object
    (after the window toggle).
    """
    season = create_season(salary_cap_cents=50_000_000)
    api_client.start_regular(season["id"], COMMISH)
    res = api_client.set_trade_window(season["id"], {"trade_window_state": "OPEN"}, COMMISH)
    return get_success_data(res)


def setup_proposed_trade(window_open=True, season_overrides=None,
                         f_salary=10_000_000, g_salary=12_000_000):
    """
    REGULAR season; teams F and G each holding one ACTIVE STANDARD contract
    (C1 on F, C2 on G); a PROPOSED trade TR moving C1 out of F and C2 out of G.
    If window_open is False, the window is left/returned to CLOSED after proposal.
    Returns dict with season, f, g, c1, c2, trade.
    """
    season = create_season(salary_cap_cents=50_000_000, **(season_overrides or {}))
    api_client.start_regular(season["id"], COMMISH)
    api_client.set_trade_window(season["id"], {"trade_window_state": "OPEN"}, COMMISH)

    f = create_team(season["id"], name="F", market_size_weight=1)
    g = create_team(season["id"], name="G", market_size_weight=1)
    pf = create_player(season["id"], handle="pf")
    pg = create_player(season["id"], handle="pg")
    c1 = sign_contract(f["id"], pf["id"], base_salary_cents=f_salary, contract_type="STANDARD")
    c2 = sign_contract(g["id"], pg["id"], base_salary_cents=g_salary, contract_type="STANDARD")

    tr_res = api_client.create_trade(
        create_trade_payload(season["id"], f["id"], g["id"],
                             contract_ids_out=[c1["id"]], contract_ids_in=[c2["id"]]),
        make_team_gm_headers(f["id"]),
    )
    trade = get_success_data(tr_res)

    if not window_open:
        api_client.set_trade_window(season["id"], {"trade_window_state": "CLOSED"}, COMMISH)

    return {"season": season, "f": f, "g": g, "c1": c1, "c2": c2, "trade": trade}


# ─── Tier 5: Posture / fines ─────────────────────────────────────────────────

def setup_restricted_team(threshold=3, fine_points=3):
    """
    Season (penalty_threshold) + team T + signed player P + one ASSESSED fine that
    pushes T to RESTRICTED. Returns (season, team, player, contract, fine).
    """
    season, team, player, contract = setup_team_with_signed_player(
        season_overrides={"penalty_threshold": threshold})
    fine = assess_fine(team["id"], player["id"], penalty_points=fine_points)
    return season, team, player, contract, fine


# ─── Tier 6: Playoff progression ─────────────────────────────────────────────

def setup_two_team_regular(roster_min=1, x_salary=8_000_000, y_salary=12_000_000):
    """
    REGULAR season (roster_min), window CLOSED; teams X and Y each with one ACTIVE
    STANDARD contract. Returns (season, x, y).
    """
    season = create_season(salary_cap_cents=50_000_000, roster_min=roster_min)
    api_client.start_regular(season["id"], COMMISH)
    x = create_team(season["id"], name="X", market_size_weight=1)
    y = create_team(season["id"], name="Y", market_size_weight=1)
    px = create_player(season["id"], handle="px")
    py = create_player(season["id"], handle="py")
    sign_contract(x["id"], px["id"], base_salary_cents=x_salary, contract_type="STANDARD")
    sign_contract(y["id"], py["id"], base_salary_cents=y_salary, contract_type="STANDARD")
    return season, x, y


def setup_two_team_playoffs(roster_min=1):
    """
    Season driven into PLAYOFFS with two teams X and Y (both eliminated==false).
    Returns (season, x, y).
    """
    season, x, y = setup_two_team_regular(roster_min=roster_min)
    api_client.start_playoffs(season["id"], COMMISH)
    return season, x, y


def setup_complete_season(roster_min=1):
    """
    Season driven all the way to COMPLETE (Y eliminated, X the lone champion).
    Returns (season, x, y).
    """
    season, x, y = setup_two_team_playoffs(roster_min=roster_min)
    api_client.eliminate_team(y["id"], COMMISH)
    api_client.complete_season(season["id"], COMMISH)
    return season, x, y
