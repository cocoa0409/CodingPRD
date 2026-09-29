"""
Cross-aggregate propagation on the transfer desk.

Two multi-level chains are pinned here. The first runs downward from market
state: publishing a rate curve snapshot retires the incumbent, stales the
valuation runs priced off it, suspends the auctions those runs anchor and
lapses the live offers in those auctions, repainting the selling portfolio's
derived valuation freshness on the way past. The second runs outward from a
decision on a child: completing a servicing transfer flips the loans carried on
the awarded tape, bubbles up to the owning portfolio once none of its loans is
still active, and closes that portfolio's open hedge positions with their marks
realised. Each chain is walked link by link, its conditional and off-chain side
effects are pinned separately, and the rows each chain must leave alone are
pinned as negative controls.
"""

from test_helpers import (
    C, F, U,
    ApiClient, JsonDict,
    ERR_HEDGE_ALREADY_CLOSED, ERR_PACKAGE_NOT_ACCEPTING_BIDS,
    build_live_bid, build_published_package, build_ready_transfer,
    build_settled_trade, build_stratified_package,
    data_of, is_iso8601_timestamp, meta_of, rows_of, validate_error,
)

# A pool whose fourth loan carries no custodial balances at all, so that loan
# can be scrubbed off the tape while the swept funds still account for the
# whole pool at reconciliation.
_POOL_WITH_ONE_UNENCUMBERED_LOAN = [
    dict(C.LOANS_T[0]),
    dict(C.LOANS_T[1]),
    dict(C.LOANS_T[2]),
    dict(C.LOANS_T[3], escrow_balance_cents=0, suspense_balance_cents=0),
]


def _assert_instant(value, expected_prefix: str) -> None:
    """A stamped instant sits at the expected logical-clock moment."""
    assert value is not None, f"expected a stamp at {expected_prefix}, got null"
    assert is_iso8601_timestamp(value), f"not an ISO 8601 instant: {value!r}"
    assert value.startswith(expected_prefix), (
        f"expected an instant at {expected_prefix}, got {value!r}"
    )


def _read_curve(api: ApiClient, curve_id: str) -> JsonDict:
    """Read one rate curve snapshot as the desk that publishes them."""
    return data_of(api.get_rate_curve(curve_id, U.HEDGE))


def _exclude_line_for_loan(api: ApiClient, env: JsonDict, loan_id: str) -> None:
    """Scrub one loan off a stratified tape and refresh the cached tape."""
    line = next(
        row for row in env["tape_lines"] if row["loan_id"] == loan_id
    )
    F.set_tape_line_inclusion(api, line["id"], False,
                              exclusion_reason="INVESTOR_RESTRICTION")
    env["tape_lines"] = F.list_tape_lines(api, env["package_id"])
    env["included_loan_ids"] = [
        row["loan_id"] for row in env["tape_lines"] if row["included"]
    ]


