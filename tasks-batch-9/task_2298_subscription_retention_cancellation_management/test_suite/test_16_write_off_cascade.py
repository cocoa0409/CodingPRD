"""One hard decline writes off an invoice and the consequences ripple to four entities.

The renewal invoice fails once, is retried inside the grace window, and the retry comes
back hard-declined.  That single settlement moves the invoice, both axes of the
subscription, three fields on the subscriber and the open cancellation conversation.
"""

import pytest

from test_helpers import (
    assert_dunning_attempt,
    assert_instant,
    charge_invoice,
    create_attempt,
    invoice_at_cycle,
    pay_invoice,
    read_invoice,
    read_session,
    read_subscriber,
    read_subscription,
    run_renewal,
    send_renewal_reminder,
    set_clock,
    settle_attempt,
    setup_active_subscription,
    setup_reason_captured_session,
)


@pytest.fixture
def renewal_invoice_about_to_be_written_off():
    """Cycle-1 invoice of 6298 failed on 2026-02-07, retried on 2026-02-10, still PENDING."""
    world = setup_active_subscription(
        clock="2026-01-10",
        subscriber_overrides={"acquisition_channel": "PAID_SOCIAL"},
        addons=[{"code": "MUG", "qty": 1}])
    pay_invoice(world["invoice"]["id"])

    set_clock("2026-01-28")
    send_renewal_reminder(world, renewal_cycle_index=1)

    set_clock("2026-02-07")
    run_renewal(world["subscription"]["id"])
    renewal_invoice = invoice_at_cycle(world["subscription"]["id"], 1)
    charge_invoice(renewal_invoice["id"], "SOFT_DECLINE", "INSUFFICIENT_FUNDS")

    set_clock("2026-02-08")
    world["session"] = setup_reason_captured_session(world, reason_code="PRICE")

    # Tenure was 28 days at the first failure, so the bare M0_1 allowance of three days
    # puts grace_end_at on 2026-02-10 and the clock has not passed it.
    set_clock("2026-02-10")
    world["renewal_invoice"] = renewal_invoice
    world["retry"] = create_attempt(renewal_invoice["id"])
    return world


class TestWriteOffCascade:

    def test_the_retry_is_scheduled_from_the_backoff_and_its_hard_decline_writes_off(self,
                                                                                    renewal_invoice_about_to_be_written_off):
        """Attempt 2 takes the first INSUFFICIENT_FUNDS backoff position, then fails hard.

        PRD §3.7: "The position used is the one whose ordinal equals the previous
        attempt's `attempt_number` — so the attempt numbered 2 uses the first position of
        the list, the attempt numbered 3 the second, and the attempt numbered 4 the
        third." and "A `HARD_DECLINE`, or a `SOFT_DECLINE` on an attempt whose `is_final`
        is true, moves the invoice from `OPEN` or `FAILED` to `WRITTEN_OFF`, and the
        consequences ripple outward in a fixed sequence."

        Design: Difficulty/transitive_cascade/write_off_cascade_invoice_subscription_subscriber_session
        """
        world = renewal_invoice_about_to_be_written_off
        retry = world["retry"]

        assert_dunning_attempt(retry)
        assert retry["attempt_number"] == 2
        assert retry["backoff_days_applied"] == 1
        # 2026-02-07 plus one day, which is earlier than the 2026-02-10 grace end.
        assert_instant(retry["scheduled_at"], "2026-02-08T00:00:00Z", "scheduled_at")
        assert retry["grace_clamped"] is False
        assert retry["is_final"] is False
        assert retry["outcome"] == "PENDING"

        settle_attempt(world["renewal_invoice"]["id"], "HARD_DECLINE", "DO_NOT_HONOR")

        written_off = read_invoice(world["renewal_invoice"]["id"])
        assert written_off["status"] == "WRITTEN_OFF"
        assert written_off["amount_cents"] == 6298
        assert written_off["cogs_cents"] == 2620

        subscription = read_subscription(world["subscription"]["id"])
        assert subscription["billing_state"] == "DELINQUENT"
        assert subscription["lifecycle_state"] == "CANCELLED"
        assert_instant(subscription["cancel_effective_at"], "2026-02-10T00:00:00Z",
                       "cancel_effective_at")

    def test_the_write_off_lapses_the_subscriber_and_abandons_the_conversation(self,
                                                                              renewal_invoice_about_to_be_written_off):
        """Involuntary churn, a thirty-day suppression, and the session dropped mid-flow.

        PRD §3.7: "The subscriber's `churn_type` is set to `INVOLUNTARY`, `lapsed_at` to
        the clock, and `winback_suppressed_until` to the clock plus 30 days.
        `realized_ltv_cents` is recomputed, subtracting this invoice's `cogs_cents`, and
        `projected_ltv_cents` is re-derived with zero expected remaining cycles so that
        it equals `realized_ltv_cents`. Finally, every non-terminal
        `CancellationSession` on this subscription moves to `ABANDONED`."

        Design: Difficulty/transitive_cascade/write_off_cascade_invoice_subscription_subscriber_session
        """
        world = renewal_invoice_about_to_be_written_off

        settle_attempt(world["renewal_invoice"]["id"], "HARD_DECLINE", "DO_NOT_HONOR")

        subscriber = read_subscriber(world["subscriber"]["id"])
        assert subscriber["churn_type"] == "INVOLUNTARY"
        assert_instant(subscriber["lapsed_at"], "2026-02-10T00:00:00Z", "lapsed_at")
        assert_instant(subscriber["winback_suppressed_until"], "2026-03-12T00:00:00Z",
                       "winback_suppressed_until")
        # 6298 - 2620 collected on cycle 0, less the 2620 of goods written off on cycle 1.
        assert subscriber["realized_ltv_cents"] == 1058
        assert subscriber["projected_ltv_cents"] == 1058

        # The paid cycle-zero invoice is untouched by the write-off.
        assert invoice_at_cycle(world["subscription"]["id"], 0)["status"] == "PAID"

        session = read_session(world["session"]["id"])
        assert session["state"] == "ABANDONED"
        assert_instant(session["completed_at"], "2026-02-10T00:00:00Z", "completed_at")
        assert session["reason_code"] == "PRICE"
