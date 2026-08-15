"""Premium collection, trust movements, remittance, and the grace cure loop
(PRD §3.4, §3.5)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    get_carrier,
    get_policy,
    get_policy_invoice,
    set_clock,
    setup_bound_policy,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestGraceCureCycle:
    """Difficulty instance: the Policy ACTIVE -> GRACE -> ACTIVE cycle driven
    by the clock sweep and the cure payment."""

    def test_clock_sweep_drives_policy_into_grace(self):
        """PRD §3.5: "First, every `OPEN` invoice whose `due_date` is strictly
        earlier than the current date — the due date itself is still payable,
        so the boundary is strictly-later-than, not on-or-after — and whose
        `paid_total_cents` still falls short of `amount_cents` flips to
        `DELINQUENT`. Second, every `AGENCY_BILL` policy in `ACTIVE` status
        that now has a delinquent invoice moves to `GRACE`."

        Design: Difficulty/non_linear_state_machine/policy_grace_cure_cycle
        """
        bundle = setup_bound_policy(
            billing_type="AGENCY_BILL",
            premium_annual_cents=2400000,
            effective_date="2026-08-01",
        )
        invoice = get_policy_invoice(bundle["policy"]["id"])
        assert invoice["status"] == "OPEN"
        assert invoice["due_date"] == "2026-08-31"

        set_clock("2026-09-05T00:00:00Z")

        invoice_after = validate_success(
            api_client.get_invoice(invoice["id"], ADMIN), 200
        )
        assert invoice_after["status"] == "DELINQUENT"
        policy_after = get_policy(bundle["policy"]["id"])
        assert policy_after["status"] == "GRACE"

    def test_cure_payment_returns_policy_to_active(self):
        """PRD §3.5: "When a payment under §3.4 flips an invoice to `PAID` and
        the policy has no other `DELINQUENT` invoices, the policy moves from
        `GRACE` back to `ACTIVE`."
        PRD §3.4: "A recorded payment increases `paid_total_cents` and
        increases the issuing carrier's `trust_balance_cents` by the same
        amount, whether the invoice was `OPEN` or `DELINQUENT`."

        Design: Difficulty/non_linear_state_machine/policy_grace_cure_cycle
        """
        bundle = setup_bound_policy(
            billing_type="AGENCY_BILL",
            premium_annual_cents=2400000,
            effective_date="2026-08-01",
        )
        invoice = get_policy_invoice(bundle["policy"]["id"])
        set_clock("2026-09-05T00:00:00Z")
        assert get_policy(bundle["policy"]["id"])["status"] == "GRACE"

        paid = validate_success(
            api_client.record_payment(
                invoice["id"], {"amount_cents": 2400000}, ADMIN
            ),
            200,
        )
        assert paid["status"] == "PAID"
        assert paid["paid_total_cents"] == 2400000
        assert get_policy(bundle["policy"]["id"])["status"] == "ACTIVE"
        assert get_carrier(bundle["carrier"]["id"])["trust_balance_cents"] == 2400000


class TestPaidInvoiceTerminal:
    def test_paid_invoice_rejects_payment_and_reversal(self):
        """PRD §3.4: "`PAID` is terminal: a further payment on a paid invoice,
        or an attempt to reverse a paid invoice, is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/paid_invoice_is_terminal_for_payments_and_reversal
        """
        bundle = setup_bound_policy(
            billing_type="AGENCY_BILL", premium_annual_cents=2400000
        )
        invoice = get_policy_invoice(bundle["policy"]["id"])
        validate_success(
            api_client.record_payment(
                invoice["id"], {"amount_cents": 2400000}, ADMIN
            ),
            200,
        )

        pay_res = api_client.record_payment(
            invoice["id"], {"amount_cents": 1}, ADMIN
        )
        validate_error(pay_res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        rev_res = api_client.reverse_payments(invoice["id"], ADMIN)
        validate_error(rev_res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestPaymentLimits:
    def test_overpayment_rejected(self):
        """PRD §3.4: "Each payment's `amount_cents` must be a positive
        whole-cent amount (violations fail as `ERR_INVALID_REQUEST`) and must
        not exceed the invoice's remaining balance — its `amount_cents` minus
        the `paid_total_cents` already collected — or the payment is rejected
        with `ERR_OVERPAYMENT`."

        Design: Corner/validations/overpayment_rejected
        """
        bundle = setup_bound_policy(
            billing_type="AGENCY_BILL", premium_annual_cents=2400000
        )
        invoice = get_policy_invoice(bundle["policy"]["id"])
        res = api_client.record_payment(
            invoice["id"], {"amount_cents": 2400001}, ADMIN
        )
        validate_error(res, ApiErrorId.ERR_OVERPAYMENT, expected_status=409)
        after = validate_success(api_client.get_invoice(invoice["id"], ADMIN), 200)
        assert after["paid_total_cents"] == 0

    def test_reverse_unpaid_invoice_rejected(self):
        """PRD §3.4: "It requires `paid_total_cents` to be greater than zero —
        otherwise there is `ERR_NOTHING_TO_REVERSE` — and requires the
        carrier's `trust_balance_cents` to be at least the amount being
        unwound, because money already remitted to the carrier cannot be
        pulled back; a shortfall is rejected with `ERR_TRUST_INSUFFICIENT`."

        Design: Corner/validations/reverse_unpaid_invoice_returns_409
        """
        bundle = setup_bound_policy(
            billing_type="AGENCY_BILL", premium_annual_cents=2400000
        )
        invoice = get_policy_invoice(bundle["policy"]["id"])
        res = api_client.reverse_payments(invoice["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_NOTHING_TO_REVERSE, expected_status=409)


class TestRemittance:
    def test_remit_above_remittable_rejected_boundary_allowed(self):
        """PRD §3.4: "The remittable amount is the carrier's
        `trust_balance_cents` minus the retained commission, where retained
        commission is the sum of booked amounts across all commission entries
        — every entry type — in `EXPECTED` or `MATCHED` status on that
        carrier's `AGENCY_BILL` policies. The requested amount must be
        positive and no greater than the remittable amount; anything larger
        is rejected with `ERR_REMIT_EXCEEDS_REMITTABLE`."
        PRD §3.4: "A successful remittance decreases `trust_balance_cents`
        and increases `total_remitted_cents` by the remitted amount."

        Design: Corner/validations/remit_exceeds_remittable_rejected
        """
        bundle = setup_bound_policy(
            billing_type="AGENCY_BILL", premium_annual_cents=2400000
        )
        invoice = get_policy_invoice(bundle["policy"]["id"])
        validate_success(
            api_client.record_payment(
                invoice["id"], {"amount_cents": 2400000}, ADMIN
            ),
            200,
        )
        # trust 2400000, retained (EXPECTED BASE 1200000) -> remittable 1200000.
        res = api_client.remit_carrier(
            bundle["carrier"]["id"], {"amount_cents": 1200001}, ADMIN
        )
        validate_error(
            res, ApiErrorId.ERR_REMIT_EXCEEDS_REMITTABLE, expected_status=409
        )

        ok = validate_success(
            api_client.remit_carrier(
                bundle["carrier"]["id"], {"amount_cents": 1200000}, ADMIN
            ),
            200,
        )
        assert ok["trust_balance_cents"] == 1200000
        assert ok["total_remitted_cents"] == 1200000

    def test_reverse_after_remit_trust_insufficient(self):
        """PRD §3.4: "It requires `paid_total_cents` to be greater than zero —
        otherwise there is `ERR_NOTHING_TO_REVERSE` — and requires the
        carrier's `trust_balance_cents` to be at least the amount being
        unwound, because money already remitted to the carrier cannot be
        pulled back; a shortfall is rejected with `ERR_TRUST_INSUFFICIENT`."
        PRD §3.4: "A partial payment leaves the invoice in its current
        status; only a payment that brings `paid_total_cents` level with
        `amount_cents` flips the invoice to `PAID`."

        Design: Corner/validations/reverse_after_remit_trust_insufficient
        """
        bundle = setup_bound_policy(
            billing_type="AGENCY_BILL", premium_annual_cents=4800000
        )
        invoice = get_policy_invoice(bundle["policy"]["id"])
        validate_success(
            api_client.record_payment(
                invoice["id"], {"amount_cents": 3000000}, ADMIN
            ),
            200,
        )
        # trust 3000000; retained = BASE EXPECTED 2400000 -> remittable 600000.
        validate_success(
            api_client.remit_carrier(
                bundle["carrier"]["id"], {"amount_cents": 600000}, ADMIN
            ),
            200,
        )
        carrier = get_carrier(bundle["carrier"]["id"])
        assert carrier["trust_balance_cents"] == 2400000

        res = api_client.reverse_payments(invoice["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_TRUST_INSUFFICIENT, expected_status=409)