# ---------------------------------------------------------------------------
# Publishing a rate curve snapshot: four links down to the live offer
# ---------------------------------------------------------------------------
def test_curve_publication_walks_all_four_supersession_links(api: ApiClient):
    """
    One curve publication retires the incumbent snapshot, stales the run bound to
    it, suspends the package that run anchors and lapses the live bid on it.

    PRD: "The fourth link kills the live offers in those auctions: every `Bid` on such a package whose status is `SUBMITTED`, `COUNTERED` or `REVISED` moves to `LAPSED` with its `version` incremented by 1; bids already `ACCEPTED`, `REJECTED` or `LAPSED` are untouched."

    Design: Difficulty/transitive_cascade/rate_curve_publication_cascades_four_levels_to_lapsed_bid
    """
    env = build_live_bid(api)

    curve_before = _read_curve(api, env["curve_id"])
    run_before = F.read_valuation_run(api, env["valuation_run_id"])
    package_before = F.read_package(api, env["package_id"])
    bid_before = F.read_bid(api, env["bid_id"])
    portfolio_before = F.read_portfolio(api, env["portfolio_id"])
    assert curve_before["status"] == "ACTIVE"
    assert curve_before["superseded_at"] is None
    assert run_before["status"] == "COMPLETED"
    assert run_before["staled_at"] is None
    assert package_before["status"] == "PUBLISHED"
    assert package_before["suspended_reason"] is None
    assert bid_before["status"] == "SUBMITTED"
    assert portfolio_before["valuation_freshness"] == "CURRENT"

    successor = F.create_rate_curve(api, C.CURVE_C2)
    assert successor["status"] == "ACTIVE"
    assert successor["superseded_at"] is None

    # Link one — the incumbent snapshot retires.
    curve = _read_curve(api, env["curve_id"])
    assert curve["status"] == "SUPERSEDED"
    _assert_instant(curve["superseded_at"], "2026-08-01T00:00:00")
    assert curve["version"] == curve_before["version"] + 1

    # Link two — the run priced off that snapshot goes stale, keeping its number.
    run = F.read_valuation_run(api, env["valuation_run_id"])
    assert run["status"] == "STALE"
    _assert_instant(run["staled_at"], "2026-08-01T00:00:00")
    assert run["value_cents"] == C.POOL_T_STATIC_VALUE_CENTS
    assert run["rate_curve_snapshot_id"] == env["curve_id"]
    assert run["version"] == run_before["version"] + 1

    # Link three — the auction that run anchors is suspended.
    package = F.read_package(api, env["package_id"])
    assert package["status"] == "BIDDING_SUSPENDED"
    assert package["suspended_reason"] == "VALUATION_STALE"
    assert package["version"] == package_before["version"] + 1

    # Link four — the live offer in that auction lapses.
    bid = F.read_bid(api, env["bid_id"])
    assert bid["status"] == "LAPSED"
    assert bid["version"] == bid_before["version"] + 1


def test_curve_publication_repaints_portfolio_freshness_only(api: ApiClient):
    """
    The staleness chain repaints the selling portfolio's derived valuation
    freshness without moving its lifecycle state or its frozen tape aggregates.

    PRD: "The second link stales the valuations that were priced off it: every `ValuationRun` whose bound snapshot is the one just superseded and whose status is `COMPLETED` moves `COMPLETED → STALE`, has `staled_at` stamped, and has its `version` incremented by 1; where such a run is the one a portfolio currently resolves to, that portfolio's `valuation_freshness` recomputes to `STALE`."

    Design: Difficulty/transitive_cascade/rate_curve_publication_cascades_four_levels_to_lapsed_bid
    """
    env = build_live_bid(api)

    before = F.read_portfolio(api, env["portfolio_id"])
    assert before["valuation_freshness"] == "CURRENT"
    assert before["status"] == "TAPE_LOCKED"

    F.create_rate_curve(api, C.CURVE_C2)

    after = F.read_portfolio(api, env["portfolio_id"])
    assert after["valuation_freshness"] == "STALE"
    assert after["status"] == "TAPE_LOCKED"
    assert after["loan_count"] == len(C.LOANS_T)
    assert after["total_upb_cents"] == C.POOL_T_TOTAL_UPB_CENTS
    assert after["custodial_funds_total_cents"] == C.POOL_T_CUSTODIAL_FUNDS_CENTS


def test_suspended_package_refuses_a_further_bid(api: ApiClient):
    """
    The suspension the staleness chain imposes is enforced, not cosmetic: the
    suspended package accepts no new offer.

    PRD: "The package must be `PUBLISHED`; a `DRAFT`, `STRATIFIED`, `BIDDING_SUSPENDED`, `AWARDED` or `CANCELLED` package accepts nothing and refuses with `ERR_PACKAGE_NOT_ACCEPTING_BIDS` (HTTP 409)."

    Design: Difficulty/transitive_cascade/rate_curve_publication_cascades_four_levels_to_lapsed_bid
    """
    env = build_live_bid(api)
    F.create_rate_curve(api, C.CURVE_C2)

    package = F.read_package(api, env["package_id"])
    assert package["status"] == "BIDDING_SUSPENDED"
    assert package["bid_count"] == 1

    response = api.create_bid(
        env["package_id"],
        {
            "bidder_id": env["buyer_id"],
            "price_bps": 118,
            "holdback_pct": 6,
            "expected_bid_package_version": package["version"],
        },
        env["buyer_headers"],
    )
    validate_error(response, ERR_PACKAGE_NOT_ACCEPTING_BIDS, 409)

    unchanged = F.read_package(api, env["package_id"])
    assert unchanged["bid_count"] == 1
    assert unchanged["version"] == package["version"]


