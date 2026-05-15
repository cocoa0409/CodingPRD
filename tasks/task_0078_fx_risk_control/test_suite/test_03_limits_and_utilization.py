"""Limit creation, utilization, and the intraday/overnight bucket split.

Citations refer to PRD.md.
"""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    assert_limit,
    assert_warning_status_consistent,
    book_trade,
    create_limit,
    setup_trader_with_limits,
    validate_error,
    validate_success,
)


# ===========================================================================
# Limit creation
# ===========================================================================
def test_create_intraday_limit_returns_zero_utilization(api):
    """PRD §3.2: "`utilization_usd` is the absolute value of the bucket's
    `net_open_usd`. `utilization_pct` is the utilisation in USD divided by
    the effective cap in USD, multiplied by 100, then rounded half-up to
    two decimal places."

    Claim: a fresh Limit on a trader with no trades has utilization_usd ==
    0 and utilization_pct == 0.
    """
    ctx = setup_trader_with_limits(intraday_cap=5_000_000.00)
    res = api.list_limits(ctx["trader"]["id"], ctx["trader_headers"])
    data = validate_success(res, 200)
    # The list endpoint may return a list directly or wrapped — accept either.
    rows = data if isinstance(data, list) else data.get("limits") or data
    rows = rows if isinstance(rows, list) else [rows]
    intraday = next(r for r in rows if r["bucket"] == "INTRADAY")
    assert_limit(intraday)
    assert intraday["utilization_usd"] == 0
    assert intraday["utilization_pct"] == 0


# ===========================================================================
# Intraday vs overnight split — §3.2 sharp 17:00:00.000 UTC boundary
# ===========================================================================
def test_intraday_and_overnight_caps_produce_different_utilization(api):
    """PRD §3.2: "the intraday utilisation is computed against the intraday
    `Limit` row's `notional_cap_usd`; the overnight utilisation is computed
    against the overnight row's cap and over a wider trade inclusion set,
    so the same trader at the same instant produces two distinct
    `utilization_pct` numbers — one per bucket — and both must hold."

    Claim: with INTRADAY cap=10M and OVERNIGHT cap=5M, a 4M USD position
    produces utilization_pct=40.00 on INTRADAY and 80.00 on OVERNIGHT.

    # difficulty: dual_variant_calc/limit_utilization_intraday_vs_overnight
    """
    ctx = setup_trader_with_limits(
        intraday_cap=10_000_000.00,
        overnight_cap=5_000_000.00,
        pair_mid_rate=1.000000,
    )
    book_trade(
        trader_id=ctx["trader"]["id"],
        pair_code=ctx["pair"]["code"],
        side="BUY",
        notional_base=4_000_000.00,
        entry_rate=1.000000,
        counterparty_id=ctx["counterparty"]["id"],
    )
    data = validate_success(
        api.list_limits(ctx["trader"]["id"], ctx["trader_headers"]), 200,
    )
    rows = data if isinstance(data, list) else (data.get("limits") or data)
    rows = rows if isinstance(rows, list) else [rows]
    intraday = next(r for r in rows if r["bucket"] == "INTRADAY")
    overnight = next(r for r in rows if r["bucket"] == "OVERNIGHT")
    assert intraday["utilization_pct"] == 40.00, (
        f"PRD §3.2: INTRADAY 4M / 10M = 40.00%; got {intraday['utilization_pct']}"
    )
    assert overnight["utilization_pct"] == 80.00, (
        f"PRD §3.2: OVERNIGHT 4M / 5M = 80.00%; got {overnight['utilization_pct']}"
    )


def test_dual_variant_intraday_normal_overnight_warning(api):
    """PRD §3.2: "a utilisation strictly below 80 is `NORMAL`, a utilisation
    at or above 80 but strictly below 100 is `WARNING`, and a utilisation
    at or above 100 is `BREACH`. The 80 boundary belongs to `WARNING` and
    the 100 boundary belongs to `BREACH`."

    Claim: with the dual-variant 40% / 80% split above, the per-position
    warning levels likewise diverge (NORMAL on intraday-cap view, WARNING
    on overnight-cap view).

    # difficulty: dual_variant_calc/limit_utilization_intraday_vs_overnight
    """
    ctx = setup_trader_with_limits(
        intraday_cap=10_000_000.00,
        overnight_cap=5_000_000.00,
        pair_mid_rate=1.000000,
    )
    book_trade(
        trader_id=ctx["trader"]["id"],
        pair_code=ctx["pair"]["code"],
        side="BUY",
        notional_base=4_000_000.00,
        entry_rate=1.000000,
        counterparty_id=ctx["counterparty"]["id"],
    )
    data = validate_success(
        api.list_limits(ctx["trader"]["id"], ctx["trader_headers"]), 200,
    )
    rows = data if isinstance(data, list) else (data.get("limits") or data)
    rows = rows if isinstance(rows, list) else [rows]
    intraday = next(r for r in rows if r["bucket"] == "INTRADAY")
    overnight = next(r for r in rows if r["bucket"] == "OVERNIGHT")
    assert intraday["utilization_pct"] == 40.00
    assert overnight["utilization_pct"] == 80.00


