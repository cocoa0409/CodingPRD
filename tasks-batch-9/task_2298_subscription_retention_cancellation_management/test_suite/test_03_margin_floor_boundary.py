"""A blended term margin landing exactly on the plan floor.

The plan floor is 0.4048 and a forty-percent two-cycle discount on a 5000/2500 plan
blends out to exactly 0.4048.  The guardrail is a strict inequality, so the offer
must clear it and be acceptable without any compliance exception at all.
"""

import pytest

from test_helpers import (
    accept_grant,
    assert_margin_exception_consistency,
    assert_price_conserved,
    modifications_for,
    read_grant,
    read_session,
    read_subscriber,
    read_subscription,
    setup_grant_at_margin,
)

BOUNDARY_PLAN = {
    "monthly_price_cents": 5000,
    "unit_cogs_cents": 2500,
    "margin_floor_pct": 0.4048,
    "is_negative_option": False,
    "allowed_frequency_weeks": [4],
}
BOUNDARY_TEMPLATE = {
    "offer_type": "DISCOUNT",
    "discount_pct": 0.4000,
    "discount_cycles": 2,
    "priority_rank": 15,
}


def _grant_blended_exactly_on_the_floor():
    return setup_grant_at_margin(
        plan_overrides=dict(BOUNDARY_PLAN),
        template_overrides=dict(BOUNDARY_TEMPLATE),
        reason_code="FINANCIAL_HARDSHIP",
        clock="2026-01-10",
        as_user_id="rs_3",
        subscriber_overrides={"acquisition_channel": "ORGANIC"},
    )


class TestBlendedMarginOnTheFloor:

    def test_blended_margin_equal_to_the_floor_needs_no_exception(self):
        """0.4048 blended against a 0.4048 floor is not a breach.

        PRD §3.6: "`margin_exception_required` is true exactly when
        `blended_term_margin_pct` is **strictly less than** the `margin_floor_pct`
        of the subscription's current plan; a blended margin exactly equal to the
        floor does not require an exception."

        Design: Difficulty/boundary_precision_check/blended_margin_exactly_equal_to_plan_floor_clears_guardrail
        """
        world = _grant_blended_exactly_on_the_floor()
        grant = world["grant"]

        # Offer cycle bills round(5000 * 0.60) = 3000 against 2500 of goods.
        assert grant["per_cycle_margin_pct"] == pytest.approx(0.1667, abs=5e-5)
        # Term revenue 2 * 3000 + 3 * 5000 = 21000; term COGS 5 * 2500 = 12500.
        assert grant["retention_value_cents"] == 8500
        assert grant["blended_term_margin_pct"] == pytest.approx(0.4048, abs=5e-5)
        assert grant["blended_term_margin_pct"] == pytest.approx(
            world["plan"]["margin_floor_pct"], abs=5e-5)

        assert grant["margin_exception_required"] is False
        assert grant["margin_exception_state"] == "NOT_REQUIRED"
        assert grant["decided_by_user_id"] is None
        assert_margin_exception_consistency(grant)

        accepted = accept_grant(grant["id"], world["subscriber_headers"])
        assert accepted["state"] == "ACCEPTED"
        assert accepted["accepted_at"].startswith("2026-01-10T00:00:00")

    def test_acceptance_on_the_boundary_applies_the_discount_and_suppresses_marketing(self):
        """The accepted offer lands as an APPLIED modification and a 90-day quiet window.

        PRD §3.6: "A `SubscriptionModification` implementing the offer's lever is
        created directly in `APPLIED` and mutates the subscription, with its
        `save_offer_grant_id` naming this grant" and "The subscriber's
        `winback_suppressed_until` is set to the clock plus 90 days, so a subscriber
        we just saved is not immediately marketed to."

        Design: Difficulty/boundary_precision_check/blended_margin_exactly_equal_to_plan_floor_clears_guardrail
        """
        world = _grant_blended_exactly_on_the_floor()
        grant = world["grant"]

        accept_grant(grant["id"], world["subscriber_headers"])

        subscription = read_subscription(world["subscription"]["id"])
        assert subscription["active_discount_pct"] == pytest.approx(0.4000, abs=5e-5)
        assert subscription["discount_remaining_cycles"] == 2
        # round(5000 * 1 * 0.60) with no addons.
        assert subscription["committed_price_cents"] == 3000
        assert subscription["lifecycle_state"] == "ACTIVE"

        mods = modifications_for(subscription["id"])
        assert len(mods) == 1
        assert mods[0]["mod_type"] == "DISCOUNT_APPLY"
        assert mods[0]["state"] == "APPLIED"
        assert mods[0]["save_offer_grant_id"] == grant["id"]
        assert_price_conserved(subscription, mods)

        subscriber = read_subscriber(world["subscriber"]["id"])
        assert subscriber["winback_suppressed_until"].startswith("2026-04-10T00:00:00")

        session = read_session(world["session"]["id"])
        assert session["state"] == "OFFER_ACCEPTED"
        assert session["completed_at"].startswith("2026-01-10T00:00:00")

        assert read_grant(grant["id"])["state"] == "ACCEPTED"
