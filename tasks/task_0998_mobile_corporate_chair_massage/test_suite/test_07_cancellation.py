"""Booking cancellation: tiered fee by hours-until-start and cascades."""
from test_helpers import (
    add_claim,
    confirm_booking,
    get_chair,
    set_clock,
    setup_scheduling_booking,
    validate_success,
)


def _confirmed_booking_with_claims(api, num_claims=8):
    """Booking (120-min window, 15-min slots, 200c/min) CONFIRMED with
    ``num_claims`` CLAIMED claims: booked = 120, committed value = 24000."""
    ctx = setup_scheduling_booking(
        assign=True,
        booking_overrides={"window_duration_minutes": 120},
        therapist_overrides={"max_minutes_per_day": 2000},
    )
    chair_id = ctx["chairs"][0]["id"]
    for i in range(num_claims):
        add_claim(ctx, chair_id, f"R{i + 1}", f"r{i + 1}@x")
    confirm_booking(ctx, ctx["booking"]["id"])
    return ctx


class TestCancellationFeeTieredThresholds:
    def test_cancel_twelve_hours_before_start_charges_fifty_percent(self, api):
        """PRD §3.7: "The fee tier depends on the whole hours, rounded down,
        from the current moment until the event start — the `event_date` at
        `window_start_minutes`: fewer than 24 hours out, the fee is fifty
        percent of the committed value, floored to whole cents; at least 24
        hours but fewer than 72 hours, twenty-five percent; at least 72 hours
        but fewer than 168 hours — one week — ten percent; and at 168 hours
        or more, no fee at all."
        PRD §3.7: "Cancelling from `CONFIRMED` releases the same chairs —
        each release decrementing the therapist's booked-minutes tally for
        the `event_date` — waives every `PLANNED` travel leg on the booking,
        zeroing its `travel_fee_cents`, which in turn reduces the
        `travel_fees_cents` of any draft invoice already created for the
        booking, and assesses a fee on the booking's committed value, defined
        as `booked_chair_minutes` multiplied by `per_minute_rate_cents`."

        Design: Difficulty/combinatorial_formula/cancellation_fee_tiered_thresholds_mode_a
        """
        ctx = _confirmed_booking_with_claims(api, num_claims=8)
        # Event start 2026-06-10T10:00Z; clock at 2026-06-09T22:00Z -> H = 12 < 24.
        set_clock("2026-06-09T22:00:00Z")
        resp = api.cancel_booking(ctx["booking"]["id"], ctx["organizer"])
        booking = validate_success(resp, expected_status=200)
        assert booking["status"] == "CANCELLED"
        # floor(120 * 200 * 0.50) == 12000
        assert booking["cancellation_fee_cents"] == 12000, (
            f"Expected 50% of 24000 = 12000, got {booking['cancellation_fee_cents']}"
        )

    def test_cancel_from_confirmed_releases_chairs_and_waives_legs(self, api):
        """PRD §3.7: "Cancelling from `CONFIRMED` releases the same chairs —
        each release decrementing the therapist's booked-minutes tally for
        the `event_date` — waives every `PLANNED` travel leg on the booking,
        zeroing its `travel_fee_cents`, which in turn reduces the
        `travel_fees_cents` of any draft invoice already created for the
        booking, and assesses a fee on the booking's committed value, defined
        as `booked_chair_minutes` multiplied by `per_minute_rate_cents`."

        Design: Difficulty/combinatorial_formula/cancellation_fee_tiered_thresholds_mode_a
        """
        ctx = _confirmed_booking_with_claims(api, num_claims=8)
        chair_id = ctx["chairs"][0]["id"]
        set_clock("2026-06-09T22:00:00Z")
        validate_success(api.cancel_booking(ctx["booking"]["id"], ctx["organizer"]))
        assert get_chair(ctx, chair_id)["status"] == "RELEASED"
        legs = api.list_booking_travel_legs(
            ctx["booking"]["id"], ctx["admin"],
        ).json()["data"]
        assert len(legs) == 1, "Confirm must have created one travel leg for the therapist"
        assert legs[0]["status"] == "WAIVED"
        assert legs[0]["travel_fee_cents"] == 0, "Waived legs have their fee zeroed"


