"""Piece-mark tracking: uniqueness, same-job references, the four start
gates, the FINAL_PIECE inspection cascade, and the piece rework loop."""
from test_helpers import (
    FOREMAN,
    QC,
    ApiErrorId,
    api_client,
    create_approved_drawing,
    create_awarded_job,
    create_drawing,
    create_in_shop_piece,
    create_job,
    create_piece,
    create_released_sequence,
    create_sequence,
    create_welder,
    decide_drawing,
    log_weld,
    pass_final_inspection,
    place_mill_order,
    schedule_final_inspection,
    setup_fabrication_ready,
    start_fabrication,
    start_piece,
    submit_drawing,
    submit_inspection,
    validate_error,
    validate_success,
)


class TestPieceMarkUniqueness:

    def test_piece_mark_uniqueness_enforced(self):
        """PRD section 3.4: "Pieces are the atoms of the system, created by a
        `FOREMAN` with a `job_id`, a `piece_mark` that must be unique within
        the job (`ERR_PIECE_MARK_NOT_UNIQUE` on collision), a positive
        `weight_lbs`, and two pins: the `drawing_id` of the approved-or-pending
        revision the piece is detailed from, and the `sequence_id` of its
        erection sequence."

        Design: Corner/entities/piece_mark_uniqueness_enforced
        """
        job = create_job("Job Q1")
        drawing = create_drawing(job["id"], "D-1")
        sequence = create_sequence(job["id"], 1)
        create_piece(job["id"], drawing["id"], sequence["id"], "P-1", 100)
        resp = api_client.create_piece(
            {
                "job_id": job["id"], "piece_mark": "P-1", "weight_lbs": 200,
                "drawing_id": drawing["id"], "sequence_id": sequence["id"],
            },
            FOREMAN,
        )
        validate_error(resp, ApiErrorId.ERR_PIECE_MARK_NOT_UNIQUE)


class TestCrossJobReferences:

    def _two_jobs_split(self):
        """Job A with a sequence; Job B with a drawing."""
        job_a = create_job("Job CA")
        seq_a = create_sequence(job_a["id"], 1)
        job_b = create_job("Job CB")
        drawing_b = create_drawing(job_b["id"], "D-B")
        return job_a, seq_a, job_b, drawing_b

    def test_cross_job_fk_reference_rejected(self):
        """PRD section 3.4: "Both pins must reference records belonging to the
        same job as the piece's `job_id`; a drawing or sequence from another
        job is rejected with `ERR_CROSS_JOB_REFERENCE`."

        Design: Corner/entities/cross_job_fk_reference_rejected
        """
        job_a, seq_a, _job_b, drawing_b = self._two_jobs_split()
        resp = api_client.create_piece(
            {
                "job_id": job_a["id"], "piece_mark": "X-1", "weight_lbs": 100,
                "drawing_id": drawing_b["id"], "sequence_id": seq_a["id"],
            },
            FOREMAN,
        )
        validate_error(resp, ApiErrorId.ERR_CROSS_JOB_REFERENCE)

    def test_referential_priority_beats_constraint(self):
        """PRD section 2.8: "Every request walks a fixed ladder of checks, and
        the first failing rung produces the response — later rungs are never
        evaluated."
        PRD section 2.8 (rung 8 before rung 9): "Referential gates. Within this
        rung the checks evaluate in a fixed order: piece staleness
        (`ERR_PIECE_STALE_REVISION`), pinned drawing approval
        (`ERR_DRAWING_NOT_APPROVED`), sequence release
        (`ERR_SEQUENCE_NOT_RELEASED`), material receipt
        (`ERR_MATERIAL_NOT_RECEIVED`), job fabricating for sequence release
        (`ERR_JOB_NOT_FABRICATING`), job billable for billing creation
        (`ERR_JOB_NOT_BILLABLE`), same-job consistency of body references
        (`ERR_CROSS_JOB_REFERENCE`), inspection target shape
        (`ERR_INSPECTION_TARGET_INVALID`), and inspection not locked by
        downstream progress (`ERR_INSPECTION_LOCKED`)."

        Design: Corner/validations/referential_priority_beats_constraint
        """
        job_a, seq_a, _job_b, drawing_b = self._two_jobs_split()
        # piece_mark "P-1" already exists in job A AND the drawing belongs to
        # job B: the cross-job reference (earlier rung) must be reported.
        drawing_a = create_drawing(job_a["id"], "D-A")
        create_piece(job_a["id"], drawing_a["id"], seq_a["id"], "P-1", 100)
        resp = api_client.create_piece(
            {
                "job_id": job_a["id"], "piece_mark": "P-1", "weight_lbs": 100,
                "drawing_id": drawing_b["id"], "sequence_id": seq_a["id"],
            },
            FOREMAN,
        )
        validate_error(resp, ApiErrorId.ERR_CROSS_JOB_REFERENCE)


