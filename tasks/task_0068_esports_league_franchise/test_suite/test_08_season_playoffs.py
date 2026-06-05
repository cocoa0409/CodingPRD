"""Season lifecycle: playoff preconditions, seeding, completion, terminal lockdown.

Covers corner queue section `state_machines` (season transitions).
"""
from test_helpers import (
    validate_success, validate_error,
    create_season, create_team, create_player, sign_contract,
    setup_two_team_regular, setup_two_team_playoffs, setup_complete_season,
    TEST_USERS,
)

COMMISH = TEST_USERS["commissioner_headers"]


def test_start_playoffs_below_roster_min_returns_precondition(api):
    """PRD §3.1: "every team in the season carries at least roster_min ACTIVE STANDARD
    contracts. If any team falls short of roster_min, the transition is rejected with
    ERR_PLAYOFF_PRECONDITION (HTTP 409)."

    Design: Corner/state_machines/start_playoffs_below_roster_min_returns_playoff_precondition
    """
    season = create_season(roster_min=5)
    api.start_regular(season["id"], COMMISH)
    team = create_team(season["id"], name="T", market_size_weight=1)
    p = create_player(season["id"], handle="p")
    sign_contract(team["id"], p["id"], base_salary_cents=5_000_000, contract_type="STANDARD")
    res = api.start_playoffs(season["id"], COMMISH)
    validate_error(res, "ERR_PLAYOFF_PRECONDITION")


def test_start_playoffs_assigns_seeds_by_payroll_desc_tiebreak(api):
    """PRD §3.1: "Seeding ranks the teams by penalty_points ascending, then by
    payroll_active_cents descending, then by created_at ascending; the seed is the
    1-based position in that ranking, so a lower seed is a better seed."

    Both teams have 0 penalty; Y (payroll 12M) outranks X (payroll 8M) on the
    payroll-descending tiebreak → Y seed 1, X seed 2.

    Design: Corner/state_machines/start_playoffs_assigns_seeds_by_penalty_then_payroll
    """
    season, x, y = setup_two_team_regular(roster_min=1, x_salary=8_000_000, y_salary=12_000_000)
    validate_success(api.start_playoffs(season["id"], COMMISH), 200)
    y_after = validate_success(api.get_team(y["id"], COMMISH), 200)
    x_after = validate_success(api.get_team(x["id"], COMMISH), 200)
    assert y_after["seed"] == 1
    assert x_after["seed"] == 2


def test_complete_with_two_non_eliminated_returns_precondition(api):
    """PRD §3.1: "Completing the season ... requires that the season is in PLAYOFFS and
    that exactly one team in the season has eliminated equal to false — a single
    surviving champion. If more than one or zero non-eliminated teams remain, the
    request is rejected with ERR_PLAYOFF_PRECONDITION (HTTP 409)."

    Design: Corner/state_machines/complete_season_with_two_non_eliminated_returns_playoff_precondition
    """
    season, x, y = setup_two_team_playoffs(roster_min=1)
    res = api.complete_season(season["id"], COMMISH)
    validate_error(res, "ERR_PLAYOFF_PRECONDITION")


def test_complete_season_cannot_start_playoffs_again(api):
    """PRD §3.1: "Completing the season advances phase from PLAYOFFS to COMPLETE, a
    terminal phase." PRD §3.1: "Any season lifecycle transition attempted from the wrong
    phase is rejected with ERR_INVALID_STATE (HTTP 409)."

    Design: Corner/state_machines/terminal_complete_season_cannot_start_playoffs_again
    """
    season, x, y = setup_complete_season(roster_min=1)
    completed = validate_success(api.get_season(season["id"], COMMISH), 200)
    assert completed["phase"] == "COMPLETE"
    res = api.start_playoffs(season["id"], COMMISH)
    validate_error(res, "ERR_INVALID_STATE")