class TestCancellationFeeTwentyFourHourBoundary:
    def test_exactly_24_hours_before_start_charges_twenty_five_percent(self, api):
        """PRD §3.7: "The fee tier depends on the whole hours, rounded down,
        from the current moment until the event start — the `event_date` at
        `window_start_minutes`: fewer than 24 hours out, the fee is fifty
        percent of the committed value, floored to whole cents; at least 24
        hours but fewer than 72 hours, twenty-five percent; at least 72 hours
        but fewer than 168 hours — one week — ten percent; and at 168 hours
        or more, no fee at all."
        PRD §3.7: "assesses a fee on the booking's committed value, defined
        as `booked_chair_minutes` multiplied by `per_minute_rate_cents`."

        Design: Difficulty/boundary_precision_check/cancellation_fee_threshold_24h_inclusive
        """
        ctx = _confirmed_booking_with_claims(api, num_claims=8)
        # Clock exactly 24h before event start (2026-06-10T10:00Z): H == 24,
        # so the H < 24 tier does NOT apply; the 25% tier does.
        set_clock("2026-06-09T10:00:00Z")
        resp = api.cancel_booking(ctx["booking"]["id"], ctx["organizer"])
        booking = validate_success(resp, expected_status=200)
        assert booking["cancellation_fee_cents"] == 6000, (
            f"H == 24 falls in the 25% tier: expected 6000, "
            f"got {booking['cancellation_fee_cents']}"
        )

    def test_23_hours_before_start_charges_fifty_percent(self, api):
        """PRD §3.7: "The fee tier depends on the whole hours, rounded down,
        from the current moment until the event start — the `event_date` at
        `window_start_minutes`: fewer than 24 hours out, the fee is fifty
        percent of the committed value, floored to whole cents; at least 24
        hours but fewer than 72 hours, twenty-five percent; at least 72 hours
        but fewer than 168 hours — one week — ten percent; and at 168 hours
        or more, no fee at all."
        PRD §3.7: "assesses a fee on the booking's committed value, defined
        as `booked_chair_minutes` multiplied by `per_minute_rate_cents`."

        Design: Difficulty/boundary_precision_check/cancellation_fee_threshold_24h_inclusive
        """
        ctx = _confirmed_booking_with_claims(api, num_claims=8)
        # Clock at 2026-06-09T11:00Z -> H == 23 < 24 -> 50% tier.
        set_clock("2026-06-09T11:00:00Z")
        resp = api.cancel_booking(ctx["booking"]["id"], ctx["organizer"])
        booking = validate_success(resp, expected_status=200)
        assert booking["cancellation_fee_cents"] == 12000, (
            f"H == 23 is inside the 50% tier: expected 12000, "
            f"got {booking['cancellation_fee_cents']}"
        )


class TestCancelFromSchedulingCascade:
    def test_cascading_release_on_booking_cancel_from_scheduling(self, api):
        """PRD §3.7: "Cancelling from `SCHEDULING` is likewise free, and every
        `ASSIGNED` chair is set to `RELEASED`."

        Design: Corner/cross_cutting_layers/cascading_release_on_booking_cancel_from_scheduling
        """
        ctx = setup_scheduling_booking(assign=True)
        chair_id = ctx["chairs"][0]["id"]
        resp = api.cancel_booking(ctx["booking"]["id"], ctx["organizer"])
        booking = validate_success(resp, expected_status=200)
        assert booking["status"] == "CANCELLED"
        assert booking["cancellation_fee_cents"] == 0, "Cancelling from SCHEDULING is free"
        assert get_chair(ctx, chair_id)["status"] == "RELEASED"
