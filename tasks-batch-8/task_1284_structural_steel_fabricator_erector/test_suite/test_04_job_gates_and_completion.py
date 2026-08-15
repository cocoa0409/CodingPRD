"""Job lifecycle gates (fabrication / erection), mill-order placement gating,
sequence numbering, and the automatic sequence/job completion cascade."""
import pytest

from test_helpers import (
    ADMIN,
    FOREMAN,
    ApiErrorId,
    api_client,
    approve_billing,
    create_approved_drawing,
    create_awarded_job,
    create_billing,
    create_drawing,
    create_job,
    create_mill_order_payload,
    create_released_sequence,
    create_sequence,
    decide_drawing,
    pay_billing,
    release_sequence,
    setup_job_with_pieces,
    start_erection,
    start_fabrication,
    submit_billing,
    submit_drawing,
    validate_error,
    validate_success,
)


class TestStartFabricationGate:

    def test_start_fabrication_requires_approved_drawing(self):
        """PRD section 3.1: "Starting fabrication moves `AWARDED` to
        `FABRICATING` and is gated on shop drawing approval: at least one
        drawing of the job must be `APPROVED`, or the request is rejected with
        `ERR_DRAWING_NOT_APPROVED`."

        Design: Corner/state_machines/start_fabrication_requires_approved_drawing
        """
        job = create_awarded_job("Job SM11")
        create_drawing(job["id"], "D-1")  # DRAFT only — not APPROVED
        resp = api_client.start_fabrication(job["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_DRAWING_NOT_APPROVED)
        after = validate_success(api_client.get_job(job["id"], ADMIN))
        assert after["status"] == "AWARDED", \
            "a rejected start-fabrication must leave the job AWARDED"


class TestStartErectionGate:

    def test_start_erection_requires_released_sequence(self):
        """PRD section 3.1: "Starting erection moves `FABRICATING` to
        `ERECTING` and is gated on field readiness: at least one erection
        sequence of the job must be `RELEASED`, or the request fails with
        `ERR_SEQUENCE_NOT_RELEASED`."

        Design: Corner/state_machines/start_erection_requires_released_sequence
        """
        job = create_awarded_job("Job SM10")
        create_approved_drawing(job["id"], "D-1")
        job = start_fabrication(job["id"])
        sequence = create_sequence(job["id"], 1)  # PLANNED, not RELEASED

        resp = api_client.start_erection(job["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SEQUENCE_NOT_RELEASED)

        release_sequence(sequence["id"])
        ok = validate_success(api_client.start_erection(job["id"], ADMIN))
        assert ok["status"] == "ERECTING", \
            f"after a release, start-erection must reach ERECTING, got {ok['status']}"


class TestMillOrderPlacementGate:

    def test_mill_order_on_estimating_job_rejected(self):
        """PRD section 3.3: "A mill order may not be placed against a job still
        in `ESTIMATING` — material buying starts only once the job is awarded —
        and such an attempt fails with `ERR_INVALID_STATE`."

        Design: Corner/errors/mill_order_on_estimating_job_rejected
        """
        job = create_job("Job ER6")
        resp = api_client.create_mill_order(
            create_mill_order_payload(job["id"]), ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestSequenceNumbering:

    def test_duplicate_sequence_number_rejected(self):
        """PRD section 3.4: "The field plan is a set of erection sequences
        created by a `FOREMAN` with a `job_id` and a `seq_number`; the sequence
        number must be unique within its job, with collisions rejected as
        `ERR_SEQUENCE_NUMBER_NOT_UNIQUE`."

        Design: Corner/errors/duplicate_sequence_number_rejected
        """
        job = create_job("Job ER3")
        create_sequence(job["id"], 1)
        resp = api_client.create_erection_sequence(
            {"job_id": job["id"], "seq_number": 1}, FOREMAN
        )
        validate_error(resp, ApiErrorId.ERR_SEQUENCE_NUMBER_NOT_UNIQUE)


class TestSequenceReleaseGate:

    def test_release_rejected_while_job_awarded(self):
        """PRD section 3.4: "Releasing one — the foreman's signal that the
        field is ready for that sequence's steel — moves it from `PLANNED` to
        `RELEASED` and requires the owning job to be in `FABRICATING` or
        `ERECTING`; releasing against a job in any other state fails with
        `ERR_JOB_NOT_FABRICATING`."

        Design: Difficulty/cross_entity_state_dependency/sequence_release_requires_job_fabricating
        """
        job = create_awarded_job("Job Z")
        sequence = create_sequence(job["id"], 1)
        resp = api_client.release_sequence(sequence["id"], FOREMAN)
        validate_error(resp, ApiErrorId.ERR_JOB_NOT_FABRICATING)
        after = validate_success(
            api_client.get_erection_sequence(sequence["id"], FOREMAN)
        )
        assert after["status"] == "PLANNED"

    def test_release_succeeds_once_job_fabricating(self):
        """PRD section 3.4: "Releasing one — the foreman's signal that the
        field is ready for that sequence's steel — moves it from `PLANNED` to
        `RELEASED` and requires the owning job to be in `FABRICATING` or
        `ERECTING`; releasing against a job in any other state fails with
        `ERR_JOB_NOT_FABRICATING`."

        Design: Difficulty/cross_entity_state_dependency/sequence_release_requires_job_fabricating
        """
        job = create_awarded_job("Job Z2")
        sequence = create_sequence(job["id"], 1)
        create_approved_drawing(job["id"], "D-1")
        start_fabrication(job["id"])
        released = validate_success(
            api_client.release_sequence(sequence["id"], FOREMAN)
        )
        assert released["status"] == "RELEASED", (
            f"release against a FABRICATING job must succeed, "
            f"got {released['status']}"
        )


class TestErectionCascade:

    def test_sequence_auto_erected_bubble_up(self):
        """PRD section 3.4: "First the job's `erected_weight_lbs` is
        recomputed. Second, if every piece of the piece's sequence now stands
        in `ERECTED`, the sequence itself moves from `RELEASED` to `ERECTED`.
        Third, the job's compound completion check of §3.9 runs."

        Design: Corner/state_machines/sequence_auto_erected_bubble_up
        """
        ctx = setup_job_with_pieces(
            "Job SM6", "WEIGHT", [("P1", 1000, True)], begin_erection=True,
        )
        piece = ctx["pieces"]["P1"]
        assert piece["status"] == "ERECTED"
        sequence = validate_success(
            api_client.get_erection_sequence(ctx["sequence"]["id"], FOREMAN)
        )
        assert sequence["status"] == "ERECTED", (
            f"the sequence must auto-complete when its last piece erects, "
            f"got {sequence['status']}"
        )
        # No billings exist, so the compound check cannot complete the job.
        job = validate_success(api_client.get_job(ctx["job"]["id"], ADMIN))
        assert job["status"] == "ERECTING"
        assert job["erected_weight_lbs"] == 1000

    def test_job_auto_complete_compound(self):
        """PRD section 3.9: "It is re-evaluated automatically after every piece
        erection, every automatic sequence completion, every billing payment,
        every billing void, and every backcharge settlement, and it passes
        exactly when all of the following hold: the job is `ERECTING`; at least
        one erection sequence exists for the job and every sequence is
        `ERECTED`; at least one progress billing exists for the job and every
        billing is `PAID` or `VOIDED`; and every backcharge of the job is
        `SETTLED` — a condition vacuously satisfied when the job has no
        backcharges."
        PRD section 3.9: "When the check passes, the job moves to `COMPLETE`,
        terminal: its `retainage_releasable_cents` is set to the
        `retainage_held_cents` current at that moment, and its `version`
        increments."

        Design: Corner/state_machines/job_auto_complete_compound
        """
        ctx = setup_job_with_pieces(
            "Job SM7", "WEIGHT", [("P1", 1000, True)], begin_erection=True,
        )
        billing = create_billing(ctx["job"]["id"], "2026-08")
        submit_billing(billing["id"])
        approve_billing(billing["id"])
        pay_billing(billing["id"])

        job = validate_success(api_client.get_job(ctx["job"]["id"], ADMIN))
        assert job["status"] == "COMPLETE", (
            f"all sequences ERECTED + billing PAID + no backcharges must "
            f"complete the job, got {job['status']}"
        )
        # pct 1.0000 -> earned 10000000, retainage 5% -> 500000 held.
        assert job["retainage_held_cents"] == 500000
        assert job["retainage_releasable_cents"] == 500000, (
            f"retainage_releasable_cents must be set to retainage_held_cents "
            f"at completion, got {job['retainage_releasable_cents']}"
        )
