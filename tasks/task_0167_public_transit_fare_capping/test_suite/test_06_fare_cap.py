"""DAILY/WEEKLY fare cap mechanics — PRD §2.9, §3.5.

Covers cap-period creation on first tap, accumulated_cents tracking,
cap-cents pinning (DAILY=600, WEEKLY=3300), cap_reached_at being set
when accumulated_cents reaches cap_cents, and the min(pre_cap_fare,
daily_remaining, weekly_remaining) cap-allocation rule.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    BASE_FARE_CENTS,
    DAILY_CAP_CENTS,
    WEEKLY_CAP_CENTS,
    advance_clock_to_iso,
    add_minutes,
    setup_rider_with_funded_card,
    tap_in,
    tap_in_and_out,
    unique_idempotency_key,
)


class TestFareCapAccumulation:

    def test_daily_cap_period_pinned_at_600_cents(self, api,
                                                   agency_officer_headers):
        """PRD §3.5: "if no `DAILY` `FareCapPeriod` exists for the UTC
        day containing `tap_in_at`, one is created with `cap_cents`
        pinned to the configured daily ceiling of 600 cents".

        Claim: after the first tap on a card, the DAILY cap period for
        that day has cap_cents=600."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=1000)
        tap_in_and_out(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
        )
        from test_helpers import get_cap_period_for_window
        cp = get_cap_period_for_window(
            card["id"], "DAILY", "2026-05-20T10:00:00.000Z",
        )
        assert cp is not None, (
            "DAILY cap period must be created on first tap-in"
        )
        assert cp["cap_cents"] == DAILY_CAP_CENTS, (
            f"DAILY cap_cents must be 600, got {cp['cap_cents']}"
        )

    def test_weekly_cap_period_pinned_at_3300_cents(self, api):
        """PRD §3.5: "if no `WEEKLY` `FareCapPeriod` exists for the ISO
        week containing `tap_in_at`, one is created with `cap_cents`
        pinned to the configured weekly ceiling of 3300 cents".

        Claim: after the first tap on a card, the WEEKLY cap period
        for that ISO week has cap_cents=3300."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=1000)
        tap_in_and_out(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
        )
        from test_helpers import get_cap_period_for_window
        cp = get_cap_period_for_window(
            card["id"], "WEEKLY", "2026-05-20T10:00:00.000Z",
        )
        assert cp is not None, (
            "WEEKLY cap period must be created on first tap-in"
        )
        assert cp["cap_cents"] == WEEKLY_CAP_CENTS, (
            f"WEEKLY cap_cents must be 3300, got {cp['cap_cents']}"
        )

    def test_accumulated_cents_sums_provisional_fares(self, api):
        """PRD §2.9: "`accumulated_cents` is the running sum of
        `provisional_fare_cents` for trips whose `tap_in_at` falls in
        the half-open window `[window_start, window_end)`, and it is
        mutated as a side effect of every trip creation".

        Claim: after two STANDARD tap-ins on the same UTC day (with no
        transfer), the DAILY cap period's accumulated_cents equals the
        sum of the two trips' provisional_fare_cents."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=1000)
        t1 = tap_in_and_out(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
        )
        t2 = tap_in_and_out(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T13:00:00.000Z",  # >120min, no transfer
        )
        from test_helpers import get_cap_period_for_window
        cp = get_cap_period_for_window(
            card["id"], "DAILY", "2026-05-20T10:00:00.000Z",
        )
        assert cp is not None
        expected = (t1["provisional_fare_cents"]
                    + t2["provisional_fare_cents"])
        assert cp["accumulated_cents"] == expected, (
            f"Expected accumulated_cents={expected}, got "
            f"{cp['accumulated_cents']}"
        )


class TestCapBinding:

    def test_cap_binds_partial_fare_at_boundary(self, api):
        """PRD §3.5: "the trip's `provisional_fare_cents` is the
        minimum of the pre-cap fare, the daily remaining, and the
        weekly remaining".

        Claim: after two STANDARD trips (cumulative 550 < 600), a
        third trip 3h later has pre_cap_fare=275 but daily_remaining=50
        — the third trip's provisional_fare_cents is bound at 50."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=10_000)
        tap_in_and_out(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
        )
        tap_in_and_out(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T13:00:00.000Z",
        )
        # Cumulative pre-third-tap = 550. Daily remaining = 50.
        trip3 = tap_in(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T16:00:00.000Z",
        )
        assert trip3["provisional_fare_cents"] == 50, (
            f"Cap-binding fare must be 50, got "
            f"{trip3['provisional_fare_cents']}"
        )

    def test_cap_reached_at_set_when_cap_reached(self, api):
        """PRD §2.9: "`cap_reached_at` is null while
        `accumulated_cents` is below `cap_cents`; the first moment
        `accumulated_cents` reaches `cap_cents`, that moment is
        written into `cap_reached_at`."

        Claim: after three taps cumulatively reach 600 (the DAILY
        cap), the period's cap_reached_at is non-null."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=10_000)
        tap_in_and_out(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
        )
        tap_in_and_out(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T13:00:00.000Z",
        )
        # 3rd tap brings cumulative to 600.
        t3 = tap_in_and_out(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T16:00:00.000Z",
        )
        from test_helpers import get_cap_period_for_window
        cp = get_cap_period_for_window(
            card["id"], "DAILY", "2026-05-20T10:00:00.000Z",
        )
        assert cp is not None
        assert cp["accumulated_cents"] == 600, (
            f"accumulated_cents should be 600 at cap, got "
            f"{cp['accumulated_cents']}"
        )
        assert cp.get("cap_reached_at") is not None, (
            "cap_reached_at must be set the first moment accumulated_cents"
            " reaches cap_cents; got null"
        )

    def test_cap_free_trip_after_cap_reached(self, api):
        """PRD §3.5: "the trip's `provisional_fare_cents` is the
        minimum of the pre-cap fare, the daily remaining, and the
        weekly remaining".

        Claim: a fourth tap after the DAILY cap is reached has
        daily_remaining=0, so its provisional_fare_cents=0."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=10_000)
        tap_in_and_out(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
        )
        tap_in_and_out(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T13:00:00.000Z",
        )
        tap_in_and_out(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T16:00:00.000Z",
        )
        # Cap is now full.
        t4 = tap_in(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T19:00:00.000Z",
        )
        assert t4["provisional_fare_cents"] == 0, (
            "Tap after DAILY cap reached must be cap-free; got "
            f"{t4['provisional_fare_cents']}"
        )
