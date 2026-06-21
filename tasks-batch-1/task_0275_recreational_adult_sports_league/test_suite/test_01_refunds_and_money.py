"""Withdrawal refunds, the three-way refund rule, the floor-truncation, and the
cash-conservation invariant.

Covers difficulty rules dual_variant_calc / combinatorial_formula /
compensating_invariant on the cash domain, plus the corner refund/fee validations.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    make_team_captain_headers, make_league_admin_headers,
)
import test_helpers.fixtures as fx
import test_helpers.factories as F

ADMIN = make_league_admin_headers()


def _payments(api, team_id):
    resp = api.list_payments(team_id, ADMIN)
    data, _meta = validate_paginated(resp)
    return data


def test_full_vs_partial_refund_diverge_on_same_fee(api):
    """PRD §3.4: "If the season's `clock_now` is at or before the season's
    `refund_full_cutoff_at`, the entire refundable base is returned and the payment's
    `reason` is `FULL_WITHDRAWAL`. Otherwise, if no game involving the team has
    `schedule_status` `PLAYED` or `score_status` `CONFIRMED`, the refund is the
    refundable base multiplied by the season's `refund_partial_pct` and then divided
    by 100, with the cents truncated downward (multiply before dividing), and the
    `reason` is `PARTIAL_WITHDRAWAL`."

    Design: Difficulty/dual_variant_calc/refund_full_vs_partial_vs_none_diverges
    """
    # Two divisions, each one CONFIRMED team that paid an 8000-cent fee.
    base1 = fx.setup_division_with_two_confirmed_teams(
        season_overrides={"refund_full_cutoff_at": "2026-09-10T00:00:00Z", "refund_partial_pct": 50},
        division_overrides={"registration_fee_cents": 8000, "team_capacity": 4},
    )
    t_full = base1["home_team"]

    # A CONFIRMED team withdraws only while CLOSED or SCHEDULED (PRD §3.4); close early.
    fx.advance_to(base1["season"]["id"], "CLOSED")
    # Clock is at 2026-08-15 (<= cutoff): a FULL refund.
    full_team = validate_success(api.withdraw_team(t_full["id"], ADMIN))
    assert full_team["refund_issued_cents"] == 8000, (
        f"full-refund team should refund 8000, got {full_team['refund_issued_cents']}"
    )
    full_rows = _payments(api, t_full["id"])
    refund_full = next((p for p in full_rows if p["kind"] == "REFUND"), None)
    assert refund_full is not None and refund_full["amount_cents"] == 8000
    assert refund_full["reason"] == "FULL_WITHDRAWAL"

    # Second team, advance clock past cutoff before any game -> PARTIAL (floor(8000*50/100)=4000).
    base2 = fx.setup_division_with_two_confirmed_teams(
        season_overrides={"refund_full_cutoff_at": "2026-09-10T00:00:00Z", "refund_partial_pct": 50},
        division_overrides={"registration_fee_cents": 8000, "team_capacity": 4},
    )
    t_partial = base2["home_team"]
    fx.advance_to(base2["season"]["id"], "CLOSED")
    fx.set_clock("2026-09-20T00:00:00Z")
    partial_team = validate_success(api.withdraw_team(t_partial["id"], ADMIN))
    assert partial_team["refund_issued_cents"] == 4000, (
        f"partial-refund team should refund 4000, got {partial_team['refund_issued_cents']}"
    )
    partial_rows = _payments(api, t_partial["id"])
    refund_partial = next((p for p in partial_rows if p["kind"] == "REFUND"), None)
    assert refund_partial is not None and refund_partial["amount_cents"] == 4000
    assert refund_partial["reason"] == "PARTIAL_WITHDRAWAL"


def test_full_refund_writes_full_withdrawal_row(api):
    """PRD §3.4: "If the season's `clock_now` is at or before the season's
    `refund_full_cutoff_at`, the entire refundable base is returned and the payment's
    `reason` is `FULL_WITHDRAWAL`."

    Design: Difficulty/dual_variant_calc/refund_full_vs_partial_vs_none_diverges
    """
    base = fx.setup_division_with_two_confirmed_teams(
        season_overrides={"refund_full_cutoff_at": "2026-09-10T00:00:00Z", "refund_partial_pct": 50},
        division_overrides={"registration_fee_cents": 8000},
    )
    team = base["home_team"]
    cap = base["home_player"]
    # A CONFIRMED team withdraws only while CLOSED or SCHEDULED (PRD §3.4); close early.
    fx.advance_to(base["season"]["id"], "CLOSED")
    # Captain withdraws own team while clock (2026-08-15) <= cutoff.
    withdrawn = validate_success(api.withdraw_team(team["id"], make_team_captain_headers(cap["id"])))
    assert withdrawn["refund_issued_cents"] == 8000
    rows = _payments(api, team["id"])
    refund = next((p for p in rows if p["kind"] == "REFUND"), None)
    assert refund is not None, "a REFUND row must be written for a full withdrawal"
    assert refund["amount_cents"] == 8000 and refund["reason"] == "FULL_WITHDRAWAL"


def test_partial_refund_floor_multiply_before_divide(api):
    """PRD §3.4: "the refund is the refundable base multiplied by the season's
    `refund_partial_pct` and then divided by 100, with the cents truncated downward
    (multiply before dividing), and the `reason` is `PARTIAL_WITHDRAWAL`."

    Design: Difficulty/combinatorial_formula/partial_refund_floor_multiply_before_divide_mode_b
    """
    # refund_partial_pct=40, fee 7500 -> floor(7500*40/100) = 3000.
    base = fx.setup_division_with_two_confirmed_teams(
        season_overrides={"refund_full_cutoff_at": "2026-09-05T00:00:00Z", "refund_partial_pct": 40},
        division_overrides={"registration_fee_cents": 7500},
    )
    team = base["home_team"]
    cap = base["home_player"]
    # A CONFIRMED team withdraws only while CLOSED or SCHEDULED (PRD §3.4); close early.
    fx.advance_to(base["season"]["id"], "CLOSED")
    fx.set_clock("2026-09-08T00:00:00Z")  # past the full cutoff, before any game
    withdrawn = validate_success(api.withdraw_team(team["id"], make_team_captain_headers(cap["id"])))
    assert withdrawn["refund_issued_cents"] == 3000, (
        f"floor(7500*40/100) must be 3000, got {withdrawn['refund_issued_cents']}"
    )
    rows = _payments(api, team["id"])
    refund = next((p for p in rows if p["kind"] == "REFUND"), None)
    assert refund is not None and refund["amount_cents"] == 3000
    assert refund["reason"] == "PARTIAL_WITHDRAWAL"


def test_partial_refund_truncates_remainder_downward(api):
    """PRD §3.4: "the refund is the refundable base multiplied by the season's
    `refund_partial_pct` and then divided by 100, with the cents truncated downward
    (multiply before dividing), and the `reason` is `PARTIAL_WITHDRAWAL`."

    fee 7333, pct 50 -> 7333*50 = 366650, /100 = 3666.5 -> floored to 3666.

    Design: Difficulty/combinatorial_formula/partial_refund_floor_multiply_before_divide_mode_b
    """
    base = fx.setup_division_with_two_confirmed_teams(
        season_overrides={"refund_full_cutoff_at": "2026-09-05T00:00:00Z", "refund_partial_pct": 50},
        division_overrides={"registration_fee_cents": 7333},
    )
    team = base["home_team"]
    cap = base["home_player"]
    # A CONFIRMED team withdraws only while CLOSED or SCHEDULED (PRD §3.4); close early.
    fx.advance_to(base["season"]["id"], "CLOSED")
    fx.set_clock("2026-09-08T00:00:00Z")  # past full cutoff, before any game
    withdrawn = validate_success(api.withdraw_team(team["id"], make_team_captain_headers(cap["id"])))
    assert withdrawn["refund_issued_cents"] == 3666, (
        f"floor(7333*50/100) must be 3666, got {withdrawn['refund_issued_cents']}"
    )
    rows = _payments(api, team["id"])
    refund = next((p for p in rows if p["kind"] == "REFUND"), None)
    assert refund is not None and refund["amount_cents"] == 3666
    assert refund["reason"] == "PARTIAL_WITHDRAWAL"


def test_cash_conserved_at_zero_after_full_withdrawal(api):
    """PRD §2.9: "Its `fee_charged_cents` is the sum of `amount_cents` over its
    `CAPTURED` `FEE` rows, and its `refund_issued_cents` is the sum of `amount_cents`
    over its `CAPTURED` `REFUND` rows."
    PRD §3.4: "If the season's `clock_now` is at or before the season's
    `refund_full_cutoff_at`, the entire refundable base is returned and the payment's
    `reason` is `FULL_WITHDRAWAL`."

    Design: Difficulty/compensating_invariant/fee_minus_refund_zero_after_full_withdrawal
    """
    base = fx.setup_division_with_two_confirmed_teams(
        season_overrides={"refund_full_cutoff_at": "2026-09-30T00:00:00Z"},
        division_overrides={"registration_fee_cents": 8000},
    )
    team = base["home_team"]
    cap = base["home_player"]
    # A CONFIRMED team withdraws only while CLOSED or SCHEDULED (PRD §3.4); close early.
    fx.advance_to(base["season"]["id"], "CLOSED")
    withdrawn = validate_success(api.withdraw_team(team["id"], make_team_captain_headers(cap["id"])))
    assert withdrawn["fee_charged_cents"] == 8000
    assert withdrawn["refund_issued_cents"] == 8000
    assert withdrawn["fee_charged_cents"] - withdrawn["refund_issued_cents"] == 0, (
        "net cash held must be conserved at zero after a full-refund withdrawal"
    )


def test_full_refund_keeps_fee_charged_intact(api):
    """PRD §2.9: "Its `fee_charged_cents` is the sum of `amount_cents` over its
    `CAPTURED` `FEE` rows, and its `refund_issued_cents` is the sum of `amount_cents`
    over its `CAPTURED` `REFUND` rows."

    Design: Difficulty/compensating_invariant/fee_minus_refund_zero_after_full_withdrawal
    """
    base = fx.setup_division_with_two_confirmed_teams(
        season_overrides={"refund_full_cutoff_at": "2026-09-30T00:00:00Z"},
        division_overrides={"registration_fee_cents": 8000},
    )
    team = base["home_team"]
    # A CONFIRMED team withdraws only while CLOSED or SCHEDULED (PRD §3.4); close early.
    fx.advance_to(base["season"]["id"], "CLOSED")
    validate_success(api.withdraw_team(team["id"], ADMIN))
    refreshed = validate_success(api.get_team(team["id"], ADMIN))
    # fee_charged_cents is a derived sum over FEE rows — the FEE row is never removed.
    assert refreshed["fee_charged_cents"] == 8000
    assert refreshed["refund_issued_cents"] == 8000


def test_refund_adjustment_exceeding_fee_rejected(api):
    """PRD §3.4: "A manual refund beyond the bound is likewise rejected with
    `ERR_REFUND_EXCEEDS_FEE`."

    Design: Corner/validations/refund_adjustment_exceeds_fee_returns_error
    """
    base = fx.setup_open_division(refund_full_cutoff_at="2026-09-30T00:00:00Z")
    cap = fx.create_player()
    # Re-fetch division version not needed; register via helper.
    division = base["division"]
    team = fx.register_team(division["id"], cap["id"])
    fx.pay_fee(team["id"], cap["id"], 5000)
    resp = api.refund_adjustment(team["id"], F.refund_adjustment_payload(6000), ADMIN)
    validate_error(resp, ApiErrorId.ERR_REFUND_EXCEEDS_FEE.value)
