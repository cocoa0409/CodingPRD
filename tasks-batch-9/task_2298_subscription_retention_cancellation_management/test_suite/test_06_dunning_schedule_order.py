"""The pinned order of the dunning scheduling procedure.

Each attempt creation recomputes the grace window before it schedules, and it reads
the card-updater state as of that moment.  A pending updater request widens the
window by four days; the backoff position is drawn from the preceding attempt's
number, so the retry numbered 2 takes the first position of its decline code's list.
"""

from test_helpers import (
    assert_append_only_fields,
    assert_dunning_attempt,
    assert_instant,
    attempts_for,
    create_attempt,
    invoice_at_cycle,
    pay_invoice,
    read_invoice,
    read_payment_method,
    read_subscription,
    run_renewal,
    send_renewal_reminder,
    set_clock,
    settle_attempt,
    setup_active_subscription,
    submit_updater_result,
)


def _renewal_invoice_after_one_expired_card_decline():
    """Signup paid, renewal issued 2026-02-07, then one soft decline on EXPIRED_CARD."""
    world = setup_active_subscription(
        clock="2026-01-10",
        subscriber_overrides={"acquisition_channel": "ORGANIC"},
        card_overrides={"exp_month": 1, "exp_year": 2026},
    )
    pay_invoice(world["invoice"]["id"])
    set_clock("2026-01-28")
    send_renewal_reminder(world, renewal_cycle_index=1)
    set_clock("2026-02-07")
    run_renewal(world["subscription"]["id"])
    renewal = invoice_at_cycle(world["subscription"]["id"], 1)
    create_attempt(renewal["id"])
    settle_attempt(renewal["id"], "SOFT_DECLINE", "EXPIRED_CARD")
    world["renewal_invoice"] = renewal
    return world


class TestDunningScheduleOrder:

    def test_pending_card_updater_widens_the_grace_window_at_the_next_attempt_creation(self):
        """Attempt 1 skips the arithmetic; attempt 2 recomputes grace as three plus four days.

        PRD §3.7: "The very first attempt is special and skips all of that. For
        `attempt_number` 1 the raw schedule instant is simply the clock,
        `backoff_days_applied` is 0, `grace_clamped` is false and `is_final` is
        false, and the grace-window steps are skipped entirely because
        `first_failed_at` is still null." and "Second, four further days are added to
        that allowance when — and only when — the invoice's payment method has
        `updater_status` `PENDING` as observed at this moment, before this attempt
        settles; otherwise nothing is added."

        Design: Difficulty/combinatorial_formula/dunning_schedule_pinned_step_order_extension_then_clamp
        """
        world = _renewal_invoice_after_one_expired_card_decline()
        invoice_id = world["renewal_invoice"]["id"]

        attempts = attempts_for(invoice_id)
        assert len(attempts) == 1
        first = attempts[0]
        assert_dunning_attempt(first)
        assert_append_only_fields(first)
        assert first["attempt_number"] == 1
        assert first["previous_attempt_id"] is None
        assert first["backoff_days_applied"] == 0
        assert first["grace_clamped"] is False
        assert first["is_final"] is False
        assert_instant(first["scheduled_at"], "2026-02-07T00:00:00Z", "scheduled_at")
        assert first["decline_code"] == "EXPIRED_CARD"

        subscription = read_subscription(world["subscription"]["id"])
        assert subscription["billing_state"] == "PAST_DUE"
        assert subscription["consecutive_failed_attempts"] == 1
        assert_instant(subscription["first_failed_at"], "2026-02-07T00:00:00Z", "first_failed_at")
        # Tenure at first_failed_at is 28 days, bucket M0_1, so the bare allowance is 3 days.
        assert_instant(subscription["grace_end_at"], "2026-02-10T00:00:00Z", "grace_end_at")
        assert read_invoice(invoice_id)["status"] == "FAILED"
        assert read_payment_method(world["payment_method"]["id"])["updater_status"] == "PENDING"

        set_clock("2026-02-09")
        create_attempt(invoice_id)

        second = attempts_for(invoice_id)[1]
        assert second["attempt_number"] == 2
        assert second["previous_attempt_id"] == first["id"]
        # EXPIRED_CARD reads zero, two, four, then six days; attempt 2 takes the first.
        assert second["backoff_days_applied"] == 0
        assert_instant(second["scheduled_at"], "2026-02-07T00:00:00Z", "scheduled_at")
        assert second["grace_clamped"] is False
        assert second["is_final"] is False

        subscription = read_subscription(world["subscription"]["id"])
        # Three days of tenure allowance plus the four-day card-updater extension.
        assert_instant(subscription["grace_end_at"], "2026-02-14T00:00:00Z", "grace_end_at")
        assert subscription["billing_state"] == "GRACE"

    def test_backoff_position_advances_with_the_preceding_attempt_number(self):
        """After an UNAVAILABLE updater result the retry numbered 3 takes the second position.

        PRD §3.7: "The position used is the one whose ordinal equals the previous
        attempt's `attempt_number` — so the attempt numbered 2 uses the first
        position of the list, the attempt numbered 3 the second, and the attempt
        numbered 4 the third." and "An `UNAVAILABLE` outcome sets `updater_status`
        to `UNAVAILABLE` and `status` to `EXPIRED`."

        Design: Difficulty/combinatorial_formula/dunning_schedule_pinned_step_order_extension_then_clamp
        """
        world = _renewal_invoice_after_one_expired_card_decline()
        invoice_id = world["renewal_invoice"]["id"]

        set_clock("2026-02-09")
        create_attempt(invoice_id)

        method = submit_updater_result(world["payment_method"]["id"], "UNAVAILABLE")
        assert method["updater_status"] == "UNAVAILABLE"
        assert method["status"] == "EXPIRED"

        settle_attempt(invoice_id, "SOFT_DECLINE", "EXPIRED_CARD")
        assert read_invoice(invoice_id)["status"] == "FAILED"
        assert read_subscription(world["subscription"]["id"])["consecutive_failed_attempts"] == 2

        set_clock("2026-02-10")
        create_attempt(invoice_id)

        attempts = attempts_for(invoice_id)
        assert len(attempts) == 3
        third = attempts[2]
        assert third["attempt_number"] == 3
        assert third["previous_attempt_id"] == attempts[1]["id"]
        # Second position of the EXPIRED_CARD list.
        assert third["backoff_days_applied"] == 2
        assert third["outcome"] == "PENDING"
        assert third["attempted_at"] is None
