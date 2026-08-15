"""Shipping loads: line edits and the weight invariant, the trailer capacity
boundary, buffered laydown-slot conflicts, ship gates, and the AISC hold."""
from test_helpers import (
    ADMIN,
    FOREMAN,
    QC,
    ApiErrorId,
    api_client,
    add_line,
    create_drawing,
    create_in_shop_piece,
    create_job,
    create_load,
    create_piece,
    create_ready_to_ship_piece,
    create_sequence,
    create_shipping_load_payload,
    revise_and_approve_drawing,
    schedule_final_inspection,
    setup_fabrication_ready,
    submit_inspection,
    validate_error,
    validate_success,
)


class TestLoadLineWeightInvariant:

    def _ready_piece_and_load(self, name="Job I"):
        ctx = setup_fabrication_ready(name)
        piece = create_ready_to_ship_piece(ctx, "I-P1", 5000)
        load = create_load(ctx["job"]["id"], load_number="L-I1",
                           laydown_slot="Y-I", trailer_capacity_lbs=20000)
        return ctx, piece, load

    def test_add_line_sets_weight_and_flips_loading(self):
        """PRD section 3.7: "A successful add sets the piece's `load_id` to the
        load, recomputes `total_weight_lbs` as the sum of `weight_lbs` over
        every piece whose `load_id` points at the load, and — when it is the
        load's first line — moves the load from `STAGING` to `LOADING`."

        Design: Difficulty/compensating_invariant/load_line_add_remove_weight_invariant
        """
        _ctx, piece, load = self._ready_piece_and_load()
        after_add = validate_success(
            api_client.add_load_line(load["id"], {"piece_id": piece["id"]},
                                     FOREMAN),
            expected_status=201,
        )
        assert after_add["total_weight_lbs"] == 5000, (
            f"load weight must equal the sum of member weights, "
            f"got {after_add['total_weight_lbs']}"
        )
        assert after_add["status"] == "LOADING", \
            f"the first line must flip STAGING to LOADING, got {after_add['status']}"
        piece_after = validate_success(api_client.get_piece(piece["id"], FOREMAN))
        assert piece_after["load_id"] == load["id"]

    def test_remove_last_line_restores_zero_and_staging(self):
        """PRD section 3.7: "Removing a line clears the piece's `load_id` to
        null, recomputes the total, and — when it was the last line — drops the
        load from `LOADING` back to `STAGING` with a recomputed total of zero."

        Design: Difficulty/compensating_invariant/load_line_add_remove_weight_invariant
        """
        _ctx, piece, load = self._ready_piece_and_load()
        add_line(load["id"], piece["id"])
        after_del = validate_success(
            api_client.remove_load_line(load["id"], piece["id"], FOREMAN)
        )
        assert after_del["total_weight_lbs"] == 0, (
            f"removing the last line must recompute the total to zero, "
            f"got {after_del['total_weight_lbs']}"
        )
        assert after_del["status"] == "STAGING", (
            f"removing the last line must drop the load back to STAGING, "
            f"got {after_del['status']}"
        )
        piece_after = validate_success(api_client.get_piece(piece["id"], FOREMAN))
        assert piece_after["load_id"] is None


