"""Rules that read the clock or a running total rather than the request body.

A renewal one day early is refused outright; the fourth pre-completion call is refused
while completion itself is exempt; and the statutory cooldown refuses a second send on day
two and admits exactly the same call on day three.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_compliance_notice,
    assert_instant,
    capture_reason_payload,
    complete_session,
    list_invoices_for,
    new_template,
    notice_of_type,
    notices_for,
    new_plan,
    present_offers,
    read_grant,
    read_session,
    read_subscription,
    schedule_notice,
    send_notice,
    set_clock,
    setup_active_subscription,
    setup_reason_captured_session,
    validate_error,
)

BILLING = TEST_USERS["billing_operator_headers"]

PRICE_OFFER = {"offer_type": "DISCOUNT", "discount_pct": 0.1000, "discount_cycles": 1,
               "priority_rank": 10, "eligible_reason_codes": ["PRICE"]}


def _notice(subscription_id, notice_id):
    """Re-read one notice: notices are readable through their subscription's list."""
    for notice in notices_for(subscription_id):
        if notice["id"] == notice_id:
            return notice
    raise AssertionError(f"notice {notice_id} is missing from subscription {subscription_id}")


class TestRenewalTiming:

    def test_a_renewal_one_day_early_is_refused_and_issues_no_invoice(self):
        """2026-02-06 against a renewal due 2026-02-07 mutates nothing at all.

        PRD §3.4: "The run is refused before the cycle is up: if the clock has not yet
        reached `next_renewal_at`, the request is rejected with `ERR_RENEWAL_NOT_DUE` (409)
        and nothing is mutated."

        Design: Corner/validations/renewal_before_next_renewal_at_returns_renewal_not_due
        """
        # A plain plan, so the reminder gate cannot be what refuses the run.
        plain_plan = new_plan(code="BOUND", monthly_price_cents=5000, unit_cogs_cents=2500,
                             margin_floor_pct=0.4048, allowed_frequency_weeks=[4],
                             is_negative_option=False)
        world = setup_active_subscription(
            clock="2026-01-10", plan=plain_plan,
            subscriber_overrides={"acquisition_channel": "SEARCH"})

        set_clock("2026-02-06")
        validate_error(api_client.run_renewal(world["subscription"]["id"], BILLING),
                       ApiErrorId.ERR_RENEWAL_NOT_DUE, 409)

        invoices = list_invoices_for(world["subscription"]["id"])
        assert [invoice["cycle_index"] for invoice in invoices] == [0]

        subscription = read_subscription(world["subscription"]["id"])
        assert_instant(subscription["next_renewal_at"], "2026-02-07T00:00:00Z", "next_renewal_at")
        assert subscription["term_shipments_delivered"] == 1
        assert subscription["version"] == 1


class TestPreCompletionBudget:

    def test_the_fourth_pre_completion_call_is_refused_but_completion_still_runs(self):
        """Create, reason and offers fill the budget of three; the revision is rejected.

        PRD §3.5: "Concretely, a pre-completion call is permitted only when the session's
        current `step_count` plus one is less than or equal to three — the boundary is
        inclusive, so `step_count` may legitimately reach 3 — and a call that would push it
        past three is rejected with `ERR_SIMPLE_CANCELLATION_VIOLATION` (422) with no state
        change of any kind."

        Design: Corner/validations/fourth_pre_completion_step_returns_simple_cancellation_violation
        """
        new_template(code="T_PRICE", **PRICE_OFFER)
        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "SEARCH"})
        session = setup_reason_captured_session(world, reason_code="PRICE")
        grant = present_offers(session["id"], as_user_id="rs_1")
        assert read_session(session["id"])["step_count"] == 3

        validate_error(
            api_client.capture_reason(
                session["id"],
                capture_reason_payload("OTHER", reason_detail="second thoughts"),
                world["subscriber_headers"]),
            ApiErrorId.ERR_SIMPLE_CANCELLATION_VIOLATION, 422)

        held = read_session(session["id"])
        assert held["state"] == "OFFERS_PRESENTED"
        assert held["reason_code"] == "PRICE"
        assert held["reason_detail"] is None
        assert held["step_count"] == 3

        completed = complete_session(session["id"], world["subscriber_headers"])
        assert completed["state"] == "COMPLETED_CANCELLED"
        assert completed["step_count"] == 4
        assert read_grant(grant["id"])["state"] == "EXPIRED"
        assert read_subscription(
            world["subscription"]["id"])["lifecycle_state"] == "PENDING_CANCEL"


class TestNoticeCooldown:

    def test_a_second_reminder_waits_exactly_three_days_before_it_may_be_sent(self):
        """Day two is a conflict; day three is a send, with sent_at at the later clock.

        PRD §2.11: "A cooldown protects subscribers from duplicate statutory mail: a notice
        may not be sent when fewer than three days have elapsed since the `sent_at` of the
        most recent `SENT` notice sharing the same `notice_type` and the same
        `renewal_cycle_index`. The boundary is inclusive on the permitted side — a send
        exactly three days later is allowed."

        Design: Corner/validations/notice_cooldown_blocks_a_second_send_two_days_later_but_admits_it_on_day_three
        """
        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "SEARCH"})
        subscription_id = world["subscription"]["id"]

        auto_reminder = notice_of_type(subscription_id, "RENEWAL_REMINDER",
                                       renewal_cycle_index=1)
        assert_instant(auto_reminder["scheduled_for"], "2026-01-28T00:00:00Z", "scheduled_for")

        # A second reminder for the same cycle, scheduled inside the closed window.
        extra_reminder = schedule_notice(subscription_id, "RENEWAL_REMINDER", "2026-01-30")
        assert_compliance_notice(extra_reminder)
        assert extra_reminder["renewal_cycle_index"] == 1
        assert extra_reminder["state"] == "SCHEDULED"

        set_clock("2026-01-28")
        send_notice(auto_reminder["id"])

        set_clock("2026-01-30")
        validate_error(api_client.send_compliance_notice(extra_reminder["id"], BILLING),
                       ApiErrorId.ERR_NOTICE_COOLDOWN_ACTIVE, 409)
        assert _notice(subscription_id, extra_reminder["id"])["state"] == "SCHEDULED"

        set_clock("2026-01-31")
        sent = send_notice(extra_reminder["id"])
        assert sent["state"] == "SENT"
        assert_instant(sent["sent_at"], "2026-01-31T00:00:00Z", "sent_at")
        assert_instant(_notice(subscription_id, auto_reminder["id"])["sent_at"],
                       "2026-01-28T00:00:00Z", "sent_at")
