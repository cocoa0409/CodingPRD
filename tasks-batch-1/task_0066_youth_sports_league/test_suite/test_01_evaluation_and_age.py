"""Player league-age computation and evaluation tier scoring.

Covers: combinatorial_formula (league_age, refund modes), boundary_precision
(tier 55 inclusive), and corner calculations (tier C 40, computed league_age,
age-out-of-range verify).
"""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    validate_error,
    ApiErrorId,
    make_league_admin_headers,
)
from test_helpers import fixtures as fx


ADMIN = make_league_admin_headers("admin-1")


# ─────────────────────────────────────────────────────────────────────────────
# combinatorial_formula / league_age_three_input_branch_mode_a  (queue A)
# ─────────────────────────────────────────────────────────────────────────────

def test_league_age_aug31_is_12_sep01_is_11(api):
    """PRD §3.2: "League age is the number of completed years from `birth_date`
    to the league's `age_cutoff_date`: take the cutoff year minus the birth
    year, and if the player's birth month-and-day falls after the cutoff's
    month-and-day, subtract one additional year because the player has not yet
    had their birthday relative to the cutoff."

    Design: Difficulty/combinatorial_formula/league_age_three_input_branch_mode_a
    """
    league = fx.create_league(draft_snake=True)
    fx.set_clock("2026-02-01T00:00:00Z")
    division = fx.create_division(league["id"])  # Majors [9,12]
    family = fx.create_family(league["id"], volunteer_deposit_cents=0)
    fx.advance(league["id"], "REGISTRATION")

    p_aug = validate_success(api.create_player({
        "league_id": league["id"], "family_id": family["id"],
        "division_id": division["id"], "full_name": "Aug31 Kid",
        "birth_date": "2014-08-31",
    }, ADMIN), 201)
    p_sep = validate_success(api.create_player({
        "league_id": league["id"], "family_id": family["id"],
        "division_id": division["id"], "full_name": "Sep01 Kid",
        "birth_date": "2014-09-01",
    }, ADMIN), 201)

    assert p_aug["league_age"] == 12, p_aug["league_age"]
    assert p_sep["league_age"] == 11, p_sep["league_age"]


def test_league_age_cutoff_day_birth_aged_up(api):
    """PRD §3.2: "if the player's birth month-and-day falls after the cutoff's
    month-and-day, subtract one additional year because the player has not yet
    had their birthday relative to the cutoff."

    A birth on the cutoff day itself (2014-08-31 vs cutoff 08-31) is NOT after
    the cutoff, so the player ages up to 12.

    Design: Difficulty/combinatorial_formula/league_age_three_input_branch_mode_a
    """
    league = fx.create_league(draft_snake=True)
    fx.set_clock("2026-02-01T00:00:00Z")
    division = fx.create_division(league["id"])
    family = fx.create_family(league["id"], volunteer_deposit_cents=0)
    fx.advance(league["id"], "REGISTRATION")

    p = validate_success(api.create_player({
        "league_id": league["id"], "family_id": family["id"],
        "division_id": division["id"], "full_name": "Cutoff Kid",
        "birth_date": "2014-08-31",
    }, ADMIN), 201)
    assert p["league_age"] == 12, p["league_age"]


# ─────────────────────────────────────────────────────────────────────────────
# boundary_precision_check / tier_boundary_eval_score_55_is_B_inclusive (A)
# ─────────────────────────────────────────────────────────────────────────────

def _setup_age_verified_player_in_evaluation(birth_date="2015-01-15"):
    league = fx.create_league(draft_snake=True)
    fx.set_clock("2026-06-01T00:00:00Z")
    division = fx.create_division(league["id"])
    family = fx.create_family(league["id"], volunteer_deposit_cents=0)
    fx.advance(league["id"], "REGISTRATION")
    p = fx.register_player(league["id"], family["id"], division["id"],
                          full_name="P1", birth_date=birth_date,
                          birth_certificate_ref="bc1")
    fx.verify_age(p["id"])
    fx.advance(league["id"], "EVALUATION")
    return league, division, family, p


def test_tier_b_boundary_eval_score_55_inclusive(api):
    """PRD §3.3: "The rounded `eval_score` then determines the player's draft
    `tier`: a score of at least 70.00 is tier `A`; otherwise a score of at least
    55.00 is tier `B`; otherwise a score of at least 40.00 is tier `C`; any
    lower score is tier `D`. The lower bounds are inclusive."

    eval all 55 -> eval_score == 55.00 -> tier B (inclusive boundary).

    Design: Difficulty/boundary_precision_check/tier_boundary_eval_score_55_is_B_inclusive
    """
    _, _, _, p = _setup_age_verified_player_in_evaluation()
    data = validate_success(api.evaluate_player(p["id"], {
        "eval_speed": 55, "eval_hitting": 55, "eval_fielding": 55,
    }, ADMIN))
    assert data["eval_score"] == pytest.approx(55.00, abs=0.001), data["eval_score"]
    assert data["tier"] == "B", data["tier"]