class TestPieceStartGates:

    def test_piece_start_without_material_rejected(self):
        """PRD section 3.4: "Four conditions guard the start, evaluated in this
        order: the piece's `stale_revision` must be false
        (`ERR_PIECE_STALE_REVISION` — a piece detailed from a superseded
        revision must be re-pinned before it can be worked); the pinned drawing
        must be `APPROVED` (`ERR_DRAWING_NOT_APPROVED`); the piece's sequence
        must be `RELEASED` (`ERR_SEQUENCE_NOT_RELEASED`); and at least one mill
        order of the job must be `RECEIVED` (`ERR_MATERIAL_NOT_RECEIVED`)."

        Design: Corner/endpoints/piece_start_without_material_rejected
        """
        job = create_awarded_job("Job EP1")
        drawing = create_approved_drawing(job["id"], "D-1")
        start_fabrication(job["id"])
        sequence = create_released_sequence(job["id"], 1)
        place_mill_order(job["id"])  # PLACED only, never received
        piece = create_piece(job["id"], drawing["id"], sequence["id"],
                             "P1", 800)
        resp = api_client.start_piece(piece["id"], FOREMAN)
        validate_error(resp, ApiErrorId.ERR_MATERIAL_NOT_RECEIVED)
        after = validate_success(api_client.get_piece(piece["id"], FOREMAN))
        assert after["status"] == "DETAILED"

    def test_piece_start_requires_drawing_approved_rejected(self):
        """PRD section 3.4: "Four conditions guard the start, evaluated in this
        order: the piece's `stale_revision` must be false
        (`ERR_PIECE_STALE_REVISION` — a piece detailed from a superseded
        revision must be re-pinned before it can be worked); the pinned drawing
        must be `APPROVED` (`ERR_DRAWING_NOT_APPROVED`); the piece's sequence
        must be `RELEASED` (`ERR_SEQUENCE_NOT_RELEASED`); and at least one mill
        order of the job must be `RECEIVED` (`ERR_MATERIAL_NOT_RECEIVED`)."

        Design: Difficulty/cross_entity_state_dependency/piece_start_requires_drawing_approved
        """
        ctx = setup_fabrication_ready("Job Y")
        # A second drawing that is SUBMITTED but never decided.
        pending = create_drawing(ctx["job"]["id"], "D-2")
        submit_drawing(pending["id"])
        piece = create_piece(ctx["job"]["id"], pending["id"],
                             ctx["sequence"]["id"], "Y-P1", 800)
        resp = api_client.start_piece(piece["id"], FOREMAN)
        validate_error(resp, ApiErrorId.ERR_DRAWING_NOT_APPROVED)
        after = validate_success(api_client.get_piece(piece["id"], FOREMAN))
        assert after["status"] == "DETAILED"

    def test_piece_start_succeeds_after_drawing_approved(self):
        """PRD section 3.4: "Starting shop work moves a piece from `DETAILED`
        to `IN_SHOP`, and the same action serves the rework loop, moving a
        piece from `REWORK` back to `IN_SHOP` under the identical gate."
        PRD section 3.4: "the pinned drawing must be `APPROVED`
        (`ERR_DRAWING_NOT_APPROVED`)".

        Design: Difficulty/cross_entity_state_dependency/piece_start_requires_drawing_approved
        """
        ctx = setup_fabrication_ready("Job Y2")
        pending = create_drawing(ctx["job"]["id"], "D-2")
        submit_drawing(pending["id"])
        piece = create_piece(ctx["job"]["id"], pending["id"],
                             ctx["sequence"]["id"], "Y-P1", 800)
        decide_drawing(pending["id"], "APPROVE")
        started = validate_success(api_client.start_piece(piece["id"], FOREMAN))
        assert started["status"] == "IN_SHOP", (
            f"once the pinned drawing is APPROVED the start must succeed, "
            f"got {started['status']}"
        )


