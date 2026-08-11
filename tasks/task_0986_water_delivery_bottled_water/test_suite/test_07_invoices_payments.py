"""Invoices and payments: dispute cycle, tier upgrade boundary, apply/refund
compensation, overpayment, immediate consistency, and period validation."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    setup_customer, setup_open_invoice, deliver_via_work_order,
    create_and_issue_invoice, create_draft_invoice, create_payment_payload,
    pay_invoice, set_clock, get_customer, get_invoice,
    make_customer_self_headers,
    OPS_ADMIN, DISPATCHER, BILLING_ADMIN,
)

STANDARD_RATE = 700  # standard_per_bottle_cents from the standard pricing config


class TestInvoiceDisputeCycle:
    def _open_invoice(self, api, bottles=5):
        return setup_open_invoice(bottles=bottles, requested_date="2026-05-10",
                                  period=("2026-05-01", "2026-06-01"),
                                  due_date="2026-06-15")

    def test_dispute_then_restore_returns_invoice_to_open(self, api):
        """PRD §3.8: "The customer may dispute an invoice standing in `OPEN` or
        `PARTIALLY_PAID` — any other source state is rejected with
        `ERR_INVALID_STATE`, and cross-account disputes earn `ERR_FORBIDDEN` —
        moving it to `DISPUTED`, where the clock-driven slide into `OVERDUE` is
        suppressed. Resolution is a `BillingAdmin` decision expressed as an
        `outcome`: `RESTORE` returns the invoice to `OPEN` with its balance
        intact, while `VOID` zeroes the `balance_due_cents`, drops the invoice
        into the terminal `VOID` state, and refreshes the customer's outstanding
        balance."

        Design: Difficulty/non_linear_state_machine/invoice_dispute_cycle
        """
        s = self._open_invoice(api)
        invoice = s["invoice"]
        balance_before = invoice["balance_due_cents"]
        self_headers = make_customer_self_headers(s["customer"]["id"])

        disputed = validate_success(api.dispute_invoice(invoice["id"], self_headers), 200)
        assert disputed["invoice_status"] == "DISPUTED"

        restored = validate_success(
            api.resolve_dispute(invoice["id"], {"outcome": "RESTORE"}, BILLING_ADMIN), 200)
        assert restored["invoice_status"] == "OPEN", \
            f"RESTORE must cycle the invoice back to OPEN, got {restored['invoice_status']}"
        assert restored["balance_due_cents"] == balance_before, \
            "RESTORE returns the invoice with its balance intact"

    def test_dispute_then_void_zeroes_balance_terminally(self, api):
        """PRD §3.8: "Resolution is a `BillingAdmin` decision expressed as an
        `outcome`: `RESTORE` returns the invoice to `OPEN` with its balance
        intact, while `VOID` zeroes the `balance_due_cents`, drops the invoice
        into the terminal `VOID` state, and refreshes the customer's outstanding
        balance."

        The full cycle — OPEN to DISPUTED, RESTORE to OPEN, DISPUTED again,
        then VOID — leaves the invoice terminal with a zeroed balance.

        Design: Difficulty/non_linear_state_machine/invoice_dispute_cycle
        """
        s = self._open_invoice(api)
        invoice = s["invoice"]
        self_headers = make_customer_self_headers(s["customer"]["id"])

        validate_success(api.dispute_invoice(invoice["id"], self_headers), 200)
        validate_success(
            api.resolve_dispute(invoice["id"], {"outcome": "RESTORE"}, BILLING_ADMIN), 200)
        validate_success(api.dispute_invoice(invoice["id"], self_headers), 200)
        voided = validate_success(
            api.resolve_dispute(invoice["id"], {"outcome": "VOID"}, BILLING_ADMIN), 200)
        assert voided["invoice_status"] == "VOID"
        assert voided["balance_due_cents"] == 0, \
            f"VOID must zero the balance, got {voided['balance_due_cents']}"

    def test_invoice_terminal_void_no_further_transitions(self, api):
        """PRD §3.8: "A `BillingAdmin` may also void an invoice directly, but
        only while it is still a `DRAFT`."
        PRD §2.6: "Whether the target resource is in a state that permits the
        requested transition — violations return `ERR_INVALID_STATE`; an
        operation attempted on a resource already sitting in a terminal state is
        instead rejected with `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/invoice_terminal_void_no_further_transitions
        """
        world = setup_customer(account_type="OFFICE", business_name="VoidCo",
                               billing_email="v@x.example", service_address="1 V",
                               service_mode="WILL_CALL", par_level_bottles=0,
                               pricing_tier="STANDARD")
        customer = world["customer"]
        invoice = create_draft_invoice(customer["id"], "2026-05-01", "2026-06-01",
                                       "2026-06-15")
        voided = validate_success(api.void_invoice(invoice["id"], BILLING_ADMIN), 200)
        assert voided["invoice_status"] == "VOID"

        res = api.dispute_invoice(invoice["id"],
                                  make_customer_self_headers(customer["id"]))
        validate_error(res, "ERR_ALREADY_TERMINAL")


class TestTierUpgradeBoundary:
    def _deliver_and_issue(self, api, bottles):
        world = setup_customer(account_type="OFFICE", business_name="TierCo",
                               billing_email="t@x.example", service_address="1 T",
                               service_mode="WILL_CALL", par_level_bottles=0,
                               pricing_tier="STANDARD")
        zone, customer = world["zone"], world["customer"]
        deliver_via_work_order(customer["id"], zone["id"], "2026-05-10", bottles,
                               actual_bottles_delivered=bottles,
                               actual_empties_collected=bottles)
        set_clock("2026-06-01T00:00:00Z")
        invoice = create_and_issue_invoice(customer["id"], "2026-05-01",
                                           "2026-06-01", "2026-06-15")
        return customer, invoice

    def test_tier_upgrade_at_threshold_inclusive(self, api):
        """PRD §3.8: "Issuing also looks forward: the bottles the customer
        actually took in the period just closed — the sum of
        `actual_bottles_delivered` across their `DELIVERED` and `PARTIAL` stops
        — are compared against the active thresholds, and a count meeting or
        exceeding `gold_volume_threshold` earns `GOLD`, meeting or exceeding
        `silver_volume_threshold` earns `SILVER`, and anything less earns
        `STANDARD`, with the thresholds inclusive and the new `pricing_tier`
        taking effect for the next period only, since the current period has
        already been billed at the prior tier."

        Exactly 20 bottles meets silver_volume_threshold=20 inclusively.

        Design: Difficulty/boundary_precision_check/tier_upgrade_at_threshold_inclusive
        """
        customer, _invoice = self._deliver_and_issue(api, 20)
        after = get_customer(customer["id"])
        assert after["pricing_tier"] == "SILVER", (
            f"20 bottles meets the inclusive silver threshold (20), "
            f"got tier {after['pricing_tier']}"
        )

    def test_one_below_threshold_keeps_standard(self, api):
        """PRD §3.8: "Issuing also looks forward: the bottles the customer
        actually took in the period just closed — the sum of
        `actual_bottles_delivered` across their `DELIVERED` and `PARTIAL` stops
        — are compared against the active thresholds, and a count meeting or
        exceeding `gold_volume_threshold` earns `GOLD`, meeting or exceeding
        `silver_volume_threshold` earns `SILVER`, and anything less earns
        `STANDARD`, with the thresholds inclusive and the new `pricing_tier`
        taking effect for the next period only, since the current period has
        already been billed at the prior tier."

        Nineteen bottles is anything less than the threshold, so STANDARD stays.

        Design: Difficulty/boundary_precision_check/tier_upgrade_at_threshold_inclusive
        """
        customer, _invoice = self._deliver_and_issue(api, 19)
        after = get_customer(customer["id"])
        assert after["pricing_tier"] == "STANDARD", (
            f"19 bottles is below the silver threshold (20), "
            f"got tier {after['pricing_tier']}"
        )


class TestPaymentApplyRefundInvariant:
    def _paid_scenario(self, api, bottles=10):
        """OPEN invoice for `bottles` bottles, then a full payment applied."""
        s = setup_open_invoice(bottles=bottles, requested_date="2026-05-10",
                               period=("2026-05-01", "2026-06-01"),
                               due_date="2026-06-15")
        invoice = s["invoice"]
        payment = pay_invoice(invoice["id"], invoice["total_due_cents"])
        return s, invoice, payment

    def test_refund_restores_balance_and_reopens_invoice(self, api):
        """PRD §3.8: "a payment already `APPLIED` against a `PAID` invoice may
        be refunded — its `payment_status` moving to the terminal `REFUNDED`
        state — which returns the amount to the invoice's balance, reopens the
        invoice from `PAID` back to `OPEN`, and again recomputes the customer's
        standing."

        Design: Difficulty/compensating_invariant/payment_apply_then_refund_invariant
        """
        s, invoice, payment = self._paid_scenario(api)
        expected_balance = 10 * STANDARD_RATE
        assert invoice["balance_due_cents"] == expected_balance

        paid = get_invoice(invoice["id"])
        assert paid["invoice_status"] == "PAID"
        assert paid["balance_due_cents"] == 0

        refunded = validate_success(api.refund_payment(payment["id"], BILLING_ADMIN), 200)
        assert refunded["payment_status"] == "REFUNDED"

        reopened = get_invoice(invoice["id"])
        assert reopened["invoice_status"] == "OPEN", \
            f"refund must reopen the invoice from PAID to OPEN, got {reopened['invoice_status']}"
        assert reopened["balance_due_cents"] == expected_balance, (
            f"apply-then-refund must restore the balance to {expected_balance}, "
            f"got {reopened['balance_due_cents']}"
        )

    def test_outstanding_balance_tracks_apply_then_refund(self, api):
        """PRD §3.8: "A customer's `outstanding_balance_cents` is always the sum
        of `balance_due_cents` across their invoices standing in `OPEN`,
        `OVERDUE`, `PARTIALLY_PAID`, or `DISPUTED`, recomputed on every invoice
        state change and every payment application or refund."

        Design: Difficulty/compensating_invariant/payment_apply_then_refund_invariant
        """
        s, invoice, payment = self._paid_scenario(api)
        customer_id = s["customer"]["id"]
        expected_balance = 10 * STANDARD_RATE

        assert get_customer(customer_id)["outstanding_balance_cents"] == 0, \
            "after a full apply the customer owes nothing"
        validate_success(api.refund_payment(payment["id"], BILLING_ADMIN), 200)
        after = get_customer(customer_id)
        assert after["outstanding_balance_cents"] == expected_balance, (
            f"refund reopens the invoice, so outstanding returns to "
            f"{expected_balance}, got {after['outstanding_balance_cents']}"
        )


class TestPaymentGuards:
    def test_overpayment_rejected(self, api):
        """PRD §3.8: "Application is where money moves: a `PENDING` payment may
        be applied only while its invoice stands in `OPEN`, `OVERDUE`,
        `PARTIALLY_PAID`, or `DISPUTED`, and its `amount_cents` may not exceed
        the invoice's `balance_due_cents` — an overlarge application is rejected
        with `ERR_OVERPAYMENT`."

        Design: Corner/validations/overpayment_rejected
        """
        s = setup_open_invoice(bottles=1, requested_date="2026-05-05")
        invoice = s["invoice"]
        assert invoice["balance_due_cents"] == 700
        payment = validate_success(
            api.create_payment(create_payment_payload(invoice["id"], 99999),
                               BILLING_ADMIN),
            201,
        )
        res = api.apply_payment(payment["id"], BILLING_ADMIN)
        validate_error(res, "ERR_OVERPAYMENT")

    def test_invoice_balance_immediately_consistent_after_payment(self, api):
        """PRD §3.8: "A successful application stamps `applied_at`, reduces the
        invoice balance by the payment amount, and lets the invoice follow the
        money: an applied amount smaller than the balance moves an `OPEN` or
        `OVERDUE` invoice to `PARTIALLY_PAID`, while an amount that covers the
        balance in full moves the invoice to `PAID` from `OPEN`, `OVERDUE`,
        `PARTIALLY_PAID`, or `DISPUTED`, zeroing its balance."
        PRD §3.8: "A customer's `outstanding_balance_cents` is always the sum of
        `balance_due_cents` across their invoices standing in `OPEN`,
        `OVERDUE`, `PARTIALLY_PAID`, or `DISPUTED`, recomputed on every invoice
        state change and every payment application or refund."

        Design: Corner/consistency_model/invoice_balance_immediately_consistent_after_payment
        """
        s = setup_open_invoice(bottles=1, requested_date="2026-05-05")
        invoice = s["invoice"]
        payment = validate_success(
            api.create_payment(create_payment_payload(invoice["id"], 700),
                               BILLING_ADMIN),
            201,
        )
        validate_success(api.apply_payment(payment["id"], BILLING_ADMIN), 200)

        after = get_invoice(invoice["id"])
        assert after["balance_due_cents"] == 0, \
            f"the very next read must show the applied payment, got {after['balance_due_cents']}"
        assert after["invoice_status"] == "PAID"
        customer = get_customer(s["customer"]["id"])
        assert customer["outstanding_balance_cents"] == 0, (
            f"customer standing must be recomputed immediately, "
            f"got {customer['outstanding_balance_cents']}"
        )

    def test_invalid_date_range_on_invoice(self, api):
        """PRD §3.8: "The period is a half-open interval — it includes the start
        date and excludes the end date — and an end that does not fall strictly
        after the start is rejected with `ERR_INVALID_DATE_RANGE`."

        Design: Corner/validations/invalid_date_range_on_invoice
        """
        world = setup_customer(account_type="HOME", business_name="BadDate",
                               billing_email="b@x.example", service_address="1 B")
        res = api.create_invoice(
            {
                "customer_id": world["customer"]["id"],
                "billing_period_start": "2026-06-01",
                "billing_period_end": "2026-05-01",
                "due_date": "2026-07-01",
            },
            BILLING_ADMIN,
        )
        validate_error(res, "ERR_INVALID_DATE_RANGE")
