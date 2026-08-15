"""Investment pool unitization: pricing, buy-in/redemption chains, pool
invariants, and pool OCC."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    create_active_fund,
    create_pool,
    get_pool,
    get_fund,
    assert_unitization_event,
    assert_money_eq,
    assert_units_eq,
    ApiErrorId,
    TEST_USERS,
)

INVESTMENT = TEST_USERS["investment_manager_headers"]


def _setup_pool_and_fund(api, seed=30000.00):
    pool = create_pool(initial_nav=1000000.00, initial_units=50000.0000)
    bundle = create_active_fund(fund_type="DESIGNATED", seed_amount=seed)
    return pool, bundle["fund"]["id"]


def test_buy_in_mints_units_at_current_price(api):
    """PRD §3.4: "A pool's `unit_price` is its `nav` divided by its
    `units_outstanding`, rounded half-up to four decimal places, and is defined
    only while `units_outstanding` is greater than zero."
    PRD §3.4: "The minted unit count is `cash_amount` divided by the current
    `unit_price`, rounded half-up to four decimal places; those units are added
    to the pool's `units_outstanding`, the cash is added to the pool's `nav`,
    the fund's `cash_balance` is debited by `cash_amount`, and the fund's
    holding row for the pool is created or increased by the minted units."

    Design: Difficulty/combinatorial_formula/buyin_mark_to_market_redemption_chain
    """
    pool, fund_id = _setup_pool_and_fund(api)
    event = validate_success(
        api.create_unitization_event(
            pool["id"],
            {
                "event_kind": "BUY_IN",
                "fund_id": fund_id,
                "cash_amount": 25000.00,
                "expected_pool_version": pool["version"],
            },
            INVESTMENT,
        ),
        201,
    )
    assert_unitization_event(event)
    assert_units_eq(event["units_delta"], 1250.0000, "units minted")
    assert_units_eq(event["unit_price_applied"], 20.0000, "unit price applied")
    pool_after = get_pool(pool["id"])
    assert_money_eq(pool_after["nav"], 1025000.00, "pool nav after buy-in")
    assert_units_eq(pool_after["units_outstanding"], 51250.0000, "units outstanding")
    fund_after = get_fund(fund_id)
    assert_money_eq(fund_after["cash_balance"], 5000.00, "fund cash after buy-in")


def test_redemption_after_mark_to_market_uses_new_price(api):
    """PRD §3.4: "A mark-to-market reprices the pool without moving units: the
    pool's `nav` is replaced outright by the supplied `new_nav` at 2 decimal
    places, `units_outstanding` is unchanged, the `unit_price` is recomputed
    from the new figures, and the event's `units_delta` is 0.0000."
    PRD §3.4: "The payout is `units_amount` multiplied by the current
    `unit_price`, rounded half-up to two decimal places; the redeemed units are
    subtracted from `units_outstanding`, the payout is subtracted from `nav`,
    the fund's `cash_balance` is credited with the payout, and the fund's
    holding is decreased by the redeemed units."

    Design: Difficulty/combinatorial_formula/buyin_mark_to_market_redemption_chain
    """
    pool, fund_id = _setup_pool_and_fund(api)
    validate_success(
        api.create_unitization_event(
            pool["id"],
            {
                "event_kind": "BUY_IN",
                "fund_id": fund_id,
                "cash_amount": 25000.00,
                "expected_pool_version": pool["version"],
            },
            INVESTMENT,
        ),
        201,
    )
    validate_success(
        api.create_unitization_event(
            pool["id"], {"event_kind": "MARK_TO_MARKET", "new_nav": 1080000.00}, INVESTMENT
        ),
        201,
    )
    repriced = get_pool(pool["id"])
    # 1080000.00 / 51250.0000 = 21.0732 (4dp round-half-up)
    assert_units_eq(repriced["unit_price"], 21.0732, "unit price after mark-to-market")

    redemption = validate_success(
        api.create_unitization_event(
            pool["id"],
            {
                "event_kind": "REDEMPTION",
                "fund_id": fund_id,
                "units_amount": 300.0000,
                "expected_pool_version": repriced["version"],
            },
            INVESTMENT,
        ),
        201,
    )
    assert_units_eq(redemption["unit_price_applied"], 21.0732, "redemption price")
    # 5000.00 remaining + round2(300 * 21.0732) = 5000.00 + 6321.96
    fund_after = get_fund(fund_id)
    assert_money_eq(fund_after["cash_balance"], 11321.96, "fund cash after redemption")
    holdings, _ = validate_paginated(
        api.list_fund_pool_holdings(fund_id, INVESTMENT)
    )
    assert len(holdings) == 1
    assert_units_eq(holdings[0]["units_held"], 950.0000, "units held after redemption")


def test_buy_in_then_full_redemption_restores_pool(api):
    """PRD §3.4: "The minted unit count is `cash_amount` divided by the current
    `unit_price`, rounded half-up to four decimal places; those units are added
    to the pool's `units_outstanding`, the cash is added to the pool's `nav`,
    the fund's `cash_balance` is debited by `cash_amount`, and the fund's
    holding row for the pool is created or increased by the minted units."
    PRD §3.4: "The payout is `units_amount` multiplied by the current
    `unit_price`, rounded half-up to two decimal places; the redeemed units are
    subtracted from `units_outstanding`, the payout is subtracted from `nav`,
    the fund's `cash_balance` is credited with the payout, and the fund's
    holding is decreased by the redeemed units."
    PRD §3.4: "A pool holding row exists only while its `units_held` is greater
    than zero, so a full redemption retires the row."

    Design: Difficulty/compensating_invariant/buyin_redemption_conserves_pool_nav_identity
    """
    pool, fund_id = _setup_pool_and_fund(api)
    validate_success(
        api.create_unitization_event(
            pool["id"],
            {
                "event_kind": "BUY_IN",
                "fund_id": fund_id,
                "cash_amount": 25000.00,
                "expected_pool_version": pool["version"],
            },
            INVESTMENT,
        ),
        201,
    )
    after_buy = get_pool(pool["id"])
    validate_success(
        api.create_unitization_event(
            pool["id"],
            {
                "event_kind": "REDEMPTION",
                "fund_id": fund_id,
                "units_amount": 1250.0000,
                "expected_pool_version": after_buy["version"],
            },
            INVESTMENT,
        ),
        201,
    )
    pool_final = get_pool(pool["id"])
    assert_money_eq(pool_final["nav"], 1000000.00, "pool nav conserved")
    assert_units_eq(pool_final["units_outstanding"], 50000.0000, "units conserved")
    holdings, _ = validate_paginated(api.list_fund_pool_holdings(fund_id, INVESTMENT))
    assert holdings == [], "full redemption retires the holding row"


def test_buy_in_then_full_redemption_restores_fund_cash(api):
    """PRD §3.4: "The minted unit count is `cash_amount` divided by the current
    `unit_price`, rounded half-up to four decimal places; those units are added
    to the pool's `units_outstanding`, the cash is added to the pool's `nav`,
    the fund's `cash_balance` is debited by `cash_amount`, and the fund's
    holding row for the pool is created or increased by the minted units."
    PRD §3.4: "The payout is `units_amount` multiplied by the current
    `unit_price`, rounded half-up to two decimal places; the redeemed units are
    subtracted from `units_outstanding`, the payout is subtracted from `nav`,
    the fund's `cash_balance` is credited with the payout, and the fund's
    holding is decreased by the redeemed units."

    Design: Difficulty/compensating_invariant/buyin_redemption_conserves_pool_nav_identity
    """
    pool, fund_id = _setup_pool_and_fund(api)
    validate_success(
        api.create_unitization_event(
            pool["id"],
            {
                "event_kind": "BUY_IN",
                "fund_id": fund_id,
                "cash_amount": 25000.00,
                "expected_pool_version": pool["version"],
            },
            INVESTMENT,
        ),
        201,
    )
    after_buy = get_pool(pool["id"])
    validate_success(
        api.create_unitization_event(
            pool["id"],
            {
                "event_kind": "REDEMPTION",
                "fund_id": fund_id,
                "units_amount": 1250.0000,
                "expected_pool_version": after_buy["version"],
            },
            INVESTMENT,
        ),
        201,
    )
    fund_final = get_fund(fund_id)
    # 30000.00 - 25000.00 + round2(1250 * 20.0000) = 30000.00 exactly
    assert_money_eq(fund_final["cash_balance"], 30000.00, "fund cash conserved")


def test_buy_in_blocked_while_pool_suspended(api):
    """PRD §3.4: "Transactional events (`BUY_IN` and `REDEMPTION`) are accepted
    only while the pool is `OPEN`; against a `SUSPENDED` or `TERMINATED` pool
    they are rejected with `ERR_POOL_NOT_OPEN` (HTTP 409), and both carry the
    `expected_pool_version` guard of §2.8."

    Design: Corner/state_machines/pool_suspend_blocks_buyin
    """
    pool = create_pool(initial_nav=100000.00, initial_units=5000.0000)
    bundle = create_active_fund(fund_type="DESIGNATED", seed_amount=20000.00)
    validate_success(api.suspend_pool(pool["id"], INVESTMENT), 200)
    suspended = get_pool(pool["id"])
    resp = api.create_unitization_event(
        pool["id"],
        {
            "event_kind": "BUY_IN",
            "fund_id": bundle["fund"]["id"],
            "cash_amount": 1000.00,
            "expected_pool_version": suspended["version"],
        },
        INVESTMENT,
    )
    validate_error(resp, ApiErrorId.ERR_POOL_NOT_OPEN)


def test_terminate_pool_with_units_rejected(api):
    """PRD §3.4: "Suspension moves an `OPEN` pool to `SUSPENDED` and blocks
    transactional events, reopening returns a `SUSPENDED` pool to `OPEN`, and
    termination — permitted only when `units_outstanding` is exactly 0.0000,
    failing which the request is rejected with `ERR_POOL_NOT_EMPTY` (HTTP 409) —
    moves an `OPEN` pool to `TERMINATED`, which is terminal."

    Design: Corner/errors/err_pool_not_empty_triggerable
    """
    pool = create_pool(initial_nav=100000.00, initial_units=5000.0000)
    resp = api.terminate_pool(pool["id"], INVESTMENT)
    validate_error(resp, ApiErrorId.ERR_POOL_NOT_EMPTY)


def test_buy_in_with_stale_pool_version_rejected(api):
    """PRD §2.8: "Recording a `BUY_IN` or `REDEMPTION` unitization event
    requires the request to carry `expected_pool_version` matching the target
    pool's current `version`, because the unit price is a function of `nav` and
    `units_outstanding` that a prior mutation may have changed."
    PRD §2.8: "A mismatch is rejected with `ERR_STALE_POOL_VERSION` (HTTP 412)."

    Design: Corner/endpoints/occ_stale_pool_version_on_buyin
    """
    pool = create_pool(initial_nav=100000.00, initial_units=5000.0000)
    stale_version = pool["version"]
    # Two pool mutations advance the pool's version past the captured one.
    validate_success(api.suspend_pool(pool["id"], INVESTMENT), 200)
    validate_success(api.reopen_pool(pool["id"], INVESTMENT), 200)
    bundle = create_active_fund(fund_type="DESIGNATED", seed_amount=20000.00)
    resp = api.create_unitization_event(
        pool["id"],
        {
            "event_kind": "BUY_IN",
            "fund_id": bundle["fund"]["id"],
            "cash_amount": 1000.00,
            "expected_pool_version": stale_version,
        },
        INVESTMENT,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_POOL_VERSION)
