"""Finishing batches: booth capacity/purge discipline, sheen conformance, gating."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS,
    validate_success, validate_error,
    make_project, make_booth, make_batch, advance_batch, measure_batch,
    setup_order_finishing, setup_openings_finished, get_batch, get_opening,
    set_order_status, machine_opening, H,
)

PL_H = TEST_USERS["production_lead_headers"]
QA_H = TEST_USERS["qa_inspector_headers"]


def _finishing_ctx(contract_code, order_code, species="MAPLE", finish="STAIN",
                   sheen="SATIN", opening_no="1", machine_code="M-F",
                   machine_species=None):
    return setup_order_finishing(
        contract_code=contract_code, order_code=order_code, species=species,
        finish_system=finish, sheen_target=sheen,
        hardware_prep_mode="INSTALLER_PREP", fire_rating_required="NONE",
        openings=({"opening_no": opening_no, "leaf_count": 1, "fire_rating": "NONE",
                   "required_on_site_date": "2026-10-01"},),
        machine_code=machine_code,
        machine_species=machine_species or [species],
    )


class TestBoothCapacityAndPurge:
    def test_overlapping_batches_allowed_up_to_capacity_then_rejected(self, api):
        """PRD §3.5: "If the number of overlapping existing batches already
        equals the booth's `capacity`, creation fails with
        `ERR_BOOTH_CAPACITY_EXCEEDED` (HTTP 402); an overlapping count exactly
        one below capacity is permitted."

        Design: Difficulty/resource_temporal_overlap/spray_booth_aggregate_capacity_and_purge
        """
        ctx = _finishing_ctx("C-9002", "O-9002")
        booth = make_booth(booth_code="K-2", capacity=2)
        b1 = make_batch(ctx["order"]["id"], booth["id"], cure_start_hour=10, cure_end_hour=16)
        # Second overlapping batch: count 1 below capacity 2 -> permitted.
        b2 = make_batch(ctx["order"]["id"], booth["id"], cure_start_hour=12, cure_end_hour=18)
        assert get_batch(b1["id"])["status"] == "MIXED"
        assert get_batch(b2["id"])["status"] == "MIXED"

        # Third overlapping batch: overlapping count 2 already equals capacity.
        resp = api.create_finishing_batch(
            {"order_id": ctx["order"]["id"], "booth_id": booth["id"],
             "cure_start_hour": 14, "cure_end_hour": 20}, PL_H,
        )
        validate_error(resp, ApiErrorId.ERR_BOOTH_CAPACITY_EXCEEDED, 402)

    def test_adjacent_window_allowed_after_capacity_reached(self, api):
        """PRD §2.8: "Touching endpoints are not overlap — a window that begins
        exactly when another ends, or ends exactly when another begins, is
        adjacent and never counts as overlapping."

        Design: Difficulty/resource_temporal_overlap/spray_booth_aggregate_capacity_and_purge
        """
        ctx = _finishing_ctx("C-9002B", "O-9002B")
        booth = make_booth(booth_code="K-2B", capacity=2)
        make_batch(ctx["order"]["id"], booth["id"], cure_start_hour=10, cure_end_hour=16)
        b2 = make_batch(ctx["order"]["id"], booth["id"], cure_start_hour=12, cure_end_hour=18)
        # [18,22) touches b2's exclusive end: adjacent, never overlapping, so
        # it books cleanly even with two batches present.
        b4 = validate_success(api.create_finishing_batch(
            {"order_id": ctx["order"]["id"], "booth_id": booth["id"],
             "cure_start_hour": 18, "cure_end_hour": 22}, PL_H,
        ), 201)
        assert b4["status"] == "MIXED"


class TestBoothPurgePriority:
    def test_purge_violation_beats_capacity_exceeded(self, api):
        """PRD §2.5: "Evaluation stops at the first rung that fails, and that
        rung's error is the one returned — a later rung never masks an earlier
        one." Fire/compliance safety (rung 7) precedes fiscal quota/capacity
        (rung 11). PRD §3.5: "any overlapping existing batch whose finish
        family differs from the new batch's family is rejected with
        `ERR_BOOTH_PURGE_VIOLATION` (HTTP 403) — a booth never cures paint and
        clear-stain work in overlapping windows".

        Design: Difficulty/priority_pair_validation_conflict/booth_create_safety_beats_fiscal
        """
        project = make_project(name="Booth Proj", site_address="9 Spray Blvd", contract_code="C-6003")
        # Order S: MAPLE/STAIN (clear-stain family), batch curing [10,16) on a
        # capacity-1 booth.
        s = setup_order_finishing(
            project=project, contract_code="C-6003", order_code="O-S", species="MAPLE",
            finish_system="STAIN", sheen_target="SATIN",
            openings=({"opening_no": "S1", "leaf_count": 1, "fire_rating": "NONE",
                       "required_on_site_date": "2026-10-01"},),
            machine_code="M-B1", machine_species=["MAPLE", "PAINT_GRADE"],
            slot_start=8, slot_end=10,
        )
        booth = make_booth(booth_code="K-1", capacity=1)
        make_batch(s["order"]["id"], booth["id"], cure_start_hour=10, cure_end_hour=16)

        # Order P: PAINT_GRADE/PAINT (paint family) in FINISHING.
        p = setup_order_finishing(
            project=project, contract_code="C-6003", order_code="O-P", species="PAINT_GRADE",
            profile_code="PR-1", finish_system="PAINT", sheen_target="MATTE",
            openings=({"opening_no": "P1", "leaf_count": 1, "fire_rating": "NONE",
                       "required_on_site_date": "2026-10-01"},),
            machine_code="M-B1", machine_species=["MAPLE", "PAINT_GRADE"],
            slot_start=12, slot_end=14,
        )

        # Overlapping [12,18) violates BOTH purge (cross-family) and capacity
        # (count 1 == capacity 1); the safety error must win.
        resp = api.create_finishing_batch(
            {"order_id": p["order"]["id"], "booth_id": booth["id"],
             "cure_start_hour": 12, "cure_end_hour": 18}, PL_H,
        )
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_BOOTH_PURGE_VIOLATION", (
            f"purge (safety) must beat capacity (fiscal), got {body['data']['error_id']}"
        )
        validate_error(resp, ApiErrorId.ERR_BOOTH_PURGE_VIOLATION, 403)

    def test_purge_violation_with_capacity_headroom(self, api):
        """PRD §3.5: "Independently of headroom, any overlapping existing batch
        whose finish family differs from the new batch's family is rejected
        with `ERR_BOOTH_PURGE_VIOLATION` (HTTP 403)"."

        Design: Difficulty/priority_pair_validation_conflict/booth_create_safety_beats_fiscal
        """
        project = make_project(name="Booth Proj 2", site_address="11 Spray Blvd", contract_code="C-6003B")
        s = setup_order_finishing(
            project=project, contract_code="C-6003B", order_code="O-S2", species="MAPLE",
            finish_system="STAIN", sheen_target="SATIN",
            openings=({"opening_no": "S1", "leaf_count": 1, "fire_rating": "NONE",
                       "required_on_site_date": "2026-10-01"},),
            machine_code="M-B2", machine_species=["MAPLE", "PAINT_GRADE"],
            slot_start=8, slot_end=10,
        )
        booth = make_booth(booth_code="K-H", capacity=2)
        make_batch(s["order"]["id"], booth["id"], cure_start_hour=10, cure_end_hour=16)
        p = setup_order_finishing(
            project=project, contract_code="C-6003B", order_code="O-P2", species="PAINT_GRADE",
            profile_code="PR-1", finish_system="PAINT", sheen_target="MATTE",
            openings=({"opening_no": "P1", "leaf_count": 1, "fire_rating": "NONE",
                       "required_on_site_date": "2026-10-01"},),
            machine_code="M-B2", machine_species=["MAPLE", "PAINT_GRADE"],
            slot_start=12, slot_end=14,
        )
        # Capacity headroom exists (1 of 2), yet the cross-family overlap fails.
        resp = api.create_finishing_batch(
            {"order_id": p["order"]["id"], "booth_id": booth["id"],
             "cure_start_hour": 12, "cure_end_hour": 18}, PL_H,
        )
        validate_error(resp, ApiErrorId.ERR_BOOTH_PURGE_VIOLATION, 403)


class TestSheenConformance:
    def test_sheen_tolerance_boundary_pass_and_fail(self, api):
        """PRD §3.5: "A deviation of no more than 2.0 gloss units passes —
        exactly 2.0 passes, while 2.1 fails — moving the batch to `PASSED`;
        anything greater moves it to `FAILED`." and "maps the order's sheen
        target into `sheen_target_gu`, the batch's gloss-unit goal: 15 for
        `MATTE`, 35 for `SATIN`, 60 for `SEMI_GLOSS`, and 85 for `HIGH_GLOSS`."

        Design: Corner/calculations/sheen_tolerance_boundary_pass_and_fail
        """
        ctx = _finishing_ctx("CT-1", "O-T1")
        booth = make_booth(booth_code="B-T1")
        b1 = make_batch(ctx["order"]["id"], booth["id"], cure_start_hour=10, cure_end_hour=14)
        assert b1["sheen_target_gu"] == 35, "SATIN maps to 35 gloss units"
        advance_batch(b1["id"], "SPRAYED")
        advance_batch(b1["id"], "CURED")
        b2 = make_batch(ctx["order"]["id"], booth["id"], cure_start_hour=15, cure_end_hour=19)
        advance_batch(b2["id"], "SPRAYED")
        advance_batch(b2["id"], "CURED")

        # delta exactly 2.0 -> PASSED (boundary inclusive)
        measured1 = measure_batch(b1["id"], 37.0)
        assert measured1["status"] == "PASSED"
        assert measured1["delta_gu"] == 2.0
        # delta 2.1 -> FAILED
        measured2 = measure_batch(b2["id"], 37.1)
        assert measured2["status"] == "FAILED"
        assert measured2["delta_gu"] == 2.1

    def test_batch_fail_then_pass_opening_effects(self, api):
        """PRD §3.5: "Passing a batch is the fabrication axis's great
        consolidator: every opening of the batch's order sitting in `MACHINED`
        or `REWORK` moves to `FINISHED`". and "A failed batch changes nothing
        downstream; the openings stay where they are."

        Design: Corner/state_machines/batch_fail_then_pass_opening_effects
        """
        ctx = setup_order_finishing(
            contract_code="CS-7", order_code="O-B", species="MAPLE", profile_code="PR-2",
            finish_system="STAIN", sheen_target="SATIN",
            openings=(
                {"opening_no": "B1", "leaf_count": 1, "fire_rating": "NONE",
                 "required_on_site_date": "2026-10-01"},
                {"opening_no": "B2", "leaf_count": 1, "fire_rating": "NONE",
                 "required_on_site_date": "2026-10-01"},
            ),
            machine_code="M-B", machine_species=["MAPLE"], slot_start=8, slot_end=9,
            estimated_minutes=30,
        )
        op1, op2 = ctx["openings"][0]["id"], ctx["openings"][1]["id"]
        booth = make_booth(booth_code="B-B")
        b1 = make_batch(ctx["order"]["id"], booth["id"], cure_start_hour=10, cure_end_hour=14)
        advance_batch(b1["id"], "SPRAYED")
        advance_batch(b1["id"], "CURED")

        # FAILED batch (delta 3.0 > 2.0) leaves both openings MACHINED.
        failed = measure_batch(b1["id"], 38)
        assert failed["status"] == "FAILED"
        assert failed["delta_gu"] == 3.0
        assert get_opening(op1)["fab_status"] == "MACHINED"

        # A later PASSED batch (delta 0.5) moves every MACHINED opening.
        b2 = make_batch(ctx["order"]["id"], booth["id"], cure_start_hour=15, cure_end_hour=19)
        advance_batch(b2["id"], "SPRAYED")
        advance_batch(b2["id"], "CURED")
        passed = measure_batch(b2["id"], 35.5)
        assert passed["status"] == "PASSED"
        assert get_opening(op1)["fab_status"] == "FINISHED"
        assert get_opening(op2)["fab_status"] == "FINISHED"


class TestBatchGates:
    def test_batch_gates_and_invalid_batch_transition(self, api):
        """PRD §3.5: "A non-rework batch may only be created while the order is
        in `FINISHING` (`ERR_ORDER_NOT_FINISHING`)". and "undeclared batch
        pairs — from `MIXED` straight to `CURED`, or anything out of the
        terminal states — fail with `ERR_INVALID_BATCH_STATUS_TRANSITION`."
        and "a `QAInspector` submits a `sheen_measured_gu` reading for the
        batch, which is only accepted while the batch is `CURED`
        (`ERR_BATCH_NOT_CURED`)."

        Design: Corner/endpoints/batch_gates_and_invalid_batch_transition
        """
        # Order driven only to IN_PRODUCTION (not FINISHING).
        from test_helpers import setup_order_in_production
        prod = setup_order_in_production(
            contract_code="CE-2", order_code="O-E2", species="MAPLE", profile_code="PR-2",
            finish_system="STAIN", sheen_target="SATIN",
            openings=({"opening_no": "1", "leaf_count": 1, "fire_rating": "NONE",
                       "required_on_site_date": "2026-10-01"},),
            machine_code="M-E2", machine_species=["MAPLE"], slot_start=8, slot_end=9,
            estimated_minutes=30,
        )
        machine_opening(prod["openings"][0]["id"])
        booth = make_booth(booth_code="B-E2")

        # Non-rework batch before FINISHING.
        resp = api.create_finishing_batch(
            {"order_id": prod["order"]["id"], "booth_id": booth["id"],
             "cure_start_hour": 10, "cure_end_hour": 14}, PL_H,
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FINISHING, 409)

        set_order_status(prod["order"]["id"], "FINISHING")
        batch = make_batch(prod["order"]["id"], booth["id"], cure_start_hour=10, cure_end_hour=14)

        # MIXED -> CURED skips SPRAYED: undeclared pair.
        resp = api.set_finishing_batch_status(batch["id"], {"target_status": "CURED"}, PL_H)
        validate_error(resp, ApiErrorId.ERR_INVALID_BATCH_STATUS_TRANSITION, 409)

        # Measuring a SPRAYED (not CURED) batch fails.
        advance_batch(batch["id"], "SPRAYED")
        resp = api.measure_finishing_batch(batch["id"], {"sheen_measured_gu": 35}, QA_H)
        validate_error(resp, ApiErrorId.ERR_BATCH_NOT_CURED, 409)

    def test_rework_batch_requires_rework_openings(self, api):
        """PRD §3.5: "a rework batch requires at least one opening of the order
        to be sitting in `REWORK` (`ERR_NO_REWORK_OPENINGS`)."

        Design: Corner/errors/rework_batch_requires_rework_openings
        """
        from test_helpers import setup_order_in_production as _setup_prod
        prod = _setup_prod(
            contract_code="CR-2", order_code="O-R2", species="PAINT_GRADE", profile_code="PR-1",
            finish_system="PAINT", sheen_target="MATTE",
            openings=({"opening_no": "1", "leaf_count": 1, "fire_rating": "NONE",
                       "required_on_site_date": "2026-10-01"},),
            machine_code="M-R2", machine_species=["PAINT_GRADE"], slot_start=6, slot_end=8,
            estimated_minutes=30,
        )
        machine_opening(prod["openings"][0]["id"])
        booth = make_booth(booth_code="B-R2")

        # Order is IN_PRODUCTION and no opening is in REWORK.
        resp = api.create_finishing_batch(
            {"order_id": prod["order"]["id"], "booth_id": booth["id"],
             "cure_start_hour": 10, "cure_end_hour": 14, "is_rework_batch": True}, PL_H,
        )
        validate_error(resp, ApiErrorId.ERR_NO_REWORK_OPENINGS, 409)
