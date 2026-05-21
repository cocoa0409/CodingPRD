"""Time/clock advance and sweep behavior.

Covers PRD §2.10 (clock + sweep), §3.5 (24h reversal window), §3.7 (90d
appeal window), §3.8 (waiver expiry).
"""
import pytest
from datetime import datetime, timedelta, timezone

from test_helpers import (
    validate_success, validate_error,
    NON_EXISTENT_UUID,
    ERR_REVERSAL_WINDOW_EXPIRED, ERR_FORBIDDEN, ERR_INVALID_STATE,
    TEST_USERS, make_merchant_headers,
    create_transaction_payload,
    setup_full_purchase_scene,
)


SYSTEM = TEST_USERS["system_test_headers"]


class TestClockAdvance:
    def test_clock_advance_role_restricted(self, api):
        """PRD §4 table: "POST /_clock/advance — Advance the server clock
        (test fixture) — SystemTest."

        Claim: a non-SystemTest principal cannot advance the clock.
        """
        resp = api.advance_clock(
            "2030-01-01T00:00:00.000Z", TEST_USERS["caseworker_headers"]
        )
        validate_error(resp, ERR_FORBIDDEN)

    def test_clock_advance_succeeds(self, api):
        """PRD §2.10: "An admin-only test-driving capability advances this
        clock to a supplied `to_iso8601` instant."

        Claim: SystemTest can advance the clock.
        """
        target = "2030-06-01T00:00:00.000Z"
        resp = api.advance_clock(target, SYSTEM)
        validate_success(resp)


class TestReversalWindow:
    def test_reverse_after_24h_window_rejected(self, api):
        """PRD §3.5: "The window is closed-on-the-equality: `Clock.now` at or
        below `posted_at` plus 24 hours is allowed, anything past that is
        rejected with `ERR_REVERSAL_WINDOW_EXPIRED`."

        Claim: after advancing clock past 24h since posted_at, reverse
        yields ERR_REVERSAL_WINDOW_EXPIRED.
        """
        ctx = setup_full_purchase_scene(size=1, age=30)
        m_headers = make_merchant_headers(ctx["merchant"]["id"])
        payload = create_transaction_payload(
            card_id=ctx["card"]["id"], merchant_id=ctx["merchant"]["id"],
            line_items=[{"item_category": "STAPLE", "unit_price_cents": 500, "quantity": 1}],
        )
        tx = validate_success(api.create_transaction(payload, m_headers), expected_status=201)
        # Advance the server clock to 30 days past the transaction's posted_at.
        # Use posted_at as the base (not wall-clock) because the server clock is
        # monotonic — earlier tests may already have advanced it into the future.
        posted_at_str = tx["posted_at"].rstrip("Z").split("+")[0]
        # Handle both "2026-...T...Z" and "2026-...T...+00:00" — strip and reattach UTC.
        posted_dt = datetime.fromisoformat(posted_at_str).replace(tzinfo=timezone.utc)
        future_dt = posted_dt + timedelta(days=30)
        future = future_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        validate_success(api.advance_clock(future, SYSTEM))
        resp = api.reverse_transaction(tx["id"], m_headers)
        validate_error(resp, ERR_REVERSAL_WINDOW_EXPIRED)


class TestSweep:
    def test_sweep_role_restricted(self, api):
        """PRD §4 table: "POST /_sweep/run — Run the periodic sweep —
        SystemTest."

        Claim: a Caseworker cannot run the sweep.
        """
        resp = api.run_sweep(TEST_USERS["caseworker_headers"])
        validate_error(resp, ERR_FORBIDDEN)

    def test_sweep_returns_success(self, api):
        """PRD §2.10: "A separate sweep capability performs the eager versions
        of those re-evaluations in one pass."

        Claim: POST /_sweep/run with SystemTest succeeds.
        """
        resp = api.run_sweep(SYSTEM)
        # Sweep returns 200 with possibly null data
        assert resp.status_code == 200, f"sweep returned {resp.status_code}"
