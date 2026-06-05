"""Buying power dual-variant, margin upgrade OCC, and cash-conservation tests."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    api_client,
    ApiErrorId,
    open_and_activate_account, upgrade_margin, submit_margin_upgrade,
    settle_acat, validate_acat, request_acat, get_account, open_position,
    CO_SUBMITTER, CO_DECIDER, HOLDER, CUST,
)


def test_buying_power_reg_t_vs_pma_divergence(api):
    """PRD §3.6: "Under a `REG_T` agreement, buying power is twice the excess
    equity, never less than zero — the larger of zero and two times excess
    equity". PRD §3.6: "Under a `PMA` (Portfolio Margin) agreement, buying
    power is the account's `equity_cents` divided by the 15 percent risk-based
    initial margin rate (the division floored to whole cents), then reduced by
    `maintenance_margin_cents` and by the reserved order notional, never less
    than zero".

    Two accounts with identical equity 20000000 and no positions yield
    REG_T = 2*20000000 = 40000000 and PMA = floor(20000000/0.15) = 133333333.

    Design: Difficulty/dual_variant_calc/buying_power_reg_t_vs_pma_divergence
    """
    acct_a = open_and_activate_account(holder_id="h_a", cash_balance_cents=20_000_000)
    upgrade_margin(acct_a["id"], "REG_T")

    acct_b = open_and_activate_account(holder_id="h_b", cash_balance_cents=20_000_000)
    upgrade_margin(acct_b["id"], "PMA")

    a = validate_success(api.get_account(acct_a["id"], CO_DECIDER))
    b = validate_success(api.get_account(acct_b["id"], CO_DECIDER))

    assert a["buying_power_cents"] == 40_000_000, a["buying_power_cents"]
    assert b["buying_power_cents"] == 133_333_333, b["buying_power_cents"]
    assert a["buying_power_cents"] != b["buying_power_cents"]


def test_buying_power_pma_variant_floor_division(api):
    """PRD §3.6: "Under a `PMA` (Portfolio Margin) agreement, buying power is
    the account's `equity_cents` divided by the 15 percent risk-based initial
    margin rate (the division floored to whole cents), then reduced by
    `maintenance_margin_cents` and by the reserved order notional, never less
    than zero".

    Design: Difficulty/dual_variant_calc/buying_power_reg_t_vs_pma_divergence
    """
    acct = open_and_activate_account(cash_balance_cents=20_000_000)
    upgrade_margin(acct["id"], "PMA")
    data = validate_success(api.get_account(acct["id"], CO_DECIDER))
    assert data["margin_type"] == "PMA"
    assert data["buying_power_cents"] == 133_333_333


def test_occ_correct_version_margin_upgrade_succeeds(api):
    """PRD §3.4: "and `expected_account_version` must equal the account's
    current `version`, otherwise `ERR_STALE_ACCOUNT_VERSION` (HTTP 412). When
    approval succeeds, the upgrade moves to `APPROVED`, the officer is recorded
    as `decided_by_user_id`, the account's `margin_type` is set to the
    `requested_margin_type` as a cross-entity write".

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_margin_upgrade_succeeds
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    mu = submit_margin_upgrade(acct["id"], "REG_T")
    ver = get_account(acct["id"])["version"]

    resp = api.approve_margin_upgrade(mu["id"], {"expected_account_version": ver}, CO_DECIDER)
    data = validate_success(resp)
    assert data["status"] == "APPROVED"

    acct_after = validate_success(api.get_account(acct["id"], CO_DECIDER))
    assert acct_after["margin_type"] == "REG_T"


