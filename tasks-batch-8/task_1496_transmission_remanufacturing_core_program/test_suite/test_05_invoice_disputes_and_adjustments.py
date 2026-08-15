"""Dispute lifecycle: gates on dispute/resolve, the re-inspection cycle, and
adjusted settlement conserving the deposit invariant."""
import pytest

from test_helpers import (
    ADMIN,
    ANY_H,
    CLERK,
    ApiErrorId,
    assert_deposit_invariant,
    create_resolve_dispute_payload,
    drive_order_to_shipped,
    get_invoice,
    get_order,
    inspect_core,
    setup_disputed_invoice,
    setup_graded_core,
    api_client,
    validate_error,
    validate_success,
)


class TestDisputeGates:

    def test_dispute_open_invoice_rejected(self):
        """PRD §3.7: "Disputing is allowed only from `SETTLED_PARTIAL` or `FORFEITED` (`ERR_INVOICE_NOT_DISPUTABLE`) and moves the invoice to `DISPUTED`."

        Design: Corner/state_machines/dispute_from_open_invoice_rejected
        """
        _m, _o, invoice = drive_order_to_shipped()
        assert invoice["status"] == "OPEN"
        resp = api_client.dispute_invoice(invoice["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_DISPUTABLE)
        after = get_invoice(invoice["id"])
        assert after["status"] == "OPEN", "a rejected dispute must not move the invoice"

    def test_resolve_without_dispute_rejected(self):
        """PRD §3.7: "Resolution is a `ProgramAdmin` act requiring `DISPUTED` status (`ERR_INVOICE_NOT_DISPUTED`) and an `action`."

        Design: Corner/errors/resolve_without_dispute_rejected
        """
        _m, _o, invoice, _core = setup_graded_core(
            findings=["SENSOR_HARNESS_MISSING"])
        assert invoice["status"] == "SETTLED_PARTIAL"
        resp = api_client.resolve_dispute(
            invoice["id"], create_resolve_dispute_payload("ADJUST", 40000), ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_DISPUTED)
        after = get_invoice(invoice["id"])
        assert after["status"] == "SETTLED_PARTIAL"
        assert after["final_credit_cents"] == 37500, \
            "a rejected resolution must not alter the settlement"

    def test_adjust_out_of_range_rejected(self):
        """PRD §3.7: "Choosing `ADJUST` settles immediately at a supplied `adjusted_credit_cents`, which must lie between 0 and `deposit_cents` inclusive (`ERR_ADJUSTMENT_OUT_OF_RANGE`)".

        Design: Corner/validations/resolve_adjust_out_of_range_rejected
        """
        _m, _o, invoice, _core = setup_disputed_invoice()
        assert invoice["status"] == "DISPUTED"
        assert invoice["deposit_cents"] == 50000
        resp = api_client.resolve_dispute(
            invoice["id"], create_resolve_dispute_payload("ADJUST", 60000), ADMIN)
        validate_error(resp, ApiErrorId.ERR_ADJUSTMENT_OUT_OF_RANGE)
        after = get_invoice(invoice["id"])
        assert after["status"] == "DISPUTED", \
            "an out-of-range adjustment must leave the invoice disputed"


class TestReinspectCycle:

    def test_reinspect_reopens_grading(self):
        """PRD §3.7: "Choosing `REINSPECT` reopens grading: the invoice returns to `AWAITING_GRADE` and the linked core — whether `GRADED` or `REJECTED` — moves to `RE_INSPECTION`".

        Design: Difficulty/non_linear_state_machine/invoice_dispute_reinspection_cycle
        """
        _m, _o, invoice, core = setup_disputed_invoice()
        resp = api_client.resolve_dispute(
            invoice["id"], create_resolve_dispute_payload("REINSPECT"), ADMIN)
        reopened = validate_success(resp)
        assert reopened["status"] == "AWAITING_GRADE"

        core_after = validate_success(api_client.get_core_unit(core["id"], ANY_H))
        assert core_after["status"] == "RE_INSPECTION"

    def test_reinspect_cycle_settles_full(self):
        """PRD §3.7: "the next inspection re-runs the full grading and settlement cascade of §3.6 and overwrites the prior `final_credit_cents` and `forfeited_cents`."
        PRD §3.6: "Whenever an invoice reaches `SETTLED_FULL`, the linked order's `core_settlement_status` flips from `PENDING` to `CLOSED`".

        Design: Difficulty/non_linear_state_machine/invoice_dispute_reinspection_cycle
        """
        _m, order, invoice, core = setup_disputed_invoice()
        # the disputed settlement was grade B: 37500 / 12500
        assert invoice["status"] == "DISPUTED"

        api_client.resolve_dispute(
            invoice["id"], create_resolve_dispute_payload("REINSPECT"), ADMIN)
        graded = inspect_core(core["id"], findings=[])  # clean re-inspection
        assert graded["grade"] == "A"
        assert graded["status"] == "GRADED"

        settled = get_invoice(invoice["id"])
        assert settled["status"] == "SETTLED_FULL"
        assert settled["final_credit_cents"] == 50000, \
            "the re-inspection overwrites the partial settlement in full"
        assert settled["forfeited_cents"] == 0
        assert_deposit_invariant(settled)

        order_after = get_order(order["id"])
        assert order_after["core_settlement_status"] == "CLOSED"


class TestDepositConservation:

    def test_grade_settlement_conserves_deposit(self):
        """PRD §2.6: "Every settled invoice honors the deposit invariant: `final_credit_cents` plus `forfeited_cents` always equals `deposit_cents`."
        PRD §3.6: "`forfeited_cents` is the deposit minus that credit".

        Design: Difficulty/compensating_invariant/deposit_settlement_adjustment_conserves_total
        """
        _m, _o, invoice, _core = setup_graded_core(
            findings=["SENSOR_HARNESS_MISSING"])
        assert invoice["status"] == "SETTLED_PARTIAL"
        assert invoice["final_credit_cents"] == 37500
        assert invoice["forfeited_cents"] == 12500
        assert invoice["final_credit_cents"] + invoice["forfeited_cents"] == 50000
        assert_deposit_invariant(invoice)

    def test_adjust_resplits_and_conserves_deposit(self):
        """PRD §3.7: "`final_credit_cents` takes the adjusted value, `forfeited_cents` becomes the deposit minus it, the invoice lands in `SETTLED_ADJUSTED`, and the linked order's `core_settlement_status` flips from `PENDING` to `CLOSED`."
        PRD §2.6: "Every settled invoice honors the deposit invariant: `final_credit_cents` plus `forfeited_cents` always equals `deposit_cents`."

        Design: Difficulty/compensating_invariant/deposit_settlement_adjustment_conserves_total
        """
        _m, order, invoice, _core = setup_disputed_invoice()
        resp = api_client.resolve_dispute(
            invoice["id"], create_resolve_dispute_payload("ADJUST", 40000), ADMIN)
        adjusted = validate_success(resp)
        assert adjusted["status"] == "SETTLED_ADJUSTED"
        assert adjusted["final_credit_cents"] == 40000
        assert adjusted["forfeited_cents"] == 10000
        assert adjusted["final_credit_cents"] + adjusted["forfeited_cents"] == 50000, \
            "the adjustment re-splits but never leaks the deposit total"
        assert adjusted["deposit_cents"] == 50000
        assert_deposit_invariant(adjusted)

        order_after = get_order(order["id"])
        assert order_after["core_settlement_status"] == "CLOSED", \
            "an adjusted settlement also closes the order's core settlement"
