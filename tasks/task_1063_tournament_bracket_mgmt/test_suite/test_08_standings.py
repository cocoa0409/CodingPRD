"""Standings ranking under GAME_DIFF tiebreak: the money-domain-independent
ranking variant, and its 3-input lexicographic sort resolved at seed.

Queue A: standings_seed_vs_gamediff_tiebreak, standings_gamediff_multiinput_sort.
"""
from test_helpers import validate_success, TEST_USERS
from test_helpers import fixtures as F

PUBLIC = TEST_USERS["public_headers"]


def _order(rows):
    return [row["registration_id"] for row in rows]


# --------------------------------------------------------------------------
# GAME_DIFF ranks a lower seed above a higher seed
# --------------------------------------------------------------------------
def test_gamediff_tiebreak_orders_by_game_difference(api):
    """PRD §3.5: "under GAME_DIFF, the larger game difference ranks higher first,
    and only then does the lower seed break a remaining tie — so under GAME_DIFF a
    lower seed can finish above a higher seed."

    Design: Difficulty/dual_variant_calc/standings_seed_vs_gamediff_tiebreak
    """
    # A>B 2-1, C>A 2-1, B>C 2-0: all tie on match_points=3; game_diff B=+1,A=0,C=-1.
    ctx = F.setup_round_robin_confirmed(
        "GAME_DIFF", {"ab": (2, 1), "ac": (1, 2), "bc": (2, 0)})
    data = validate_success(api.get_standings(ctx["t_id"], PUBLIC))
    rows = F.standings_rows(data)
    assert _order(rows) == [ctx["rb"], ctx["ra"], ctx["rc"]], _order(rows)


def test_gamediff_tiebreak_game_diff_values(api):
    """PRD §3.5: "match points are the wins times 3 ... the game difference is
    games-for minus games-against. Registrations are ranked by match points from
    highest to lowest. Ties on match points are broken by tiebreak_method".

    Design: Difficulty/dual_variant_calc/standings_seed_vs_gamediff_tiebreak
    """
    ctx = F.setup_round_robin_confirmed(
        "GAME_DIFF", {"ab": (2, 1), "ac": (1, 2), "bc": (2, 0)})
    rows = F.standings_rows(validate_success(api.get_standings(ctx["t_id"], PUBLIC)))
    by_reg = {row["registration_id"]: row for row in rows}
    assert by_reg[ctx["rb"]]["match_points"] == 3
    assert by_reg[ctx["rb"]]["game_diff"] == 1
    assert by_reg[ctx["ra"]]["game_diff"] == 0
    assert by_reg[ctx["rc"]]["game_diff"] == -1


# --------------------------------------------------------------------------
# 3-input sort: full tie on (match_points, game_diff) resolved only by seed
# --------------------------------------------------------------------------
def test_gamediff_cyclic_tie_resolved_by_seed(api):
    """PRD §3.5: "under GAME_DIFF, the larger game difference ranks higher first,
    and only then does the lower seed break a remaining tie".

    Design: Difficulty/combinatorial_formula/standings_gamediff_multiinput_sort
    """
    # Cyclic A>B, B>C, C>A all 2-1: every player 1W1L, match_points=3, game_diff=0,
    # so only seed ASC (A=1,B=2,C=3) orders them.
    ctx = F.setup_round_robin_confirmed(
        "GAME_DIFF", {"ab": (2, 1), "ac": (1, 2), "bc": (2, 1)},
        ratings=(1500, 1400, 1000))
    rows = F.standings_rows(validate_success(api.get_standings(ctx["t_id"], PUBLIC)))
    assert _order(rows) == [ctx["ra"], ctx["rb"], ctx["rc"]], _order(rows)


def test_gamediff_cyclic_tie_all_equal_metrics(api):
    """PRD §3.5: "match points are the wins times 3 plus the losses times 0 ...
    the game difference is games-for minus games-against."

    Design: Difficulty/combinatorial_formula/standings_gamediff_multiinput_sort
    """
    ctx = F.setup_round_robin_confirmed(
        "GAME_DIFF", {"ab": (2, 1), "ac": (1, 2), "bc": (2, 1)},
        ratings=(1500, 1400, 1000))
    rows = F.standings_rows(validate_success(api.get_standings(ctx["t_id"], PUBLIC)))
    assert all(row["match_points"] == 3 for row in rows), rows
    assert all(row["game_diff"] == 0 for row in rows), rows