def test_curve_publication_transitions_rows_in_place(api: ApiClient):
    """
    Every link of the staleness chain transitions the existing row rather than
    writing a replacement, so no extra run, package or bid appears.

    PRD: "Every entity a cascade touches has its own `updated_at` refreshed and its own `version` incremented by 1 — a cascade is not a silent write."

    Design: Difficulty/transitive_cascade/rate_curve_publication_cascades_four_levels_to_lapsed_bid
    """
    env = build_live_bid(api)
    F.create_rate_curve(api, C.CURVE_C2)

    bids = api.list_bids(U.MANAGER)
    assert meta_of(bids)["total_count"] == 1
    bid_rows = rows_of(bids)
    assert [row["id"] for row in bid_rows] == [env["bid_id"]]
    assert bid_rows[0]["status"] == "LAPSED"

    runs = api.list_valuation_runs(U.ANALYST)
    assert meta_of(runs)["total_count"] == 1
    run_rows = rows_of(runs)
    assert [row["id"] for row in run_rows] == [env["valuation_run_id"]]
    assert run_rows[0]["status"] == "STALE"

    packages = api.list_bid_packages(U.MANAGER)
    assert meta_of(packages)["total_count"] == 1
    package_rows = rows_of(packages)
    assert [row["id"] for row in package_rows] == [env["package_id"]]
    assert package_rows[0]["status"] == "BIDDING_SUSPENDED"

    curves = api.list_rate_curves(U.HEDGE)
    assert meta_of(curves)["total_count"] == 2


# ---------------------------------------------------------------------------
# Completing a servicing transfer: loans, then the portfolio, then the hedge
# ---------------------------------------------------------------------------
def test_transfer_completion_cascades_to_loans_portfolio_and_hedge(
        api: ApiClient):
    """
    Completing the transfer flips the tape loans, bubbles the portfolio to
    TRANSFERRED with its aggregates collapsed, and closes the open hedge with
    its mark realised.

    PRD: "Reaching `TRANSFERRED` in turn closes the hedge: every `HedgePosition` on that portfolio still `OPEN` moves to `CLOSED` with `closed_at`, `close_base_rate_bps` and `realized_pnl_cents` stamped exactly as a manual close would stamp them."

    Design: Difficulty/transitive_cascade/transfer_completion_cascades_loans_portfolio_and_open_hedge
    """
    env = build_settled_trade(api)

    opened = F.open_hedge(api, env["portfolio_id"], instrument="TBA_LONG",
                          notional_cents=260000, hedge_ratio_pct=60)
    assert opened["entry_base_rate_bps"] == 4000
    assert opened["status"] == "OPEN"
    assert opened["mark_to_market_cents"] == 0

    # The curve moves 50 bps against the long before the transfer completes.
    F.create_rate_curve(api, C.CURVE_C2)
    marked = F.read_hedge(api, opened["id"])
    assert marked["mark_to_market_cents"] == -3510

    build_ready_transfer(api, env)
    F.set_clock(api, C.CLOCK_TRANSFER_DAY)

    portfolio_before = F.read_portfolio(api, env["portfolio_id"])
    assert portfolio_before["status"] == "UNDER_CONTRACT"
    assert portfolio_before["total_upb_cents"] == C.POOL_T_TOTAL_UPB_CENTS
    assert portfolio_before["loan_count"] == len(C.LOANS_T)

    transfer = F.complete_transfer(api, env["transfer_id"])
    assert transfer["status"] == "COMPLETED"
    assert transfer["transferred_loan_count"] == len(C.LOANS_T)
    _assert_instant(transfer["completed_at"], "2026-09-01T00:00:00")

    # Level one — every loan on the awarded tape moves over.
    loans = F.list_loans(api, env["portfolio_id"])
    assert len(loans) == len(C.LOANS_T)
    for loan in loans:
        assert loan["status"] == "TRANSFERRED"
        _assert_instant(loan["transferred_at"], "2026-09-01T00:00:00")

    # Level two — the portfolio follows and its ACTIVE-only aggregates collapse.
    portfolio = F.read_portfolio(api, env["portfolio_id"])
    assert portfolio["status"] == "TRANSFERRED"
    assert portfolio["loan_count"] == 0
    assert portfolio["total_upb_cents"] == 0
    assert float(portfolio["weighted_avg_note_rate_pct"]) == 0.0

    # Level three — the open hedge closes with its mark realised.
    hedge = F.read_hedge(api, opened["id"])
    assert hedge["status"] == "CLOSED"
    assert hedge["close_base_rate_bps"] == 4050
    assert hedge["realized_pnl_cents"] == -3510
    _assert_instant(hedge["closed_at"], "2026-09-01T00:00:00")


