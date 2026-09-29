"""The four ways a collections call can be refused rather than charged.

A settled invoice is closed to further retries, a gateway result needs an attempt to land
on, the grace window bounds the retry schedule in time, and the attempt ceiling bounds it in
count — and the two bounds are refused with different codes at different statuses.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_dunning_attempt,
    assert_instant,
    pay_invoice,
    read_invoice,
    read_subscriber,
    read_subscription,
    set_clock,
    setup_active_subscription,
    setup_dunning_chain,
    simulate_payment_payload,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BILLING = TEST_USERS["billing_operator_headers"]


def _attempt_count_of(invoice_id):
    _, meta = validate_paginated(api_client.list_dunning_attempts(
        ADMIN, params={"invoice_id": invoice_id}))
    return meta["total_count"]


class TestSettledInvoiceIsClosed:

    def test_a_paid_invoice_can_never_accumulate_another_retry(self):
        """The payable set is OPEN or FAILED, and PAID is neither.

        PRD §3.7: "**Scheduling an attempt** is a `BillingOperator` capability whose guards
        run in this order: the invoice's `status` must be `OPEN` or `FAILED`, and a `PAID` or
        `WRITTEN_OFF` invoice is rejected with `ERR_INVOICE_NOT_PAYABLE` (409); then, for any
        attempt after the first, the grace window must still be open; then the retry ceiling."

        Design: Corner/errors/retrying_a_paid_invoice_is_rejected_as_not_payable
        """
        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "SEARCH"})
        pay_invoice(world["invoice"]["id"])

        validate_error(api_client.create_dunning_attempt(world["invoice"]["id"], BILLING),
                       ApiErrorId.ERR_INVOICE_NOT_PAYABLE, 409)

        invoice = read_invoice(world["invoice"]["id"])
        assert invoice["status"] == "PAID"
        assert invoice["attempt_count"] == 1

        subscription = read_subscription(world["subscription"]["id"])
        assert subscription["billing_state"] == "CURRENT"
        assert subscription["consecutive_failed_attempts"] == 0


class TestGatewayResultNeedsAnAttempt:

    def test_a_settlement_with_no_pending_attempt_leaves_the_invoice_open(self):
        """Nothing was ever charged, so a success result cannot mark the invoice paid.

        PRD §3.7: "Its guards run in this order: the invoice's `status` must be `OPEN` or
        `FAILED` (`ERR_INVOICE_NOT_PAYABLE`, 409), then an attempt with `outcome` `PENDING`
        must actually exist on the invoice (`ERR_NO_PENDING_ATTEMPT`, 409)."

        Design: Corner/errors/settling_an_invoice_with_no_pending_attempt_is_rejected
        """
        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "SEARCH"})

        validate_error(api_client.simulate_payment(
            simulate_payment_payload(world["invoice"]["id"], "SUCCEEDED"), BILLING),
            ApiErrorId.ERR_NO_PENDING_ATTEMPT, 409)

        invoice = read_invoice(world["invoice"]["id"])
        assert invoice["status"] == "OPEN"
        assert invoice["attempt_count"] == 0
        assert _attempt_count_of(invoice["id"]) == 0
        assert read_subscriber(world["subscriber"]["id"])["realized_ltv_cents"] == 0


class TestGraceWindowBoundsTheSchedule:

    def test_a_retry_one_day_after_the_window_closes_is_refused(self):
        """The ceiling is nowhere near reached; it is the clock that ends the collection.

        PRD §3.7: "A retry requested for `attempt_number` 2 or higher when the clock has
        passed the `grace_end_at` just recomputed is rejected with `ERR_GRACE_PERIOD_ENDED`
        (409)."

        Design: Corner/errors/retrying_after_the_grace_window_closes_is_rejected
        """
        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "SEARCH"})
        setup_dunning_chain(world, ["INSUFFICIENT_FUNDS"])

        set_clock("2026-01-14")
        validate_error(api_client.create_dunning_attempt(world["invoice"]["id"], BILLING),
                       ApiErrorId.ERR_GRACE_PERIOD_ENDED, 409)

        invoice = read_invoice(world["invoice"]["id"])
        assert invoice["status"] == "FAILED"
        assert invoice["attempt_count"] == 1

        subscription = read_subscription(world["subscription"]["id"])
        assert_instant(subscription["grace_end_at"], "2026-01-13T00:00:00Z", "grace_end_at")
        assert subscription["billing_state"] == "PAST_DUE"
        assert subscription["consecutive_failed_attempts"] == 1


class TestAttemptCeiling:

    def test_a_fifth_attempt_is_refused_once_four_have_been_spent(self):
        """A zero-backoff decline keeps every attempt inside the window, so only the count bites.

        PRD §3.7: "An attempt that would carry an `attempt_number` above four — the retry
        ceiling — is rejected with `ERR_DUNNING_ATTEMPTS_EXHAUSTED` (422)."

        Design: Corner/errors/creating_a_fifth_attempt_is_rejected_as_attempts_exhausted
        """
        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "SEARCH"})
        attempts = setup_dunning_chain(world, ["LOST_STOLEN"] * 4)

        fourth = attempts[3]
        assert_dunning_attempt(fourth)
        assert fourth["attempt_number"] == 4
        assert fourth["backoff_days_applied"] == 0
        assert_instant(fourth["scheduled_at"], "2026-01-10T00:00:00Z", "scheduled_at")
        assert fourth["grace_clamped"] is False
        assert fourth["is_final"] is False

        validate_error(api_client.create_dunning_attempt(world["invoice"]["id"], BILLING),
                       ApiErrorId.ERR_DUNNING_ATTEMPTS_EXHAUSTED, 422)

        invoice = read_invoice(world["invoice"]["id"])
        assert invoice["status"] == "FAILED"
        assert invoice["attempt_count"] == 4
        assert _attempt_count_of(invoice["id"]) == 4

        subscription = read_subscription(world["subscription"]["id"])
        assert subscription["consecutive_failed_attempts"] == 4
        assert subscription["lifecycle_state"] == "ACTIVE"