class TestTrailerCapacityBoundary:

    def _three_piece_job(self):
        ctx = setup_fabrication_ready("Job X")
        p1 = create_ready_to_ship_piece(ctx, "X-P1", 5000)
        p2 = create_ready_to_ship_piece(ctx, "X-P2", 5000)
        p3 = create_ready_to_ship_piece(ctx, "X-P3", 1)
        load = create_load(ctx["job"]["id"], load_number="L-X1",
                           laydown_slot="Y-X", trailer_capacity_lbs=10000)
        return ctx, p1, p2, p3, load

    def test_load_weight_exactly_capacity_accepted(self):
        """PRD section 3.7: "The capacity gate weighs the candidate against the
        trailer: the load's current `total_weight_lbs` plus the candidate's
        `weight_lbs` must not exceed `trailer_capacity_lbs`, with a total
        landing exactly on capacity accepted and a single pound over rejected
        with `ERR_LOAD_OVERWEIGHT`."

        Design: Difficulty/boundary_precision_check/load_weight_exactly_capacity
        """
        _ctx, p1, p2, _p3, load = self._three_piece_job()
        add_line(load["id"], p1["id"])
        after = validate_success(
            api_client.add_load_line(load["id"], {"piece_id": p2["id"]}, FOREMAN),
            expected_status=201,
        )
        assert after["total_weight_lbs"] == 10000, (
            f"a total landing exactly on capacity must be accepted, "
            f"got {after['total_weight_lbs']}"
        )
        assert after["status"] == "LOADING"

    def test_load_weight_one_pound_over_rejected(self):
        """PRD section 3.7: "The capacity gate weighs the candidate against the
        trailer: the load's current `total_weight_lbs` plus the candidate's
        `weight_lbs` must not exceed `trailer_capacity_lbs`, with a total
        landing exactly on capacity accepted and a single pound over rejected
        with `ERR_LOAD_OVERWEIGHT`."

        Design: Difficulty/boundary_precision_check/load_weight_exactly_capacity
        """
        _ctx, p1, p2, p3, load = self._three_piece_job()
        add_line(load["id"], p1["id"])
        add_line(load["id"], p2["id"])
        resp = api_client.add_load_line(load["id"], {"piece_id": p3["id"]},
                                        FOREMAN)
        validate_error(resp, ApiErrorId.ERR_LOAD_OVERWEIGHT)
        piece_after = validate_success(api_client.get_piece(p3["id"], FOREMAN))
        assert piece_after["load_id"] is None, \
            "a rejected add must not attach the piece to the load"