def test_curve_publication_remarks_the_open_hedge_alongside(api: ApiClient):
    """
    Re-marking the hedge book is an off-chain side effect of publishing a
    snapshot: the open position takes a new mark but stays open and unrealised.

    PRD: "Alongside — but explicitly *not* part of that chain — publishing a snapshot re-marks the hedge book: every `HedgePosition` whose status is `OPEN` has `mark_to_market_cents` recomputed against the new `ACTIVE` snapshot."

    Design: Difficulty/transitive_cascade/transfer_completion_cascades_loans_portfolio_and_open_hedge
    """
    env = build_settled_trade(api)
    opened = F.open_hedge(api, env["portfolio_id"], instrument="TBA_LONG",
                          notional_cents=260000, hedge_ratio_pct=60)
    assert opened["entry_base_rate_bps"] == 4000
    assert opened["mark_to_market_cents"] == 0

    F.create_rate_curve(api, C.CURVE_C2)

    hedge = F.read_hedge(api, opened["id"])
    # 260000 applied at 60 percent, times the 4.5 duration factor of a TBA long,
    # times the 50 bps the curve rose against it, over 10,000.
    assert hedge["mark_to_market_cents"] == -3510
    assert hedge["status"] == "OPEN"
    assert hedge["closed_at"] is None
    assert hedge["close_base_rate_bps"] is None
    assert hedge["realized_pnl_cents"] is None


def test_completion_closed_hedge_refuses_a_second_close(api: ApiClient):
    """
    A position the completion cascade closed cannot be closed again, and its
    realised result stays frozen.

    PRD: "Closing a position requires it to be `OPEN` — a second close, including one aimed at a position already closed by the completion cascade, is refused with `ERR_HEDGE_ALREADY_CLOSED` (HTTP 409) — and requires an active curve."

    Design: Difficulty/transitive_cascade/transfer_completion_cascades_loans_portfolio_and_open_hedge
    """
    env = build_settled_trade(api)
    opened = F.open_hedge(api, env["portfolio_id"], instrument="TBA_LONG",
                          notional_cents=260000, hedge_ratio_pct=60)
    build_ready_transfer(api, env)
    F.set_clock(api, C.CLOCK_TRANSFER_DAY)
    F.complete_transfer(api, env["transfer_id"])

    closed = F.read_hedge(api, opened["id"])
    assert closed["status"] == "CLOSED"
    assert closed["close_base_rate_bps"] == 4000
    assert closed["realized_pnl_cents"] == 0

    response = api.close_hedge_position(opened["id"], U.HEDGE)
    validate_error(response, ERR_HEDGE_ALREADY_CLOSED, 409)

    after = F.read_hedge(api, opened["id"])
    assert after["status"] == "CLOSED"
    assert after["realized_pnl_cents"] == closed["realized_pnl_cents"]
    assert after["closed_at"] == closed["closed_at"]
    assert after["version"] == closed["version"]


