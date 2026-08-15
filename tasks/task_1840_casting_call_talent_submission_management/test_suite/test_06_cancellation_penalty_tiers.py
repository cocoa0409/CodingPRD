"""Cancellation penalty tiers: boundary inclusivity and pinned evaluation order
(PRD sections 2.6, 3.9).

All scenarios: offer weekly 1,000,000 / guarantee 800,000, CALENDAR_SPAN memo
with engagement 2026-08-20..2026-08-22; booking confirmed, then the logical
clock is moved to the cancellation date.
"""
from test_helpers import (
    setup_confirmed_booking,
    set_clock,
    validate_success,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]

GUARANTEE = 800_000


def _confirmed_booking_ctx():
    return setup_confirmed_booking(
        role_overrides={
            "engagement_start": "2026-08-20T00:00:00Z",
            "engagement_end": "2026-08-22T00:00:00Z",
        },
        accept_overrides={
            "engagement_start": "2026-08-20T00:00:00Z",
            "engagement_end": "2026-08-22T00:00:00Z",
            "proration_mode": "CALENDAR_SPAN",
        },
    )


def _cancel(api, booking_id, reason="PRODUCTION_CANCELLED"):
    return api.cancel_booking(booking_id, {"cancellation_reason": reason}, COORDINATOR)


class TestTierBoundaries:
    def test_seven_days_out_lands_in_25_percent_tier(self, api):
        """PRD section 3.9: "Third, pick the tier, whose boundaries are inclusive
        at the lower bound: fourteen or more days out carries a 0 percent penalty;
        seven through thirteen days out carries 25 percent; three through six days
        out carries 50 percent; zero through two days out carries 100 percent.
        Exactly seven days out lands at 25 percent; exactly fourteen lands at 0."

        Design: Difficulty/combinatorial_formula/cancellation_penalty_tiered_threshold_mode_a
        """
        ctx = _confirmed_booking_ctx()
        set_clock("2026-08-13T00:00:00Z")  # days_out == 7
        resp = _cancel(api, ctx["booking"]["id"])
        booking = validate_success(resp)
        assert booking["status"] == "CANCELLED"
        memo = validate_success(api.get_deal_memo(ctx["memo"]["id"], DIRECTOR))
        assert memo["cancellation_penalty_cents"] == 200_000, (
            "days_out == 7 falls inclusively into the 25% tier: 800000 * 25 / 100"
        )

    def test_six_days_out_lands_in_50_percent_tier(self, api):
        """PRD section 3.9: "Third, pick the tier, whose boundaries are inclusive
        at the lower bound: fourteen or more days out carries a 0 percent penalty;
        seven through thirteen days out carries 25 percent; three through six days
        out carries 50 percent; zero through two days out carries 100 percent."

        Design: Difficulty/combinatorial_formula/cancellation_penalty_tiered_threshold_mode_a
        """
        ctx = _confirmed_booking_ctx()
        set_clock("2026-08-14T00:00:00Z")  # days_out == 6
        resp = _cancel(api, ctx["booking"]["id"])
        booking = validate_success(resp)
        assert booking["status"] == "CANCELLED"
        memo = validate_success(api.get_deal_memo(ctx["memo"]["id"], DIRECTOR))
        assert memo["cancellation_penalty_cents"] == 400_000, (
            "days_out == 6 is below the 7-day inclusive boundary: 800000 * 50 / 100"
        )


class TestLateTierExactness:
    def test_one_day_out_returns_full_guarantee(self, api):
        """PRD section 3.9: "Third, pick the tier, whose boundaries are inclusive
        at the lower bound: fourteen or more days out carries a 0 percent penalty;
        seven through thirteen days out carries 25 percent; three through six days
        out carries 50 percent; zero through two days out carries 100 percent."
        PRD section 3.9: "First resolve the guarantee: follow the booking to its
        deal memo, follow the memo to its offer, and take that offer's
        `guarantee_cents`."
        PRD section 3.9: "Fourth, the penalty is the guarantee multiplied by the
        tier percentage and divided by one hundred — an exact integer, because
        offer guarantees were constrained to multiples of 100 cents at input
        time."

        Design: Difficulty/combinatorial_formula/cancellation_penalty_late_100pct_mode_b_rounding
        """
        ctx = _confirmed_booking_ctx()
        set_clock("2026-08-19T00:00:00Z")  # days_out == 1
        resp = _cancel(api, ctx["booking"]["id"], reason="TALENT_CANCELLED")
        booking = validate_success(resp)
        assert booking["status"] == "CANCELLED"
        assert booking.get("cancellation_reason") == "TALENT_CANCELLED"
        memo = validate_success(api.get_deal_memo(ctx["memo"]["id"], DIRECTOR))
        assert memo["cancellation_penalty_cents"] == 800_000, (
            "100% tier returns the full guarantee with zero rounding remainder"
        )

    def test_zero_days_out_still_full_guarantee(self, api):
        """PRD section 3.9: "Third, pick the tier, whose boundaries are inclusive
        at the lower bound: fourteen or more days out carries a 0 percent penalty;
        seven through thirteen days out carries 25 percent; three through six days
        out carries 50 percent; zero through two days out carries 100 percent."
        PRD section 3.9: "Second, count whole calendar days between the current
        logical clock's date and the memo's `engagement_start`; a negative count —
        cancelling after the engagement has begun — clamps to zero."
        PRD section 3.9: "Cancelling a `CONFIRMED` booking is the full unwind. The
        server stamps `cancelled_at`, computes the penalty onto the memo (below),
        recomputes the talent's `union_engagement_count_365d` — decrementing it if
        this booking's engagement fell inside the rolling window — and transitions
        any `PENDING` Taft-Hartley report referencing this booking to `WAIVED`."

        Design: Difficulty/combinatorial_formula/cancellation_penalty_late_100pct_mode_b_rounding
        """
        ctx = _confirmed_booking_ctx()
        set_clock("2026-08-20T00:00:00Z")  # days_out == 0 (the engagement start date)
        resp = _cancel(api, ctx["booking"]["id"])
        booking = validate_success(resp)
        assert booking["status"] == "CANCELLED"
        assert booking.get("cancelled_at") is not None, "cancelled_at stamped with the logical clock"
        memo = validate_success(api.get_deal_memo(ctx["memo"]["id"], DIRECTOR))
        assert memo["cancellation_penalty_cents"] == 800_000
