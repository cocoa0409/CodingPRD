"""Money to the cent, deposits behind the fee dimension, embargoes only on the green route."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import PRODUCTION_STAFF_HEADERS, api_client


def _payment_request(invoice_id, amount_cents):
    return api_client.settle_apc_invoice(
        invoice_id, f.pay_settlement_payload(amount_cents), PRODUCTION_STAFF_HEADERS
    )


def _deposit_request(job_id):
    return api_client.record_archival_deposit(
        job_id,
        f.archival_deposit_payload(
            "PORTICO", deposit_reference="PORTICO-RECEIPT-0009"
        ),
        PRODUCTION_STAFF_HEADERS,
    )


def _licensing_request(manuscript_id, oa_license, author_headers):
    return api_client.change_licensing(
        manuscript_id,
        f.licensing_payload(oa_license, embargo_requested=True),
        author_headers,
    )


def _setup_issued_invoice_in_production():
    """An accepted manuscript in production carrying one `ISSUED` invoice."""
    world = fx.setup_in_production()
    world["invoice"] = fx.issue_invoice(world["manuscript"]["id"])
    world["job"] = fx.get_production_job(world["job"]["id"])
    return world


def _setup_proof_approved_without_fee_clearance():
    """A job at `PROOF_APPROVED` whose clearance dimension never left `LICENSE_PENDING`."""
    world = fx.setup_in_production()
    job_id = world["job"]["id"]
    fx.book_typeset_slot(job_id, "2026-08-10", "2026-08-12")
    fx.advance_content(job_id, "TYPESETTING")
    fx.advance_content(job_id, "PROOF_SENT")
    fx.approve_proof(job_id, world["author_headers"], True)
    world["job"] = fx.get_production_job(job_id)
    return world


def test_payment_one_cent_short_is_not_a_payment():
    """A cent short of the invoice is refused exactly like any other partial payment.

    PRD: "Partial payments, over-payments and attempts to pay a zero-value invoice are all refused with `ERR_PAYMENT_AMOUNT_MISMATCH`."

    Design: Corner/validations/settlement_pay_rejected_when_amount_is_one_cent_short
    """
    world = _setup_issued_invoice_in_production()
    a.assert_invoice_amounts(world["invoice"], total_due_cents=180000)

    response = _payment_request(world["invoice"]["id"], 179999)

    validate_error(
        response, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value, expected_status=409
    )


def test_short_payment_leaves_the_receivable_ledger_standing():
    """The invoice is still owed, and the journal still carries the full receivable.

    PRD: "A journal's `apc_receivable_cents` rises by an invoice's `total_due_cents` when that invoice is issued and falls by exactly the same amount when the invoice is paid, waived or cancelled, so the receivable ledger of a journal always equals the sum of `total_due_cents` over that journal's invoices still in status `ISSUED`."

    Design: Corner/validations/settlement_pay_rejected_when_amount_is_one_cent_short
    """
    world = _setup_issued_invoice_in_production()

    _payment_request(world["invoice"]["id"], 179999)

    invoice = fx.get_invoice(world["invoice"]["id"])
    a.assert_fields(invoice, status="ISSUED")
    a.assert_invoice_amounts(invoice, total_due_cents=180000)
    assert invoice.get("settled_at") is None
    a.assert_journal_ledgers(
        fx.get_journal(world["journal"]["id"]),
        apc_receivable_cents=180000,
        apc_waived_cents=0,
    )
    a.assert_production_stages(
        fx.get_production_job(world["job"]["id"]), "COPYEDITING", "LICENSE_PENDING"
    )


def test_payment_of_the_exact_amount_settles_the_invoice():
    """One cent more than the refused amount closes the invoice.

    PRD: "On success the invoice moves `ISSUED → PAID` and the journal's `apc_receivable_cents` falls by `total_due_cents`."

    Design: Corner/validations/settlement_pay_rejected_when_amount_is_one_cent_short
    """
    world = _setup_issued_invoice_in_production()

    paid = validate_success(_payment_request(world["invoice"]["id"], 180000))

    a.assert_fields(paid, status="PAID")
    a.assert_journal_ledgers(
        fx.get_journal(world["journal"]["id"]),
        apc_receivable_cents=0,
        apc_waived_cents=0,
    )
    a.assert_production_stages(
        fx.get_production_job(world["job"]["id"]), "COPYEDITING", "FEE_CLEARED"
    )


def test_archival_deposit_before_fee_clearance_is_premature():
    """An approved proof is no substitute for a cleared fee.

    PRD: "Archival deposit, `FEE_CLEARED → DEPOSIT_CONFIRMED`, is recorded by the production desk with an `archival_repository` drawn from `CLOCKSS`, `PORTICO` and `LOCKSS` and a `deposit_reference` carrying the archive's receipt identifier; it requires the manuscript to be `IN_PRODUCTION` and the clearance dimension to have reached `FEE_CLEARED`, an earlier attempt being refused with `ERR_DEPOSIT_NOT_READY`."

    Design: Corner/validations/archival_deposit_rejected_before_the_fee_dimension_clears
    """
    world = _setup_proof_approved_without_fee_clearance()
    a.assert_production_stages(world["job"], "PROOF_APPROVED", "LICENSE_PENDING")

    response = _deposit_request(world["job"]["id"])

    validate_error(
        response, ApiErrorId.ERR_DEPOSIT_NOT_READY.value, expected_status=409
    )


def test_premature_deposit_stores_neither_repository_nor_receipt():
    """The refused deposit wrote no archive fields and moved no dimension.

    PRD: "A successful deposit stores both fields, leaves the content dimension untouched, and raises the job's `version` by 1."

    Design: Corner/validations/archival_deposit_rejected_before_the_fee_dimension_clears
    """
    world = _setup_proof_approved_without_fee_clearance()

    _deposit_request(world["job"]["id"])

    job = fx.get_production_job(world["job"]["id"])
    a.assert_production_stages(job, "PROOF_APPROVED", "LICENSE_PENDING")
    assert job.get("archival_repository") is None
    assert job.get("deposit_reference") is None
    assert fx.get_manuscript(world["manuscript"]["id"])["status"] == "IN_PRODUCTION"


def test_embargo_is_refused_on_a_cc_by_manuscript():
    """A liberal licence publishes immediately, so there is nothing to embargo.

    PRD: "The same request may carry `embargo_requested`, and here the licence choice is decisive: an embargo is meaningful only on the green self-archiving route, so `embargo_requested` set to true against `CC_BY`, `CC_BY_NC` or `CC_BY_NC_ND` is refused with `ERR_EMBARGO_NOT_APPLICABLE`, those three licences publishing immediately."

    Design: Corner/validations/embargo_request_rejected_for_cc_by_then_accepted_for_green
    """
    world = fx.setup_submitted_manuscript()
    a.assert_fields(world["manuscript"], oa_license="CC_BY")

    response = _licensing_request(
        world["manuscript"]["id"], "CC_BY", world["author_headers"]
    )

    validate_error(
        response, ApiErrorId.ERR_EMBARGO_NOT_APPLICABLE.value, expected_status=409
    )
    manuscript = fx.get_manuscript(world["manuscript"]["id"])
    a.assert_fields(manuscript, oa_license="CC_BY", status="SUBMITTED")
    assert manuscript.get("embargo_end_date") is None


def test_embargo_is_accepted_on_the_green_self_archive_route():
    """The identical request carried on the green licence goes through.

    PRD: "An embargo is requested only for the `GREEN_SELF_ARCHIVE` licence — otherwise `ERR_EMBARGO_NOT_APPLICABLE` (409), on the licensing change."

    Design: Corner/validations/embargo_request_rejected_for_cc_by_then_accepted_for_green
    """
    world = fx.setup_submitted_manuscript()

    changed = validate_success(
        _licensing_request(
            world["manuscript"]["id"], "GREEN_SELF_ARCHIVE", world["author_headers"]
        )
    )

    a.assert_fields(changed, oa_license="GREEN_SELF_ARCHIVE", status="SUBMITTED")
    assert changed.get("embargo_end_date") is None
