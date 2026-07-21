"""Trade pricing, tier governance, and credit conservation (PRD §2.9, §3.3, §3.4)."""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_account, create_fixture, create_order, add_line, quote, confirm, cancel, pay,
    setup_gold_account,
)

SM = TEST_USERS["sm_headers"]


# --------------------------- dual-variant: estimate (STANDARD) vs final (GOLD) ----------
def test_order_estimate_uses_standard_tier_at_quote_time(api):
    """PRD §3.3: "for a trade order it is the account's current `discount_pct` as observed
    at quote time, and for a retail order (no `trade_account_id`) it is zero."
    PRD §2.9: "The `discount_pct` follows the tier: `STANDARD` earns 0.00, `SILVER` earns
    0.08, and `GOLD` earns 0.15."

    Design: Difficulty/dual_variant_calc/order_estimate_vs_final_tier_upgrade
    """
    acct = create_account(api, credit_limit_cents=100000000)
    fx = create_fixture(api, sku_base="F-DV", category="CHANDELIER", base_price_cents=1000000, base_wattage=100)
    ox = create_order(api, customer_name="X", trade_account_id=acct["id"])
    add_line(api, ox["id"], fx["id"], quantity=1)
    quoted = quote(api, ox["id"])
    assert quoted["total_estimate_cents"] == 1000000


def test_order_final_uses_upgraded_gold_tier_at_settlement(api):
    """PRD §3.4: "the tier (and thus the discount percentage) is re-read at settlement time,
    so an account that has upgraded since the quote gets the better rate".
    PRD §2.9: "The `discount_pct` follows the tier: `STANDARD` earns 0.00, `SILVER` earns
    0.08, and `GOLD` earns 0.15."

    Design: Difficulty/dual_variant_calc/order_estimate_vs_final_tier_upgrade
    """
    acct = create_account(api, credit_limit_cents=100000000)
    fx = create_fixture(api, sku_base="F-DV", category="CHANDELIER", base_price_cents=1000000, base_wattage=100)
    # OrderX quoted while STANDARD (estimate 1000000).
    ox = create_order(api, customer_name="X", trade_account_id=acct["id"])
    add_line(api, ox["id"], fx["id"], quantity=1)
    quote(api, ox["id"])
    # OrderY settled for 5,000,000 -> account tier becomes GOLD.
    oy = create_order(api, customer_name="Y", trade_account_id=acct["id"])
    add_line(api, oy["id"], fx["id"], quantity=5)
    quote(api, oy["id"])
    confirm(api, oy["id"])
    pay(api, oy["id"], "SETTLEMENT", 5000000)
    # OrderX confirmed (commits the STANDARD estimate) then settled -> final at GOLD.
    confirm(api, ox["id"])
    settled = pay(api, ox["id"], "SETTLEMENT", 1000000)
    assert settled["discount_final_cents"] == 150000
    assert settled["total_final_cents"] == 850000


# --------------------------- combinatorial: non-linear discount cap ---------------------
def test_discount_cap_subtotal_estimate(api):
    """PRD §3.3: "The `subtotal_estimate_cents` is the sum, over every `ACTIVE` line of the
    order, of that line's `unit_price_cents` multiplied by its `quantity`."

    Design: Difficulty/combinatorial_formula/order_discount_cap_min_nonlinear
    """
    acct, fx = setup_gold_account(api, credit_limit_cents=100000000)
    oc = create_order(api, customer_name="cap", trade_account_id=acct["id"])
    add_line(api, oc["id"], fx["id"], quantity=2)
    quoted = quote(api, oc["id"])
    assert quoted["subtotal_estimate_cents"] == 2000000


def test_discount_cap_clamps_gold_discount_to_two_thousand_dollars(api):
    """PRD §3.3: "The `discount_estimate_cents` is the smaller of that raw discount and a
    hard cap of 200,000 cents (two thousand dollars) — the discount can never exceed that
    cap regardless of tier or order size."

    Design: Difficulty/combinatorial_formula/order_discount_cap_min_nonlinear
    """
    acct, fx = setup_gold_account(api, credit_limit_cents=100000000)
    oc = create_order(api, customer_name="cap", trade_account_id=acct["id"])
    add_line(api, oc["id"], fx["id"], quantity=2)  # subtotal 2,000,000; raw discount 300,000
    quoted = quote(api, oc["id"])
    assert quoted["discount_estimate_cents"] == 200000
    assert quoted["total_estimate_cents"] == 1800000


