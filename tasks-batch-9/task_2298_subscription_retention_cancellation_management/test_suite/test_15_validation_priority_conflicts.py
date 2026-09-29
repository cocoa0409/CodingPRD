"""Two requests that break two rules at once, and only one error comes back.

An acceptance of an expired, below-floor offer reports the expiry, because the state
check is stated before the fiscal check.  A renewal of a subscription that has neither
its reminder sent nor a usable card reports the missing reminder, because the
negative-option gate is step five and the payment-instrument check is step seven.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_instant,
    charge_invoice,
    invoice_at_cycle,
    list_invoices_for,
    notice_of_type,
    read_grant,
    read_payment_method,
    read_subscription,
    send_renewal_reminder,
    set_clock,
    setup_active_subscription,
    setup_grant_at_margin,
    submit_updater_result,
    validate_error,
)

BILLING = TEST_USERS["billing_operator_headers"]

BELOW_FLOOR_PLAN = {
    "monthly_price_cents": 5000,
    "unit_cogs_cents": 2500,
    "margin_floor_pct": 0.4048,
    "is_negative_option": False,
    "allowed_frequency_weeks": [4],
}
DEEP_OFFER = {
    "discount_pct": 0.4500,
    "discount_cycles": 2,
    "priority_rank": 16,
    "expires_after_hours": 48,
}


@pytest.fixture
def undecided_below_floor_grant():
    """A grant presented 2026-01-10 by rs_2, blended 0.3902 under a 0.4048 floor."""
    world = setup_grant_at_margin(
        BELOW_FLOOR_PLAN, DEEP_OFFER,
        reason_code="SHIPPING_ISSUES", clock="2026-01-10", as_user_id="rs_2",
        subscriber_overrides={"acquisition_channel": "SEARCH"})
    return world


@pytest.fixture
def two_subscriptions_with_expired_cards():
    """Both signed up 2026-01-10 on expiring cards; only the second was reminded."""
    unreminded = setup_active_subscription(
        clock="2026-01-10",
        subscriber_overrides={"acquisition_channel": "AFFILIATE"},
        card_overrides={"exp_month": 1, "exp_year": 2026})
    reminded = setup_active_subscription(
        clock="2026-01-10",
        subscriber_overrides={"acquisition_channel": "AFFILIATE"},
        card_overrides={"exp_month": 1, "exp_year": 2026})

    for world in (unreminded, reminded):
        charge_invoice(world["invoice"]["id"], "SOFT_DECLINE", "EXPIRED_CARD")
        submit_updater_result(world["payment_method"]["id"], "UNAVAILABLE")

    set_clock("2026-01-28")
    send_renewal_reminder(reminded, renewal_cycle_index=1)

    set_clock("2026-02-07")
    return unreminded, reminded


class TestOfferExpiryOutranksMarginFloor:

    def test_before_expiry_the_below_floor_offer_reports_the_fiscal_breach(self,
                                                                          undecided_below_floor_grant):
        """On 2026-01-11 the grant is live, so the undecided exception is what fails.

        PRD §3.6: "Its guards run in this order after the ownership check: the grant's
        `state` must be `PRESENTED`, otherwise `ERR_OFFER_ALREADY_RESOLVED` (409); the
        clock must be strictly before `expires_at`, an acceptance at or after that
        instant being rejected with `ERR_OFFER_EXPIRED` (409); when the offer's
        `offer_type` is `DISCOUNT` or `PLAN_DOWNGRADE`, the subscription's
        `billing_state` must be `CURRENT`, otherwise `ERR_SUBSCRIPTION_PAST_DUE` (409)
        — we do not hand a discount to an account we are still trying to collect from;
        and finally either `margin_exception_required` must be false or
        `margin_exception_state` must be `APPROVED`, otherwise
        `ERR_MARGIN_FLOOR_BREACH` (422)."

        Design: Difficulty/priority_pair_validation_conflict/offer_expiry_state_outranks_margin_floor_fiscal
        """
        world = undecided_below_floor_grant
        grant = world["grant"]

        # 2750 revenue against 2500 of goods in each of two offer cycles, then three
        # cycles at 5000 against 2500.
        assert grant["per_cycle_margin_pct"] == pytest.approx(0.0909, abs=5e-5)
        assert grant["blended_term_margin_pct"] == pytest.approx(0.3902, abs=5e-5)
        assert grant["retention_value_cents"] == 8000
        assert grant["margin_exception_required"] is True
        assert grant["margin_exception_state"] == "PENDING"
        assert_instant(grant["expires_at"], "2026-01-12T00:00:00Z", "expires_at")

        set_clock("2026-01-11")
        validate_error(api_client.accept_grant(grant["id"], world["subscriber_headers"]),
                       ApiErrorId.ERR_MARGIN_FLOOR_BREACH, 422)

        assert read_grant(grant["id"])["state"] == "PRESENTED"
        subscription = read_subscription(world["subscription"]["id"])
        assert subscription["active_discount_pct"] == pytest.approx(0.0000, abs=5e-5)

    def test_at_the_expiry_instant_the_state_check_wins_over_the_fiscal_one(self,
                                                                           undecided_below_floor_grant):
        """On 2026-01-12 the same doubly-invalid acceptance reports the expiry instead.

        PRD §2.6: "When a single request violates more than one rule, exactly one error
        is returned, and which one is not left to implementation taste. Checks are
        ranked, and the highest-ranked failing check determines the response." and
        PRD §3.6: "the clock must be strictly before `expires_at`, an acceptance at or
        after that instant being rejected with `ERR_OFFER_EXPIRED` (409)".

        Design: Difficulty/priority_pair_validation_conflict/offer_expiry_state_outranks_margin_floor_fiscal
        """
        world = undecided_below_floor_grant
        grant = world["grant"]

        # Exactly expires_at: the window is closed at its upper end.
        set_clock("2026-01-12")
        validate_error(api_client.accept_grant(grant["id"], world["subscriber_headers"]),
                       ApiErrorId.ERR_OFFER_EXPIRED, 409)

        # The margin breach is still true of this grant; it simply never got to speak.
        still_presented = read_grant(grant["id"])
        assert still_presented["state"] == "PRESENTED"
        assert still_presented["margin_exception_state"] == "PENDING"
        assert still_presented["accepted_at"] is None

        subscription = read_subscription(world["subscription"]["id"])
        assert subscription["active_discount_pct"] == pytest.approx(0.0000, abs=5e-5)
        assert subscription["discount_remaining_cycles"] == 0


class TestReminderSafetyOutranksPaymentReferential:

    def test_an_unreminded_renewal_reports_the_missing_reminder_not_the_dead_card(self,
                                                                                 two_subscriptions_with_expired_cards):
        """Step five fires before step seven ever reads the payment method.

        PRD §3.4: "Step five is the negative-option gate. For a subscription on a
        negative-option plan, the run may only issue an invoice if a `ComplianceNotice`
        exists with `notice_type` `RENEWAL_REMINDER`, `state` `SENT`, and
        `renewal_cycle_index` equal to the cycle being renewed, whose `sent_at` falls
        inside the closed reminder window described in §2.11."

        Design: Difficulty/priority_pair_validation_conflict/renewal_reminder_safety_outranks_payment_method_referential
        """
        unreminded, _ = two_subscriptions_with_expired_cards
        subscription_id = unreminded["subscription"]["id"]

        assert read_payment_method(unreminded["payment_method"]["id"])["status"] == "EXPIRED"

        validate_error(api_client.run_renewal(subscription_id, BILLING),
                       ApiErrorId.ERR_RENEWAL_REMINDER_MISSING, 422)

        assert notice_of_type(subscription_id, "RENEWAL_REMINDER",
                              renewal_cycle_index=1)["state"] == "SCHEDULED"
        subscription = read_subscription(subscription_id)
        assert_instant(subscription["next_renewal_at"], "2026-02-07T00:00:00Z", "next_renewal_at")
        assert subscription["term_shipments_delivered"] == 1
        assert [invoice["cycle_index"] for invoice in list_invoices_for(subscription_id)] == [0]

    def test_once_the_reminder_is_sent_the_dead_card_is_what_stops_the_renewal(self,
                                                                              two_subscriptions_with_expired_cards):
        """With step five satisfied, step seven refuses to issue against an EXPIRED method.

        PRD §3.4: "Otherwise the payment instrument must still be usable — a
        subscription whose `payment_method_id` points at a method whose `status` is
        `REPLACED` or `EXPIRED` is rejected with `ERR_PAYMENT_METHOD_INACTIVE` (409),
        because a stale card may be retried against an invoice that already exists but
        may never have a new invoice issued against it".

        Design: Difficulty/priority_pair_validation_conflict/renewal_reminder_safety_outranks_payment_method_referential
        """
        _, reminded = two_subscriptions_with_expired_cards
        subscription_id = reminded["subscription"]["id"]

        notice = notice_of_type(subscription_id, "RENEWAL_REMINDER", renewal_cycle_index=1)
        assert notice["state"] == "SENT"
        assert_instant(notice["sent_at"], "2026-01-28T00:00:00Z", "sent_at")
        assert read_payment_method(reminded["payment_method"]["id"])["status"] == "EXPIRED"

        validate_error(api_client.run_renewal(subscription_id, BILLING),
                       ApiErrorId.ERR_PAYMENT_METHOD_INACTIVE, 409)

        subscription = read_subscription(subscription_id)
        assert_instant(subscription["next_renewal_at"], "2026-02-07T00:00:00Z", "next_renewal_at")
        assert subscription["term_shipments_delivered"] == 1
        assert [invoice["cycle_index"] for invoice in list_invoices_for(subscription_id)] == [0]
        assert invoice_at_cycle(subscription_id, 0)["status"] == "FAILED"
