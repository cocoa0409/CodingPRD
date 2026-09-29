"""Gates on the way into and through production: the data statement, the booked slot and the proof ceiling."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import PRODUCTION_STAFF_HEADERS, api_client

SLOT_START = "2026-09-01"
SLOT_END = "2026-09-05"


def _attempt_accept_decision(manuscript_id, handling_headers):
    return api_client.create_decision(
        manuscript_id,
        f.decision_payload(
            category="ACCEPT", editorial_note="Accepted after a single positive review."
        ),
        handling_headers,
    )


def _attempt_content_advance(job_id, to_stage):
    return api_client.advance_production_content(
        job_id, f.content_advance_payload(to_stage), PRODUCTION_STAFF_HEADERS
    )


def _attempt_proof_rejection(job_id, author_headers):
    return api_client.approve_proof(
        job_id, f.proof_approval_payload(False), author_headers
    )


def _setup_decision_pending_without_a_statement():
    """A manuscript at `DECISION_PENDING` with no data statement, on a journal that now demands one."""
    world = fx.setup_world(
        journal_overrides={
            "requires_data_availability_statement": False,
            "min_completed_reviews_for_decision": 1,
        }
    )
    payload = f.manuscript_payload(world["journal"]["id"], world["author"]["id"])
    payload.pop("data_availability_statement")
    manuscript = validate_success(
        api_client.create_manuscript(payload, world["author_headers"]),
        expected_status=201,
    )
    fx.file_plagiarism_screening(manuscript["id"])
    assignment = fx.assign_editor(
        manuscript["id"], world["chief_headers"], editor_id=world["handling"]["id"]
    )
    fx.declare_no_conflict(assignment["id"], world["handling_headers"])
    fx.advance_to_review(manuscript["id"], world["handling_headers"])
    reviewer, _reviewer_headers = fx.create_reviewer()
    fx.deliver_review(
        manuscript["id"], world["handling_headers"], reviewer, "ACCEPT"
    )
    fx.update_journal(
        world["journal"]["id"], requires_data_availability_statement=True
    )
    world["manuscript"] = fx.get_manuscript(manuscript["id"])
    return world


def _setup_job_at_the_proof_ceiling():
    """A production job whose single permitted proof round has already been sent."""
    world = fx.setup_in_production(journal_overrides={"max_proof_rounds": 1})
    job_id = world["job"]["id"]
    fx.book_typeset_slot(job_id, SLOT_START, SLOT_END)
    fx.advance_content(job_id, "TYPESETTING")
    fx.advance_content(job_id, "PROOF_SENT")
    world["job"] = fx.get_production_job(job_id)
    return world


def test_accept_decision_is_refused_once_the_journal_requires_a_data_statement():
    """The manuscript never carried a statement, and the journal now insists on one.

    PRD: "A resolved category of `ACCEPT` moves the manuscript `DECISION_PENDING → IN_PRODUCTION`, but only when the journal either does not require a data availability statement or the manuscript's `data_availability_statement` is a non-empty string; otherwise the decision is refused with `ERR_DATA_AVAILABILITY_REQUIRED`."

    Design: Corner/errors/accept_decision_rejected_when_journal_starts_requiring_data_availability
    """
    world = _setup_decision_pending_without_a_statement()
    a.assert_fields(world["manuscript"], status="DECISION_PENDING")
    assert world["manuscript"].get("data_availability_statement") is None

    response = _attempt_accept_decision(
        world["manuscript"]["id"], world["handling_headers"]
    )

    validate_error(
        response, ApiErrorId.ERR_DATA_AVAILABILITY_REQUIRED.value, expected_status=409
    )


def test_refused_acceptance_records_no_decision_and_creates_no_production_job():
    """The gate is read live at decision time, and it stops the whole cascade.

    PRD: "One `ProductionJob` is created for the manuscript, at `content_stage` `COPYEDITING` and `clearance_stage` `LICENSE_PENDING` — production jobs are **never** created by a direct client call, so this decision is the only way one comes into existence, and a manuscript may have at most one."

    Design: Corner/errors/accept_decision_rejected_when_journal_starts_requiring_data_availability
    """
    world = _setup_decision_pending_without_a_statement()
    version_before = world["manuscript"]["version"]

    _attempt_accept_decision(world["manuscript"]["id"], world["handling_headers"])

    assert fx.list_production_jobs(world["manuscript"]["id"]) == []
    manuscript = fx.get_manuscript(world["manuscript"]["id"])
    a.assert_fields(
        manuscript,
        status="DECISION_PENDING",
        decision_count=0,
        version=version_before,
    )


def test_typesetting_advance_without_a_booked_slot_is_refused():
    """The step itself is declared; what is missing is the desk booking it depends on.

    PRD: "Advancing `COPYEDITING → TYPESETTING` requires a booked slot: an advance attempted while `slot_start` is absent is refused with `ERR_SLOT_NOT_BOOKED`."

    Design: Corner/errors/typesetting_advance_without_a_booked_slot_rejected
    """
    world = fx.setup_in_production()
    a.assert_production_stages(world["job"], "COPYEDITING", "LICENSE_PENDING")

    response = _attempt_content_advance(world["job"]["id"], "TYPESETTING")

    error = validate_error(
        response, ApiErrorId.ERR_SLOT_NOT_BOOKED.value, expected_status=409
    )
    assert error["error_id"] != ApiErrorId.ERR_INVALID_PRODUCTION_STAGE.value, (
        "copyediting does declare the step to typesetting, so the stage pair is not the fault"
    )
    job = fx.get_production_job(world["job"]["id"])
    a.assert_production_stages(job, "COPYEDITING", "LICENSE_PENDING")
    a.assert_fields(job, proof_round=0, version=world["job"]["version"])
    assert job.get("slot_start") is None
    assert job.get("slot_end") is None


def test_booking_the_slot_lets_the_identical_advance_through():
    """Only the booking changed, and the same content advance now succeeds.

    PRD: "A successful booking stores `slot_start` and `slot_end` and advances the job's `version` by 1; rebooking is permitted while the content dimension is at `COPYEDITING` or `TYPESETTING`, subject to the same version guard."

    Design: Corner/errors/typesetting_advance_without_a_booked_slot_rejected
    """
    world = fx.setup_in_production()
    job_id = world["job"]["id"]
    _attempt_content_advance(job_id, "TYPESETTING")

    fx.book_typeset_slot(job_id, SLOT_START, SLOT_END)
    validate_success(_attempt_content_advance(job_id, "TYPESETTING"))

    job = fx.get_production_job(job_id)
    a.assert_production_stages(job, "TYPESETTING", "LICENSE_PENDING")
    a.assert_fields(job, slot_start=SLOT_START, slot_end=SLOT_END)


def test_proof_rejection_at_the_round_ceiling_is_refused():
    """One proof round was permitted and one was sent, so the loop back is closed.

    PRD: "An `approved` of false loops it back, `PROOF_SENT → TYPESETTING`, but only while the job's `proof_round` is strictly less than the journal's `max_proof_rounds`; a rejection attempted when `proof_round` has already reached that ceiling is refused with `ERR_PROOF_ROUND_LIMIT_REACHED`."

    Design: Corner/errors/proof_rejection_at_the_round_ceiling_rejected
    """
    world = _setup_job_at_the_proof_ceiling()
    a.assert_fields(world["job"], proof_round=1)

    response = _attempt_proof_rejection(world["job"]["id"], world["author_headers"])

    validate_error(
        response, ApiErrorId.ERR_PROOF_ROUND_LIMIT_REACHED.value, expected_status=409
    )
    job = fx.get_production_job(world["job"]["id"])
    a.assert_production_stages(job, "PROOF_SENT", "LICENSE_PENDING")
    a.assert_fields(job, proof_round=1, version=world["job"]["version"])


def test_approving_the_final_proof_is_still_open_at_the_ceiling():
    """The ceiling closes the rejection branch only; approval still moves the job on.

    PRD: "An `approved` of true moves the content dimension `PROOF_SENT → PROOF_APPROVED`."

    Design: Corner/errors/proof_rejection_at_the_round_ceiling_rejected
    """
    world = _setup_job_at_the_proof_ceiling()
    _attempt_proof_rejection(world["job"]["id"], world["author_headers"])

    fx.approve_proof(world["job"]["id"], world["author_headers"], True)

    job = fx.get_production_job(world["job"]["id"])
    a.assert_production_stages(job, "PROOF_APPROVED", "LICENSE_PENDING")
    a.assert_fields(job, proof_round=1)
