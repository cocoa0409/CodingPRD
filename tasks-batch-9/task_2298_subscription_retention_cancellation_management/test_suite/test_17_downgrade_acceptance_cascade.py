"""Accepting a plan-downgrade offer cascades to four entities at once.

The grant, a fresh modification, the still-open invoice and a statutory notice all move
inside the one acceptance call, and the subscriber picks up a suppression window on top.
The downgrade drops an addon the target plan does not carry, so the repriced invoice has
a single line.
"""

import pytest

from test_helpers import (
    accept_grant,
    assert_instant,
    assert_line_items_pinned_order,
    assert_lines_sum_to_amount,
    assert_price_conserved,
    modifications_for,
    new_core_plan,
    new_lite_plan,
    new_template,
    notice_of_type,
    present_offers,
    read_grant,
    read_invoice,
    read_session,
    read_subscriber,
    read_subscription,
    set_clock,
    setup_active_subscription,
    setup_reason_captured_session,
)

DOWNGRADE_OFFER = {
    "offer_type": "PLAN_DOWNGRADE",
    "priority_rank": 40,
    "eligible_reason_codes": ["PRODUCT_FIT"],
}


@pytest.fixture
def presented_downgrade_offer():
    """CORE + MUG signed up 2026-01-10 with the invoice still OPEN; grant presented 2026-01-24."""
    lite = new_lite_plan()
    core = new_core_plan(downgrade_target_plan_id=lite["id"])
    new_template(code="DOWNGRADE_FIT", **DOWNGRADE_OFFER)

    world = setup_active_subscription(
        clock="2026-01-10", plan=core,
        subscriber_overrides={"acquisition_channel": "REFERRAL"},
        addons=[{"code": "MUG", "qty": 1}])

    set_clock("2026-01-24")
    session = setup_reason_captured_session(world, reason_code="PRODUCT_FIT",
                                            entry_channel="AGENT_ASSISTED")
    world["lite"] = lite
    world["grant"] = present_offers(session["id"], as_user_id="rs_7")
    return world


class TestDowngradeAcceptanceCascade:

    def test_acceptance_creates_the_applied_downgrade_and_repoints_the_subscription(self,
                                                                                   presented_downgrade_offer):
        """A downgrade offer prices its whole horizon on the target plan, then lands as APPLIED.

        PRD §3.6: "A `SubscriptionModification` implementing the offer's lever is created
        directly in `APPLIED` and mutates the subscription, with its `save_offer_grant_id`
        naming this grant; a `PLAN_DOWNGRADE` acceptance additionally re-prices the
        subscription's `OPEN` invoice from the target plan under the mid-cycle repricing
        variant and schedules a `PRICE_CHANGE` notice."

        Design: Difficulty/transitive_cascade/downgrade_acceptance_cascade_grant_subscription_invoice_notice
        """
        world = presented_downgrade_offer
        grant = world["grant"]

        # Three post-offer cycles at 2999 against 1400, and no offer cycle at all.
        assert grant["per_cycle_margin_pct"] == pytest.approx(0.5332, abs=5e-5)
        assert grant["blended_term_margin_pct"] == pytest.approx(0.5332, abs=5e-5)
        assert grant["retention_value_cents"] == 4797
        assert grant["margin_exception_required"] is False
        assert grant["margin_exception_state"] == "NOT_REQUIRED"

        accepted = accept_grant(grant["id"], world["subscriber_headers"])
        assert accepted["state"] == "ACCEPTED"
        assert_instant(accepted["accepted_at"], "2026-01-24T00:00:00Z", "accepted_at")
        assert read_grant(grant["id"])["state"] == "ACCEPTED"

        downgrades = modifications_for(world["subscription"]["id"], mod_type="PLAN_DOWNGRADE")
        assert len(downgrades) == 1
        assert downgrades[0]["state"] == "APPLIED"
        assert downgrades[0]["target_plan_id"] == world["lite"]["id"]
        assert downgrades[0]["save_offer_grant_id"] == grant["id"]
        # 2999 committed on the target plan against 6298 before, with MUG dropped.
        assert downgrades[0]["delta_price_cents"] == -3299
        assert_instant(downgrades[0]["applied_at"], "2026-01-24T00:00:00Z", "applied_at")

        subscription = read_subscription(world["subscription"]["id"])
        assert subscription["plan_id"] == world["lite"]["id"]
        assert subscription["addons"] == []
        assert subscription["committed_price_cents"] == 2999
        assert subscription["lifecycle_state"] == "ACTIVE"
        assert_price_conserved(subscription, modifications_for(subscription["id"]))

    def test_acceptance_reprices_the_open_invoice_and_schedules_the_price_change_notice(self,
                                                                                       presented_downgrade_offer):
        """Fourteen of twenty-eight days remain, so the target plan bills at half.

        PRD §3.4: "When an `OPEN` invoice is re-priced mid-cycle, it is instead the
        remaining days divided by the cycle length in days, rounded half up to four
        decimal places, where the remaining days is the difference between
        `next_renewal_at` and the clock expressed in days and rounded **down** to a whole
        number." and PRD §3.3: "If the subscription has an `OPEN` invoice at that moment,
        that invoice is re-priced from the target plan under the mid-cycle repricing rules
        of §3.4, and a `PRICE_CHANGE` notice is created `SCHEDULED` with `scheduled_for`
        one day after the clock."

        Design: Difficulty/transitive_cascade/downgrade_acceptance_cascade_grant_subscription_invoice_notice
        """
        world = presented_downgrade_offer

        accept_grant(world["grant"]["id"], world["subscriber_headers"])

        invoice = read_invoice(world["invoice"]["id"])
        assert invoice["status"] == "OPEN"
        assert invoice["proration_factor"] == pytest.approx(0.5000, abs=5e-5)
        # 2999 * 0.5 rounds half up to 1500; 1400 * 0.5 rounds half up to 700.
        assert invoice["amount_cents"] == 1500
        assert invoice["cogs_cents"] == 700
        # MUG is absent from the target plan's catalogue, so only the plan line survives.
        assert len(invoice["line_items"]) == 1
        assert_line_items_pinned_order(invoice)
        assert_lines_sum_to_amount(invoice)

        notice = notice_of_type(world["subscription"]["id"], "PRICE_CHANGE")
        assert notice["state"] == "SCHEDULED"
        assert_instant(notice["scheduled_for"], "2026-01-25T00:00:00Z", "scheduled_for")
        assert notice["sent_at"] is None

        session = read_session(world["session"]["id"])
        assert session["state"] == "OFFER_ACCEPTED"
        assert_instant(session["completed_at"], "2026-01-24T00:00:00Z", "completed_at")

        subscriber = read_subscriber(world["subscriber"]["id"])
        assert_instant(subscriber["winback_suppressed_until"], "2026-04-24T00:00:00Z",
                       "winback_suppressed_until")
