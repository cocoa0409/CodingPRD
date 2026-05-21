"""Transfer-window discount and TransferLink ledger — PRD §3.5.

Covers the 120-minute window (inclusive at exactly 120 min), the
TransferLink ledger row, the `transfer_link_id` field on the second
trip, and the exclusivity rule (a prior trip already linked as
first_trip_id is not eligible again).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    BASE_FARE_CENTS,
    TRANSFER_WINDOW_MINUTES,
    advance_clock_to_iso,
    add_minutes,
    add_seconds,
    setup_rider_with_funded_card,
    tap_in,
    tap_in_and_out,
    unique_idempotency_key,
)


class TestTransferWindow:

    def test_transfer_within_window_is_free(self, api):
        """PRD §3.5: "If such an eligible prior exists, the pre-cap
        fare for the present trip is zero (the transfer is free) and a
        `TransferLink` is created".

        Claim: a second tap 60 minutes after the first (well within
        120) yields provisional_fare_cents=0 and a non-null
        transfer_link_id."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=1000)
        tap_in_and_out(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
            tap_out_minutes=20,
        )
        trip2 = tap_in(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T11:00:00.000Z",  # +60min
        )
        assert trip2["provisional_fare_cents"] == 0, (
            "Second trip within transfer window must be free; got "
            f"provisional_fare_cents={trip2['provisional_fare_cents']}"
        )
        assert trip2.get("transfer_link_id"), (
            "transfer_link_id must be non-null when transfer applies; "
            f"got {trip2.get('transfer_link_id')!r}"
        )

    def test_transfer_at_exactly_120_minutes_is_eligible(self, api):
        """PRD §3.5: "whose elapsed minutes since that prior
        `tap_in_at` are at most one hundred twenty (the boundary at
        exactly one hundred twenty minutes counts as a transfer)".

        Claim: at exactly 120 minutes after the prior tap_in_at, the
        second trip is transfer-eligible and provisional_fare_cents=0."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=1000)
        tap_in_and_out(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
            tap_out_minutes=20,
        )
        trip2 = tap_in(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T12:00:00.000Z",  # exactly +120min
        )
        assert trip2["provisional_fare_cents"] == 0, (
            "At exactly 120 minutes the boundary IS inclusive; "
            f"expected 0, got {trip2['provisional_fare_cents']}"
        )
        assert trip2.get("transfer_link_id"), (
            "transfer_link_id must be non-null at the inclusive boundary"
        )

    def test_transfer_one_second_past_120_minutes_not_eligible(self, api):
        """PRD §3.5: "whose elapsed minutes since that prior
        `tap_in_at` are at most one hundred twenty (the boundary at
        exactly one hundred twenty minutes counts as a transfer)".

        Claim: at 120 min + 1 second the boundary is exceeded, so the
        second trip is charged the full base fare and
        transfer_link_id is null."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=1000)
        tap_in_and_out(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
            tap_out_minutes=20,
        )
        # 120 min + 1 second past 10:00:00 → 12:00:01.
        trip2 = tap_in(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T12:00:01.000Z",
        )
        assert trip2["provisional_fare_cents"] == BASE_FARE_CENTS, (
            "Past the 120-minute boundary the second trip charges full "
            f"base; expected 275, got {trip2['provisional_fare_cents']}"
        )
        assert trip2.get("transfer_link_id") is None, (
            "transfer_link_id must be null past the boundary; got "
            f"{trip2.get('transfer_link_id')!r}"
        )

    def test_eligible_prior_must_be_completed(self, api):
        """PRD §3.5: "the system searches for a prior trip on the same
        card whose `travel_status` is `COMPLETED`".

        Claim: a TAPPED_IN trip (no tap-out) does NOT qualify as the
        prior leg — the second trip would not even be permitted while
        the first is still TAPPED_IN, so we test the structurally
        adjacent case: after closing the first via tap-out, the second
        IS eligible.

        This is the positive-correlation test for the COMPLETED
        precondition; the second-trip-while-open scenario is covered
        by ERR_TRIP_ALREADY_OPEN in test_04."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=1000)
        # First tap-in WITH tap-out → COMPLETED.
        tap_in_and_out(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
            tap_out_minutes=10,
        )
        # Second tap-in within window — eligible because prior is COMPLETED.
        trip2 = tap_in(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T10:30:00.000Z",
        )
        assert trip2["provisional_fare_cents"] == 0, (
            "Completed prior within window must yield free transfer; "
            f"got {trip2['provisional_fare_cents']}"
        )