class TestLaydownSlotConflict:

    def test_delivery_two_days_apart_conflicts(self):
        """PRD section 3.7: "The yard is shared across every job the shop
        serves, so the laydown slot is checked globally: creating a load
        conflicts when another load of any job holds the same `laydown_slot` in
        `STAGING` or `LOADING` status with a `delivery_date` at most two days
        away in either direction. The buffer is closed at two days — delivery
        dates exactly two days apart conflict and the create is rejected with
        `ERR_LAYDOWN_SLOT_CONFLICT`, while dates three or more days apart
        coexist freely."

        Design: Difficulty/resource_temporal_overlap/laydown_slot_buffered_date_conflict
        """
        job = create_job("Job L")
        create_load(job["id"], load_number="L-1", laydown_slot="Y-7",
                    delivery_date="2026-09-10", trailer_capacity_lbs=40000)
        resp = api_client.create_shipping_load(
            create_shipping_load_payload(
                job["id"], load_number="L-2", laydown_slot="Y-7",
                delivery_date="2026-09-12", trailer_capacity_lbs=40000,
            ),
            FOREMAN,
        )
        validate_error(resp, ApiErrorId.ERR_LAYDOWN_SLOT_CONFLICT)

    def test_delivery_three_days_apart_allowed(self):
        """PRD section 3.7: "The buffer is closed at two days — delivery dates
        exactly two days apart conflict and the create is rejected with
        `ERR_LAYDOWN_SLOT_CONFLICT`, while dates three or more days apart
        coexist freely."

        Design: Difficulty/resource_temporal_overlap/laydown_slot_buffered_date_conflict
        """
        job = create_job("Job L2")
        create_load(job["id"], load_number="L-1", laydown_slot="Y-7",
                    delivery_date="2026-09-10", trailer_capacity_lbs=40000)
        resp = api_client.create_shipping_load(
            create_shipping_load_payload(
                job["id"], load_number="L-3", laydown_slot="Y-7",
                delivery_date="2026-09-13", trailer_capacity_lbs=40000,
            ),
            FOREMAN,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "STAGING"


class TestAddLineGates:

    def test_add_line_requires_ready_to_ship(self):
        """PRD section 3.7: "Lines are added and removed while the load is
        `STAGING` or `LOADING`; against a `SHIPPED` load either edit fails with
        `ERR_INVALID_STATE`. Adding a line names a `piece_id`; the piece must
        be in `READY_TO_SHIP` status."
        PRD section 2.8: "The target entity must be in a valid from-state for
        the requested transition — including a mill order placed only against a
        job that is not `ESTIMATING`, load line edits only while the load is
        `STAGING` or `LOADING`, and a field fix reported only on a `SHIPPED` or
        `ERECTED` piece — failing as `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/endpoints/add_line_requires_ready_to_ship
        """
        job = create_job("Job EP4")
        drawing = create_drawing(job["id"], "D-1")
        sequence = create_sequence(job["id"], 1)
        piece = create_piece(job["id"], drawing["id"], sequence["id"],
                             "P1", 800)  # DETAILED
        load = create_load(job["id"], load_number="L-1", laydown_slot="Y-EP4")
        resp = api_client.add_load_line(load["id"], {"piece_id": piece["id"]},
                                        FOREMAN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        piece_after = validate_success(api_client.get_piece(piece["id"], FOREMAN))
        assert piece_after["load_id"] is None

    def test_cross_job_load_line_rejected(self):
        """PRD section 2.8 (rung 8): "Referential gates. Within this rung the
        checks evaluate in a fixed order: piece staleness
        (`ERR_PIECE_STALE_REVISION`), pinned drawing approval
        (`ERR_DRAWING_NOT_APPROVED`), sequence release
        (`ERR_SEQUENCE_NOT_RELEASED`), material receipt
        (`ERR_MATERIAL_NOT_RECEIVED`), job fabricating for sequence release
        (`ERR_JOB_NOT_FABRICATING`), job billable for billing creation
        (`ERR_JOB_NOT_BILLABLE`), same-job consistency of body references
        (`ERR_CROSS_JOB_REFERENCE`), inspection target shape
        (`ERR_INSPECTION_TARGET_INVALID`), and inspection not locked by
        downstream progress (`ERR_INSPECTION_LOCKED`)."

        Design: Corner/endpoints/cross_job_load_line_rejected
        """
        ctx = setup_fabrication_ready("Job EP9A")
        piece = create_ready_to_ship_piece(ctx, "P1", 800)
        job_b = create_job("Job EP9B")
        load_b = create_load(job_b["id"], load_number="L-B1",
                             laydown_slot="Y-EP9")
        resp = api_client.add_load_line(load_b["id"], {"piece_id": piece["id"]},
                                        FOREMAN)
        validate_error(resp, ApiErrorId.ERR_CROSS_JOB_REFERENCE)
        piece_after = validate_success(api_client.get_piece(piece["id"], FOREMAN))
        assert piece_after["load_id"] is None


class TestShipGates:

    def test_ship_load_with_stale_piece_rejected(self):
        """PRD section 3.7: "The load must hold at least one line, and every
        piece on it must be `READY_TO_SHIP` with `stale_revision` false — an
        empty load, an unready piece, or a stale piece each fail with
        `ERR_PIECES_NOT_READY`."

        Design: Corner/endpoints/ship_load_with_stale_piece_rejected
        """
        ctx = setup_fabrication_ready("Job EP6")
        piece = create_ready_to_ship_piece(ctx, "P1", 800)
        # Supersede the pinned revision: the piece turns stale off-load.
        revise_and_approve_drawing(ctx["drawing"]["id"])
        stale = validate_success(api_client.get_piece(piece["id"], FOREMAN))
        assert stale["stale_revision"] is True
        assert stale["status"] == "READY_TO_SHIP"

        load = create_load(ctx["job"]["id"], load_number="L-1",
                           laydown_slot="Y-EP6")
        add_line(load["id"], piece["id"])  # add gate checks status only
        resp = api_client.ship_load(load["id"], FOREMAN)
        validate_error(resp, ApiErrorId.ERR_PIECES_NOT_READY)
        load_after = validate_success(api_client.get_shipping_load(load["id"], FOREMAN))
        assert load_after["status"] == "LOADING", \
            "a rejected ship must leave the load LOADING"

    def test_aisc_hold_blocks_ship_until_audit_passes(self):
        """PRD section 3.7: "And when the job's `requires_aisc_hold` flag is
        true, a `PASSED`, non-`VOIDED` `AISC_AUDIT` inspection must exist for
        the job at ship time; without one the ship is rejected with
        `ERR_AISC_HOLD_ACTIVE`."
        PRD section 3.1: "The optional `requires_aisc_hold` flag defaults to
        false; when set true, no load of the job may ship until a passed AISC
        audit inspection exists for the job (§3.7)."

        Design: Corner/calculations/aisc_hold_blocks_ship_until_audit_passes
        """
        ctx = setup_fabrication_ready("Job CA3", requires_aisc_hold=True)
        piece = create_ready_to_ship_piece(ctx, "P1", 800)
        load = create_load(ctx["job"]["id"], load_number="L-1",
                           laydown_slot="Y-CA3")
        add_line(load["id"], piece["id"])

        resp = api_client.ship_load(load["id"], FOREMAN)
        validate_error(resp, ApiErrorId.ERR_AISC_HOLD_ACTIVE)

        audit = validate_success(
            api_client.create_inspection(
                {"job_id": ctx["job"]["id"], "kind": "AISC_AUDIT"}, QC
            ), expected_status=201,
        )
        submit_inspection(audit["id"], "PASSED")

        shipped = validate_success(api_client.ship_load(load["id"], FOREMAN))
        assert shipped["status"] == "SHIPPED", \
            f"after a passed AISC audit the ship must succeed, got {shipped['status']}"
        piece_after = validate_success(api_client.get_piece(piece["id"], FOREMAN))
        assert piece_after["status"] == "SHIPPED"


class TestLoadNumberUniqueness:

    def test_duplicate_load_number_rejected(self):
        """PRD section 3.7: "Outbound steel moves on shipping loads created by
        a `FOREMAN` with a `job_id`, a `load_number` unique within the job
        (`ERR_LOAD_NUMBER_NOT_UNIQUE`), a `laydown_slot` yard code, a
        `delivery_date` ISO calendar date, and a positive
        `trailer_capacity_lbs`."

        Design: Corner/errors/duplicate_load_number_rejected
        """
        job = create_job("Job ER4")
        create_load(job["id"], load_number="L-1", laydown_slot="Y-ER4")
        resp = api_client.create_shipping_load(
            create_shipping_load_payload(
                job["id"], load_number="L-1", laydown_slot="Y-ER4B",
                delivery_date="2026-09-05",
            ),
            FOREMAN,
        )
        validate_error(resp, ApiErrorId.ERR_LOAD_NUMBER_NOT_UNIQUE)


class TestInspectionLockedOnLoad:

    def test_void_final_inspection_locked_on_load(self):
        """PRD section 3.6: "Voiding a passed inspection reverts the dependent
        transition, but only while downstream progress has not consumed the
        result; once it has, the inspection is locked and the void is rejected
        with `ERR_INSPECTION_LOCKED`."
        PRD section 3.6: "a passed `FINAL_PIECE` inspection is voidable only
        while its piece is `READY_TO_SHIP` with a null `load_id` — a piece
        already shipped or sitting on a load locks the inspection — and voiding
        reverts the piece from `READY_TO_SHIP` back to `AWAITING_INSPECTION`."

        Design: Corner/state_machines/void_final_inspection_locked_on_load
        """
        ctx = setup_fabrication_ready("Job SM9")
        piece = create_in_shop_piece(ctx, "P1", 800)
        inspection = schedule_final_inspection(ctx["job"]["id"], piece["id"])
        submit_inspection(inspection["id"], "PASSED")
        load = create_load(ctx["job"]["id"], load_number="L-1",
                           laydown_slot="Y-SM9")
        add_line(load["id"], piece["id"])

        resp = api_client.void_inspection(inspection["id"], QC)
        validate_error(resp, ApiErrorId.ERR_INSPECTION_LOCKED)
        after = validate_success(api_client.get_inspection(inspection["id"], QC))
        assert after["status"] == "PASSED", \
            "a locked void must leave the inspection PASSED"
