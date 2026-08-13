"""Invoicing, payments, voids, and arrears: payable-state gating, balance caps,
the post/void compensating pair, overdue sweeps, and PAID-state lockdown."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    assert_payment,
    create_payment_payload,
    get_lease,
    get_settlement,
    make_tenant_headers,
    setup_invoiced_settlement,
    setup_paid_settlement,
    setup_settlement_with_reports,
    validate_error,
    validate_success,
)


class TestPayableStateGate:
    def test_payment_on_accruing_settlement_rejected(self, api):
        """PRD §3.5: "Posting a payment requires the settlement to be in `INVOICED`,
        `PARTIALLY_PAID`, or `OVERDUE` — a payment aimed at an `ACCRUING` or `PAID`
        settlement is rejected with `ERR_SETTLEMENT_NOT_PAYABLE`."

        Design: Difficulty/cross_entity_state_dependency/payment_requires_payable_settlement
        """
        sc = setup_settlement_with_reports([])
        assert sc["settlement"]["status"] == "ACCRUING"
        res = api.create_payment(
            sc["settlement"]["id"],
            create_payment_payload(amount_cents=100_000),
            make_tenant_headers(sc["tenant"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_SETTLEMENT_NOT_PAYABLE)

    def test_payment_on_paid_settlement_rejected(self, api):
        """PRD §3.5: "Posting a payment requires the settlement to be in `INVOICED`,
        `PARTIALLY_PAID`, or `OVERDUE` — a payment aimed at an `ACCRUING` or `PAID`
        settlement is rejected with `ERR_SETTLEMENT_NOT_PAYABLE`."

        Design: Difficulty/cross_entity_state_dependency/payment_requires_payable_settlement
        """
        sc = setup_paid_settlement()
        assert sc["settlement"]["status"] == "PAID"
        res = api.create_payment(
            sc["settlement"]["id"],
            create_payment_payload(amount_cents=1),
            make_tenant_headers(sc["tenant"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_SETTLEMENT_NOT_PAYABLE)


class TestPostVoidLedgerConservation:
    def test_partial_payment_posts_and_repositions_settlement(self, api):
        """PRD §3.5: "A smaller payment moves an `INVOICED` settlement to
        `PARTIALLY_PAID`, and leaves a `PARTIALLY_PAID` or `OVERDUE` settlement in
        `PARTIALLY_PAID`."
        PRD §3.5: "The new payment's `settlement_id` is taken from the settlement
        being paid rather than supplied in the body, and the payment is created in
        `POSTED` status."

        Design: Difficulty/compensating_invariant/payment_post_void_conserves_ledger
        """
        sc = setup_invoiced_settlement()
        settlement = sc["settlement"]
        assert settlement["amount_due_cents"] == 1_200_000

        res = api.create_payment(
            settlement["id"],
            create_payment_payload(amount_cents=300_000),
            make_tenant_headers(sc["tenant"]["id"]),
        )
        payment = validate_success(res, 201)
        assert_payment(payment)
        assert payment["status"] == "POSTED"
        assert payment["settlement_id"] == settlement["id"]

        after = get_settlement(settlement["id"])
        assert after["status"] == "PARTIALLY_PAID"
        assert after["amount_paid_cents"] == 300_000
        assert after["balance_due_cents"] == 900_000

    def test_void_restores_ledger_and_status(self, api, analyst_headers):
        """PRD §3.5: "The void decrements the settlement's paid total by the voided
        amount, recomputes the balance, and re-derives the settlement's status: when
        no `POSTED` payments remain the settlement returns to `INVOICED`, otherwise
        it sits in `PARTIALLY_PAID`."

        Design: Difficulty/compensating_invariant/payment_post_void_conserves_ledger
        """
        sc = setup_invoiced_settlement()
        settlement = sc["settlement"]
        payment = validate_success(
            api.create_payment(
                settlement["id"],
                create_payment_payload(amount_cents=300_000),
                make_tenant_headers(sc["tenant"]["id"]),
            ),
            201,
        )

        voided = validate_success(api.void_payment(payment["id"], analyst_headers), 200)
        assert voided["status"] == "VOIDED"

        after = get_settlement(settlement["id"])
        assert after["amount_paid_cents"] == 0
        assert after["balance_due_cents"] == 1_200_000
        assert after["status"] == "INVOICED"
        # Ledger identity conserved across post + void.
        assert (
            after["amount_paid_cents"] + after["balance_due_cents"]
            == after["amount_due_cents"]
        )


class TestInvoiceGuards:
    def test_invoice_before_year_end_returns_settlement_period_open(
        self, api, analyst_headers
    ):
        """PRD §3.5: "A `ConcessionAnalyst` may invoice only from `ACCRUING` — any
        other status is rejected with `ERR_SETTLEMENT_NOT_INVOICABLE` — and only once
        the current date is later than the last day of the `period_year`, that is,
        once the year has fully elapsed; invoicing earlier is rejected with
        `ERR_SETTLEMENT_PERIOD_OPEN`."

        Design: Corner/endpoints/invoice_before_year_end_returns_settlement_period_open
        """
        # Clock stays at the startup default 2026-08-01, inside period year 2026.
        sc = setup_settlement_with_reports([])
        res = api.invoice_settlement(sc["settlement"]["id"], analyst_headers)
        validate_error(res, ApiErrorId.ERR_SETTLEMENT_PERIOD_OPEN)

    def test_invoice_paid_settlement_returns_settlement_not_invoicable(
        self, api, analyst_headers
    ):
        """PRD §3.5: "A `ConcessionAnalyst` may invoice only from `ACCRUING` — any
        other status is rejected with `ERR_SETTLEMENT_NOT_INVOICABLE` — and only once
        the current date is later than the last day of the `period_year`, that is,
        once the year has fully elapsed; invoicing earlier is rejected with
        `ERR_SETTLEMENT_PERIOD_OPEN`."

        Design: Corner/state_machines/invoice_paid_settlement_returns_settlement_not_invoicable
        """
        sc = setup_paid_settlement()
        assert sc["settlement"]["status"] == "PAID"
        res = api.invoice_settlement(sc["settlement"]["id"], analyst_headers)
        validate_error(res, ApiErrorId.ERR_SETTLEMENT_NOT_INVOICABLE)

    def test_recalculate_paid_settlement_returns_settlement_state_forbids(
        self, api, analyst_headers
    ):
        """PRD §3.4: "Manual recalculation of a `PAID` settlement is forbidden — a
        paid year reopens only through audit findings — and is rejected with
        `ERR_SETTLEMENT_STATE_FORBIDS`."

        Design: Corner/validations/recalculate_paid_settlement_returns_settlement_state_forbids
        """
        sc = setup_paid_settlement()
        assert sc["settlement"]["status"] == "PAID"
        res = api.recalculate_settlement(sc["settlement"]["id"], analyst_headers)
        validate_error(res, ApiErrorId.ERR_SETTLEMENT_STATE_FORBIDS)


class TestPaymentAmounts:
    def test_full_payment_transitions_to_paid(self, api):
        """PRD §3.5: "A payment exactly covering the outstanding balance moves an
        `INVOICED`, `PARTIALLY_PAID`, or `OVERDUE` settlement to `PAID`."

        Design: Corner/endpoints/full_payment_transitions_to_paid
        """
        sc = setup_invoiced_settlement()
        settlement = sc["settlement"]
        res = api.create_payment(
            settlement["id"],
            create_payment_payload(amount_cents=1_200_000, method="WIRE"),
            make_tenant_headers(sc["tenant"]["id"]),
        )
        payment = validate_success(res, 201)
        assert payment["status"] == "POSTED"

        after = get_settlement(settlement["id"])
        assert after["status"] == "PAID"
        assert after["amount_paid_cents"] == 1_200_000
        assert after["balance_due_cents"] == 0

    def test_payment_exceeds_balance_returns_payment_exceeds_balance(self, api):
        """PRD §3.5: "The payment carries `amount_cents`, which must be positive
        (`ERR_INVALID_AMOUNT`) and no greater than the settlement's
        `balance_due_cents` at posting time (`ERR_PAYMENT_EXCEEDS_BALANCE`), and a
        `method` of `ACH`, `CHECK`, `WIRE`, or `CARD`."

        Design: Corner/validations/payment_exceeds_balance_returns_payment_exceeds_balance
        """
        sc = setup_invoiced_settlement()
        assert sc["settlement"]["balance_due_cents"] == 1_200_000
        res = api.create_payment(
            sc["settlement"]["id"],
            create_payment_payload(amount_cents=1_200_001),
            make_tenant_headers(sc["tenant"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE)

    def test_arrears_reconciles_after_partial_payment(self, api):
        """PRD §2.9: "`arrears_cents` is the sum of `balance_due_cents` over the
        lease's settlements whose status is `INVOICED`, `PARTIALLY_PAID`, or
        `OVERDUE`; settlements still `ACCRUING` and settlements already `PAID`
        contribute zero."
        PRD §3.5: "Every posting recomputes the lease's `arrears_cents`."

        Design: Corner/cross_cutting_layers/arrears_reconciles_after_partial_payment
        """
        sc = setup_invoiced_settlement()
        settlement = sc["settlement"]
        validate_success(
            api.create_payment(
                settlement["id"],
                create_payment_payload(amount_cents=300_000),
                make_tenant_headers(sc["tenant"]["id"]),
            ),
            201,
        )
        lease = get_lease(sc["lease"]["id"])
        assert lease["arrears_cents"] == 900_000


class TestVoidIdempotency:
    def test_payment_void_twice_returns_payment_already_voided(
        self, api, analyst_headers
    ):
        """PRD §3.5: "A `ConcessionAnalyst` may void a payment as the compensating
        action, valid only while the payment is `POSTED`; voiding an already-`VOIDED`
        payment is rejected with `ERR_PAYMENT_ALREADY_VOIDED`."

        Design: Corner/state_machines/payment_void_twice_returns_payment_already_voided
        """
        sc = setup_invoiced_settlement()
        settlement = sc["settlement"]
        payment = validate_success(
            api.create_payment(
                settlement["id"],
                create_payment_payload(amount_cents=300_000),
                make_tenant_headers(sc["tenant"]["id"]),
            ),
            201,
        )
        validate_success(api.void_payment(payment["id"], analyst_headers), 200)

        res = api.void_payment(payment["id"], analyst_headers)
        validate_error(res, ApiErrorId.ERR_PAYMENT_ALREADY_VOIDED)

        after = get_settlement(settlement["id"])
        assert after["amount_paid_cents"] == 0, (
            "A rejected second void must not double-decrement the paid total"
        )


class TestOverdueSweep:
    def test_settlement_overdue_by_clock_sweep(self, api, admin_headers):
        """PRD §3.5: "The overdue sweep runs whenever the logical clock is set
        (§2.4): a settlement in `INVOICED` or `PARTIALLY_PAID` whose `due_date` is
        earlier than the new current date, and whose balance remains positive, moves
        to `OVERDUE`."
        PRD §3.5: "Invoicing performs the final recalculation, sets `variant_used` to
        `FINAL`, stamps `due_date` as the current date plus thirty days, moves the
        settlement to `INVOICED`, and recomputes the lease's `arrears_cents`."

        Design: Corner/state_machines/settlement_overdue_by_clock_sweep
        """
        sc = setup_invoiced_settlement()  # invoiced at clock 2027-01-15
        settlement = sc["settlement"]
        assert settlement["due_date"] == "2027-02-14"
        assert settlement["status"] == "INVOICED"

        advance_clock("2027-02-15T00:00:00Z")
        after = get_settlement(settlement["id"])
        assert after["status"] == "OVERDUE"

    def test_overdue_settlement_accepts_payment_to_paid(self, api):
        """PRD §3.5: "Posting a payment requires the settlement to be in `INVOICED`,
        `PARTIALLY_PAID`, or `OVERDUE` — a payment aimed at an `ACCRUING` or `PAID`
        settlement is rejected with `ERR_SETTLEMENT_NOT_PAYABLE`."
        PRD §3.5: "A payment exactly covering the outstanding balance moves an
        `INVOICED`, `PARTIALLY_PAID`, or `OVERDUE` settlement to `PAID`."

        Design: Corner/cross_cutting_layers/overdue_settlement_accepts_payment_to_paid
        """
        sc = setup_invoiced_settlement()
        settlement = sc["settlement"]
        advance_clock("2027-02-15T00:00:00Z")  # past due_date 2027-02-14
        assert get_settlement(settlement["id"])["status"] == "OVERDUE"

        validate_success(
            api.create_payment(
                settlement["id"],
                create_payment_payload(amount_cents=1_200_000),
                make_tenant_headers(sc["tenant"]["id"]),
            ),
            201,
        )
        after = get_settlement(settlement["id"])
        assert after["status"] == "PAID"
        assert after["balance_due_cents"] == 0