class TestErectGate:

    def test_erect_requires_shipped_state(self):
        """PRD section 3.4: "The last step belongs to the field: erecting moves
        a piece from `SHIPPED` to `ERECTED` — from any other state the request
        fails with `ERR_INVALID_STATE` — and fires the three-hop erection
        cascade."

        Design: Corner/endpoints/erect_requires_shipped_state
        """
        ctx = setup_fabrication_ready("Job EP3")
        piece = create_in_shop_piece(ctx, "P1", 800)
        pass_final_inspection(ctx, piece["id"])  # -> READY_TO_SHIP, no load
        resp = api_client.erect_piece(piece["id"], FOREMAN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestInspectionTargetShape:

    def test_inspection_target_shape_rejected(self):
        """PRD section 3.6: "The kind dictates the target shape, enforced as
        `ERR_INSPECTION_TARGET_INVALID` when violated: a `FINAL_PIECE`
        inspection requires a `piece_id`; a `WELD_VISUAL` or `WELD_NDT`
        inspection requires a `weld_id`; an `AISC_AUDIT` inspection targets the
        job alone and carries neither."

        Design: Corner/errors/inspection_target_shape_rejected
        """
        job = create_job("Job ER2")
        resp = api_client.create_inspection(
            {"job_id": job["id"], "kind": "WELD_VISUAL"}, QC
        )
        validate_error(resp, ApiErrorId.ERR_INSPECTION_TARGET_INVALID)


class TestFinalInspectionGate:

    def test_final_inspection_requires_welds_complete(self):
        """PRD section 3.6: "Scheduling a `FINAL_PIECE` inspection is itself a
        shop milestone: it advances the piece from `IN_SHOP` to
        `AWAITING_INSPECTION`, so the piece must currently be `IN_SHOP` (any
        other state fails `ERR_INVALID_STATE`), and every weld logged against
        that piece must already stand in `NDT_PASSED` — if any weld of the
        piece is short of that mark the scheduling is rejected with
        `ERR_WELDS_INCOMPLETE`."

        Design: Corner/state_machines/final_inspection_requires_welds_complete
        """
        ctx = setup_fabrication_ready("Job SM5")
        piece = create_in_shop_piece(ctx, "P1", 800)
        welder = create_welder("Weld Five")
        log_weld(piece["id"], welder["id"])  # left in WELDED
        resp = api_client.create_inspection(
            {"job_id": ctx["job"]["id"], "kind": "FINAL_PIECE",
             "piece_id": piece["id"]},
            QC,
        )
        validate_error(resp, ApiErrorId.ERR_WELDS_INCOMPLETE)
        after = validate_success(api_client.get_piece(piece["id"], FOREMAN))
        assert after["status"] == "IN_SHOP", \
            "a rejected scheduling must leave the piece IN_SHOP"


class TestPieceReworkLoop:

    def test_failed_final_inspection_loops_piece_through_rework(self):
        """PRD section 3.6: "A failed `FINAL_PIECE` inspection moves its piece
        from `AWAITING_INSPECTION` to `REWORK`, from which the restart path of
        §3.4 returns it to `IN_SHOP`."
        PRD section 3.4: "Starting shop work moves a piece from `DETAILED` to
        `IN_SHOP`, and the same action serves the rework loop, moving a piece
        from `REWORK` back to `IN_SHOP` under the identical gate."

        Design: Difficulty/non_linear_state_machine/piece_rework_loop
        """
        ctx = setup_fabrication_ready("Job N")
        piece = create_in_shop_piece(ctx, "N-P1", 800)
        inspection = schedule_final_inspection(ctx["job"]["id"], piece["id"])
        failed = submit_inspection(inspection["id"], "FAILED")
        assert failed["status"] == "FAILED"

        after_fail = validate_success(api_client.get_piece(piece["id"], FOREMAN))
        assert after_fail["status"] == "REWORK", (
            f"a failed final inspection must loop the piece to REWORK, "
            f"got {after_fail['status']}"
        )

        restarted = validate_success(api_client.start_piece(piece["id"], FOREMAN))
        assert restarted["status"] == "IN_SHOP", (
            f"the rework loop must return the piece to IN_SHOP under the "
            f"identical gate, got {restarted['status']}"
        )

    def test_piece_completes_normally_after_rework_loop(self):
        """PRD section 3.6: "A passed `FINAL_PIECE` inspection moves its piece
        from `AWAITING_INSPECTION` to `INSPECTED` and then, within the same
        request, immediately onward to `READY_TO_SHIP`."
        PRD section 3.6: "A failed `FINAL_PIECE` inspection moves its piece
        from `AWAITING_INSPECTION` to `REWORK`, from which the restart path of
        §3.4 returns it to `IN_SHOP`."

        Design: Difficulty/non_linear_state_machine/piece_rework_loop
        """
        ctx = setup_fabrication_ready("Job N2")
        piece = create_in_shop_piece(ctx, "N-P1", 800)
        first = schedule_final_inspection(ctx["job"]["id"], piece["id"])
        submit_inspection(first["id"], "FAILED")
        start_piece(piece["id"])  # REWORK -> IN_SHOP
        second = schedule_final_inspection(ctx["job"]["id"], piece["id"])
        passed = submit_inspection(second["id"], "PASSED")
        assert passed["status"] == "PASSED"
        after = validate_success(api_client.get_piece(piece["id"], FOREMAN))
        assert after["status"] == "READY_TO_SHIP", (
            f"the piece must complete normally after the loop, "
            f"got {after['status']}"
        )


class TestVoidFinalInspection:

    def test_void_final_inspection_reverts_piece(self):
        """PRD section 3.6: "A passed `FINAL_PIECE` inspection is voidable only
        while its piece is `READY_TO_SHIP` with a null `load_id` — a piece
        already shipped or sitting on a load locks the inspection — and voiding
        reverts the piece from `READY_TO_SHIP` back to `AWAITING_INSPECTION`."

        Design: Corner/state_machines/void_final_inspection_reverts_piece
        """
        ctx = setup_fabrication_ready("Job SM8")
        piece = create_in_shop_piece(ctx, "P1", 800)
        inspection = schedule_final_inspection(ctx["job"]["id"], piece["id"])
        submit_inspection(inspection["id"], "PASSED")

        voided = validate_success(
            api_client.void_inspection(inspection["id"], QC)
        )
        assert voided["status"] == "VOIDED"
        piece_after = validate_success(api_client.get_piece(piece["id"], FOREMAN))
        assert piece_after["status"] == "AWAITING_INSPECTION", (
            f"voiding the passed final inspection must revert the piece to "
            f"AWAITING_INSPECTION, got {piece_after['status']}"
        )
