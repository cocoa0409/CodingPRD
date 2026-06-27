"""Hedge positions: OPEN->MARGIN_CALL->OPEN cycle, strict-< maintenance boundary,
equity conservation, and LONG sign correctness.

Queue A (Difficulty) — non_linear_state_machine (hedge cycle),
                       boundary_precision_check (strict-< maintenance),
                       compensating_invariant (equity conserved).
Queue B (Corner) — calculations (LONG pnl sign).
"""
import pytest

from test_helpers import (
    validate_success, TEST_USERS, assert_hedge_equity_identity, assert_hedge_position,
)
import test_helpers.fixtures as fx

RISK = TEST_USERS["risk_manager_headers"]


def test_hedge_mark_into_margin_call(api):
    """PRD §3.8: "A margin call is triggered when, after applying the new mark, the account
    equity is strictly less than the maintenance margin total". PRD §3.8: "the
    `margin_call_dollars` are set to the initial margin total minus the account equity".

    Design: Difficulty/non_linear_state_machine/hedge_position_open_margincall_open_cycle
    """
    commodity = fx.create_commodity()
    hedge = fx.open_hedge(commodity["id"], side="SHORT", contracts=3, entry_futures_price=4.50)
    marked = validate_success(api.mark_hedge_position(hedge["id"], {"mark_futures_price": 4.80}, RISK))
    assert_hedge_position(marked)
    # SHORT pnl = (4.50-4.80)*5000*3 = -4500; equity = 6000-4500 = 1500 < 4500 maintenance
    assert marked["status"] == "MARGIN_CALL"
    assert marked["margin_call_dollars"] == pytest.approx(4500.00, abs=0.01)


def test_hedge_meet_call_returns_to_open_cycle(api):
    """PRD §3.8: "**Meeting a margin call** ... moves the position from `MARGIN_CALL` back
    to `OPEN`. ... On a sufficient deposit, the deposit is added to
    `posted_margin_dollars`, the account equity is recomputed, the `margin_call_dollars`
    are reset to 0, the position returns to `OPEN`".

    Design: Difficulty/non_linear_state_machine/hedge_position_open_margincall_open_cycle
    """
    commodity = fx.create_commodity()
    hedge, _marked = fx.open_hedge_in_margin_call(commodity_id=commodity["id"])
    cured = fx.meet_call(hedge["id"], deposit_dollars=4500)
    assert cured["status"] == "OPEN"
    assert cured["margin_call_dollars"] == 0
    assert cured["posted_margin_dollars"] == pytest.approx(10500.00, abs=0.01)


def test_margin_call_not_triggered_when_equity_equals_maintenance(api):
    """PRD §3.8: "the comparison is strict, so equity exactly equal to the maintenance
    total does not trigger a call. ... the position stays `OPEN`, and the
    `margin_call_dollars` remain 0."

    Design: Difficulty/boundary_precision_check/margin_call_strict_less_than_maintenance_boundary
    """
    commodity = fx.create_commodity()
    hedge = fx.open_hedge(commodity["id"], side="SHORT", contracts=3, entry_futures_price=4.50)
    # SHORT pnl at mark 4.60 = (4.50-4.60)*5000*3 = -1500; equity = 6000-1500 = 4500 == maintenance
    marked = validate_success(api.mark_hedge_position(hedge["id"], {"mark_futures_price": 4.60}, RISK))
    assert marked["account_equity_dollars"] == pytest.approx(4500.00, abs=0.01)
    assert marked["status"] == "OPEN"
    assert marked["margin_call_dollars"] == 0


def test_margin_call_triggered_just_below_maintenance(api):
    """PRD §3.8: "A margin call is triggered when, after applying the new mark, the account
    equity is strictly less than the maintenance margin total". PRD §3.8: "When the call
    triggers, the position moves from `OPEN` to `MARGIN_CALL`".

    Design: Difficulty/boundary_precision_check/margin_call_strict_less_than_maintenance_boundary
    """
    commodity = fx.create_commodity()
    hedge = fx.open_hedge(commodity["id"], side="SHORT", contracts=3, entry_futures_price=4.50)
    # mark 4.61 -> pnl = (4.50-4.61)*5000*3 = -1650; equity = 6000-1650 = 4350 < 4500
    marked = validate_success(api.mark_hedge_position(hedge["id"], {"mark_futures_price": 4.61}, RISK))
    assert marked["account_equity_dollars"] == pytest.approx(4350.00, abs=0.01)
    assert marked["status"] == "MARGIN_CALL"


def test_hedge_equity_identity_after_mark(api):
    """PRD §3.8: "The `account_equity_dollars` are the posted margin plus the unrealized
    profit and loss." PRD §3.8: "For a `SHORT` position, the `unrealized_pnl_dollars` are
    the entry futures price minus the mark futures price, that difference multiplied by the
    contract size and by the number of contracts".

    Design: Difficulty/compensating_invariant/hedge_equity_conserved_mark_then_meet_call
    """
    commodity = fx.create_commodity()
    hedge = fx.open_hedge(commodity["id"], side="SHORT", contracts=3, entry_futures_price=4.50)
    marked = validate_success(api.mark_hedge_position(hedge["id"], {"mark_futures_price": 4.80}, RISK))
    assert marked["posted_margin_dollars"] == pytest.approx(6000.00, abs=0.01)
    assert marked["unrealized_pnl_dollars"] == pytest.approx(-4500.00, abs=0.01)
    assert marked["account_equity_dollars"] == pytest.approx(1500.00, abs=0.01)
    assert_hedge_equity_identity(marked)


def test_hedge_equity_identity_after_meet_call(api):
    """PRD §3.8: "On a sufficient deposit, the deposit is added to `posted_margin_dollars`,
    the account equity is recomputed". PRD §3.8: "The `account_equity_dollars` are the
    posted margin plus the unrealized profit and loss."

    Design: Difficulty/compensating_invariant/hedge_equity_conserved_mark_then_meet_call
    """
    commodity = fx.create_commodity()
    hedge, _marked = fx.open_hedge_in_margin_call(commodity_id=commodity["id"])
    cured = fx.meet_call(hedge["id"], deposit_dollars=4500)
    assert cured["posted_margin_dollars"] == pytest.approx(10500.00, abs=0.01)
    assert cured["unrealized_pnl_dollars"] == pytest.approx(-4500.00, abs=0.01)
    assert cured["account_equity_dollars"] == pytest.approx(6000.00, abs=0.01)
    assert cured["margin_call_dollars"] == 0
    assert_hedge_equity_identity(cured)


def test_hedge_long_pnl_sign_correct(api):
    """PRD §3.8: "For a `LONG` position, the unrealized profit and loss are the mark futures
    price minus the entry futures price, multiplied by the contract size and the number of
    contracts, rounded to 2 decimal places."

    Design: Corner/calculations/hedge_long_pnl_sign_correct
    """
    commodity = fx.create_commodity()
    hedge = fx.open_hedge(commodity["id"], side="LONG", contracts=2, entry_futures_price=4.50)
    marked = validate_success(api.mark_hedge_position(hedge["id"], {"mark_futures_price": 4.70}, RISK))
    # LONG pnl = (4.70-4.50)*5000*2 = +2000
    assert marked["unrealized_pnl_dollars"] == pytest.approx(2000.00, abs=0.01)
    assert marked["account_equity_dollars"] == pytest.approx(6000.00, abs=0.01)
    assert marked["status"] == "OPEN"
