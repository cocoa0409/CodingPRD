"""Trade booking, Position recompute, and trade-level validations.

Citations refer to PRD.md §3.4.
"""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    assert_trade,
    book_trade,
    create_counterparty,
    create_trade_payload,
    make_trader_headers,
    setup_trader_with_limits,
    validate_error,
    validate_success,
)


# ===========================================================================
# Basic trade booking — PRD §3.4
# ===========================================================================
def test_book_trade_returns_booked_status_with_server_stamped_fields(api):
    """PRD §3.4: "The system stamps `executed_at` with the current server
    clock as an ISO 8601 UTC instant, and computes `trading_day` as the
    YYYY-MM-DD calendar date of that clock; both fields are server-stamped
    and never accepted from the caller. The trade enters `BOOKED` status."

    Claim: a successful trade returns status=BOOKED with server-stamped
    executed_at and trading_day fields.
    """
    ctx = setup_trader_with_limits()
    trade = book_trade(
        trader_id=ctx["trader"]["id"],
        pair_code=ctx["pair"]["code"],
        side="BUY",
        notional_base=1_000_000.00,
        entry_rate=1.000000,
        counterparty_id=ctx["counterparty"]["id"],
    )
    assert_trade(trade)
    assert trade["status"] == "BOOKED"
    assert trade["side"] == "BUY"
    assert trade["notional_base"] == 1_000_000.00


# ===========================================================================
# Trader-status gate (suspended) — PRD §3.4 / §2.9 priority 6
# ===========================================================================
def test_trade_booking_gated_by_trader_status(api):
    """PRD §3.4: "the trader's `status` must be `ACTIVE`, otherwise the
    trade is rejected with `ERR_TRADER_SUSPENDED`."

    To synthesize a SUSPENDED trader we use the depth-4 settlement-failure
    cascade described in PRD §3.7, then attempt /trades.

    Claim: trader.status==SUSPENDED → /trades returns ERR_TRADER_SUSPENDED.

    # difficulty: cross_entity_state_dependency/trade_booking_gated_by_trader_status
    """
    from test_helpers import (
        TEST_USERS,
        setup_sent_settlement_for_failure_cascade,
    )
    s = setup_sent_settlement_for_failure_cascade(
        counterparty_external_rating="BBB",
        counterparty_internal_score=44,
        notional_base=9_000_000.00,
        entry_rate=1.000000,
        pair_mid_rate=1.000000,
        intraday_cap=50_000_000.00,
    )
    # Trigger the cascade: /mark-failed with the canonical SettlementOperator.
    validate_success(
        api.mark_failed_settlement(
            s["sent_instruction"]["id"],
            TEST_USERS["settlement_operator_headers"],
        ),
        200,
    )
    # The trader should now be SUSPENDED. Confirm via GET.
    trader_after = validate_success(
        api.get_trader(s["ctx"]["trader"]["id"], s["ctx"]["trader_headers"]),
        200,
    )
    assert trader_after["status"] == "SUSPENDED", (
        f"PRD §3.7: settlement failure cascade must drive trader → "
        f"SUSPENDED when aggregate facing notional > new credit_limit; "
        f"got {trader_after['status']!r}"
    )
    # Now /trades MUST surface ERR_TRADER_SUSPENDED.
    # We need a NEW counterparty (existing one is now WATCH; PRD §3.4 also
    # blocks watch counterparties via the same code).
    new_cp = create_counterparty(external_rating="AAA", internal_score=90)
    res = api.create_trade(
        create_trade_payload(
            pair_code=s["ctx"]["pair"]["code"],
            side="BUY",
            notional_base=1.00,
            entry_rate=1.000000,
            counterparty_id=new_cp["id"],
        ),
        make_trader_headers(s["ctx"]["trader"]["id"]),
    )
    validate_error(
        res, ApiErrorId.ERR_TRADER_SUSPENDED.value, expected_status=409,
    )


# ===========================================================================
# Limit breach on trade — PRD §3.4 priority 9
# ===========================================================================
def test_trade_rejected_when_intraday_limit_would_be_breached(api):
    """PRD §3.4: "Then the trade's projected impact on `utilization_usd` is
    computed against the trader's effective caps in both `INTRADAY` and
    `OVERNIGHT` buckets; if either projection would exceed the bucket's
    `notional_cap_usd + temporary_override_usd`, the booking is rejected
    with `ERR_LIMIT_BREACH` (HTTP 409)."

    Claim: a trade whose projected notional would exceed intraday cap →
    ERR_LIMIT_BREACH (409).
    """
    ctx = setup_trader_with_limits(intraday_cap=1_000_000.00, overnight_cap=100_000_000.00)
    res = api.create_trade(
        create_trade_payload(
            pair_code=ctx["pair"]["code"],
            side="BUY",
            notional_base=1_500_000.00,
            entry_rate=1.000000,
            counterparty_id=ctx["counterparty"]["id"],
        ),
        ctx["trader_headers"],
    )
    validate_error(res, ApiErrorId.ERR_LIMIT_BREACH.value, expected_status=409)


