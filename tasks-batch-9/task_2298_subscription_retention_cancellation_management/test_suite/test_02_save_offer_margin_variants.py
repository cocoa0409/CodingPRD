"""The two margin readings a save-offer grant carries, and which one the guardrail uses.

A thirty-five percent discount for two cycles on a 4999/2100 plan looks unprofitable
read one cycle at a time and comfortable read across the offer plus the three
post-offer cycles.  Both figures land on the same grant, and only the blended one
decides whether a compliance exception is needed.
"""

import pytest

from test_helpers import (
    assert_margin_exception_consistency,
    assert_save_offer_grant,
    read_session,
    setup_grant_at_margin,
)

DISCOUNT_TEMPLATE = {
    "offer_type": "DISCOUNT",
    "discount_pct": 0.3500,
    "discount_cycles": 2,
    "priority_rank": 30,
    "min_tenure_days": 60,
    "expires_after_hours": 48,
}


def _grant_on_a_deep_two_cycle_discount():
    """Sign up on 2026-01-10, reach tenure 60 on 2026-03-11, present the one candidate."""
    return setup_grant_at_margin(
        plan_overrides={},
        template_overrides=dict(DISCOUNT_TEMPLATE),
        reason_code="PRICE",
        clock="2026-01-10",
        tenure_days=60,
        as_user_id="rs_1",
        subscriber_overrides={"acquisition_channel": "SEARCH"},
    )


class TestSaveOfferMarginVariants:

    def test_per_cycle_reading_is_pessimistic_while_the_blended_reading_clears_the_floor(self):
        """0.3536 on the first offer cycle, 0.5115 across the whole horizon.

        PRD §3.6: "`blended_term_margin_pct` is the guardrail margin: total term
        revenue minus total term cost of goods, divided by total term revenue,
        rounded half up to four decimal places, and exactly `0.0000` when total
        term revenue is zero." and "**The guardrail uses `blended_term_margin_pct`
        and never `per_cycle_margin_pct`.**"

        Design: Difficulty/dual_variant_calc/save_offer_margin_per_cycle_versus_blended_term_guardrail
        """
        world = _grant_on_a_deep_two_cycle_discount()
        grant = world["grant"]

        assert_save_offer_grant(grant)
        assert grant["save_offer_template_id"] == world["template"]["id"]

        # Offer cycle bills round(4999 * 0.65) = 3249 against 2100 of goods.
        assert grant["per_cycle_margin_pct"] == pytest.approx(0.3536, abs=5e-5)
        # Term revenue 2 * 3249 + 3 * 4999 = 21495; term COGS 5 * 2100 = 10500.
        assert grant["retention_value_cents"] == 10995
        assert grant["blended_term_margin_pct"] == pytest.approx(0.5115, abs=5e-5)

        # The plan floor is 0.4200: the per-cycle reading breaches it, the blended
        # reading does not, and only the blended reading is consulted.
        assert grant["per_cycle_margin_pct"] < 0.4200
        assert grant["blended_term_margin_pct"] > 0.4200
        assert grant["margin_exception_required"] is False
        assert grant["margin_exception_state"] == "NOT_REQUIRED"
        assert_margin_exception_consistency(grant)

    def test_presented_grant_records_its_presenter_and_a_forty_eight_hour_window(self):
        """The grant opens PRESENTED, expiring 48 hours after creation.

        PRD §3.6: "Its `expires_at` is its `created_at` plus the template's
        `expires_after_hours` hours." and "It moves the session from
        `REASON_CAPTURED` to `OFFERS_PRESENTED`, sets the session's
        `presented_by_user_id` to the acting `X-User-ID`, sets
        `offers_presented_count` to 1 and increments `step_count`."

        Design: Difficulty/dual_variant_calc/save_offer_margin_per_cycle_versus_blended_term_guardrail
        """
        world = _grant_on_a_deep_two_cycle_discount()
        grant = world["grant"]

        assert grant["state"] == "PRESENTED"
        assert grant["accepted_at"] is None
        assert grant["presented_by_user_id"] == "rs_1"
        # Presented at 2026-03-11 with a 48 hour template window.
        assert grant["expires_at"].startswith("2026-03-13T00:00:00")

        session = read_session(world["session"]["id"])
        assert session["state"] == "OFFERS_PRESENTED"
        assert session["presented_by_user_id"] == "rs_1"
        assert session["offers_presented_count"] == 1
        assert session["step_count"] == 3
        assert grant["cancellation_session_id"] == session["id"]
        assert grant["subscription_id"] == world["subscription"]["id"]
