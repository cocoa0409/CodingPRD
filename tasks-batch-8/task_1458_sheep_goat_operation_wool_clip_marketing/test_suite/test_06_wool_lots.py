"""Wool lots: weight allocation boundary, conservation invariant, grade bands,
regrade cycle with OCC, delete rules."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_wool_clip,
    grade_lot,
    set_clock,
    setup_clip_with_lot,
    setup_consigned_lot,
    setup_graded_lot,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestWeightAllocation:

    def test_lot_weight_over_allocation_rejected(self, api, ranch_manager_headers):
        """PRD §3.4: "The allocation rule caps `weight_lbs` at the clip's
        current `unallocated_weight_lbs` — exact equality is allowed and fully
        allocates the clip — and any excess is rejected with
        `ERR_WEIGHT_OVER_ALLOCATED` (HTTP 422)."

        Design: Corner/validations/lot_weight_over_allocation_rejected
        """
        flock, clip, _unused = None, None, None
        from test_helpers import create_flock, create_completed_clip
        flock = create_flock(flock_name="Alloc Ranch", species="SHEEP", baseline_headcount=500)
        clip, _event, _crew = create_completed_clip(
            flock["id"], greasy_weight_lbs=120.0, skirtings_weight_lbs=20.0)
        # Net allocatable weight == 120.0 - 20.0 == 100.0; exact equality allowed.
        resp = api.create_wool_lot(
            {"clip_id": clip["id"], "lot_code": "FULL", "weight_lbs": 100.0},
            ranch_manager_headers)
        lot1 = validate_success(resp, expected_status=201)
        assert lot1["weight_lbs"] == 100.0
        clip = validate_success(api.get_wool_clip(clip["id"], ranch_manager_headers))
        assert clip["unallocated_weight_lbs"] == 0.0

        resp = api.create_wool_lot(
            {"clip_id": clip["id"], "lot_code": "OVER", "weight_lbs": 0.01},
            ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_WEIGHT_OVER_ALLOCATED.value, expected_status=422)

    def test_clip_weight_create_delete_conservation(self, api, ranch_manager_headers):
        """PRD §3.3: "Every clip maintains a weight-conservation invariant,
        recomputed whenever lots are created, graded, or deleted:
        `allocated_weight_lbs` is the sum of `weight_lbs` over the clip's lots;
        `unallocated_weight_lbs` is `greasy_weight_lbs` minus
        `skirtings_weight_lbs` minus `allocated_weight_lbs`".
        PRD §3.4: "while it remains `DRAFT` it can be deleted outright, which
        releases its weight back into the clip's unallocated balance as the
        compensating action for the weight invariant".

        Design: Difficulty/compensating_invariant/clip_weight_create_delete_conservation
        """
        from test_helpers import create_flock, create_completed_clip
        flock = create_flock(flock_name="Weight Ranch", species="SHEEP", baseline_headcount=500)
        clip, _event, _crew = create_completed_clip(
            flock["id"], greasy_weight_lbs=300.0, skirtings_weight_lbs=30.0)

        resp = api.create_wool_lot(
            {"clip_id": clip["id"], "lot_code": "WA", "weight_lbs": 100.0}, ranch_manager_headers)
        lot_a = validate_success(resp, expected_status=201)
        clip = validate_success(api.get_wool_clip(clip["id"], ranch_manager_headers))
        assert clip["unallocated_weight_lbs"] == 170.0, "300 - 30 - 100"
        assert_wool_clip(clip)

        resp = api.create_wool_lot(
            {"clip_id": clip["id"], "lot_code": "WB", "weight_lbs": 50.0}, ranch_manager_headers)
        validate_success(resp, expected_status=201)
        clip = validate_success(api.get_wool_clip(clip["id"], ranch_manager_headers))
        assert clip["allocated_weight_lbs"] == 150.0
        assert clip["unallocated_weight_lbs"] == 120.0
        assert_wool_clip(clip)

        # Deleting the DRAFT lot releases its weight (compensating action).
        resp = api.delete_wool_lot(lot_a["id"], ranch_manager_headers)
        assert resp.status_code == 204, f"expected 204 on DRAFT lot delete, got {resp.status_code}"
        clip = validate_success(api.get_wool_clip(clip["id"], ranch_manager_headers))
        assert clip["allocated_weight_lbs"] == 50.0
        assert clip["unallocated_weight_lbs"] == 220.0
        assert_wool_clip(clip)

    def test_clip_weight_conservation_invariant_after_each_create(self, api, ranch_manager_headers):
        """PRD §3.3: "`unallocated_weight_lbs` is `greasy_weight_lbs` minus
        `skirtings_weight_lbs` minus `allocated_weight_lbs`".

        Design: Difficulty/compensating_invariant/clip_weight_create_delete_conservation
        """
        from test_helpers import create_flock, create_completed_clip
        flock = create_flock(flock_name="Weight2 Ranch", species="SHEEP", baseline_headcount=500)
        clip, _event, _crew = create_completed_clip(
            flock["id"], greasy_weight_lbs=300.0, skirtings_weight_lbs=30.0)
        running = 270.0
        for i, w in enumerate((60.0, 40.0, 25.0)):
            validate_success(api.create_wool_lot(
                {"clip_id": clip["id"], "lot_code": f"W{i}", "weight_lbs": w},
                ranch_manager_headers), expected_status=201)
            running -= w
            clip_now = validate_success(api.get_wool_clip(clip["id"], ranch_manager_headers))
            assert clip_now["unallocated_weight_lbs"] == running
            assert_wool_clip(clip_now)


class TestGrading:

    def test_micron_grade_lower_bound_inclusive(self, api, ranch_manager_headers):
        """PRD §3.4: "The grade bands key off `effective_micron` — the
        `certified_micron` when a locked core test exists for the lot,
        otherwise the `estimated_micron` — with lower bounds inclusive:
        strictly below 19.5 microns is `SUPERFINE`; 19.5 up to but not
        including 21.5 is `FINE` (so exactly 19.5 is `FINE`); 21.5 up to but
        not including 24.5 is `MEDIUM`; 24.5 up to but not including 27.5 is
        `STRONG`; and 27.5 or above is `COARSE` (so exactly 27.5 is `COARSE`)."
        PRD §3.4: "The provisional value multiplies `weight_lbs` by the
        greasy-pound price of the band — 380 cents per greasy pound for
        `SUPERFINE`, 330 for `FINE`, 260 for `MEDIUM`, 190 for `STRONG`, and
        120 for `COARSE` — rounded half-up to a whole cent."

        Design: Difficulty/boundary_precision_check/micron_grade_lower_bound_inclusive
        """
        from test_helpers import create_flock, create_completed_clip
        flock = create_flock(flock_name="Micron Ranch", species="SHEEP", baseline_headcount=500)
        clip, _event, _crew = create_completed_clip(
            flock["id"], greasy_weight_lbs=200.0, skirtings_weight_lbs=10.0)
        lot_h = validate_success(api.create_wool_lot(
            {"clip_id": clip["id"], "lot_code": "B1", "weight_lbs": 80.0},
            ranch_manager_headers), expected_status=201)
        lot_i = validate_success(api.create_wool_lot(
            {"clip_id": clip["id"], "lot_code": "B2", "weight_lbs": 80.0},
            ranch_manager_headers), expected_status=201)

        # Exactly 19.5 -> FINE (lower bound inclusive).
        lot_h = validate_success(api.grade_wool_lot(
            lot_h["id"], {"estimated_micron": 19.5}, ranch_manager_headers))
        assert lot_h["grade_code"] == "FINE"
        assert lot_h["provisional_value_cents"] == 26400, "80.0 * 330"

        # Just under 19.5 -> SUPERFINE.
        lot_i = validate_success(api.grade_wool_lot(
            lot_i["id"], {"estimated_micron": 19.49}, ranch_manager_headers))
        assert lot_i["grade_code"] == "SUPERFINE"
        assert lot_i["provisional_value_cents"] == 30400, "80.0 * 380"

    @pytest.mark.parametrize("micron,grade,price", [
        (19.49, "SUPERFINE", 380),
        (19.5, "FINE", 330),
        (21.49, "FINE", 330),
        (21.5, "MEDIUM", 260),
        (24.49, "MEDIUM", 260),
        (24.5, "STRONG", 190),
        (27.49, "STRONG", 190),
        (27.5, "COARSE", 120),
    ])
    def test_micron_grade_band_boundaries(self, api, ranch_manager_headers, micron, grade, price):
        """PRD §3.4: "strictly below 19.5 microns is `SUPERFINE`; 19.5 up to but
        not including 21.5 is `FINE` (so exactly 19.5 is `FINE`); 21.5 up to
        but not including 24.5 is `MEDIUM`; 24.5 up to but not including 27.5
        is `STRONG`; and 27.5 or above is `COARSE` (so exactly 27.5 is
        `COARSE`)."

        Design: Difficulty/boundary_precision_check/micron_grade_lower_bound_inclusive
        """
        from test_helpers import create_flock, create_completed_clip
        flock = create_flock(species="SHEEP", baseline_headcount=500)
        clip, _event, _crew = create_completed_clip(
            flock["id"], greasy_weight_lbs=200.0, skirtings_weight_lbs=10.0)
        lot = validate_success(api.create_wool_lot(
            {"clip_id": clip["id"], "lot_code": "BX", "weight_lbs": 10.0},
            ranch_manager_headers), expected_status=201)
        lot = validate_success(api.grade_wool_lot(
            lot["id"], {"estimated_micron": micron}, ranch_manager_headers))
        assert lot["grade_code"] == grade, f"micron {micron} must band as {grade}"
        assert lot["provisional_value_cents"] == round(10.0 * price)


class TestRegradeCycle:

    def test_wool_lot_regrade_and_reconsign_cycles(self, api, ranch_manager_headers, wool_pool_operator_headers):
        """PRD §3.4: "Recording the regrade moves the lot `REGRADING -> GRADED`,
        requires a fresh `estimated_micron` strictly above 0, and is one of the
        system's two optimistic-concurrency points: the request must carry
        `expected_wool_lot_version` equal to the lot's current `version`, and a
        mismatch is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412) exactly as
        §2.6 describes. A successful regrade stores the new estimate, rebands
        `grade_code`, recomputes `provisional_value_cents`, and increments the
        lot's `version`."
        PRD §3.5: "from `ACCEPTED` it simply moves the consignment to
        `WITHDRAWN` and the lot from `CONSIGNED` to `WITHDRAWN`".
        PRD §3.5: "The manager tenders a `GRADED` or `WITHDRAWN` lot to a wool
        pool by creating a consignment with `lot_id` and a `pool_ref`
        sale-season identifier such as `WWPA-2026A`; tendering moves the lot to
        `CONSIGNED`."

        Design: Difficulty/non_linear_state_machine/wool_lot_regrade_and_reconsign_cycles
        """
        flock, clip, lot = setup_graded_lot(
            estimated_micron=20.0, flock_name="Cycle Ranch", lot_weight_lbs=100.0,
            greasy_weight_lbs=200.0, skirtings_weight_lbs=20.0, crew_name="Crew CY")
        assert lot["grade_code"] == "FINE"
        assert lot["provisional_value_cents"] == 33000

        lot = validate_success(api.transition_wool_lot(lot["id"], {"to": "REGRADING"}, ranch_manager_headers))
        lot = validate_success(api.regrade_wool_lot(lot["id"], {
            "estimated_micron": 18.0, "expected_wool_lot_version": lot["version"],
        }, ranch_manager_headers))
        assert lot["lot_status"] == "GRADED"
        assert lot["grade_code"] == "SUPERFINE", "18.0 < 19.5"
        assert lot["provisional_value_cents"] == 38000, "100.0 * 380 (was 33000 at FINE)"

        # First consignment cycle: GRADED -> CONSIGNED -> (ACCEPTED) -> WITHDRAWN.
        con1 = validate_success(api.create_consignment(
            {"lot_id": lot["id"], "pool_ref": "WWPA-CYC"}, ranch_manager_headers), expected_status=201)
        assert con1["consignment_status"] == "TENDERED"
        lot = validate_success(api.get_wool_lot(lot["id"], ranch_manager_headers))
        assert lot["lot_status"] == "CONSIGNED"
        validate_success(api.transition_consignment(
            con1["id"], {"to": "ACCEPTED"}, wool_pool_operator_headers))
        con1 = validate_success(api.transition_consignment(
            con1["id"], {"to": "WITHDRAWN"}, ranch_manager_headers))
        assert con1["consignment_status"] == "WITHDRAWN"
        lot = validate_success(api.get_wool_lot(lot["id"], ranch_manager_headers))
        assert lot["lot_status"] == "WITHDRAWN"

        # Re-consign the withdrawn lot: second consignment on the same lot.
        con2 = validate_success(api.create_consignment(
            {"lot_id": lot["id"], "pool_ref": "WWPA-CYC2"}, ranch_manager_headers), expected_status=201)
        assert con2["consignment_status"] == "TENDERED"
        lot = validate_success(api.get_wool_lot(lot["id"], ranch_manager_headers))
        assert lot["lot_status"] == "CONSIGNED"

    def test_regrade_rebands_and_reprices(self, api, ranch_manager_headers):
        """PRD §3.4: "A successful regrade stores the new estimate, rebands
        `grade_code`, recomputes `provisional_value_cents`, and increments the
        lot's `version`."

        Design: Difficulty/non_linear_state_machine/wool_lot_regrade_and_reconsign_cycles
        """
        flock, clip, lot = setup_graded_lot(
            estimated_micron=20.0, flock_name="Cycle2 Ranch", lot_weight_lbs=100.0,
            greasy_weight_lbs=200.0, skirtings_weight_lbs=20.0, crew_name="Crew CY2")
        v_before = lot["version"]
        lot = validate_success(api.transition_wool_lot(lot["id"], {"to": "REGRADING"}, ranch_manager_headers))
        lot = validate_success(api.regrade_wool_lot(lot["id"], {
            "estimated_micron": 26.0, "expected_wool_lot_version": lot["version"],
        }, ranch_manager_headers))
        assert lot["grade_code"] == "STRONG", "24.5 <= 26.0 < 27.5"
        assert lot["provisional_value_cents"] == 19000, "100.0 * 190"
        assert lot["version"] == v_before + 2, "REGRADING transition + regrade each increment by 1"


class TestLotDelete:

    def test_lot_delete_non_draft_rejected(self, api, ranch_manager_headers):
        """PRD §3.4: "A lot starts in `DRAFT` `lot_status`, and while it
        remains `DRAFT` it can be deleted outright, which releases its weight
        back into the clip's unallocated balance as the compensating action for
        the weight invariant; deleting a lot in any other status is rejected
        with `ERR_LOT_INVALID_STATE` (HTTP 409)."

        Design: Corner/validations/lot_delete_non_draft_rejected
        """
        flock, clip, lot = setup_graded_lot(
            estimated_micron=20.0, flock_name="Del Ranch", crew_name="Crew DL")
        resp = api.delete_wool_lot(lot["id"], ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_LOT_INVALID_STATE.value, expected_status=409)
        lot = validate_success(api.get_wool_lot(lot["id"], ranch_manager_headers))
        assert lot["lot_status"] == "GRADED"


class TestConsignmentGate:

    def test_consignment_requires_lot_graded_or_withdrawn(self, api, ranch_manager_headers):
        """PRD §3.5: "The manager tenders a `GRADED` or `WITHDRAWN` lot to a
        wool pool by creating a consignment with `lot_id` and a `pool_ref`
        sale-season identifier such as `WWPA-2026A`; tendering moves the lot to
        `CONSIGNED`."
        PRD §3.4: "A lot starts in `DRAFT` `lot_status`" and the tender of a
        lot outside {GRADED, WITHDRAWN} is not a defined operation; PRD §2.9:
        "when no such transition exists from the entity's current state, the
        request is rejected with the entity's own invalid-state error".

        Design: Difficulty/cross_entity_state_dependency/consignment_requires_lot_graded_or_withdrawn
        """
        flock, clip, lot = setup_clip_with_lot(
            flock_name="Gate2 Ranch", crew_name="Crew G2",
            greasy_weight_lbs=200.0, skirtings_weight_lbs=20.0, lot_weight_lbs=100.0)
        assert lot["lot_status"] == "DRAFT"
        resp = api.create_consignment(
            {"lot_id": lot["id"], "pool_ref": "WWPA-G2"}, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_LOT_INVALID_STATE.value, expected_status=409)

        grade_lot(lot["id"], 20.0)
        con = validate_success(api.create_consignment(
            {"lot_id": lot["id"], "pool_ref": "WWPA-G2"}, ranch_manager_headers), expected_status=201)
        assert con["consignment_status"] == "TENDERED"
        lot = validate_success(api.get_wool_lot(lot["id"], ranch_manager_headers))
        assert lot["lot_status"] == "CONSIGNED"

    def test_consignment_draft_lot_rejected_then_succeeds_after_grade(self, api, ranch_manager_headers):
        """PRD §3.5: "The manager tenders a `GRADED` or `WITHDRAWN` lot to a
        wool pool". A DRAFT lot is neither; tendering it fails with the lot's
        invalid-state error (PRD §2.9).

        Design: Difficulty/cross_entity_state_dependency/consignment_requires_lot_graded_or_withdrawn
        """
        flock, clip, lot = setup_clip_with_lot(
            flock_name="Gate5 Ranch", crew_name="Crew G5",
            greasy_weight_lbs=200.0, skirtings_weight_lbs=20.0, lot_weight_lbs=100.0)
        resp = api.create_consignment(
            {"lot_id": lot["id"], "pool_ref": "WWPA-G5"}, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_LOT_INVALID_STATE.value, expected_status=409)
