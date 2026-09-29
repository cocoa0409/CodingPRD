"""Invoices read through their parent manuscript, and cancellation once the fees have cleared."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import PRODUCTION_STAFF_HEADERS, api_client


def _setup_two_invoiced_manuscripts():
    world = fx.setup_submitted_manuscript()
    second_manuscript = fx.create_manuscript(
        world["journal"]["id"], world["author"], world["author_headers"], page_count=9
    )
    world["second_manuscript"] = second_manuscript
    world["invoice"] = fx.issue_invoice(world["manuscript"]["id"])
    world["second_invoice"] = fx.issue_invoice(second_manuscript["id"])
    return world


def _setup_cleared_fees_with_a_second_invoice():
    world = fx.setup_in_production()
    manuscript_id = world["manuscript"]["id"]
    world["invoice"] = fx.issue_invoice(manuscript_id)
    fx.pay_invoice(world["invoice"]["id"], world["invoice"]["total_due_cents"])
    world["second_invoice"] = fx.issue_invoice(manuscript_id)
    return world


def _cancel_request(invoice_id):
    return api_client.settle_apc_invoice(
        invoice_id, f.cancel_settlement_payload(), PRODUCTION_STAFF_HEADERS
    )


def test_nested_invoice_read_refuses_an_invoice_of_another_manuscript():
    """Both rows exist, so the mismatch is reported rather than the invoice returned.

    PRD: "Only once both rows exist does the server check that the invoice's `manuscript_id` equals the manuscript in the path; a mismatch is rejected with `ERR_PARENT_MISMATCH` (HTTP 409) rather than silently returning the invoice."

    Design: Corner/endpoints/nested_invoice_read_rejects_an_invoice_of_another_manuscript
    """
    world = _setup_two_invoiced_manuscripts()

    response = api_client.get_manuscript_apc_invoice(
        world["manuscript"]["id"],
        world["second_invoice"]["id"],
        PRODUCTION_STAFF_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_PARENT_MISMATCH.value, expected_status=409)


def test_nested_invoice_read_returns_the_invoice_of_its_own_manuscript():
    """Addressed through the parent it does belong to, the same row comes back.

    PRD: "Only once both rows exist does the server check that the invoice's `manuscript_id` equals the manuscript in the path; a mismatch is rejected with `ERR_PARENT_MISMATCH` (HTTP 409) rather than silently returning the invoice."

    Design: Corner/endpoints/nested_invoice_read_rejects_an_invoice_of_another_manuscript
    """
    world = _setup_two_invoiced_manuscripts()

    nested = validate_success(
        api_client.get_manuscript_apc_invoice(
            world["second_manuscript"]["id"],
            world["second_invoice"]["id"],
            PRODUCTION_STAFF_HEADERS,
        )
    )

    flat = fx.get_invoice(world["second_invoice"]["id"])
    a.assert_fields(
        nested,
        id=world["second_invoice"]["id"],
        manuscript_id=world["second_manuscript"]["id"],
        status=flat["status"],
        total_due_cents=flat["total_due_cents"],
    )


def test_payment_clears_the_fee_dimension_of_the_production_job():
    """Nothing is left at `ISSUED`, so the clearance dimension advances on the paid invoice.

    PRD: "Both `PAY` and `WAIVE` advance the manuscript's production job on the clearance dimension, `LICENSE_PENDING → FEE_CLEARED`, once no invoice of that manuscript remains at status `ISSUED`."

    Design: Corner/endpoints/invoice_cancel_rejected_once_the_fee_dimension_has_cleared
    """
    world = fx.setup_in_production()
    a.assert_production_stages(world["job"], "COPYEDITING", "LICENSE_PENDING")
    invoice = fx.issue_invoice(world["manuscript"]["id"])
    a.assert_invoice_amounts(invoice, total_due_cents=180000)

    fx.pay_invoice(invoice["id"], 180000)

    job = fx.get_only_production_job(world["manuscript"]["id"])
    a.assert_production_stages(job, "COPYEDITING", "FEE_CLEARED")
    assert fx.get_invoice(invoice["id"])["status"] == "PAID"


def test_cancellation_is_refused_once_the_clearance_dimension_has_moved_on():
    """A later invoice cannot be cancelled after an earlier payment cleared the fees.

    PRD: "`CANCEL` withdraws an invoice that should not have been issued, and is permitted only while the manuscript either has no production job at all or has one still at `clearance_stage` `LICENSE_PENDING`; a cancellation attempted after the clearance dimension has moved on is refused with `ERR_WAIVER_NOT_ALLOWED`."

    Design: Corner/endpoints/invoice_cancel_rejected_once_the_fee_dimension_has_cleared
    """
    world = _setup_cleared_fees_with_a_second_invoice()
    job = fx.get_only_production_job(world["manuscript"]["id"])
    a.assert_production_stages(job, "COPYEDITING", "FEE_CLEARED")

    response = _cancel_request(world["second_invoice"]["id"])

    validate_error(
        response, ApiErrorId.ERR_WAIVER_NOT_ALLOWED.value, expected_status=409
    )
    second = fx.get_invoice(world["second_invoice"]["id"])
    a.assert_fields(second, status="ISSUED")
    assert second.get("settled_at") is None


def test_refused_cancellation_leaves_the_receivable_ledger_standing():
    """The second invoice is still outstanding, so the journal still expects its money.

    PRD: "A journal's `apc_receivable_cents` rises by an invoice's `total_due_cents` when that invoice is issued and falls by exactly the same amount when the invoice is paid, waived or cancelled, so the receivable ledger of a journal always equals the sum of `total_due_cents` over that journal's invoices still in status `ISSUED`."

    Design: Corner/endpoints/invoice_cancel_rejected_once_the_fee_dimension_has_cleared
    """
    world = _setup_cleared_fees_with_a_second_invoice()

    _cancel_request(world["second_invoice"]["id"])

    a.assert_invoice_amounts(
        fx.get_invoice(world["second_invoice"]["id"]), total_due_cents=180000
    )
    assert fx.get_invoice(world["invoice"]["id"])["status"] == "PAID"
    a.assert_journal_ledgers(
        fx.get_journal(world["journal"]["id"]),
        apc_receivable_cents=180000,
        apc_waived_cents=0,
    )