# --------------------------- boundary: SILVER inclusive threshold -----------------------
def test_settlement_at_silver_threshold_yields_silver_tier(api):
    """PRD §2.9: "The `tier` is `GOLD` when `annual_spend_cents` is at least 5,000,000 cents
    (fifty thousand dollars), `SILVER` when it is at least 2,000,000 cents (twenty thousand
    dollars) but below the gold threshold, and `STANDARD` otherwise; the threshold
    comparisons are inclusive."

    Design: Difficulty/boundary_precision_check/trade_tier_silver_inclusive_boundary
    """
    acct = create_account(api, credit_limit_cents=100000000)
    fx = create_fixture(api, sku_base="F-TB", category="CHANDELIER", base_price_cents=2000000, base_wattage=100)
    o = create_order(api, customer_name="TB", trade_account_id=acct["id"])
    add_line(api, o["id"], fx["id"], quantity=1)
    quote(api, o["id"])
    confirm(api, o["id"])
    pay(api, o["id"], "SETTLEMENT", 2000000)
    data = validate_success(api.get_trade_account(acct["id"], SM), 200)
    assert data["tier"] == "SILVER"


def test_settlement_at_silver_threshold_spend_and_discount(api):
    """PRD §2.9: "An account also accrues `annual_spend_cents`: the sum of `total_final_cents`
    over that account's orders whose `payment_status` is `SETTLED`".
    PRD §2.9: "The `discount_pct` follows the tier: `STANDARD` earns 0.00, `SILVER` earns
    0.08, and `GOLD` earns 0.15."

    Design: Difficulty/boundary_precision_check/trade_tier_silver_inclusive_boundary
    """
    acct = create_account(api, credit_limit_cents=100000000)
    fx = create_fixture(api, sku_base="F-TB", category="CHANDELIER", base_price_cents=2000000, base_wattage=100)
    o = create_order(api, customer_name="TB", trade_account_id=acct["id"])
    add_line(api, o["id"], fx["id"], quantity=1)
    quote(api, o["id"])
    confirm(api, o["id"])
    pay(api, o["id"], "SETTLEMENT", 2000000)
    data = validate_success(api.get_trade_account(acct["id"], SM), 200)
    assert data["annual_spend_cents"] == 2000000
    assert data["discount_pct"] == pytest.approx(0.08)


# --------------------------- compensating invariant: credit confirm/cancel --------------
def test_confirm_debits_available_credit(api):
    """PRD §3.3: "On success the order's `committed_credit_cents` is set to its
    `total_estimate_cents`, which debits the account's available credit by that amount".
    PRD §2.9: "Available credit equals `credit_limit_cents` minus the sum of
    `committed_credit_cents` across all of that account's orders whose `fulfillment_status`
    is `CONFIRMED`."

    Design: Difficulty/compensating_invariant/trade_credit_confirm_cancel_conserved
    """
    acct = create_account(api, credit_limit_cents=1000000)
    fx = create_fixture(api, sku_base="F-9A", category="CHANDELIER", base_price_cents=300000, base_wattage=100)
    o = create_order(api, customer_name="9A", trade_account_id=acct["id"])
    add_line(api, o["id"], fx["id"], quantity=1)
    quote(api, o["id"])
    order = confirm(api, o["id"])
    assert order["committed_credit_cents"] == 300000
    acct_data = validate_success(api.get_trade_account(acct["id"], SM), 200)
    assert acct_data["available_credit_cents"] == 700000


