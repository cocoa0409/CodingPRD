"""Billing: invoice composition and rounding order, issue pins, payments with
the prepaid draw, reversals, statement read, and invoice OCC (PRD §3.9, §2.7,
§3.1, §2.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_invoice,
    assert_payment,
    complete_run,
    confirm_ticket,
    create_draft_invoice,
    create_dried_lot,
    create_issued_invoice,
    create_payment_payload,
    create_schedule,
    create_tested_lot,
    create_ticket,
    get_customer,
    get_invoice,
    make_operator_headers,
    schedule_run,
    set_clock,
    setup_base,
    setup_dried_lot_scenario,
    start_run,
    validate_error,
    validate_paginated,
    validate_success,
)


def _lines_of_type(invoice, line_type):
    return [ln for ln in invoice["lines"] if ln["line_type"] == line_type]


class TestInvoiceRoundingOrder:
    """Per-line rounding, then sum — the 9915-vs-9916 discriminator."""

    def _two_estimated_runs_scenario(self):
        ctx = setup_base(with_schedule=True)
        # Lot A: 10000 lbs @22.5 fm 4.2 -> drying 7366; run A 4.0 h estimated.
        dried_a = create_dried_lot(
            ctx["cust"]["id"], ctx["unit"]["id"],
            sample_moisture_pct=22.5, foreign_material_pct=4.2,
            run_start="2026-09-05T08:00:00Z", run_end="2026-09-05T12:00:00Z",
            meter_start=100.0, scale_out=9050, discharge=15.0,
            energy_estimated=True)
        # Lot B: 5600 lbs @20.0 fm 2.0 -> drying 2000; run B 3.0 h estimated.
        dried_b = create_dried_lot(
            ctx["cust"]["id"], ctx["unit"]["id"],
            gross_weight_lbs=39600, sample_moisture_pct=20.0,
            foreign_material_pct=2.0,
            run_start="2026-09-05T13:00:00Z", run_end="2026-09-05T16:00:00Z",
            meter_start=100.0, scale_out=5400, discharge=15.0,
            energy_estimated=True, requested_bushels=100)
        invoice = create_draft_invoice(ctx["cust"]["id"])
        return ctx, invoice, dried_a, dried_b

    def test_energy_lines_rounded_per_line(self, api, manager_headers):
        """PRD §3.9: "Rounding order is pinned: every line rounds to whole cents
        within its own calculation, and the invoice's `total_cents` is the plain
        integer sum of the rounded line amounts — never a single rounding of
        unrounded amounts."
        PRD §3.9: "`ENERGY` lines come one per `COMPLETED` run of the customer's
        lots completed inside the period, at the run's `energy_charge_cents`."

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_then_sum
        """
        _ctx, invoice, dried_a, dried_b = self._two_estimated_runs_scenario()
        energy = sorted(ln["amount_cents"] for ln in _lines_of_type(invoice, "ENERGY"))
        # run A: 68.75 therms -> 5931.25 -> 5931; run B: 46.875 -> 3984.375 -> 3984
        assert energy == [3984, 5931]
        # Per-line rounding: 5931 + 3984 = 9915; sum-then-round would give 9916.
        assert sum(energy) == 9915
        energy_refs = {ln["ref_id"] for ln in _lines_of_type(invoice, "ENERGY")}
        assert energy_refs == {dried_a["run"]["id"], dried_b["run"]["id"]}

    def test_invoice_total_is_sum_of_rounded_lines(self, api, manager_headers):
        """PRD §3.9: "Rounding order is pinned: every line rounds to whole cents
        within its own calculation, and the invoice's `total_cents` is the plain
        integer sum of the rounded line amounts — never a single rounding of
        unrounded amounts."
        PRD §3.9: "`DRYING` lines come one per distinct lot of the customer
        having at least one `COMPLETED` run whose completion date falls inside
        the period, priced by the §3.3 drying charge under the schedule whose
        window covers that completion date."
        PRD §3.9: "The new invoice stands `DRAFT`; the invoice list filters by
        `customer_id`, `schedule_id`, and `status`."

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_then_sum
        """
        _ctx, invoice, _da, _db = self._two_estimated_runs_scenario()
        assert_invoice(invoice)
        assert invoice["status"] == "DRAFT"
        drying = sorted(ln["amount_cents"] for ln in _lines_of_type(invoice, "DRYING"))
        assert drying == [2000, 7366]
        # 7366 + 5931 + 2000 + 3984 = 19281
        assert invoice["total_cents"] == 19281


class TestPaymentApplyReverseConservation:
    """Payment application and its compensating reversal restore both ledgers."""

    def _issued_scenario(self):
        # fm 4.2 -> drying 7366; metered 65 therms -> energy 5575; total 12941.
        return setup_dried_lot_scenario(
            with_schedule=True, prepaid_balance_cents=5000,
            sample_moisture_pct=22.5, foreign_material_pct=4.2,
            meter_start=1200.0, meter_end=1265.0, scale_out=9050, discharge=15.0)

    def test_payment_draws_prepaid_first_then_cash(self, api, manager_headers):
        """PRD §3.9: "The prepaid ledger draws first: the draw is the lesser of
        the account's `prepaid_balance_cents` and the invoice's
        `amount_due_cents`, and the cash `amount_cents` may not exceed the due
        remaining after that draw — `ERR_PAYMENT_EXCEEDS_DUE` (HTTP 422). The
        resulting Payment records `invoice_id`, the `direction` `APPLICATION`,
        the prepaid portion in `applied_from_prepaid_cents`, and the cash
        portion in `applied_from_cash_cents`. The invoice's due falls by draw
        plus cash, the account's prepaid balance falls by the draw, the
        invoice's version increments, and a due of zero moves the invoice
        `ISSUED` → `PAID`."

        Design: Difficulty/compensating_invariant/payment_apply_reverse_receivables_conservation
        """
        ctx = self._issued_scenario()
        invoice = create_issued_invoice(ctx["cust"]["id"], ctx["sched"])
        assert invoice["amount_due_cents"] == 12941
        payment = validate_success(api.create_payment(
            invoice["id"],
            create_payment_payload(7941, get_invoice(invoice["id"])["version"]),
            manager_headers), 201)
        assert_payment(payment)
        assert payment["direction"] == "APPLICATION"
        assert payment["applied_from_prepaid_cents"] == 5000
        assert payment["applied_from_cash_cents"] == 7941
        after = get_invoice(invoice["id"])
        assert after["amount_due_cents"] == 0
        assert after["status"] == "PAID"
        assert get_customer(ctx["cust"]["id"])["prepaid_balance_cents"] == 0

    def test_reversal_restores_due_and_prepaid(self, api, manager_headers):
        """PRD §3.9: "Reversal restores the invoice's `amount_due_cents` by the
        original prepaid plus cash portions, refunds the prepaid portion to the
        account's `prepaid_balance_cents` (the cash portion is refunded
        externally, outside this ledger), and reopens the invoice `PAID` →
        `ISSUED` when the restored due is positive."

        Design: Difficulty/compensating_invariant/payment_apply_reverse_receivables_conservation
        """
        ctx = self._issued_scenario()
        invoice = create_issued_invoice(ctx["cust"]["id"], ctx["sched"])
        payment = validate_success(api.create_payment(
            invoice["id"],
            create_payment_payload(7941, get_invoice(invoice["id"])["version"]),
            manager_headers), 201)
        reversal = validate_success(
            api.reverse_payment(payment["id"], manager_headers), 201)
        assert reversal["direction"] == "REVERSAL"
        assert reversal["reversal_of_payment_id"] == payment["id"]
        after = get_invoice(invoice["id"])
        assert after["amount_due_cents"] == 12941  # 5000 + 7941 restored
        assert after["status"] == "ISSUED"
        # Prepaid draw refunded; (due, prepaid) identical to before the payment.
        assert get_customer(ctx["cust"]["id"])["prepaid_balance_cents"] == 5000


class TestInvoiceCompositionRules:
    def test_invoice_no_billable_activity_rejected(self, api, manager_headers):
        """PRD §3.9: "A composition that produces zero lines is rejected
        outright with `ERR_NO_BILLABLE_ACTIVITY` (HTTP 422)."

        Design: Corner/validations/invoice_no_billable_activity_rejected
        """
        ctx = setup_base(with_schedule=True, with_unit=False)
        res = api.create_invoice(
            {"customer_id": ctx["cust"]["id"], "period_start": "2026-09-01",
             "period_end": "2026-09-30"}, manager_headers)
        validate_error(res, ApiErrorId.ERR_NO_BILLABLE_ACTIVITY, expected_status=422)

    def test_invoice_excludes_aborted_run_and_bills_drying_once(self, api, manager_headers):
        """PRD §3.9: "`ABORTED` and `CANCELLED` runs are excluded everywhere,
        and no lot of another customer ever contributes."
        PRD §3.9: "`DRYING` lines come one per distinct lot of the customer
        having at least one `COMPLETED` run whose completion date falls inside
        the period, priced by the §3.3 drying charge under the schedule whose
        window covers that completion date."

        Design: Corner/calculations/invoice_excludes_aborted_run_and_bills_drying_once
        """
        ctx = setup_base(with_schedule=True)
        lot, _test = create_tested_lot(ctx["cust"]["id"], sample_moisture_pct=22.5,
                                       foreign_material_pct=2.0)
        ticket = create_ticket(lot, ctx["unit"]["id"], window_date="2026-09-05",
                               requested_bushels=200)
        confirm_ticket(ticket["id"])
        # First run aborted mid-morning; the lot is dried by a second run.
        run1 = schedule_run(ctx["unit"]["id"], lot["id"], ticket["id"],
                            scheduled_start="2026-09-05T08:00:00Z",
                            scheduled_end="2026-09-05T12:00:00Z")
        set_clock("2026-09-05T08:00:00Z")
        start_run(run1["id"], meter_start_therms=1200.0)
        set_clock("2026-09-05T09:00:00Z")
        api.abort_dryer_run(run1["id"], make_operator_headers("op-1"))
        run2 = schedule_run(ctx["unit"]["id"], lot["id"], ticket["id"],
                            scheduled_start="2026-09-05T13:00:00Z",
                            scheduled_end="2026-09-05T17:00:00Z")
        set_clock("2026-09-05T13:00:00Z")
        start_run(run2["id"], meter_start_therms=1200.0)
        set_clock("2026-09-05T17:00:00Z")
        complete_run(run2["id"], scale_out_weight_lbs=9050, discharge_moisture_pct=15.0,
                     meter_end_therms=1265.0)

        invoice = create_draft_invoice(ctx["cust"]["id"])
        assert_invoice(invoice)
        drying = _lines_of_type(invoice, "DRYING")
        energy = _lines_of_type(invoice, "ENERGY")
        # 178.571428 bu * 7.5 pt * 5c = 6696.43 -> 6696 (no FM surcharge)
        assert [ln["amount_cents"] for ln in drying] == [6696]
        # Only the COMPLETED re-run's metered 65 therms -> 5575
        assert [ln["amount_cents"] for ln in energy] == [5575]
        assert all(ln["ref_id"] != run1["id"] for ln in energy)
        assert invoice["total_cents"] == 12271


class TestPaymentGates:
    def test_payment_exceeds_due_rejected(self, api, manager_headers):
        """PRD §3.9: "The prepaid ledger draws first: the draw is the lesser of
        the account's `prepaid_balance_cents` and the invoice's
        `amount_due_cents`, and the cash `amount_cents` may not exceed the due
        remaining after that draw — `ERR_PAYMENT_EXCEEDS_DUE` (HTTP 422)."

        Design: Corner/validations/payment_exceeds_due_rejected
        """
        ctx = setup_dried_lot_scenario(
            with_schedule=True, sample_moisture_pct=22.5, foreign_material_pct=4.2,
            meter_start=1200.0, meter_end=1265.0)
        invoice = create_issued_invoice(ctx["cust"]["id"], ctx["sched"])
        assert invoice["amount_due_cents"] == 12941
        # prepaid 0 -> draw 0; cash 13000 > 12941 due
        res = api.create_payment(
            invoice["id"],
            create_payment_payload(13000, get_invoice(invoice["id"])["version"]),
            manager_headers)
        validate_error(res, ApiErrorId.ERR_PAYMENT_EXCEEDS_DUE, expected_status=422)
        assert get_invoice(invoice["id"])["amount_due_cents"] == 12941
        payments, meta = validate_paginated(
            api.list_invoice_payments(invoice["id"], manager_headers))
        assert meta["total_count"] == 0

    def test_payment_on_draft_invoice_rejected(self, api, manager_headers):
        """PRD §3.9: "Payments settle ISSUED invoices, and only ISSUED invoices:
        against a `DRAFT` invoice the attempt is `ERR_INVOICE_NOT_ISSUED`
        (HTTP 409), and a fully paid invoice has nothing due, so any positive
        cash amount exceeds the remainder and is rejected with
        `ERR_PAYMENT_EXCEEDS_DUE`."

        Design: Corner/validations/payment_on_draft_invoice_rejected
        """
        ctx = setup_dried_lot_scenario(
            with_schedule=True, sample_moisture_pct=22.5, foreign_material_pct=4.2,
            meter_start=1200.0, meter_end=1265.0)
        invoice = create_draft_invoice(ctx["cust"]["id"])
        assert invoice["status"] == "DRAFT"
        # The OCC version is current; the state gate must surface instead.
        res = api.create_payment(
            invoice["id"],
            create_payment_payload(5000, invoice["version"]),
            manager_headers)
        validate_error(res, ApiErrorId.ERR_INVOICE_NOT_ISSUED, expected_status=409)


class TestPaymentReversal:
    def _paid_then_reversed(self, api, manager_headers):
        ctx = setup_dried_lot_scenario(
            with_schedule=True, sample_moisture_pct=22.5, foreign_material_pct=4.2,
            meter_start=1200.0, meter_end=1265.0)
        invoice = create_issued_invoice(ctx["cust"]["id"], ctx["sched"])
        payment = validate_success(api.create_payment(
            invoice["id"],
            create_payment_payload(12941, get_invoice(invoice["id"])["version"]),
            manager_headers), 201)
        reversal = validate_success(
            api.reverse_payment(payment["id"], manager_headers), 201)
        return ctx, invoice, payment, reversal

    def test_payment_reversal_not_reversible(self, api, manager_headers):
        """PRD §3.9: "Only a not-yet-reversed `APPLICATION` may be reversed —
        reversing a `REVERSAL`, or an `APPLICATION` already reversed, is
        `ERR_PAYMENT_NOT_REVERSIBLE` (HTTP 409)."

        Design: Corner/validations/payment_reversal_not_reversible
        """
        _ctx, _invoice, payment, reversal = self._paid_then_reversed(
            api, manager_headers)
        # Reversing the REVERSAL record is rejected.
        res = api.reverse_payment(reversal["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_PAYMENT_NOT_REVERSIBLE,
                       expected_status=409)
        # So is reversing the already-reversed APPLICATION.
        res2 = api.reverse_payment(payment["id"], manager_headers)
        validate_error(res2, ApiErrorId.ERR_PAYMENT_NOT_REVERSIBLE,
                       expected_status=409)

    def test_payment_immutability_reverse_creates_compensating_record(self, api, manager_headers):
        """PRD §3.9: "An `ElevatorManager` may reverse a payment, which mints a
        compensating Payment whose `direction` is `REVERSAL` and whose
        `reversal_of_payment_id` names the original record."
        PRD §2.5: "Payment records are immutable ledger entries and carry only
        `id` and `created_at`; both `updated_at` and `version` are absent from
        them."
        PRD §3.9: "The payments of one invoice are listable from the invoice,
        and a cross-invoice payment list filters by `invoice_id` and
        `reversal_of_payment_id`."

        Design: Corner/entities/payment_immutability_reverse_creates_compensating_record
        """
        _ctx, invoice, payment, reversal = self._paid_then_reversed(
            api, manager_headers)
        original = validate_success(api.get_payment(payment["id"], manager_headers), 200)
        # The original APPLICATION record is unchanged by the reversal.
        assert original["direction"] == "APPLICATION"
        assert original["amount_cents"] == 12941
        assert original["reversal_of_payment_id"] is None
        assert_payment(original)
        # Exactly one compensating REVERSAL record names the original.
        reversals, meta = validate_paginated(api.list_payments(
            manager_headers, params={"reversal_of_payment_id": payment["id"]}))
        assert meta["total_count"] == 1
        assert reversals[0]["id"] == reversal["id"]
        assert reversals[0]["direction"] == "REVERSAL"
        assert_payment(reversals[0])


class TestStatement:
    def test_statement_computed_read(self, api, manager_headers):
        """PRD §3.1: "A computed statement gives each account's receivables
        position at a glance: `customer_id`, `outstanding_due_cents` (the sum of
        `amount_due_cents` across the account's ISSUED invoices), the current
        `prepaid_balance_cents`, and `issued_invoice_count`."

        Design: Corner/endpoints/statement_computed_read
        """
        ctx = setup_dried_lot_scenario(
            with_schedule=True, sample_moisture_pct=22.5, foreign_material_pct=4.2,
            meter_start=1200.0, meter_end=1265.0)
        invoice = create_issued_invoice(ctx["cust"]["id"], ctx["sched"])
        statement = validate_success(
            api.get_customer_statement(ctx["cust"]["id"], manager_headers), 200)
        assert statement["customer_id"] == ctx["cust"]["id"]
        assert statement["outstanding_due_cents"] == 12941
        assert statement["issued_invoice_count"] == 1
        assert statement["prepaid_balance_cents"] == 0


class TestInvoicePaymentOcc:
    def test_occ_invoice_payment_stale_version(self, api, manager_headers):
        """PRD §2.7: "Posting a payment against an invoice requires
        `expected_invoice_version`, the client's last observed `version` of that
        invoice. A mismatch with the invoice's current version is rejected with
        `ERR_STALE_INVOICE_VERSION` (HTTP 412). Payments legitimately stack
        against the same invoice; the check prevents a client from applying cash
        against an `amount_due_cents` it has not observed. Posting a payment
        increments the invoice's version by one."

        Design: Corner/cross_cutting_layers/occ_invoice_payment_stale_version
        """
        ctx = setup_dried_lot_scenario(
            with_schedule=True, sample_moisture_pct=22.5, foreign_material_pct=4.2,
            meter_start=1200.0, meter_end=1265.0)
        invoice = create_issued_invoice(ctx["cust"]["id"], ctx["sched"])
        observed = get_invoice(invoice["id"])["version"]
        first = api.create_payment(
            invoice["id"], create_payment_payload(5000, observed), manager_headers)
        validate_success(first, 201)
        assert get_invoice(invoice["id"])["amount_due_cents"] == 7941
        # Replaying the stale observed version is rejected and changes nothing.
        replay = api.create_payment(
            invoice["id"], create_payment_payload(5000, observed), manager_headers)
        validate_error(replay, ApiErrorId.ERR_STALE_INVOICE_VERSION,
                       expected_status=412)
        assert get_invoice(invoice["id"])["amount_due_cents"] == 7941