def test_limit_breach_wins_over_counterparty_limit_breach(api):
    """PRD §2.9: "(9) fiscal checks raise `ERR_LIMIT_BREACH` or
    `ERR_COUNTERPARTY_LIMIT_BREACH`" — both are priority 9 in §2.9 prose,
    but PRD §1.4 / scaffold pin ERR_LIMIT_BREACH at priority 10 and
    ERR_COUNTERPARTY_LIMIT_BREACH at priority 11. PRD §3.4 confirms:
    "Then the trade's projected impact on `utilization_usd` is computed
    against the trader's effective caps ... if either projection would
    exceed ... the booking is rejected with `ERR_LIMIT_BREACH`. Then the
    aggregate notional facing the same counterparty ... is projected
    against `Counterparty.credit_limit_usd`; if it would exceed, the
    booking is rejected with `ERR_COUNTERPARTY_LIMIT_BREACH`."

    Claim: when BOTH would fail, the FIRST check (trader limit) fires →
    ERR_LIMIT_BREACH.

    # difficulty: priority_pair_validation_conflict/limit_breach_vs_counterparty_limit_breach_on_trade
    """
    # Trader with tiny INTRADAY cap, counterparty also tiny (WATCH band).
    from test_helpers import create_counterparty
    # B + 30 → both external SPECULATIVE and internal WATCH → WATCH band
    # → credit_limit_usd = 1M.
    # We need counterparty NOT on watchlist (else ERR_TRADER_SUSPENDED
    # would fire first per PRD §3.4 "The counterparty must not be on the
    # watchlist"). So use external=BB + internal=44 → SPECULATIVE band →
    # credit_limit_usd = 10M? No, we need credit_limit = 1M and NOT on
    # watchlist. Re-read: PRD §3.6 says "on_watchlist boolean is true if
    # and only if rating_band is WATCH". So a 1M credit limit IMPLIES
    # WATCH IMPLIES on_watchlist. Therefore the priority-pair test with
    # watch-tier credit_limit cannot avoid the §3.4 watchlist gate.
    # Use SPECULATIVE band (10M credit_limit) and arrange so an existing
    # 9.5M position + new 1M trade => 10.5M (exceeds counterparty 10M),
    # while INTRADAY cap=1M and existing 9.5M would also blow trader cap.
    cp = create_counterparty(external_rating="BB", internal_score=44)
    ctx = setup_trader_with_limits(
        intraday_cap=1_000_000.00,
        overnight_cap=100_000_000.00,
        counterparty_external_rating="AAA",  # placeholder, replaced below
    )
    # Use the new cp explicitly. Book 9 small trades all under 1M each but
    # they'd push utilization > cap on aggregate — actually the simpler
    # approach is to arrange the single test trade itself to breach BOTH.
    # Trade: notional_base=2,000,000 against cp (credit_limit=10M).
    # Aggregate facing cp after this trade = 2M < 10M → counterparty NOT
    # breached. So a single small trade can't blow both. We need pre-
    # existing aggregate notional facing cp via another trader.
    # Setup another trader (large caps) who already has 9.5M facing cp.
    # Then OUR trader, with cap=1M, attempts a 2M trade against cp:
    # - INTRADAY breach: 0+2M > 1M ✓
    # - Counterparty breach: 9.5M+2M > 10M ✓
    other = setup_trader_with_limits(
        intraday_cap=100_000_000.00,
        overnight_cap=100_000_000.00,
    )
    book_trade(
        trader_id=other["trader"]["id"],
        pair_code=other["pair"]["code"],
        side="BUY",
        notional_base=9_500_000.00,
        entry_rate=1.000000,
        counterparty_id=cp["id"],
    )
    res = api.create_trade(
        create_trade_payload(
            pair_code=ctx["pair"]["code"],
            side="BUY",
            notional_base=2_000_000.00,
            entry_rate=1.000000,
            counterparty_id=cp["id"],
        ),
        ctx["trader_headers"],
    )
    validate_error(
        res, ApiErrorId.ERR_LIMIT_BREACH.value, expected_status=409,
    )


# ===========================================================================
# Large-trade ComplianceReport emission — PRD §3.4 / §3.9
# ===========================================================================
def test_large_trade_emits_large_trade_report(api, compliance_officer_headers):
    """PRD §3.4: "If the trade's notional in USD lands at ten million USD or
    more — a threshold that is pinned at the constant ten-million-USD
    value — the system additionally emits a `ComplianceReport` of
    `report_type` `LARGE_TRADE` referencing the new trade, at `version`
    one greater than the prior largest `version` for the same
    (`report_type`, `reference_trade_id`) pair, defaulting to 1 on first
    emission."

    Claim: a 10M USD trade produces a LARGE_TRADE ComplianceReport with
    reference_trade_id == trade.id, at version 1.
    """
    ctx = setup_trader_with_limits(
        intraday_cap=50_000_000.00,
        overnight_cap=50_000_000.00,
        pair_mid_rate=1.000000,
    )
    trade = book_trade(
        trader_id=ctx["trader"]["id"],
        pair_code=ctx["pair"]["code"],
        side="BUY",
        notional_base=10_000_000.00,  # ten million USD at rate 1.0
        entry_rate=1.000000,
        counterparty_id=ctx["counterparty"]["id"],
    )
    reports_res = api.list_reports(
        compliance_officer_headers,
        params={"report_type": "LARGE_TRADE", "reference_trade_id": trade["id"]},
    )
    data = validate_success(reports_res, 200)
    rows = data if isinstance(data, list) else (data.get("reports") or data)
    rows = rows if isinstance(rows, list) else [rows]
    matching = [r for r in rows if r.get("reference_trade_id") == trade["id"]]
    assert matching, (
        "PRD §3.4: a 10M USD trade MUST emit a LARGE_TRADE ComplianceReport; "
        "none was returned"
    )
    r = matching[0]
    assert r["report_type"] == "LARGE_TRADE"
    assert r["version"] == 1