def test_cancel_restores_committed_credit(api):
    """PRD §3.3: "When the order later completes or is cancelled, that committed credit is
    released back to zero, restoring the account's availability."

    Design: Difficulty/compensating_invariant/trade_credit_confirm_cancel_conserved
    """
    acct = create_account(api, credit_limit_cents=1000000)
    fx = create_fixture(api, sku_base="F-9A", category="CHANDELIER", base_price_cents=300000, base_wattage=100)
    o = create_order(api, customer_name="9A", trade_account_id=acct["id"])
    add_line(api, o["id"], fx["id"], quantity=1)
    quote(api, o["id"])
    confirm(api, o["id"])
    cancelled = cancel(api, o["id"])
    assert cancelled["committed_credit_cents"] == 0
    acct_data = validate_success(api.get_trade_account(acct["id"], SM), 200)
    assert acct_data["available_credit_cents"] == 1000000


# --------------------------- priority pair: state guard beats fiscal guard --------------
def test_confirm_cancelled_order_reports_invalid_state_over_credit(api):
    """PRD §2.8: "Only after all of these pass does the server evaluate stateful and business
    rules: the quote concurrency check (`ERR_STALE_VERSION`), the draft-only guard on adding
    lines (`ERR_ORDER_NOT_DRAFT`), the generic "resource is not in a state that permits this
    transition" guard (`ERR_INVALID_STATE`), and then the domain-specific referential,
    temporal, safety, and fiscal rules described in Section 3."

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_fiscal
    """
    acct = create_account(api, credit_limit_cents=0)
    fx = create_fixture(api, sku_base="F-SF", category="CHANDELIER", base_price_cents=300000, base_wattage=100)
    o = create_order(api, customer_name="SF", trade_account_id=acct["id"])
    add_line(api, o["id"], fx["id"], quantity=1)
    quote(api, o["id"])
    cancel(api, o["id"])
    resp = api.confirm_order(o["id"], SM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_confirm_rejected_by_state_leaves_order_cancelled(api):
    """PRD §2.8: "the generic "resource is not in a state that permits this transition" guard
    (`ERR_INVALID_STATE`), and then the domain-specific referential, temporal, safety, and
    fiscal rules described in Section 3."

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_fiscal
    """
    acct = create_account(api, credit_limit_cents=0)
    fx = create_fixture(api, sku_base="F-SF", category="CHANDELIER", base_price_cents=300000, base_wattage=100)
    o = create_order(api, customer_name="SF", trade_account_id=acct["id"])
    add_line(api, o["id"], fx["id"], quantity=1)
    quote(api, o["id"])
    cancel(api, o["id"])
    api.confirm_order(o["id"], SM)
    data = validate_success(api.get_order(o["id"], SM), 200)
    assert data["fulfillment_status"] == "CANCELLED"


# --------------------------- corner: single-failure fiscal + patch ----------------------
def test_confirm_insufficient_credit_returns_error(api):
    """PRD §3.3: "For a trade order, confirmation is permitted only when the account's
    `available_credit_cents` is at least the order's `total_estimate_cents`; if available
    credit falls short the confirmation is rejected with `ERR_INSUFFICIENT_CREDIT`."

    Design: Corner/validations/confirm_insufficient_credit_single_failure
    """
    acct = create_account(api, credit_limit_cents=100000)
    fx = create_fixture(api, sku_base="F-IC", category="CHANDELIER", base_price_cents=300000, base_wattage=100)
    o = create_order(api, customer_name="IC", trade_account_id=acct["id"])
    add_line(api, o["id"], fx["id"], quantity=1)
    quote(api, o["id"])
    resp = api.confirm_order(o["id"], SM)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDIT.value)


def test_patch_credit_limit_recomputes_available_credit(api):
    """PRD §3.1: "Later the manager may adjust an account's `credit_limit_cents` or move its
    `status` among `ACTIVE`, `SUSPENDED`, and `CLOSED`; adjusting the ceiling triggers a
    recomputation of `available_credit_cents`."

    Design: Corner/endpoints/patch_trade_account_credit_limit_recomputes_available
    """
    acct = create_account(api, credit_limit_cents=0)
    resp = api.patch_trade_account(acct["id"], {"credit_limit_cents": 500000}, SM)
    data = validate_success(resp, 200)
    assert data["credit_limit_cents"] == 500000
    assert data["available_credit_cents"] == 500000
