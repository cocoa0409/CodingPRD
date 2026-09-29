"""Non-linear state machines: the manuscript revision cycle and the production job's two dimensions."""

from test_helpers import assertions as a
from test_helpers import fixtures as fx

REVISED_STATEMENT = "Data at repository DOI 10.9999/cr-r1"


def test_revision_submission_opens_a_new_round_at_pending_integrity():
    """The cycle's second leg resets the integrity rollup and the review tally.

    PRD: "The manuscript moves `REVISION_REQUESTED → REVISION_SUBMITTED`, its `revision_round` rises by 1, the supplied `page_count`, `figure_count` and `data_availability_statement` replace the stored ones so that `formatting_status` is recomputed against the journal's limits, its `integrity_status` returns to `PENDING` because the new round has no screening yet, its `submitted_review_count` is recomputed for the new round and is therefore 0, and its `version` advances by 1."

    Design: Difficulty/non_linear_state_machine/manuscript_revision_cycle_returns_to_under_review
    """
    world = fx.setup_revision_requested_manuscript()
    assert world["manuscript"]["status"] == "REVISION_REQUESTED"

    fx.submit_revision(
        world["manuscript"]["id"],
        world["author_headers"],
        page_count=22,
        figure_count=5,
        data_availability_statement=REVISED_STATEMENT,
    )

    manuscript = fx.get_manuscript(world["manuscript"]["id"])
    a.assert_fields(
        manuscript,
        status="REVISION_SUBMITTED",
        revision_round=1,
        integrity_status="PENDING",
        page_count=22,
        submitted_review_count=0,
        formatting_status="COMPLIANT",
    )


def test_clean_screening_of_the_new_round_re_enters_under_review():
    """`UNDER_REVIEW` is re-entered rather than advanced past, closing the cycle.

    PRD: "When the manuscript sits at `REVISION_SUBMITTED` and a newly filed screening for the current round yields `PASS` or `FLAG` while the manuscript's `formatting_status` is `COMPLIANT`, the manuscript automatically advances `REVISION_SUBMITTED → UNDER_REVIEW` within the same request, and its `review_shortfall_flag` is cleared to false."

    Design: Difficulty/non_linear_state_machine/manuscript_revision_cycle_returns_to_under_review
    """
    world = fx.setup_revision_requested_manuscript()
    manuscript_id = world["manuscript"]["id"]
    fx.submit_revision(
        manuscript_id,
        world["author_headers"],
        page_count=22,
        figure_count=5,
        data_availability_statement=REVISED_STATEMENT,
    )

    screening = fx.file_plagiarism_screening(manuscript_id, 6.0)

    a.assert_fields(screening, round=1, verdict="PASS")
    manuscript = fx.get_manuscript(manuscript_id)
    a.assert_fields(
        manuscript,
        status="UNDER_REVIEW",
        revision_round=1,
        integrity_status="PASS",
        review_shortfall_flag=False,
    )


def test_revision_request_keeps_the_handling_assignment_active():
    """The editor who asked for the revision keeps the manuscript for the next round.

    PRD: "The handling editor's assignment stays `ACTIVE`, because the same editor will handle the next round."

    Design: Difficulty/non_linear_state_machine/manuscript_revision_cycle_returns_to_under_review
    """
    world = fx.setup_revision_requested_manuscript()

    decision = world["decision"]
    a.assert_fields(decision, auto_category="MINOR_REVISION", round=0)
    a.assert_score_equals(decision["consensus_index"], 3.00, "consensus_index")

    assignment = fx.get_assignment(world["assignment"]["id"])
    assert assignment["state"] == "ACTIVE"
    assert fx.get_manuscript(world["manuscript"]["id"])["decision_count"] == 1


def test_content_advance_leaves_the_clearance_dimension_untouched():
    """Copyediting to typesetting moves one dimension and one version only.

    PRD: "Each successful advance leaves the clearance dimension completely untouched and raises the job's `version` by 1."

    Design: Difficulty/non_linear_state_machine/production_job_parallel_dimensions_advance_independently
    """
    world = fx.setup_in_production()
    job_id = world["job"]["id"]
    a.assert_production_stages(world["job"], "COPYEDITING", "LICENSE_PENDING")

    booked = fx.book_typeset_slot(job_id, "2026-09-01", "2026-09-05")
    advanced = fx.advance_content(job_id, "TYPESETTING")

    a.assert_production_stages(advanced, "TYPESETTING", "LICENSE_PENDING")
    assert advanced["version"] == booked["version"] + 1
    assert advanced["slot_start"] == "2026-09-01"


def test_waiver_advances_the_clearance_dimension_without_moving_the_content_dimension():
    """Fee clearance arrives from an invoice event while the content dimension stands still.

    PRD: "Neither dimension constrains the other's progress, so a job can be at `clearance_stage` `FEE_CLEARED` while still at `content_stage` `COPYEDITING`, or at `content_stage` `PROOF_APPROVED` while still at `clearance_stage` `LICENSE_PENDING`."

    Design: Difficulty/non_linear_state_machine/production_job_parallel_dimensions_advance_independently
    """
    world = fx.setup_in_production()
    job_id = world["job"]["id"]
    fx.book_typeset_slot(job_id, "2026-09-01", "2026-09-05")
    fx.advance_content(job_id, "TYPESETTING")
    invoice = fx.issue_invoice(world["manuscript"]["id"])

    fx.waive_invoice(invoice["id"], waiver_reason="Society membership waiver")

    job = fx.get_production_job(job_id)
    a.assert_production_stages(job, "TYPESETTING", "FEE_CLEARED")
    a.assert_fields(
        job, proof_round=0, indexing_status="NOT_INDEXED", slot_start="2026-09-01"
    )


def test_waiver_moves_the_two_fee_ledgers_of_the_journal():
    """The waived invoice leaves the receivable at zero and the waived ledger at its total.

    PRD: "On success the invoice moves `ISSUED → WAIVED`, the journal's `apc_receivable_cents` falls by `total_due_cents`, and its `apc_waived_cents` rises by the same amount — the only event in the system that moves the waived ledger."

    Design: Difficulty/non_linear_state_machine/production_job_parallel_dimensions_advance_independently
    """
    world = fx.setup_in_production()
    job_id = world["job"]["id"]
    fx.book_typeset_slot(job_id, "2026-09-01", "2026-09-05")
    fx.advance_content(job_id, "TYPESETTING")
    invoice = fx.issue_invoice(world["manuscript"]["id"])

    fx.waive_invoice(invoice["id"], waiver_reason="Society membership waiver")

    settled = fx.get_invoice(invoice["id"])
    a.assert_fields(settled, status="WAIVED")
    a.assert_invoice_amounts(settled, total_due_cents=180000)
    a.assert_journal_ledgers(
        fx.get_journal(world["journal"]["id"]),
        apc_receivable_cents=0,
        apc_waived_cents=180000,
    )
    assert fx.get_manuscript(world["manuscript"]["id"])["status"] == "IN_PRODUCTION"
