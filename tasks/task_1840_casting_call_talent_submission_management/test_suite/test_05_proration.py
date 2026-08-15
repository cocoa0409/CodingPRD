"""Engagement fee proration: dual variants, frozen fee, and the floor-division
constant order (PRD sections 2.6, 3.7).

Span used throughout: Friday 2026-08-07 through Tuesday 2026-08-11 inclusive.
CALENDAR_SPAN counts all 5 dates; WORKDAY_SPAN counts Fri/Mon/Tue = 3 dates.
Daily rate for weekly 1,000,000 cents is 200,000 (integer division by 5).
"""
from test_helpers import (
    assert_deal_memo,
    setup_accepted_memo,
    validate_success,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]

SPAN_START = "2026-08-07T00:00:00Z"  # Friday
SPAN_END = "2026-08-11T00:00:00Z"    # Tuesday
WEEKLY = 1_000_000
DAILY = 200_000


def _ctx_with_memo(proration_mode, weekly_rate=WEEKLY, span=(SPAN_START, SPAN_END)):
    return setup_accepted_memo(
        production_overrides={"union_signatory": True},
        role_overrides={
            "is_union_covered": True,
            "engagement_start": span[0],
            "engagement_end": span[1],
        },
        talent_overrides={"union_status": "UNION_MEMBER"},
        offer_overrides={"weekly_rate_cents": weekly_rate, "guarantee_cents": 800_000},
        accept_overrides={
            "engagement_start": span[0],
            "engagement_end": span[1],
            "proration_mode": proration_mode,
        },
    )


class TestDualVariantProration:
    def test_calendar_span_counts_weekend_days(self, api):
        """PRD section 3.7: "Under `CALENDAR_SPAN` — the common choice for daily
        and weekly players on film — every date in the span counts, weekends
        included."
        PRD section 3.7: "Acceptance moves the offer `EXTENDED → ACCEPTED` and, in
        the same operation, creates the deal memo in `EXECUTED` status."

        Design: Difficulty/dual_variant_calc/proration_calendar_vs_workday_span
        """
        ctx = _ctx_with_memo("CALENDAR_SPAN")
        memo = ctx["memo"]
        assert_deal_memo(memo)
        assert memo["computed_fee_cents"] == 5 * DAILY, (
            "5 calendar days (Fri..Tue) * 200000 daily rate"
        )
        assert memo["status"] == "EXECUTED"
        offer = validate_success(api.get_offer(ctx["offer"]["id"], DIRECTOR))
        assert offer["status"] == "ACCEPTED"

    def test_calendar_span_fee_frozen_on_reread(self, api):
        """PRD section 3.7: "The `computed_fee_cents` is frozen at memo creation
        and never recomputed afterward."

        Design: Difficulty/dual_variant_calc/proration_calendar_vs_workday_span
        """
        ctx = _ctx_with_memo("CALENDAR_SPAN")
        memo = ctx["memo"]
        assert memo["proration_mode"] == "CALENDAR_SPAN"
        assert memo["offer_id"] == ctx["offer"]["id"]
        reread = validate_success(api.get_deal_memo(memo["id"], DIRECTOR))
        assert reread["computed_fee_cents"] == 1_000_000, "frozen fee unchanged on re-read"

    def test_workday_span_excludes_weekend_days(self, api):
        """PRD section 3.7: "Under `WORKDAY_SPAN` — the common choice for episodic
        — only Monday-through-Friday dates count."

        Design: Difficulty/dual_variant_calc/proration_workday_span_smaller_fee
        """
        ctx = _ctx_with_memo("WORKDAY_SPAN")
        memo = ctx["memo"]
        assert_deal_memo(memo)
        assert memo["computed_fee_cents"] == 3 * DAILY, (
            "3 weekdays (Fri, Mon, Tue) * 200000 daily rate"
        )

    def test_workday_span_strictly_smaller_for_same_span(self, api):
        """PRD section 3.7: "The fee is the daily rate multiplied by the effective
        day count, an exact integer with no rounding after multiplication; an
        identical span under `WORKDAY_SPAN` yields a strictly smaller fee whenever
        the span contains a weekend day."

        Design: Difficulty/dual_variant_calc/proration_workday_span_smaller_fee
        """
        calendar_ctx = _ctx_with_memo("CALENDAR_SPAN")
        workday_ctx = _ctx_with_memo("WORKDAY_SPAN")
        calendar_fee = calendar_ctx["memo"]["computed_fee_cents"]
        workday_fee = workday_ctx["memo"]["computed_fee_cents"]
        assert calendar_fee == 1_000_000
        assert workday_fee == 600_000
        assert workday_fee < calendar_fee, "span 2026-08-07..2026-08-11 contains a weekend"


class TestProrationConstants:
    def test_daily_rate_floor_divided_before_multiplication(self, api):
        """PRD section 2.6: "Fee proration derives a daily rate by dividing the
        weekly rate by five workdays per union week using integer division,
        discarding any remainder; this floor division happens **before** any
        multiplication, and no rounding of any kind is applied after the
        multiplication."

        Design: Corner/calculations/engagement_fee_proration_constants_applied
        """
        ctx = setup_accepted_memo(
            role_overrides={
                "engagement_start": "2026-08-10T00:00:00Z",
                "engagement_end": "2026-08-10T00:00:00Z",
            },
            offer_overrides={"weekly_rate_cents": 1_000_003, "guarantee_cents": 800_000},
            accept_overrides={
                "engagement_start": "2026-08-10T00:00:00Z",  # Monday
                "engagement_end": "2026-08-10T00:00:00Z",
                "proration_mode": "WORKDAY_SPAN",
            },
        )
        memo = ctx["memo"]
        assert memo["computed_fee_cents"] == 200_000, (
            "floor_div(1000003, 5) = 200000 daily, times 1 weekday; the 3-cent remainder is discarded before multiplication"
        )