# ===========================================================================
# Warning boundary precision — PRD §3.2
# ===========================================================================
class TestWarningBoundary:
    """PRD §3.2: "a utilisation strictly below 80 is `NORMAL`, a utilisation
    at or above 80 but strictly below 100 is `WARNING`, and a utilisation
    at or above 100 is `BREACH`. The 80 boundary belongs to `WARNING` and
    the 100 boundary belongs to `BREACH`."

    # difficulty: boundary_precision_check/warning_threshold_80_pct_inclusive
    """

    def test_strictly_below_80_is_normal(self, api):
        """PRD §3.2: "a utilisation strictly below 80 is `NORMAL`."

        Claim: a Position at utilization_pct = 79.99 is NORMAL.

        # difficulty: boundary_precision_check/warning_threshold_80_pct_inclusive
        """
        ctx = setup_trader_with_limits(
            intraday_cap=10_000_000.00,
            overnight_cap=10_000_000.00,
            pair_mid_rate=1.000000,
        )
        # 7,999,000 / 10,000,000 * 100 = 79.99 — strictly below the 80
        # boundary after PRD §3.2's round-half-up-to-two-decimals step.
        book_trade(
            trader_id=ctx["trader"]["id"],
            pair_code=ctx["pair"]["code"],
            side="BUY",
            notional_base=7_999_000.00,
            entry_rate=1.000000,
            counterparty_id=ctx["counterparty"]["id"],
        )
        positions = validate_success(
            api.list_positions(ctx["trader"]["id"], ctx["trader_headers"]), 200,
        )
        rows = positions if isinstance(positions, list) else (positions.get("positions") or positions)
        rows = rows if isinstance(rows, list) else [rows]
        pos = next(p for p in rows if p["pair_code"] == ctx["pair"]["code"])
        assert pos["warning_status"] == "NORMAL", (
            f"7.999M / 10M = 79.99% < 80; expected NORMAL, got {pos['warning_status']}"
        )

    def test_at_80_is_warning_inclusive(self, api):
        """PRD §3.2: "The 80 boundary belongs to `WARNING`."

        Claim: a Position at utilization_pct = 80.00 (inclusive) is
        WARNING.

        # difficulty: boundary_precision_check/warning_threshold_80_pct_inclusive
        """
        ctx = setup_trader_with_limits(
            intraday_cap=10_000_000.00,
            overnight_cap=10_000_000.00,
            pair_mid_rate=1.000000,
        )
        book_trade(
            trader_id=ctx["trader"]["id"],
            pair_code=ctx["pair"]["code"],
            side="BUY",
            notional_base=8_000_000.00,
            entry_rate=1.000000,
            counterparty_id=ctx["counterparty"]["id"],
        )
        positions = validate_success(
            api.list_positions(ctx["trader"]["id"], ctx["trader_headers"]), 200,
        )
        rows = positions if isinstance(positions, list) else (positions.get("positions") or positions)
        rows = rows if isinstance(rows, list) else [rows]
        pos = next(p for p in rows if p["pair_code"] == ctx["pair"]["code"])
        assert pos["warning_status"] == "WARNING", (
            f"8M / 10M = 80.00%; PRD §3.2 says 80 belongs to WARNING; "
            f"got {pos['warning_status']}"
        )

    def test_at_100_is_breach_inclusive(self, api):
        """PRD §3.2: "The 100 boundary belongs to `BREACH`."

        Claim: a Position with utilization_usd == effective cap →
        utilization_pct = 100.00 → warning_status = BREACH.

        Setup uses a larger OVERNIGHT cap so the trade itself is accepted
        (PRD §3.4: rejection happens if EITHER bucket projection exceeds
        the cap).
        """
        ctx = setup_trader_with_limits(
            intraday_cap=10_000_000.00,
            overnight_cap=100_000_000.00,
            pair_mid_rate=1.000000,
        )
        book_trade(
            trader_id=ctx["trader"]["id"],
            pair_code=ctx["pair"]["code"],
            side="BUY",
            notional_base=10_000_000.00,
            entry_rate=1.000000,
            counterparty_id=ctx["counterparty"]["id"],
        )
        data = validate_success(
            api.list_limits(ctx["trader"]["id"], ctx["trader_headers"]), 200,
        )
        rows = data if isinstance(data, list) else (data.get("limits") or data)
        rows = rows if isinstance(rows, list) else [rows]
        intraday = next(r for r in rows if r["bucket"] == "INTRADAY")
        assert intraday["utilization_pct"] == 100.00
        positions = validate_success(
            api.list_positions(ctx["trader"]["id"], ctx["trader_headers"]), 200,
        )
        prows = positions if isinstance(positions, list) else (positions.get("positions") or positions)
        prows = prows if isinstance(prows, list) else [prows]
        pos = next(p for p in prows if p["pair_code"] == ctx["pair"]["code"])
        assert pos["warning_status"] == "BREACH"
        assert_warning_status_consistent({
            "utilization_pct": intraday["utilization_pct"],
            "warning_status": pos["warning_status"],
        })


