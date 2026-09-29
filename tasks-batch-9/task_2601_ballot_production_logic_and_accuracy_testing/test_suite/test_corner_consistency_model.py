"""Immediate consistency of the print-run money and quality ledgers.

The service recomputes every derived figure inside the request that changes its
inputs, including figures that live on a different aggregate from the row being
written. These tests prove that the press-proof approval already carries its
estimate invoice and has already moved the election's committed print total, and
that the delivery already carries the final invoice, the re-derived vendor
defect rate, the created lot rows and the appended custody trail.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users

ELECTION_INSTANT = "2026-11-03T00:00:00Z"


def _proof_pending_job(client):
    """A locked election with one secure two-press-line vendor and one PROOF_PENDING job."""
    sc = fx.styles_locked(client, election_overrides={"election_date": ELECTION_INSTANT},
                          registered_voter_count=100)
    fx.add_vendor(sc)
    fx.add_print_job(sc, quantity_ordered=12500)
    return sc


# ---- The estimate invoice and the election's committed total ----

def test_cm_estimate_invoice_lands_inside_the_approval_response(client):
    """Approving the press proof returns the whole ESTIMATE invoice in its own response and
    has already raised the election's committed print total to the same figure.

    PRD Section 2.10: "The service is immediately consistent: derived fields are recomputed inside the request that changes their inputs, and the response body of the triggering request already reflects the new values."

    Design: Corner/consistency_model/cm_derived_fields_are_visible_in_the_triggering_response
    """
    sc = _proof_pending_job(client)

    job = validate_success(client.approve_press_proof(sc.job_id, users.DIRECTOR))

    a.assert_fields_equal(
        job,
        {
            "status": c.JOB_PRINTING,
            "invoice_basis": c.INVOICE_ESTIMATE,
            "invoice_subtotal_cents": 105625,
            "freight_cents": 45000,
            "defect_credit_cents": 0,
            "invoice_total_cents": 150625,
            "delivered_quantity": 0,
        },
        "print job",
    )

    election = validate_success(client.get_election(sc.election_id, users.DIRECTOR))
    a.assert_fields_equal(election, {"committed_print_cents": 150625}, "election")


# ---- The cumulative defect rate and the final invoice ----

def test_cm_inspection_and_delivery_rewrite_every_ledger_in_one_request(client):
    """The inspection response already carries the 120-basis-point cumulative rate and the
    vendor's rolling rate, and the delivery response already carries the FINAL invoice, the
    lot row and the appended custody line.

    PRD Section 3.6: "`invoice_subtotal_cents` is computed lot by lot rather than in one line: the job's lots whose custody state is not `VOIDED` are taken in `lot_code` ascending order, each lot's shipped quantity is multiplied by the contract rate and divided by 1000 and **rounded half up to a whole cent individually**, and those per-lot amounts are then added together — round-then-sum, rather than the estimate's sum-then-round."

    Design: Corner/consistency_model/cm_derived_fields_are_visible_in_the_triggering_response
    """
    sc = _proof_pending_job(client)
    validate_success(client.approve_press_proof(sc.job_id, users.DIRECTOR))

    inspected = validate_success(
        client.inspect_print_job(sc.job_id, f.inspect_payload(500, 6), users.CUSTODIAN))
    a.assert_fields_equal(
        inspected,
        {
            "defect_rate_bp": 120,
            "status": c.JOB_QC_PASSED,
            "inspection_count": 1,
            "sample_size": 500,
            "defect_count": 6,
        },
        "print job",
    )

    vendor = validate_success(client.get_print_vendor(sc.vendor_id, users.DIRECTOR))
    a.assert_fields_equal(
        vendor, {"quality_defect_rate_bp": 120, "active_job_count": 1}, "print vendor")

    delivered = validate_success(
        client.deliver_print_job(
            sc.job_id,
            f.deliver_payload([f.manifest_line(c.LOT_CODE_1, 12500, c.SEAL_1)]),
            sc.vendor_headers))
    a.assert_fields_equal(
        delivered,
        {
            "status": c.JOB_DELIVERED,
            "invoice_basis": c.INVOICE_FINAL,
            "invoice_subtotal_cents": 105625,
            "freight_cents": 45000,
            "defect_credit_cents": 1268,
            "delivered_quantity": 12500,
            "invoice_total_cents": 149357,
        },
        "print job",
    )

    election = validate_success(client.get_election(sc.election_id, users.DIRECTOR))
    a.assert_fields_equal(election, {"committed_print_cents": 149357}, "election")

    lots, lot_meta = validate_paginated(
        client.list_ballot_lots(users.CUSTODIAN, {"print_job_id": sc.job_id}))
    assert lot_meta["total_count"] == 1, (
        f"the manifest must have created exactly one lot, got {lot_meta['total_count']}"
    )
    a.assert_fields_equal(
        lots[0],
        {"lot_code": c.LOT_CODE_1, "custody_state": c.LOT_IN_TRANSIT},
        "ballot lot",
    )

    events, _ = validate_paginated(
        client.list_custody_events(sc.election_id, users.CUSTODIAN, {"limit": 100}))
    assert events, "the delivery must have appended a custody event"
    a.assert_custody_event(events[0], c.EVENT_TRANSFER_OUT,
                           subject_type=c.SUBJECT_BALLOT_LOT,
                           subject_id=lots[0]["id"],
                           to_state=c.LOT_IN_TRANSIT)