def test_completion_leaves_the_awarded_marketing_rows_alone(api: ApiClient):
    """
    The completion cascade reaches the loans, the portfolio and the hedge, and
    leaves the awarded package and the accepted bid exactly where they were.

    PRD: "Cascades are also idempotent with respect to rows that are already in the target state: a row that does not match the stated source status is skipped, never re-stamped."

    Design: Difficulty/transitive_cascade/transfer_completion_cascades_loans_portfolio_and_open_hedge
    """
    env = build_ready_transfer(api)

    package_before = F.read_package(api, env["package_id"])
    bid_before = F.read_bid(api, env["bid_id"])
    run_before = F.read_valuation_run(api, env["valuation_run_id"])
    assert package_before["status"] == "AWARDED"
    assert bid_before["status"] == "ACCEPTED"

    F.set_clock(api, C.CLOCK_TRANSFER_DAY)
    transfer = F.complete_transfer(api, env["transfer_id"])
    assert transfer["status"] == "COMPLETED"

    package = F.read_package(api, env["package_id"])
    assert package["status"] == "AWARDED"
    assert package["version"] == package_before["version"]

    bid = F.read_bid(api, env["bid_id"])
    assert bid["status"] == "ACCEPTED"
    assert bid["version"] == bid_before["version"]

    run = F.read_valuation_run(api, env["valuation_run_id"])
    assert run["status"] == run_before["status"]
    assert run["version"] == run_before["version"]


def test_completion_holds_at_the_portfolio_while_a_loan_stays_active(
        api: ApiClient):
    """
    A loan scrubbed off the tape stays active, so the portfolio does not advance
    and its open hedge is not closed even though the transfer completed.

    PRD: "This chain is **conditional at its second link**: a loan that was excluded from the tape stays `ACTIVE`, and while any loan on the portfolio is `ACTIVE` the portfolio does not advance and the hedge positions are not closed."

    Design: Difficulty/transitive_cascade/transfer_completion_cascades_loans_portfolio_and_open_hedge
    """
    env = build_stratified_package(api, loans=_POOL_WITH_ONE_UNENCUMBERED_LOAN)
    held_back_loan_id = env["loan_ids"][3]
    _exclude_line_for_loan(api, env, held_back_loan_id)
    assert len(env["included_loan_ids"]) == 3

    build_published_package(api, env)
    build_ready_transfer(api, env)
    opened = F.open_hedge(api, env["portfolio_id"], instrument="TBA_LONG",
                          notional_cents=260000, hedge_ratio_pct=60)

    F.set_clock(api, C.CLOCK_TRANSFER_DAY)
    transfer = F.complete_transfer(api, env["transfer_id"])
    assert transfer["status"] == "COMPLETED"
    assert transfer["transferred_loan_count"] == 3

    loans = F.list_loans(api, env["portfolio_id"])
    moved = [loan for loan in loans if loan["status"] == "TRANSFERRED"]
    held = [loan for loan in loans if loan["status"] == "ACTIVE"]
    assert len(moved) == 3
    assert [loan["id"] for loan in held] == [held_back_loan_id]
    assert held[0]["transferred_at"] is None

    portfolio = F.read_portfolio(api, env["portfolio_id"])
    assert portfolio["status"] == "UNDER_CONTRACT"
    assert portfolio["loan_count"] == 1
    assert portfolio["total_upb_cents"] == 10000050

    hedge = F.read_hedge(api, opened["id"])
    assert hedge["status"] == "OPEN"
    assert hedge["closed_at"] is None
    assert hedge["realized_pnl_cents"] is None