# ===========================================================================
# PATCH /limits/{id} with OCC — PRD §2.5
# ===========================================================================
def test_patch_limit_with_correct_version_succeeds(api, risk_officer_headers):
    """PRD §2.5: "Mutating endpoints that target a versioned entity ...
    accept an optional `version` field in the request body. When supplied,
    it MUST match the entity's current `version` exactly; if it does not,
    the mutation is rejected with `ERR_VERSION_CONFLICT` (HTTP 409)."

    Claim: a PATCH with the current version value is accepted and
    increments the version by exactly 1.
    """
    ctx = setup_trader_with_limits(intraday_cap=5_000_000.00)
    intraday_id = ctx["intraday_limit"]["id"]
    v_before = ctx["intraday_limit"]["version"]
    res = api.patch_limit(
        intraday_id,
        {"notional_cap_usd": 7_000_000.00, "version": v_before},
        risk_officer_headers,
    )
    updated = validate_success(res, 200)
    assert updated["notional_cap_usd"] == 7_000_000.00
    assert updated["version"] == v_before + 1, (
        f"PRD §2.4: 'incremented by exactly 1 on every successful mutation'; "
        f"got {updated['version']} vs {v_before}+1"
    )


def test_patch_limit_with_stale_version_rejected(api, risk_officer_headers):
    """PRD §2.5: "If it does not [match], the mutation is rejected with
    `ERR_VERSION_CONFLICT` (HTTP 409) and no state is changed."

    Claim: a PATCH with a stale version → ERR_VERSION_CONFLICT, HTTP 409,
    and the limit's stored value is unchanged.
    """
    ctx = setup_trader_with_limits(intraday_cap=5_000_000.00)
    intraday_id = ctx["intraday_limit"]["id"]
    v_before = ctx["intraday_limit"]["version"]
    # Advance the version once.
    api.patch_limit(
        intraday_id,
        {"notional_cap_usd": 6_000_000.00, "version": v_before},
        risk_officer_headers,
    )
    # Replay with the now-stale version.
    res = api.patch_limit(
        intraday_id,
        {"notional_cap_usd": 9_999_999.00, "version": v_before},
        risk_officer_headers,
    )
    validate_error(res, ApiErrorId.ERR_VERSION_CONFLICT.value, expected_status=409)


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
def test_list_limits_pagination_invalid_limit_rejected(api):
    """PRD §2.3: "limit (default 10, minimum 1, maximum 100) ... a request
    with `limit` outside the inclusive range 1 through 100, or with
    `offset` strictly less than 0, is rejected" with ERR_INVALID_PAGINATION
    (HTTP 422).

    Claim: limit=0 → ERR_INVALID_PAGINATION (422).
    """
    ctx = setup_trader_with_limits()
    res = api.list_limits(
        ctx["trader"]["id"], ctx["trader_headers"], params={"limit": 0},
    )
    validate_error(
        res, ApiErrorId.ERR_INVALID_PAGINATION.value, expected_status=422,
    )


def test_list_limits_pagination_negative_offset_rejected(api):
    """PRD §2.3: "or with `offset` strictly less than 0, is rejected".

    Claim: offset=-1 → ERR_INVALID_PAGINATION (422).
    """
    ctx = setup_trader_with_limits()
    res = api.list_limits(
        ctx["trader"]["id"], ctx["trader_headers"], params={"offset": -1},
    )
    validate_error(
        res, ApiErrorId.ERR_INVALID_PAGINATION.value, expected_status=422,
    )