def test_occ_stale_version_margin_upgrade_rejected(api):
    """PRD §2.8: "If that value does not equal the account's current `version`
    at approval time, the approval is rejected with `ERR_STALE_ACCOUNT_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_margin_upgrade_rejected
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    mu = submit_margin_upgrade(acct["id"], "REG_T")
    stale_version = get_account(acct["id"])["version"]

    # A settled ACAT IN transfer advances Account.version between observation and approve.
    settle_acat(acct["id"], direction="IN", transfer_value_cents=100_000)

    resp = api.approve_margin_upgrade(
        mu["id"], {"expected_account_version": stale_version}, CO_DECIDER)
    validate_error(resp, ApiErrorId.ERR_STALE_ACCOUNT_VERSION.value)


def test_acat_settle_in_raises_cash_recomputes_buying_power(api):
    """PRD §3.10: "Settlement adjusts the account's cash: when `direction` is
    `IN`, the `transfer_value_cents` is added to the account's
    `cash_balance_cents`". PRD §3.10: "In both cases the account's buying power
    is recomputed and the account's `version` increments by one."

    Design: Difficulty/transitive_cascade/acat_settle_in_raises_cash_recomputes_buying_power
    """
    acct = open_and_activate_account(cash_balance_cents=0)
    t = validate_acat(acct["id"], direction="IN", transfer_value_cents=500_000)

    resp = api.settle_acat_transfer(t["id"], CUST)
    settled = validate_success(resp)
    assert settled["status"] == "SETTLED"

    after = validate_success(api.get_account(acct["id"], CO_SUBMITTER))
    assert after["cash_balance_cents"] == 500_000
    assert after["buying_power_cents"] == 500_000


def test_acat_settle_in_version_increments(api):
    """PRD §3.10: "In both cases the account's buying power is recomputed and
    the account's `version` increments by one."

    Design: Difficulty/transitive_cascade/acat_settle_in_raises_cash_recomputes_buying_power
    """
    acct = open_and_activate_account(cash_balance_cents=0)
    before = get_account(acct["id"])["version"]
    t = validate_acat(acct["id"], direction="IN", transfer_value_cents=500_000)
    validate_success(api.settle_acat_transfer(t["id"], CUST))
    after = get_account(acct["id"])["version"]
    assert after == before + 1, f"version {before} -> {after}"


def test_acat_in_then_out_conserves_cash_balance(api):
    """PRD §3.10: "Settlement adjusts the account's cash: when `direction` is
    `IN`, the `transfer_value_cents` is added to the account's
    `cash_balance_cents`; when `direction` is `OUT`, the `transfer_value_cents`
    is subtracted from it."

    Design: Difficulty/compensating_invariant/acat_in_then_out_conserves_cash_balance
    """
    acct = open_and_activate_account(cash_balance_cents=0)
    settle_acat(acct["id"], direction="IN", transfer_value_cents=500_000)
    assert get_account(acct["id"])["cash_balance_cents"] == 500_000

    t_out = validate_acat(acct["id"], direction="OUT", transfer_value_cents=500_000)
    resp = api.settle_acat_transfer(t_out["id"], CUST)
    settled = validate_success(resp)
    assert settled["status"] == "SETTLED"

    after = validate_success(api.get_account(acct["id"], CO_SUBMITTER))
    assert after["cash_balance_cents"] == 0
    assert after["buying_power_cents"] == 0


def test_buying_power_recomputed_after_position_close(api):
    """PRD §3.5: "closing it recomputes the account's maintenance margin
    excluding that position, then recomputes equity and buying power." PRD §3.6:
    "Under a `REG_T` agreement, buying power is twice the excess equity, never
    less than zero — the larger of zero and two times excess equity".

    With cash 1000000 and one OPEN EQUITY position market_value 1000000 (maint
    floor(1000000*0.25)=250000): excess = (1000000+1000000)-250000 = 1750000,
    REG_T buying power = 2*1750000 = 3500000; after closing the position equity
    is 1000000, maint 0, buying power = 2*1000000 = 2000000.

    Design: Corner/cross_cutting_complexity_layers/buying_power_recomputed_after_position_close
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    upgrade_margin(acct["id"], "REG_T")
    pos = open_position(acct["id"], symbol="ACME", instrument_type="EQUITY",
                        quantity=10, market_value_cents=1_000_000)
    assert get_account(acct["id"])["buying_power_cents"] == 3_500_000

    resp = api.close_position(pos["id"], HOLDER)
    closed = validate_success(resp)
    assert closed["status"] == "CLOSED"

    after = validate_success(api.get_account(acct["id"], CO_SUBMITTER))
    assert after["buying_power_cents"] == 2_000_000


def test_acat_transfer_branching_settle_vs_reject_vs_cancel(api):
    """PRD §3.10: "Settlement adjusts the account's cash: when `direction` is
    `IN`, the `transfer_value_cents` is added to the account's
    `cash_balance_cents`". PRD §3.10: "A `Custodian` may reject a transfer that
    is in `REQUESTED` or `VALIDATED`, moving it to `REJECTED`".

    One transfer settles (cash rises by 500000), another is rejected (no balance
    change) — divergent side-effect sets per branch.

    Design: Difficulty/non_linear_state_machine/acat_transfer_branching_settle_vs_reject_vs_cancel
    """
    acct = open_and_activate_account(cash_balance_cents=0)
    settle_acat(acct["id"], direction="IN", transfer_value_cents=500_000)

    t2 = request_acat(acct["id"], direction="IN", transfer_value_cents=999_999)
    resp = api.reject_acat_transfer(t2["id"], {"reject_code": "SSN_MISMATCH"}, CUST)
    rejected = validate_success(resp)
    assert rejected["status"] == "REJECTED"

    assert validate_success(api.get_account(acct["id"], CO_SUBMITTER))["cash_balance_cents"] == 500_000


def test_acat_reject_leaves_cash_unchanged(api):
    """PRD §3.10: "A `Custodian` may reject a transfer that is in `REQUESTED` or
    `VALIDATED`, moving it to `REJECTED`". PRD §3.10: "`SETTLED`, `REJECTED`, and
    `CANCELLED` are all terminal for a transfer."

    Rejecting a REQUESTED IN transfer does not change cash_balance_cents.

    Design: Difficulty/non_linear_state_machine/acat_transfer_branching_settle_vs_reject_vs_cancel
    """
    acct = open_and_activate_account(cash_balance_cents=0)
    t = request_acat(acct["id"], direction="IN", transfer_value_cents=999_999)
    resp = api.reject_acat_transfer(t["id"], {"reject_code": "TITLE_MISMATCH"}, CUST)
    assert validate_success(resp)["status"] == "REJECTED"
    assert validate_success(api.get_account(acct["id"], CO_SUBMITTER))["cash_balance_cents"] == 0


def test_acat_in_then_out_buying_power_conserved(api):
    """PRD §3.10: "In both cases the account's buying power is recomputed and
    the account's `version` increments by one."

    A settled IN of 500000 then a settled OUT of 500000 leaves buying_power_cents
    back at 0 (CASH account, no other reservations).

    Design: Difficulty/compensating_invariant/acat_in_then_out_conserves_cash_balance
    """
    acct = open_and_activate_account(cash_balance_cents=0)
    settle_acat(acct["id"], direction="IN", transfer_value_cents=500_000)
    t_out = validate_acat(acct["id"], direction="OUT", transfer_value_cents=500_000)
    validate_success(api.settle_acat_transfer(t_out["id"], CUST))
    assert validate_success(api.get_account(acct["id"], CO_SUBMITTER))["buying_power_cents"] == 0
