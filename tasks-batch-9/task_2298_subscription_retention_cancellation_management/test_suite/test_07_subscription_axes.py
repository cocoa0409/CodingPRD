"""The lifecycle and billing axes of one subscription move independently.

A pause drives the lifecycle axis and leaves collections alone; a soft decline drives
the billing axis and leaves fulfilment alone.  The two therefore co-exist, and a
resume unwinds only the axis it owns.
"""

from test_helpers import (
    assert_instant,
    assert_subscription,
    charge_invoice,
    pause_subscription,
    read_invoice,
    read_subscription,
    request_modification,
    setup_active_subscription,
)


def _paused_and_past_due_subscription():
    """Pause on the signup instant, then soft-decline the still-open signup invoice."""
    world = setup_active_subscription(
        clock="2026-01-10",
        subscriber_overrides={"acquisition_channel": "AFFILIATE"},
    )
    world["pause"] = pause_subscription(world, "2026-01-10", "2026-02-07")
    charge_invoice(world["invoice"]["id"], "SOFT_DECLINE", "INSUFFICIENT_FUNDS")
    return world


class TestSubscriptionAxes:

    def test_a_paused_subscription_can_sit_past_due_on_the_billing_axis(self):
        """PAUSED on the lifecycle axis and PAST_DUE on the billing axis at once.

        PRD §2.10: "A `Subscription` runs two state machines at once, and they evolve
        from different triggers. Neither axis constrains the other, and a subscription
        may legitimately sit in any combination of the two — a paused subscription can
        be past due, and reading a subscription returns both axes."

        Design: Difficulty/non_linear_state_machine/subscription_parallel_axes_paused_while_past_due
        """
        world = _paused_and_past_due_subscription()

        assert world["pause"]["mod_type"] == "PAUSE"
        assert world["pause"]["state"] == "APPLIED"
        assert world["pause"]["delta_price_cents"] == 0

        subscription = read_subscription(world["subscription"]["id"])
        assert_subscription(subscription)

        assert subscription["lifecycle_state"] == "PAUSED"
        assert_instant(subscription["paused_until"], "2026-02-07T00:00:00Z", "paused_until")
        assert subscription["pause_cycles_used"] == 1
        assert_instant(subscription["next_renewal_at"], "2026-02-07T00:00:00Z", "next_renewal_at")

        assert subscription["billing_state"] == "PAST_DUE"
        assert_instant(subscription["first_failed_at"], "2026-01-10T00:00:00Z", "first_failed_at")
        # Tenure 0 days at the first failure, bucket M0_1, a three-day allowance.
        assert_instant(subscription["grace_end_at"], "2026-01-13T00:00:00Z", "grace_end_at")
        assert subscription["consecutive_failed_attempts"] == 1
        assert read_invoice(world["invoice"]["id"])["status"] == "FAILED"

    def test_resume_clears_only_the_lifecycle_axis(self):
        """Resuming restarts billing immediately and leaves every collections field intact.

        PRD §3.3: "A **resume** moves `lifecycle_state` from `PAUSED` back to
        `ACTIVE`, clears `paused_until` to null, and — when it was requested as a
        modification rather than reached by the renewal run — sets `next_renewal_at`
        to the clock, so billing restarts immediately rather than at the originally
        deferred instant."

        Design: Difficulty/non_linear_state_machine/subscription_parallel_axes_paused_while_past_due
        """
        world = _paused_and_past_due_subscription()

        resume = request_modification(world["subscription"]["id"], "RESUME",
                                      world["subscriber_headers"])
        assert resume["mod_type"] == "RESUME"
        assert resume["state"] == "APPLIED"
        assert resume["delta_price_cents"] == 0

        subscription = read_subscription(world["subscription"]["id"])
        assert subscription["lifecycle_state"] == "ACTIVE"
        assert subscription["paused_until"] is None
        assert_instant(subscription["next_renewal_at"], "2026-01-10T00:00:00Z", "next_renewal_at")
        # The pause modification remains APPLIED, so the cycles it consumed still count.
        assert subscription["pause_cycles_used"] == 1

        # The billing axis never heard about any of this.
        assert subscription["billing_state"] == "PAST_DUE"
        assert_instant(subscription["first_failed_at"], "2026-01-10T00:00:00Z", "first_failed_at")
        assert_instant(subscription["grace_end_at"], "2026-01-13T00:00:00Z", "grace_end_at")
        assert subscription["consecutive_failed_attempts"] == 1
        assert read_invoice(world["invoice"]["id"])["status"] == "FAILED"