def test_tier_just_below_b_boundary_is_c(api):
    """PRD §3.3: "otherwise a score of at least 55.00 is tier `B`; otherwise a
    score of at least 40.00 is tier `C`; any lower score is tier `D`. The lower
    bounds are inclusive."

    A blend of 54 (0.50*54 + 0.30*54 + 0.20*54 = 54.00) is just below the 55.00
    bound, so it falls to tier C — confirming the boundary is exclusive below.

    Design: Difficulty/boundary_precision_check/tier_boundary_eval_score_55_is_B_inclusive
    """
    _, _, _, p = _setup_age_verified_player_in_evaluation()
    data = validate_success(api.evaluate_player(p["id"], {
        "eval_speed": 54, "eval_hitting": 54, "eval_fielding": 54,
    }, ADMIN))
    assert data["eval_score"] == pytest.approx(54.00, abs=0.001), data["eval_score"]
    assert data["tier"] == "C", data["tier"]


# ─────────────────────────────────────────────────────────────────────────────
# corner: calculations / tier_C_lower_boundary_40  (queue B)
# ─────────────────────────────────────────────────────────────────────────────

def test_tier_c_lower_boundary_40_inclusive(api):
    """PRD §3.3: "otherwise a score of at least 40.00 is tier `C`; any lower
    score is tier `D`. The lower bounds are inclusive."

    eval all 40 -> eval_score == 40.00 -> tier C (inclusive 40.00 boundary).

    Design: Corner/calculations/tier_C_lower_boundary_40
    """
    _, _, _, p = _setup_age_verified_player_in_evaluation()
    data = validate_success(api.evaluate_player(p["id"], {
        "eval_speed": 40, "eval_hitting": 40, "eval_fielding": 40,
    }, ADMIN))
    assert data["eval_score"] == pytest.approx(40.00, abs=0.001), data["eval_score"]
    assert data["tier"] == "C", data["tier"]


# ─────────────────────────────────────────────────────────────────────────────
# corner: entities / computed_league_age_ignores_client_input  (queue B)
# ─────────────────────────────────────────────────────────────────────────────

def test_computed_league_age_from_birth_date(api):
    """PRD §3.2: "League age is the number of completed years from `birth_date`
    to the league's `age_cutoff_date`: take the cutoff year minus the birth
    year, and if the player's birth month-and-day falls after the cutoff's
    month-and-day, subtract one additional year because the player has not yet
    had their birthday relative to the cutoff."

    Birth 2016-12-25 vs cutoff 2026-08-31: 2026-2016=10, Dec-25 is after Aug-31
    so subtract 1 -> league_age 9. The value is computed, not client-supplied.

    Design: Corner/entities/computed_league_age_ignores_client_input
    """
    league = fx.create_league(draft_snake=True)
    fx.set_clock("2026-06-01T00:00:00Z")
    division = fx.create_division(league["id"])
    family = fx.create_family(league["id"], volunteer_deposit_cents=0)
    fx.advance(league["id"], "REGISTRATION")

    p = validate_success(api.create_player({
        "league_id": league["id"], "family_id": family["id"],
        "division_id": division["id"], "full_name": "Kid",
        "birth_date": "2016-12-25",
    }, ADMIN), 201)
    assert p["league_age"] == 9, p["league_age"]


# ─────────────────────────────────────────────────────────────────────────────
# corner: validations / age_out_of_range_rejects_verify  (queue B)
# ─────────────────────────────────────────────────────────────────────────────

def test_age_out_of_range_rejected_on_verify(api):
    """PRD §3.3: "Verification also rechecks eligibility: the player's
    `league_age` must fall within the inclusive band of their division, at least
    the division's `min_league_age` and at most its `max_league_age`. A player
    whose league age falls below the minimum or above the maximum is rejected
    with `ERR_AGE_OUT_OF_RANGE`."

    Design: Corner/validations/age_out_of_range_rejects_verify
    """
    league = fx.create_league(draft_snake=True)
    fx.set_clock("2026-06-01T00:00:00Z")
    division = fx.create_division(league["id"], name="Juniors",
                                 min_league_age=10, max_league_age=12)
    family = fx.create_family(league["id"], volunteer_deposit_cents=0)
    fx.advance(league["id"], "REGISTRATION")
    p = fx.register_player(league["id"], family["id"], division["id"],
                          full_name="Young", birth_date="2016-12-25",
                          birth_certificate_ref="bc1")
    assert p["league_age"] == 9, p["league_age"]

    resp = api.verify_age(p["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_AGE_OUT_OF_RANGE.value)
