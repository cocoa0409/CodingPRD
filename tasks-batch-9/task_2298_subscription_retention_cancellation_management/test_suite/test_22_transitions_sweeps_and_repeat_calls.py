"""Repeated calls, illegal from-states, the renewal sweep and a clean pause round trip.

Declining twice is a conflict rather than a no-op; a notice created already sent cannot be
sent again; the renewal run sweeps a stale conversation and still bills the cycle; and a
pause followed by a resume leaves the price exactly where it started.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_instant,
    assert_price_conserved,
    invoice_at_cycle,
    modifications_for,
    new_template,
    notice_of_type,
    pause_subscription,
    pay_invoice,
    present_offers,
    read_grant,
    read_session,
    read_subscriber,
    read_subscription,
    request_modification,
    run_renewal,
    send_renewal_reminder,
    set_clock,
    setup_active_subscription,
    setup_reason_captured_session,
    validate_error,
    validate_success,
)

BILLING = TEST_USERS["billing_operator_headers"]

PRICE_OFFER = {"offer_type": "DISCOUNT", "discount_pct": 0.1000, "discount_cycles": 1,
               "priority_rank": 10, "eligible_reason_codes": ["PRICE"]}
PAUSE_OFFER = {"offer_type": "PAUSE", "pause_cycles": 2, "priority_rank": 20,
               "eligible_reason_codes": ["TOO_MUCH_PRODUCT"]}


class TestRepeatedDecline:

    def test_declining_an_already_declined_grant_is_a_conflict(self):
        """The second decline conflicts, and the session is still able to complete.

        PRD §3.6: "It is also exclusive to the `Subscriber`, takes an optional
        `decline_note`, and is guarded by the same `state` check yielding
        `ERR_OFFER_ALREADY_RESOLVED` (409)."

        Design: Corner/state_machines/second_decline_of_the_same_grant_returns_offer_already_resolved
        """
        template = new_template(code="T_PRICE", **PRICE_OFFER)
        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "SEARCH"})
        session = setup_reason_captured_session(world, reason_code="PRICE")
        grant = present_offers(session["id"], as_user_id="rs_1")

        validate_success(api_client.decline_grant(grant["id"], world["subscriber_headers"]), 200)
        validate_error(api_client.decline_grant(grant["id"], world["subscriber_headers"]),
                       ApiErrorId.ERR_OFFER_ALREADY_RESOLVED, 409)

        declined = read_grant(grant["id"])
        assert declined["state"] == "DECLINED"
        assert declined["save_offer_template_id"] == template["id"]

        still_open = read_session(session["id"])
        assert still_open["state"] == "OFFERS_PRESENTED"
        assert still_open["step_count"] == 3

        # A declined grant leaves the trailing window.
        assert read_subscriber(world["subscriber"]["id"])["save_offer_grants_365d_count"] == 0


class TestIllegalNoticeTransition:

    def test_a_disclosure_created_already_sent_cannot_be_sent_again(self):
        """SENT is not a legal from-state, and the original sent_at is not refreshed.

        PRD §3.4: "Sending a notice is a `BillingOperator` capability whose guards run in
        this order: the notice's `state` must be `SCHEDULED`, and a notice already `SENT`
        or `MISSED` is rejected with `ERR_NOTICE_ALREADY_SENT` (409)".

        Design: Corner/state_machines/sending_an_already_sent_disclosure_notice_returns_notice_already_sent
        """
        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "SEARCH"})
        disclosure = notice_of_type(world["subscription"]["id"], "NEGATIVE_OPTION_DISCLOSURE")
        assert disclosure["state"] == "SENT"

        set_clock("2026-01-20")
        validate_error(api_client.send_compliance_notice(disclosure["id"], BILLING),
                       ApiErrorId.ERR_NOTICE_ALREADY_SENT, 409)

        unchanged = notice_of_type(world["subscription"]["id"], "NEGATIVE_OPTION_DISCLOSURE")
        assert unchanged["state"] == "SENT"
        assert_instant(unchanged["sent_at"], "2026-01-10T00:00:00Z", "sent_at")
        assert unchanged["renewal_cycle_index"] == 0
        assert unchanged["version"] == 1


class TestRenewalSweep:

    def test_the_renewal_run_abandons_a_stale_session_and_still_bills_the_cycle(self):
        """A 28-day-old conversation is swept, its grant expires, and cycle one is issued.

        PRD §3.5: "When the renewal run finds a non-terminal session older than 48 hours
        it moves it to `ABANDONED` with `completed_at` at the clock, expiring its
        `PRESENTED` grants; the same happens when the subscription reaches `CANCELLED`
        involuntarily."

        Design: Corner/state_machines/renewal_sweep_abandons_stale_session_and_expires_its_grant
        """
        new_template(code="T_PAUSE", **PAUSE_OFFER)
        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "SEARCH"})
        pay_invoice(world["invoice"]["id"])
        session = setup_reason_captured_session(world, reason_code="TOO_MUCH_PRODUCT")
        grant = present_offers(session["id"], as_user_id="rs_1")
        # A pause offer bills nothing during its two cycles, so the blended reading is
        # 8697 of margin over 14997 of revenue across the three post-offer cycles.
        assert grant["blended_term_margin_pct"] == pytest.approx(0.5799, abs=5e-5)

        set_clock("2026-01-28")
        send_renewal_reminder(world, renewal_cycle_index=1)

        set_clock("2026-02-07")
        run_renewal(world["subscription"]["id"])

        swept = read_session(session["id"])
        assert swept["state"] == "ABANDONED"
        assert_instant(swept["completed_at"], "2026-02-07T00:00:00Z", "completed_at")
        # Abandonment preserves the reason for later win-back scoring.
        assert swept["reason_code"] == "TOO_MUCH_PRODUCT"
        assert read_grant(grant["id"])["state"] == "EXPIRED"

        renewal_invoice = invoice_at_cycle(world["subscription"]["id"], 1)
        assert renewal_invoice["amount_cents"] == 4999
        assert renewal_invoice["is_renewal"] is True

        subscription = read_subscription(world["subscription"]["id"])
        assert subscription["lifecycle_state"] == "ACTIVE"
        assert_instant(subscription["next_renewal_at"], "2026-03-07T00:00:00Z", "next_renewal_at")
        assert subscription["term_shipments_delivered"] == 2
        assert subscription["term_shipments_remaining"] == 10


class TestPauseResumeRoundTrip:

    def test_a_pause_and_a_resume_leave_the_price_untouched_and_the_budget_spent(self):
        """Two applied rows, both with a zero delta, and one pause cycle consumed for good.

        PRD §3.3: "An applied pause moves `lifecycle_state` from `ACTIVE` to `PAUSED`,
        sets `paused_until` to `pause_end_at`, advances `next_renewal_at` to
        `pause_end_at`, increases `pause_cycles_used` by the same rounded-up cycle count,
        and records `delta_price_cents` of 0 — a pause defers revenue but does not reprice
        the subscription."

        Design: Corner/state_machines/resume_modification_returns_paused_subscription_to_active
        """
        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "SEARCH"})

        pause = pause_subscription(world, "2026-01-10", "2026-02-07")
        assert pause["state"] == "APPLIED"
        assert pause["delta_price_cents"] == 0

        resume = request_modification(world["subscription"]["id"], "RESUME",
                                      world["subscriber_headers"])
        assert resume["state"] == "APPLIED"
        assert resume["delta_price_cents"] == 0

        subscription = read_subscription(world["subscription"]["id"])
        assert subscription["lifecycle_state"] == "ACTIVE"
        assert subscription["paused_until"] is None
        assert subscription["pause_cycles_used"] == 1
        assert subscription["committed_price_cents"] == 4999
        assert subscription["version"] == 3
        assert_price_conserved(subscription, modifications_for(subscription["id"]))
