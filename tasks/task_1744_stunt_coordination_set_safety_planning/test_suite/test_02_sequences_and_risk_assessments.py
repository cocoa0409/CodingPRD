"""Sequence design, the risk-assessment cycle, risk scoring variants, the
board-score lock threshold, and approval-driven readiness invalidation
(PRD §3.2, §2.6, §2.10)."""
from test_helpers import (
    ApiErrorId,
    COORD,
    SAFETY,
    create_approved_assessment,
    create_draft_assessment,
    create_equipment,
    create_production,
    create_sequence,
    create_sequence_payload,
    create_risk_assessment_payload,
    get_sequence,
    setup_ready_sequence,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSequenceCreation:
    def test_sequence_initial_state(self, api):
        """PRD §3.2: "The new sequence starts `DRAFT` with `design_revision` 1,
        both rehearsal counters at zero, `coordinator_user_id` set to the
        creator, and `required_rehearsal_count`, `board_score`, and
        `current_assessment_id` all null until the design is locked."

        Design: Corner/state_machines/sm_sequence_initial_state
        """
        prod = create_production(name="P", budget=5000000)
        data = validate_success(api.create_sequence(create_sequence_payload(prod["id"], name="Init Seq"), COORD), 201)
        assert data["status"] == "DRAFT"
        assert data["design_revision"] == 1
        assert data["completed_rehearsal_count"] == 0
        assert data["completed_rehearsal_minutes"] == 0
        assert data["coordinator_user_id"] == "coord-1", "creator X-User-ID is stamped for SoD"
        assert data["required_rehearsal_count"] is None
        assert data["board_score"] is None
        assert data["current_assessment_id"] is None

    def test_sequence_missing_required_field_rejected(self, api):
        """PRD §2.7: "Structurally malformed requests — a missing required
        field, an unknown field (including any client-supplied computed or
        system-managed field), an invalid enum value, or a non-positive amount —
        fail with `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/ent_sequence_missing_required_field_rejected
        """
        prod = create_production(name="P", budget=5000000)
        payload = create_sequence_payload(prod["id"], name="No Hazard")
        del payload["hazard_class"]
        resp = api.create_sequence(payload, COORD)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_sequence_invalid_enum_rejected(self, api):
        """PRD §2.7: "Structurally malformed requests — a missing required
        field, an unknown field (including any client-supplied computed or
        system-managed field), an invalid enum value, or a non-positive amount —
        fail with `ERR_VALIDATION` (HTTP 400)."
        PRD §3.2: "the declared `risk_category` (one of `LOW`, `MEDIUM`,
        `HIGH`, `CRITICAL`)"

        Design: Corner/entities/ent_sequence_invalid_enum_rejected
        """
        prod = create_production(name="P", budget=5000000)
        payload = create_sequence_payload(prod["id"], name="Bad Enum", risk_category="EXTREME")
        resp = api.create_sequence(payload, COORD)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_sequence_computed_field_input_rejected(self, api):
        """PRD §2.7: "Structurally malformed requests — a missing required
        field, an unknown field (including any client-supplied computed or
        system-managed field), an invalid enum value, or a non-positive amount —
        fail with `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/ent_sequence_computed_field_input_ignored
        """
        prod = create_production(name="P", budget=5000000)
        payload = create_sequence_payload(prod["id"], name="Sneaky")
        payload["status"] = "READY"  # status is system-managed, not client-settable
        resp = api.create_sequence(payload, COORD)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_sequence_cross_production_equipment_rejected(self, api):
        """PRD §2.10: "every element of a sequence's `required_equipment_ids`
        must belong to that sequence's production — and a reference that crosses
        productions is rejected with `ERR_CROSS_PRODUCTION_REFERENCE`
        (HTTP 422)."

        Design: Corner/entities/ent_equipment_fk_integrity_rejected
        """
        p1 = create_production(name="P1", budget=5000000)
        p2 = create_production(name="P2", budget=5000000)
        foreign_eq = create_equipment(p2["id"], name="Foreign rig", serial_number="RG-X")
        payload = create_sequence_payload(p1["id"], name="Bad FK", required_equipment_ids=[foreign_eq["id"]])
        resp = api.create_sequence(payload, COORD)
        validate_error(resp, ApiErrorId.ERR_CROSS_PRODUCTION_REFERENCE)

    def test_list_sequences_filter_by_status(self, api):
        """PRD §4: "List sequences; filterable by `production_id`, `status`,
        `hazard_class`, `required_equipment_ids` membership"
        PRD §2.3: "The `meta` object of every list response carries `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/ep_list_filter_by_status
        """
        prod = create_production(name="P", budget=5000000)
        keep = create_sequence(prod["id"], name="Keep")
        drop = create_sequence(prod["id"], name="Drop")
        validate_success(api.cancel_sequence(drop["id"], COORD, {"reason": "scene cut"}))
        resp = api.list_sequences(COORD, params={"production_id": prod["id"], "status": "CANCELLED"})
        items, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        assert len(items) == 1
        assert items[0]["id"] == drop["id"]
        assert items[0]["status"] == "CANCELLED"
        assert all(item["id"] != keep["id"] for item in items), "DRAFT sequence must be filtered out"

    def test_cancel_terminal_sequence_rejected(self, api):
        """PRD §3.6: "Cancellation moves a sequence from `DRAFT`,
        `DESIGN_LOCKED`, `READY`, `SAFETY_HOLD`, or `EXECUTED` to `CANCELLED` —
        from `REVIEWED` or `CANCELLED` the attempt is rejected with
        `ERR_SEQUENCE_INVALID_STATE`"

        Design: Corner/state_machines/sm_cancel_terminal_sequence_rejected
        """
        prod = create_production(name="P", budget=5000000)
        seq = create_sequence(prod["id"], name="Term Seq")
        first = validate_success(api.cancel_sequence(seq["id"], COORD, {"reason": "cut"}))
        assert first["status"] == "CANCELLED"
        resp = api.cancel_sequence(seq["id"], COORD, {"reason": "again"})
        validate_error(resp, ApiErrorId.ERR_SEQUENCE_INVALID_STATE)


class TestAssessmentCycle:
    def test_approve_draft_assessment_rejected(self, api):
        """PRD §3.2: "Approval moves `SUBMITTED → APPROVED` — from any other
        state it is rejected with `ERR_ASSESSMENT_INVALID_STATE`"

        Design: Corner/errors/err_approve_draft_assessment_rejected
        """
        prod = create_production(name="P", budget=10000000)
        seq = create_sequence(prod["id"], name="Ap Seq")
        ra = create_draft_assessment(prod["id"], seq["id"], 2, 2)
        resp = api.approve_assessment(ra["id"], SAFETY)
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_INVALID_STATE)

    def test_category_score_mismatch_rejected(self, api):
        """PRD §3.2: "the screening band of the `screening_score` must equal the
        sequence's declared `risk_category`, where `LOW` spans scores 1 through
        5, `MEDIUM` spans 6 through 11, `HIGH` spans 12 through 19, and
        `CRITICAL` spans 20 through 25; a mismatch is rejected with
        `ERR_CATEGORY_SCORE_MISMATCH`."

        Design: Corner/errors/err_category_score_mismatch_rejected
        """
        prod = create_production(name="P", budget=10000000)
        seq = create_sequence(prod["id"], name="Mis Seq", risk_category="LOW")
        ra = create_draft_assessment(prod["id"], seq["id"], 4, 4)
        assert ra["screening_score"] == 16, "4x4 lands in the HIGH band (12..19)"
        resp = api.submit_assessment(ra["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_CATEGORY_SCORE_MISMATCH)

    def test_assessment_create_stale_version_rejected(self, api):
        """PRD §2.6: "First, creating a risk assessment requires
        `expected_sequence_version` in the payload, carrying the `version` of
        the target sequence as the client last observed it. If the sequence's
        current `version` differs, the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/cc_occ_assessment_create_stale_rejected
        """
        prod = create_production(name="P", budget=10000000)
        seq = create_sequence(prod["id"], name="OCC Seq")
        ra1 = create_draft_assessment(prod["id"], seq["id"], 2, 2)
        assert ra1["status"] == "DRAFT"
        stale_version = seq["version"]  # 1 — the create above bumped it to 2
        current_version = get_sequence(seq["id"])["version"]
        assert current_version == stale_version + 1
        stale_payload = create_risk_assessment_payload(prod["id"], seq["id"], stale_version,
                                                       severity_rating=2, likelihood_rating=3)
        resp = api.create_risk_assessment(stale_payload, COORD)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        ok_payload = create_risk_assessment_payload(prod["id"], seq["id"], current_version,
                                                    severity_rating=2, likelihood_rating=3)
        ra2 = validate_success(api.create_risk_assessment(ok_payload, COORD), 201)
        assert ra2["status"] == "DRAFT"


class TestRiskScoreVariants:
    """Dual-variant risk scoring: screening at assessment time, board at
    lock-design (PRD §3.2)."""

    def _build_locked_pair(self, api):
        prod = create_production(name="DV Risk Prod", budget=10000000)
        # Sequence A: 5x5 FIGHT, no mitigation -> screening 25, board 27
        seq_a = create_sequence(prod["id"], name="Seq A", hazard_class="FIGHT", risk_category="CRITICAL")
        ra_a = create_approved_assessment(prod["id"], seq_a["id"], 5, 5)
        # Sequence B: same ratings with mitigation notes -> board 24
        seq_b = create_sequence(prod["id"], name="Seq B", hazard_class="FIGHT", risk_category="CRITICAL")
        create_approved_assessment(prod["id"], seq_b["id"], 5, 5,
                                   mitigation_notes="Full wire decelerator rig and doubled spotters")
        return prod, seq_a, ra_a, seq_b

    def test_screening_passes_but_board_variant_rejects_lock(self, api):
        """PRD §3.2: "computes `screening_score` as `severity_rating` multiplied
        by `likelihood_rating` — an integer from 1 to 25" and "If the board
        score reaches 26 or more, the lock is rejected with
        `ERR_RISK_SCORE_ABOVE_THRESHOLD`; a board score of at most 25 locks."
        PRD §3.2: "plus a hazard weight of 6 for `PYRO`, 5 for `FIRE`, 4 each
        for `HEIGHT`, `VEHICLE`, and `AERIAL`, 3 for `WATER`, and 2 for `FIGHT`"

        Design: Difficulty/dual_variant_calc/dv_risk_screening_vs_board_divergence
        """
        _, seq_a, ra_a, _ = self._build_locked_pair(api)
        assert ra_a["screening_score"] == 25, "screening variant is pure severity x likelihood"
        resp = api.lock_design(seq_a["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_RISK_SCORE_ABOVE_THRESHOLD)
        assert get_sequence(seq_a["id"])["status"] == "DRAFT"

    def test_mitigation_credit_brings_board_under_threshold(self, api):
        """PRD §3.2: "minus a mitigation credit of 3 when `mitigation_notes` is
        non-empty" and "Identical ratings can therefore pass screening yet fail
        the lock: a 3-by-4 `VEHICLE` assessment screens at 12 but boards at 16.
        If the board score reaches 26 or more, the lock is rejected with
        `ERR_RISK_SCORE_ABOVE_THRESHOLD`; a board score of at most 25 locks."

        Design: Difficulty/dual_variant_calc/dv_risk_screening_vs_board_divergence
        """
        _, _, _, seq_b = self._build_locked_pair(api)
        locked = validate_success(api.lock_design(seq_b["id"], COORD))
        assert locked["status"] == "DESIGN_LOCKED"
        assert locked["board_score"] == 24, "5x5 FIGHT with mitigation: 25 + 2 - 3 = 24"


class TestBoardScoreBoundary:
    def _build_pair_at_threshold(self, api):
        prod = create_production(name="Boundary Score Prod", budget=10000000)
        # PYRO 4x5: screening 20 (CRITICAL band), board 20+6 = 26
        seq1 = create_sequence(prod["id"], name="Pyro Seq", hazard_class="PYRO", risk_category="CRITICAL")
        create_approved_assessment(prod["id"], seq1["id"], 4, 5)
        # FIRE 4x5: board 20+5 = 25
        seq2 = create_sequence(prod["id"], name="Fire Seq", hazard_class="FIRE", risk_category="CRITICAL")
        create_approved_assessment(prod["id"], seq2["id"], 4, 5)
        return seq1, seq2

    def test_board_26_rejected(self, api):
        """PRD §3.2: "If the board score reaches 26 or more, the lock is
        rejected with `ERR_RISK_SCORE_ABOVE_THRESHOLD`; a board score of at
        most 25 locks."

        Design: Difficulty/boundary_precision_check/bp_board_score_threshold_26_vs_25
        """
        seq1, _ = self._build_pair_at_threshold(api)
        resp = api.lock_design(seq1["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_RISK_SCORE_ABOVE_THRESHOLD)

    def test_board_25_locks(self, api):
        """PRD §3.2: "If the board score reaches 26 or more, the lock is
        rejected with `ERR_RISK_SCORE_ABOVE_THRESHOLD`; a board score of at
        most 25 locks."

        Design: Difficulty/boundary_precision_check/bp_board_score_threshold_26_vs_25
        """
        _, seq2 = self._build_pair_at_threshold(api)
        locked = validate_success(api.lock_design(seq2["id"], COORD))
        assert locked["board_score"] == 25
        assert locked["status"] == "DESIGN_LOCKED"


class TestAssessmentRevisionCycle:
    def _setup_rejected_assessment(self, api):
        prod = create_production(name="Cycle Prod", budget=10000000)
        seq = create_sequence(prod["id"], name="Cycle Seq", risk_category="MEDIUM")
        ra = create_draft_assessment(prod["id"], seq["id"], 2, 4)
        validate_success(api.submit_assessment(ra["id"], COORD))
        rejected = validate_success(api.reject_assessment(ra["id"], {"reason": "Mitigations insufficient"}, SAFETY))
        assert rejected["status"] == "REJECTED"
        return ra

    def test_revise_returns_draft_and_recomputes_screening(self, api):
        """PRD §3.2: "The author may then revise (`REJECTED → DRAFT`, else
        `ERR_ASSESSMENT_INVALID_STATE`), replacing `severity_rating`,
        `likelihood_rating`, and `mitigation_notes` with the payload values,
        recomputing `screening_score`, and clearing `rejection_reason`; the loop
        permits unlimited revision rounds"

        Design: Difficulty/non_linear_state_machine/nsm_assessment_revision_cycle
        """
        ra = self._setup_rejected_assessment(api)
        revised = validate_success(
            api.revise_assessment(
                ra["id"],
                {"severity_rating": 3, "likelihood_rating": 3, "mitigation_notes": "Added wire decelerators"},
                COORD,
            )
        )
        assert revised["status"] == "DRAFT"
        assert revised["screening_score"] == 9, "3x3 recomputed on revise"
        assert revised["rejection_reason"] is None

    def test_revision_loop_converges_to_approved(self, api):
        """PRD §3.2: "the loop permits unlimited revision rounds, and the move
        `APPROVED → SUPERSEDED` only ever happens system-side, driven by the
        next approval."

        Design: Difficulty/non_linear_state_machine/nsm_assessment_revision_cycle
        """
        ra = self._setup_rejected_assessment(api)
        validate_success(
            api.revise_assessment(
                ra["id"],
                {"severity_rating": 3, "likelihood_rating": 3, "mitigation_notes": "Added wire decelerators"},
                COORD,
            )
        )
        validate_success(api.submit_assessment(ra["id"], COORD))
        approved = validate_success(api.approve_assessment(ra["id"], SAFETY))
        assert approved["status"] == "APPROVED"


class TestApprovalInvalidatesReadiness:
    def _setup_ready_with_second_assessment_submitted(self, api):
        ctx = setup_ready_sequence(name="Pin", hazard_class="FIGHT", risk_category="LOW")
        prod_id = ctx["production"]["id"]
        seq_id = ctx["sequence"]["id"]
        ra1_id = ctx["sequence"]["current_assessment_id"]
        # Second assessment: 1x3 = 3 -> still within the LOW band (1..5); the
        # OCC version is fresh-read inside the helper.
        ra2 = create_draft_assessment(prod_id, seq_id, 1, 3, mitigation_notes="extra mats")
        validate_success(api.submit_assessment(ra2["id"], COORD))
        return ctx, ra1_id, ra2

    def test_approval_supersedes_and_holds_ready_sequence(self, api):
        """PRD §3.2: "If another assessment of the same sequence is currently
        `APPROVED`, that assessment becomes `SUPERSEDED` and the new
        assessment's `supersedes_assessment_id` points at it" and "The
        sequence's `current_assessment_id` is re-pinned to the newly approved
        assessment and its `board_score` recomputed." and "And if the sequence
        is `READY` or already in `SAFETY_HOLD`, its readiness is invalidated and
        it is forced to `SAFETY_HOLD`."

        Design: Corner/cross_cutting_complexity_layers/cc_version_pinning_approval_invalidates_readiness
        """
        ctx, ra1_id, ra2 = self._setup_ready_with_second_assessment_submitted(api)
        assert ctx["sequence"]["status"] == "READY"
        approved = validate_success(api.approve_assessment(ra2["id"], SAFETY))
        assert approved["status"] == "APPROVED"
        assert approved["supersedes_assessment_id"] == ra1_id
        seq = get_sequence(ctx["sequence"]["id"])
        assert seq["status"] == "SAFETY_HOLD"
        assert seq["current_assessment_id"] == ra2["id"]
        ra1 = validate_success(api.get_risk_assessment(ra1_id, SAFETY))
        assert ra1["status"] == "SUPERSEDED"

    def test_reverify_restores_ready(self, api):
        """PRD §3.6: "Re-verifying readiness — `SAFETY_HOLD → READY`, owner
        coordinator only — requires the sequence in `SAFETY_HOLD`
        (`ERR_SEQUENCE_INVALID_STATE` otherwise) and posture `ACTIVE`
        (`ERR_PRODUCTION_STOPPED` while stopped), then re-runs every mark-ready
        gate, in the same order and with the same error ids, against current
        state and the current `design_revision`."

        Design: Corner/cross_cutting_complexity_layers/cc_version_pinning_approval_invalidates_readiness
        """
        ctx, _, ra2 = self._setup_ready_with_second_assessment_submitted(api)
        validate_success(api.approve_assessment(ra2["id"], SAFETY))
        seq_id = ctx["sequence"]["id"]
        assert get_sequence(seq_id)["status"] == "SAFETY_HOLD"
        reverified = validate_success(api.reverify_readiness(seq_id, COORD))
        assert reverified["status"] == "READY", "operational gates still pass after re-pinning"
