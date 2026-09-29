"""The production job's two dimensions: the proof loop, the fee-clearance leg and termination."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import ApiErrorId
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import PRODUCTION_STAFF_HEADERS, SYSTEM_ADMIN_HEADERS, api_client
from test_helpers.constants import CLOCK_EPOCH_MS

SLOT_START = "2026-09-01"
SLOT_END = "2026-09-05"


def _setup_proof_sent_job():
    """A job whose content dimension has been carried to `PROOF_SENT` on its first proof."""
    world = fx.setup_in_production(journal_overrides={"max_proof_rounds": 2})
    job_id = world["job"]["id"]
    fx.book_typeset_slot(job_id, SLOT_START, SLOT_END)
    fx.advance_content(job_id, "TYPESETTING")
    world["job"] = fx.advance_content(job_id, "PROOF_SENT")
    a.assert_fields(world["job"], proof_round=1)
    return world


def _setup_retraction_candidate():
    """A published article carrying an unresolved `HIGH` case at `COMMITTEE_REVIEW`."""
    world = fx.setup_published_manuscript(journal_overrides={"apc_base_cents": 0})
    case = fx.open_ethics_case(
        world["manuscript"]["id"],
        SYSTEM_ADMIN_HEADERS,
        case_type="AUTHORSHIP_DISPUTE",
        severity="HIGH",
    )
    fx.advance_case_to_committee_review(case["id"], world["chief_headers"])
    world["case"] = case
    return world


def _retract(world):
    return fx.resolve_ethics_case(
        world["case"]["id"],
        world["chief_headers"],
        "RETRACTION",
        resolution_statement="The committee found the authorship claim unsustainable.",
    )


def test_rejected_proof_loops_the_content_dimension_back_to_typesetting():
    """The author's refusal is a backward step on one dimension only.

    PRD: "An `approved` of false loops it back, `PROOF_SENT → TYPESETTING`, but only while the job's `proof_round` is strictly less than the journal's `max_proof_rounds`; a rejection attempted when `proof_round` has already reached that ceiling is refused with `ERR_PROOF_ROUND_LIMIT_REACHED`."

    Design: Corner/state_machines/proof_rejection_loops_back_to_typesetting_and_reopens_proof_round
    """
    world = _setup_proof_sent_job()

    looped = fx.approve_proof(
        world["job"]["id"],
        world["author_headers"],
        approved=False,
        proof_comments="Figure 2 caption is still wrong.",
    )

    a.assert_production_stages(looped, "TYPESETTING", "LICENSE_PENDING")
    a.assert_fields(looped, proof_round=1, slot_start=SLOT_START)
    assert looped["version"] == world["job"]["version"] + 1


def test_resending_the_proof_after_a_rejection_opens_the_second_round():
    """Proof rounds are counted on the way out, so the loop's second pass reads 2.

    PRD: "Advancing `TYPESETTING → PROOF_SENT` raises the job's `proof_round` by 1, so the proof rounds are counted as they are sent rather than as they are answered."

    Design: Corner/state_machines/proof_rejection_loops_back_to_typesetting_and_reopens_proof_round
    """
    world = _setup_proof_sent_job()
    job_id = world["job"]["id"]
    fx.approve_proof(
        job_id,
        world["author_headers"],
        approved=False,
        proof_comments="Figure 2 caption is still wrong.",
    )

    resent = fx.advance_content(job_id, "PROOF_SENT")

    a.assert_production_stages(resent, "PROOF_SENT", "LICENSE_PENDING")
    a.assert_fields(resent, proof_round=2, slot_start=SLOT_START, slot_end=SLOT_END)
    assert fx.get_manuscript(world["manuscript"]["id"])["status"] == "IN_PRODUCTION"


def test_zero_total_invoice_is_issued_with_nothing_written_off():
    """A journal that charges nothing produces a settled-by-construction invoice.

    PRD: "A `net_apc_cents` of exactly 2000 is billed as it stands; one that was already 0 leaves `auto_waived` false, because nothing was written off."

    Design: Corner/state_machines/clearance_dimension_reaches_fee_cleared_while_content_stays_copyediting
    """
    world = fx.setup_in_production(journal_overrides={"apc_base_cents": 0})

    invoice = fx.issue_invoice(world["manuscript"]["id"])

    a.assert_invoice_amounts(
        invoice,
        base_cents=0,
        net_apc_cents=0,
        total_due_cents=0,
        auto_waived=False,
        status="ISSUED",
    )
    a.assert_journal_ledgers(
        fx.get_journal(world["journal"]["id"]), apc_receivable_cents=0
    )


def test_zero_total_invoice_clears_fees_while_the_content_dimension_stands_still():
    """Issuance alone moves the clearance dimension; copyediting has not begun to move.

    PRD: "An invoice whose `total_due_cents` computes to 0 — a green self-archived paper with no surcharges, or a fully waived one — needs no settlement at all, and its issuance immediately advances the manuscript's production job on the clearance dimension, `LICENSE_PENDING → FEE_CLEARED`."

    Design: Corner/state_machines/clearance_dimension_reaches_fee_cleared_while_content_stays_copyediting
    """
    world = fx.setup_in_production(journal_overrides={"apc_base_cents": 0})
    a.assert_production_stages(world["job"], "COPYEDITING", "LICENSE_PENDING")

    fx.issue_invoice(world["manuscript"]["id"])

    job = fx.get_production_job(world["job"]["id"])
    a.assert_production_stages(job, "COPYEDITING", "FEE_CLEARED")
    a.assert_fields(job, proof_round=0, indexing_status="NOT_INDEXED")
    assert job.get("slot_start") is None
    assert job.get("slot_end") is None


def test_content_dimension_refuses_to_skip_typesetting():
    """`PROOF_SENT` is not declared from `COPYEDITING`, even with the slot already booked.

    PRD: "A `to_stage` that is not declared from the job's current stage pair is refused with `ERR_INVALID_PRODUCTION_STAGE`."

    Design: Corner/state_machines/content_advance_to_proof_sent_from_copyediting_rejected
    """
    world = fx.setup_in_production()
    job_id = world["job"]["id"]
    fx.book_typeset_slot(job_id, SLOT_START, SLOT_END)

    response = api_client.advance_production_content(
        job_id, f.content_advance_payload("PROOF_SENT"), PRODUCTION_STAFF_HEADERS
    )

    validate_error(
        response, ApiErrorId.ERR_INVALID_PRODUCTION_STAGE.value, expected_status=409
    )
    job = fx.get_production_job(job_id)
    a.assert_production_stages(job, "COPYEDITING", "LICENSE_PENDING")
    a.assert_fields(job, proof_round=0, slot_start=SLOT_START)


def test_retraction_resolution_closes_the_case_and_retracts_the_article():
    """The first two links of the cascade, both stamped at the current clock instant.

    PRD: "The second, caused by the first, moves the manuscript `PUBLISHED → RETRACTED` — or `CORRECTED → RETRACTED` when a correction had already been issued — and sets its `retracted_at` to the current clock instant; `RETRACTED` is terminal."

    Design: Corner/state_machines/retraction_cascade_terminates_job_and_flips_journal_counters
    """
    world = _setup_retraction_candidate()
    assert world["manuscript"]["status"] == "PUBLISHED"

    resolved = _retract(world)

    a.assert_fields(
        resolved, state="RETRACTION_APPROVED", resolved_at=CLOCK_EPOCH_MS
    )
    manuscript = fx.get_manuscript(world["manuscript"]["id"])
    a.assert_fields(manuscript, status="RETRACTED", retracted_at=CLOCK_EPOCH_MS)


def test_retraction_terminates_both_dimensions_of_the_production_job():
    """The third link drives content, clearance and indexing to their withdrawal values.

    PRD: "The third, caused by the second, drives the manuscript's production job to `content_stage` `TERMINATED`, `clearance_stage` `WITHDRAWN` and `indexing_status` `WITHDRAWN`, which as a side consequence frees that job's typesetting-slot occupancy for other articles."

    Design: Corner/state_machines/retraction_cascade_terminates_job_and_flips_journal_counters
    """
    world = _setup_retraction_candidate()
    before = world["job"]
    a.assert_production_stages(before, "PROOF_APPROVED", "DEPOSIT_CONFIRMED")

    _retract(world)

    job = fx.get_production_job(before["id"])
    a.assert_production_stages(job, "TERMINATED", "WITHDRAWN")
    a.assert_fields(job, indexing_status="WITHDRAWN")
    assert job["version"] == before["version"] + 1


def test_retraction_flips_the_two_journal_article_counters():
    """The fourth link moves one article out of the published tally and into the retracted one.

    PRD: "The fourth, caused by the third, lowers the journal's `published_article_count` by 1 and raises its `retracted_article_count` by 1."

    Design: Corner/state_machines/retraction_cascade_terminates_job_and_flips_journal_counters
    """
    world = _setup_retraction_candidate()
    a.assert_fields(world["journal"], published_article_count=1)

    _retract(world)

    journal = fx.get_journal(world["journal"]["id"])
    a.assert_fields(journal, published_article_count=0, retracted_article_count=1)
    a.assert_invoice_amounts(
        fx.get_invoice(world["invoice"]["id"]), total_due_cents=0
    )
