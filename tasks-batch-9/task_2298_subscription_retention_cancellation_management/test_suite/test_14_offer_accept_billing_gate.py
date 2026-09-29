"""Accepting a discount offer is gated by the subscription's billing axis.

The selector picks between two equally ranked templates on the blended margin, and the
grant it produces is perfectly valid — but while the signup invoice sits failed the
acceptance is refused.  Collecting the money reopens exactly the same acceptance.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    accept_grant,
    api_client,
    assert_instant,
    charge_invoice,
    modifications_for,
    new_core_plan,
    new_template,
    pay_invoice,
    present_offers,
    read_grant,
    read_invoice,
    read_session,
    read_subscriber,
    read_subscription,
    setup_active_subscription,
    setup_reason_captured_session,
    validate_error,
)

SHALLOWER_OFFER = {"offer_type": "DISCOUNT", "discount_pct": 0.2000, "discount_cycles": 2,
                   "priority_rank": 50, "eligible_reason_codes": ["OTHER"]}
DEEPER_OFFER = {"offer_type": "DISCOUNT", "discount_pct": 0.1000, "discount_cycles": 2,
                "priority_rank": 50, "eligible_reason_codes": ["OTHER"]}


@pytest.fixture
def past_due_subscription_holding_a_presented_discount():
    """Signup 2026-01-10 on the 4999/2100 plan, invoice soft-declined, one grant presented."""
    plan = new_core_plan()
    shallower = new_template(code="OTHERA", **SHALLOWER_OFFER)
    deeper = new_template(code="OTHERB", **DEEPER_OFFER)

    world = setup_active_subscription(
        clock="2026-01-10", plan=plan,
        subscriber_overrides={"acquisition_channel": "SEARCH"})
    charge_invoice(world["invoice"]["id"], "SOFT_DECLINE", "INSUFFICIENT_FUNDS")

    session = setup_reason_captured_session(world, reason_code="OTHER")
    world["shallower"] = shallower
    world["deeper"] = deeper
    world["grant"] = present_offers(session["id"], as_user_id="rs_1")
    return world


class TestOfferAcceptBillingGate:

    def test_a_past_due_subscription_may_not_accept_a_discount(self,
                                                               past_due_subscription_holding_a_presented_discount):
        """The equal-rank tie goes to the healthier blended margin, and the accept is refused.

        PRD §3.6: "Candidates are ordered by `priority_rank` ascending; where those tie,
        by `blended_term_margin_pct` descending; and where both tie, by `created_at`
        ascending." and "when the offer's `offer_type` is `DISCOUNT` or `PLAN_DOWNGRADE`,
        the subscription's `billing_state` must be `CURRENT`, otherwise
        `ERR_SUBSCRIPTION_PAST_DUE` (409) — we do not hand a discount to an account we
        are still trying to collect from".

        Design: Difficulty/cross_entity_state_dependency/offer_accept_gated_by_subscription_billing_state
        """
        world = past_due_subscription_holding_a_presented_discount
        grant = world["grant"]

        # Both templates rank 50; the ten-percent offer blends to 0.5624 against the
        # twenty-percent offer's 0.5434, so it is presented.
        assert grant["save_offer_template_id"] == world["deeper"]["id"]
        assert grant["blended_term_margin_pct"] == pytest.approx(0.5624, abs=5e-5)
        assert grant["per_cycle_margin_pct"] == pytest.approx(0.5332, abs=5e-5)
        assert grant["retention_value_cents"] == 13495
        assert grant["margin_exception_required"] is False
        assert grant["state"] == "PRESENTED"

        assert read_subscription(world["subscription"]["id"])["billing_state"] == "PAST_DUE"

        validate_error(api_client.accept_grant(grant["id"], world["subscriber_headers"]),
                       ApiErrorId.ERR_SUBSCRIPTION_PAST_DUE, 409)

        assert read_grant(grant["id"])["state"] == "PRESENTED"
        assert read_grant(grant["id"])["accepted_at"] is None

        session = read_session(world["session"]["id"])
        assert session["state"] == "OFFERS_PRESENTED"
        assert session["step_count"] == 3

        subscription = read_subscription(world["subscription"]["id"])
        assert subscription["active_discount_pct"] == pytest.approx(0.0000, abs=5e-5)
        assert subscription["discount_remaining_cycles"] == 0
        assert subscription["committed_price_cents"] == 4999
        assert modifications_for(subscription["id"]) == []

    def test_collecting_the_invoice_reopens_the_acceptance(self,
                                                          past_due_subscription_holding_a_presented_discount):
        """A SUCCEEDED settlement returns the axis to CURRENT and the same grant now lands.

        PRD §3.7: "A `SUCCEEDED` settlement moves the invoice from `OPEN` or `FAILED` to
        `PAID` with `paid_at` at the clock, drives `billing_state` from `PAST_DUE` or
        `GRACE` back to `CURRENT`, clears `first_failed_at` and `grace_end_at` to null,
        resets `consecutive_failed_attempts` to 0, and recomputes both of the
        subscriber's lifetime-value figures."

        Design: Difficulty/cross_entity_state_dependency/offer_accept_gated_by_subscription_billing_state
        """
        world = past_due_subscription_holding_a_presented_discount
        grant = world["grant"]

        validate_error(api_client.accept_grant(grant["id"], world["subscriber_headers"]),
                       ApiErrorId.ERR_SUBSCRIPTION_PAST_DUE, 409)

        pay_invoice(world["invoice"]["id"])
        assert read_invoice(world["invoice"]["id"])["status"] == "PAID"

        subscription = read_subscription(world["subscription"]["id"])
        assert subscription["billing_state"] == "CURRENT"
        assert subscription["first_failed_at"] is None
        assert subscription["grace_end_at"] is None
        assert subscription["consecutive_failed_attempts"] == 0

        accepted = accept_grant(grant["id"], world["subscriber_headers"])
        assert accepted["state"] == "ACCEPTED"
        assert_instant(accepted["accepted_at"], "2026-01-10T00:00:00Z", "accepted_at")

        subscription = read_subscription(world["subscription"]["id"])
        assert subscription["active_discount_pct"] == pytest.approx(0.1000, abs=5e-5)
        assert subscription["discount_remaining_cycles"] == 2
        # 4999 * (1 - 0.1000) rounded half up.
        assert subscription["committed_price_cents"] == 4499

        applied = modifications_for(subscription["id"], mod_type="DISCOUNT_APPLY")
        assert len(applied) == 1
        assert applied[0]["state"] == "APPLIED"
        assert applied[0]["save_offer_grant_id"] == grant["id"]

        assert read_session(world["session"]["id"])["state"] == "OFFER_ACCEPTED"

        subscriber = read_subscriber(world["subscriber"]["id"])
        # 4999 collected less 2100 of goods on the only settled invoice.
        assert subscriber["realized_ltv_cents"] == 2899
        assert_instant(subscriber["winback_suppressed_until"], "2026-04-10T00:00:00Z",
                       "winback_suppressed_until")
