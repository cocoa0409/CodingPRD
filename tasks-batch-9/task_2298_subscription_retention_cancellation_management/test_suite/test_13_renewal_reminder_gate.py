"""Renewal on a negative-option plan is gated by a SENT renewal reminder.

Two identical subscriptions reach their renewal instant together; only one has had its
auto-scheduled reminder sent inside the legal window.  The reminder is a separate
resource, so the gate is a cross-entity read: the subscription itself is otherwise
perfectly renewable.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_instant,
    invoice_at_cycle,
    list_invoices_for,
    notice_of_type,
    pay_invoice,
    read_subscription,
    run_renewal,
    send_renewal_reminder,
    set_clock,
    setup_active_subscription,
    validate_error,
)

BILLING = TEST_USERS["billing_operator_headers"]


@pytest.fixture
def two_subscriptions_only_one_reminded():
    """Both signed up 2026-01-10; only the second has a reminder sent on 2026-01-28."""
    unreminded = setup_active_subscription(
        clock="2026-01-10", subscriber_overrides={"acquisition_channel": "ORGANIC"})
    pay_invoice(unreminded["invoice"]["id"])

    reminded = setup_active_subscription(
        clock="2026-01-10", subscriber_overrides={"acquisition_channel": "ORGANIC"})
    pay_invoice(reminded["invoice"]["id"])

    # 2026-02-07 minus the default ten-day reminder lead: the open end of the window.
    set_clock("2026-01-28")
    send_renewal_reminder(reminded, renewal_cycle_index=1)

    set_clock("2026-02-07")
    return unreminded, reminded


class TestRenewalReminderGate:

    def test_a_subscription_whose_reminder_never_went_out_cannot_renew(self,
                                                                      two_subscriptions_only_one_reminded):
        """The reminder is still SCHEDULED, so the run is refused and mutates nothing.

        PRD §3.4: "Step five is the negative-option gate. For a subscription on a
        negative-option plan, the run may only issue an invoice if a `ComplianceNotice`
        exists with `notice_type` `RENEWAL_REMINDER`, `state` `SENT`, and
        `renewal_cycle_index` equal to the cycle being renewed, whose `sent_at` falls
        inside the closed reminder window described in §2.11. If no such notice exists,
        the run is rejected with `ERR_RENEWAL_REMINDER_MISSING` (422) and **nothing at
        all is mutated**."

        Design: Difficulty/cross_entity_state_dependency/renewal_gated_by_compliance_notice_sent_state
        """
        unreminded, _ = two_subscriptions_only_one_reminded
        subscription_id = unreminded["subscription"]["id"]

        validate_error(api_client.run_renewal(subscription_id, BILLING),
                       ApiErrorId.ERR_RENEWAL_REMINDER_MISSING, 422)

        notice = notice_of_type(subscription_id, "RENEWAL_REMINDER", renewal_cycle_index=1)
        assert notice["state"] == "SCHEDULED"
        assert notice["sent_at"] is None

        subscription = read_subscription(subscription_id)
        assert_instant(subscription["next_renewal_at"], "2026-02-07T00:00:00Z", "next_renewal_at")
        assert subscription["term_shipments_delivered"] == 1
        assert subscription["term_shipments_remaining"] == 11
        # No cycle-one invoice was issued.
        assert [invoice["cycle_index"] for invoice in list_invoices_for(subscription_id)] == [0]

    def test_the_same_run_succeeds_once_the_reminder_is_sent(self,
                                                             two_subscriptions_only_one_reminded):
        """A SENT reminder for cycle one lets the run bill cycle one.

        PRD §3.4: "a new `Invoice` is created with `cycle_index` one greater than the
        previous invoice's, `status` `OPEN` and `is_renewal` true. `term_shipments_delivered`
        increments and `term_shipments_remaining` decrements, `discount_remaining_cycles`
        decrements when it is above zero, `next_renewal_at` and `next_ship_at` each
        advance by one cycle length in days".

        Design: Difficulty/cross_entity_state_dependency/renewal_gated_by_compliance_notice_sent_state
        """
        _, reminded = two_subscriptions_only_one_reminded
        subscription_id = reminded["subscription"]["id"]

        notice = notice_of_type(subscription_id, "RENEWAL_REMINDER", renewal_cycle_index=1)
        assert notice["state"] == "SENT"
        assert_instant(notice["sent_at"], "2026-01-28T00:00:00Z", "sent_at")

        run_renewal(subscription_id)

        renewal_invoice = invoice_at_cycle(subscription_id, 1)
        assert renewal_invoice["is_renewal"] is True
        assert renewal_invoice["status"] == "OPEN"
        assert renewal_invoice["amount_cents"] == 4999
        assert renewal_invoice["proration_factor"] == pytest.approx(1.0000, abs=5e-5)

        subscription = read_subscription(subscription_id)
        assert_instant(subscription["next_renewal_at"], "2026-03-07T00:00:00Z", "next_renewal_at")
        assert_instant(subscription["next_ship_at"], "2026-03-07T00:00:00Z", "next_ship_at")
        assert subscription["term_shipments_delivered"] == 2
        assert subscription["term_shipments_remaining"] == 10
