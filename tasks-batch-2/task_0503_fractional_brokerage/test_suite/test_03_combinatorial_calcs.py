"""Options suitability, DRIP reinvest rounding, dividend branching, PFOF routing.

Covers the combinatorial-formula and non-linear-state-machine difficulty
instances plus the calculations corner probes.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_account_holder_headers,
    create_account, create_security, funded_cash_account, get_account_version,
    buy_and_fill, get_first_position,
    submitted_options_approval, position_with_paid_dividend, approved_options_account,
    factories as F,
)


def _holder(account_id):
    return make_account_holder_headers(account_id)


def _compliance():
    return TEST_USERS["compliance_officer_headers"]


def _clearing():
    return TEST_USERS["clearing_system_headers"]


# --------------------------------------------------------------------------
# Options suitability (mode a: nonlinear net-worth gate)
# --------------------------------------------------------------------------
def test_options_suitability_networth_gate_caps_level_three(api):
    """PRD §3.8: "the base cap is 3 when stated experience is at least 3 years and liquid net
    worth is at least ten million cents; otherwise it is 2 when experience is at least 2 years;
    otherwise 1 when experience is at least 1 year; otherwise 0. The net-worth gate matters only
    at the level-3 boundary. The `granted_level` is then the smaller of the `requested_level`
    and that base cap."
    PRD §3.8: "the account's `options_level` is raised to the larger of its current value and
    the granted level."

    Design: Difficulty/combinatorial_formula/options_suitability_nonlinear_networth_gate
    """
    acc = create_account(account_type="CASH")
    approval = submitted_options_approval(
        acc["id"], requested_level=3, stated_experience_years=4, liquid_net_worth_cents=8_000_000
    )
    version = get_account_version(acc["id"])
    decided = validate_success(api.decide_options_approval(
        approval["id"], F.decide_options_approval_payload("APPROVE", version), _compliance()
    ))
    # exp 4 >= 3 but net_worth 8M < 10M -> level-3 gate fails -> base cap 2 -> granted min(3,2)=2.
    assert decided["granted_level"] == 2, decided
    assert decided["status"] == "APPROVED", decided
    acc_after = validate_success(api.get_account(acc["id"], _compliance()))
    assert acc_after["options_level"] == 2, acc_after


def test_options_suitability_level_three_granted_when_networth_met(api):
    """PRD §3.8: "the base cap is 3 when stated experience is at least 3 years and liquid net
    worth is at least ten million cents ... The `granted_level` is then the smaller of the
    `requested_level` and that base cap."

    Design: Difficulty/combinatorial_formula/options_suitability_nonlinear_networth_gate
    """
    acc = create_account(account_type="CASH")
    approval = submitted_options_approval(
        acc["id"], requested_level=3, stated_experience_years=3, liquid_net_worth_cents=10_000_000
    )
    version = get_account_version(acc["id"])
    decided = validate_success(api.decide_options_approval(
        approval["id"], F.decide_options_approval_payload("APPROVE", version), _compliance()
    ))
    assert decided["granted_level"] == 3, decided
    assert decided["status"] == "APPROVED", decided


# --------------------------------------------------------------------------
# DRIP reinvest (mode b: pinned rounding order)
# --------------------------------------------------------------------------
def test_drip_reinvest_truncate_shares_then_round_spend_residual(api):
    """PRD §3.7: "Second, the `reinvest_quantity` is the gross amount divided by the security's
    `last_price_cents`, truncated to six decimal places — share quantities are truncated, never
    rounded up. Third, the spent cash is the `reinvest_quantity` multiplied by `last_price_cents`,
    rounded half up to whole cents. The `residual_cash_cents` is the gross amount minus that
    spend; because shares are truncated first, the residual is always at least zero."
    PRD §3.7: "computes a `gross_amount_cents` as the `record_quantity` multiplied by
    `rate_per_share_cents` rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/drip_reinvest_truncate_then_round_residual
    """
    # 100 sh of HIGHCO @ 3,000,000c; dividend 50c/share -> gross 100*50 = 5000c.
    account_id, sec_id, position, div = position_with_paid_dividend(
        symbol="HIGHCO", shares=100, rate_per_share_cents=50, ex_date="2026-02-01T00:00:00Z",
        last_price_cents=3_000_000, drip_enabled=True, deposit_cents=400_000_000,
    )
    assert div["gross_amount_cents"] == 5000, div
    reinvested = validate_success(api.reinvest_dividend(div["id"], _clearing()))
    # 5000 / 3000000 = 0.001666... truncated to 6dp = 0.001666;
    # spend = round_half_up(0.001666 * 3000000) = 4998; residual = 5000 - 4998 = 2.
    assert reinvested["reinvest_quantity"] == 0.001666, reinvested
    assert reinvested["residual_cash_cents"] == 2, reinvested
    assert reinvested["status"] == "REINVESTED", reinvested


def test_drip_reinvest_leaves_residual_in_settled_cash(api):
    """PRD §3.7: "Reinvesting subtracts the spend (gross amount minus residual) from
    `settled_cash_cents`, opens a new `Lot` for the `reinvest_quantity` (cascading into a
    recompute of `Position.quantity` and `average_cost_cents`), leaves the `residual_cash_cents`
    in settled cash."
    PRD §3.7: "The `residual_cash_cents` is the gross amount minus that spend; because shares are
    truncated first, the residual is always at least zero."

    Design: Difficulty/combinatorial_formula/drip_reinvest_truncate_then_round_residual
    """
    account_id, sec_id, position, div = position_with_paid_dividend(
        symbol="HIGHCR", shares=100, rate_per_share_cents=50, ex_date="2026-02-01T00:00:00Z",
        last_price_cents=3_000_000, drip_enabled=True, deposit_cents=400_000_000,
    )
    before = validate_success(api.get_account(account_id, _holder(account_id)))
    reinvested = validate_success(api.reinvest_dividend(div["id"], _clearing()))
    # gross 5000, residual 2 -> spend 4998 subtracted from settled cash.
    after = validate_success(api.get_account(account_id, _holder(account_id)))
    assert reinvested["residual_cash_cents"] == 2, reinvested
    assert after["settled_cash_cents"] == before["settled_cash_cents"] - 4998, (before, after)


def test_drip_reinvest_opens_lot_for_reinvest_quantity(api):
    """PRD §3.7: "Reinvesting subtracts the spend (gross amount minus residual) from
    `settled_cash_cents`, opens a new `Lot` for the `reinvest_quantity` (cascading into a
    recompute of `Position.quantity` and `average_cost_cents`), leaves the `residual_cash_cents`
    in settled cash."

    Design: Difficulty/non_linear_state_machine/dividend_branching_paid_to_reinvested_vs_reversed
    """
    # 10 sh of DIVCO @ 10000c; dividend 100c/share -> gross 1000c.
    account_id, sec_id, position, div = position_with_paid_dividend(
        symbol="DIVCO", shares=10, rate_per_share_cents=100, ex_date="2026-03-01T00:00:00Z",
        last_price_cents=10000, drip_enabled=True, deposit_cents=200000,
    )
    assert div["gross_amount_cents"] == 1000, div
    reinvested = validate_success(api.reinvest_dividend(div["id"], _clearing()))
    # 1000 / 10000 = 0.1 exactly; residual 0.
    assert reinvested["reinvest_quantity"] == 0.1, reinvested
    assert reinvested["residual_cash_cents"] == 0, reinvested
    assert reinvested["status"] == "REINVESTED", reinvested

    lots = get_success_data(api.list_lots(position["id"], _holder(account_id)))
    new_lot = next((lt for lt in lots if lt["original_quantity"] == 0.1), None)
    assert new_lot is not None, lots


def test_dividend_reverse_branch_subtracts_gross(api):
    """PRD §3.7: "a `PAID` dividend that has not yet been reinvested may be reversed
    (`PAID → REVERSED`) as a correction, which subtracts the `gross_amount_cents` back out of
    `settled_cash_cents` to compensate the earlier pay credit."

    Design: Difficulty/non_linear_state_machine/dividend_branching_paid_to_reinvested_vs_reversed
    """
    account_id, sec_id, position, div = position_with_paid_dividend(
        symbol="DIVCOR", shares=10, rate_per_share_cents=100, ex_date="2026-03-01T00:00:00Z",
        last_price_cents=10000, drip_enabled=False, deposit_cents=200000,
    )
    before = validate_success(api.get_account(account_id, _holder(account_id)))
    reversed_div = validate_success(api.reverse_dividend(div["id"], _clearing()))
    assert reversed_div["status"] == "REVERSED", reversed_div
    after = validate_success(api.get_account(account_id, _holder(account_id)))
    # gross was 1000; reverse subtracts it back out.
    assert after["settled_cash_cents"] == before["settled_cash_cents"] - 1000, (before, after)


# --------------------------------------------------------------------------
# PFOF routing and rebate (calculations corner)
# --------------------------------------------------------------------------
def test_pfof_routing_option_routes_to_venue_a(api):
    """PRD §3.4: "For an `EQUITY` instrument all three venues are eligible; for an `OPTION`
    instrument only `VENUE_A` and `VENUE_B` are eligible. The selector scores each eligible
    venue by its rebate in basis points and picks the highest score, so a higher rebate ranks
    first ... The chosen venue is recorded as the order's `pfof_venue`."

    Design: Corner/calculations/pfof_routing_option_excludes_venue_c
    """
    sec = create_security(symbol="OPTC", instrument_type="OPTION", last_price_cents=10000,
                          fractional_enabled=False, required_options_level=1)
    # Approve options level 1 on a funded account.
    acc = create_account(account_type="CASH")
    from test_helpers import deposit as _deposit
    _deposit(acc["id"], 5_000_000, instant_eligible=True)
    approval = submitted_options_approval(acc["id"], 1, 2, 5_000_000)
    v1 = get_account_version(acc["id"])
    validate_success(api.decide_options_approval(
        approval["id"], F.decide_options_approval_payload("APPROVE", v1), _compliance()))
    v2 = get_account_version(acc["id"])
    order = validate_success(api.create_order(
        F.create_order_payload(acc["id"], sec["id"], v2, side="BUY", order_type="LIMIT",
                               quantity=1, limit_price_cents=10000),
        _holder(acc["id"])),
        expected_status=201,
    )
    assert order["order_status"] == "ACCEPTED", order
    assert order["pfof_venue"] == "VENUE_A", order


def test_pfof_rebate_computed_per_fill(api):
    """PRD §3.5/§3.4: "on each fill, the per-fill `pfof_rebate_cents` is computed as the fill's
    `gross_value_cents` multiplied by the chosen venue's rebate basis points divided by 10000,
    rounded half up to whole cents."
    PRD §3.5: "Each fill computes its `gross_value_cents` as `fill_quantity` multiplied by
    `fill_price_cents`, rounded half up to whole cents."

    Design: Corner/calculations/pfof_rebate_computed_per_fill
    """
    sec = create_security(symbol="REBCO", last_price_cents=10000, fractional_enabled=True)
    account_id, _v = funded_cash_account(amount_cents=200000)
    order, fill = buy_and_fill(account_id, sec["id"], 10, 10000, order_type="MARKET")
    assert order["pfof_venue"] == "VENUE_A", order
    # gross 10*10000 = 100000; rebate VENUE_A 30bps -> 100000*30/10000 = 300.
    assert fill["gross_value_cents"] == 100000, fill
    assert fill["pfof_rebate_cents"] == 300, fill


def test_drip_below_minimum_rejected(api):
    """PRD §3.7: "if the gross dividend buys less than a single fractional share at the current
    price — yielding a `reinvest_quantity` of zero — it is rejected with `ERR_DRIP_BELOW_MINIMUM`."

    Design: Corner/calculations/drip_below_minimum_returns_error
    """
    # 1 sh of MEGA @ 50,000,000c; dividend 2c/share -> gross 2c; 2/50000000 truncates to 0.
    account_id, sec_id, position, div = position_with_paid_dividend(
        symbol="MEGA", shares=1, rate_per_share_cents=2, ex_date="2026-07-01T00:00:00Z",
        last_price_cents=50_000_000, drip_enabled=True, deposit_cents=60_000_000,
    )
    assert div["gross_amount_cents"] == 2, div
    assert div["reinvest_quantity"] == 0, div
    resp = api.reinvest_dividend(div["id"], _clearing())
    validate_error(resp, ApiErrorId.ERR_DRIP_BELOW_MINIMUM, expected_status=409)


def test_options_revoke_resets_account_level(api):
    """PRD §3.8: "An approved application may later be revoked (`APPROVED → REVOKED`), upon which
    the account's `options_level` is reset to the highest level still held under another
    `APPROVED` application for that account (or 0 if none remains)."

    Design: Corner/state_machines/options_revoke_resets_account_level
    """
    account_id, approval = approved_options_account(
        requested_level=2, stated_experience_years=3, liquid_net_worth_cents=5_000_000
    )
    assert approval["granted_level"] == 2, approval
    revoked = validate_success(api.revoke_options_approval(approval["id"], _compliance()))
    assert revoked["status"] == "REVOKED", revoked
    acc_after = validate_success(api.get_account(account_id, _compliance()))
    assert acc_after["options_level"] == 0, acc_after
