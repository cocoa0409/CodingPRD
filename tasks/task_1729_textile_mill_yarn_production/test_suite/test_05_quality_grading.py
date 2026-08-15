"""Quality testing: the grading ladder, provisional-vs-final variants, quality gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_dye_lot,
    assert_quality_test,
    create_dye_lot,
    record_quality_test,
    setup_dye_lot_in_dyeing,
    setup_dye_lot_shade_pending,
    setup_yarn_lot,
    validate_error,
    validate_success,
)

SUPERVISOR = TEST_USERS["spinning_supervisor_headers"]
OPERATOR = TEST_USERS["dye_house_operator_headers"]
INSPECTOR = TEST_USERS["quality_inspector_headers"]


class TestProvisionalVsFinalGrading:
    def test_provisional_grade_at_recording(self, api):
        """PRD §3.5: "Every test derives a `grade` the moment it is recorded, and again when the final shrinkage arrives. The grading ladder uses the final shrinkage when it is present and the provisional shrinkage otherwise: a shrinkage input of 8.0 percent or more grades the lot `REJECTED`; a shrinkage input of at least 5.0 percent but below 8.0 grades it `SECOND_QUALITY`; below that, a `hand_score` under 3 still grades it `SECOND_QUALITY`; only a lot clearing all three hurdles earns `FIRST_QUALITY`."

        Design: Difficulty/dual_variant_calc/quality_grading_provisional_vs_final
        """
        ctx = setup_dye_lot_in_dyeing()
        test = record_quality_test(
            ctx["dye_lot"]["id"], shrinkage_pct_provisional=5.5, hand_score=4
        )
        assert_quality_test(test)
        assert test["grade"] == "SECOND_QUALITY", (
            "Provisional variant: 5.5 >= 5.0 (and < 8.0) grades SECOND_QUALITY"
        )
        assert test["shrinkage_pct_final"] is None

    def test_final_shrinkage_regrades(self, api):
        """PRD §3.5: "The grading ladder uses the final shrinkage when it is present and the provisional shrinkage otherwise: a shrinkage input of 8.0 percent or more grades the lot `REJECTED`; a shrinkage input of at least 5.0 percent but below 8.0 grades it `SECOND_QUALITY`; below that, a `hand_score` under 3 still grades it `SECOND_QUALITY`; only a lot clearing all three hurdles earns `FIRST_QUALITY`."
        PRD §3.5: "Because the final measurement replaces the provisional input, patching in the final shrinkage may upgrade or downgrade the earlier provisional grade."

        Design: Difficulty/dual_variant_calc/quality_grading_provisional_vs_final
        """
        ctx = setup_dye_lot_in_dyeing()
        test = record_quality_test(
            ctx["dye_lot"]["id"], shrinkage_pct_provisional=5.5, hand_score=4
        )
        assert test["grade"] == "SECOND_QUALITY"

        updated = validate_success(
            api.patch_quality_test(
                test["id"], {"shrinkage_pct_final": 4.8}, INSPECTOR
            )
        )
        assert updated["grade"] == "FIRST_QUALITY", (
            "Final variant: 4.8 < 5.0 with hand_score 4 >= 3 upgrades the lot"
        )
        assert updated["id"] == test["id"], "The same record is re-graded in place"


class TestGradingLadder:
    def test_hand_score_below_min_second_quality(self, api):
        """PRD §3.5: "below that, a `hand_score` under 3 still grades it `SECOND_QUALITY`; only a lot clearing all three hurdles earns `FIRST_QUALITY`."

        Design: Corner/calculations/quality_grading_hand_score_below_min_yields_second
        """
        ctx = setup_dye_lot_in_dyeing()
        test = record_quality_test(
            ctx["dye_lot"]["id"], shrinkage_pct_provisional=3.0, hand_score=2
        )
        assert test["grade"] == "SECOND_QUALITY", (
            "Low shrinkage cannot rescue a hand_score under 3"
        )

    def test_shrinkage_reject_threshold(self, api):
        """PRD §3.5: "a shrinkage input of 8.0 percent or more grades the lot `REJECTED`"

        Design: Corner/calculations/quality_grading_reject_threshold
        """
        ctx = setup_dye_lot_in_dyeing()
        test = record_quality_test(
            ctx["dye_lot"]["id"], shrinkage_pct_provisional=9.5, hand_score=5
        )
        assert test["grade"] == "REJECTED", "9.5 >= 8.0 grades REJECTED"


class TestShrinkageBoundary:
    def test_shrinkage_exactly_5_grades_second(self, api):
        """PRD §3.5: "a shrinkage input of at least 5.0 percent but below 8.0 grades it `SECOND_QUALITY`"

        Design: Difficulty/boundary_precision_check/shrinkage_exactly_at_second_quality_threshold
        """
        ctx = setup_dye_lot_in_dyeing()
        test = record_quality_test(
            ctx["dye_lot"]["id"], shrinkage_pct_provisional=5.0, hand_score=5
        )
        assert test["grade"] == "SECOND_QUALITY", (
            "The 5.0 threshold is inclusive: exactly 5.0 grades SECOND_QUALITY"
        )

    def test_shrinkage_just_below_5_grades_first(self, api):
        """PRD §3.5: "a shrinkage input of at least 5.0 percent but below 8.0 grades it `SECOND_QUALITY`; below that, a `hand_score` under 3 still grades it `SECOND_QUALITY`; only a lot clearing all three hurdles earns `FIRST_QUALITY`."

        Design: Difficulty/boundary_precision_check/shrinkage_exactly_at_second_quality_threshold
        """
        ctx = setup_dye_lot_in_dyeing()
        test = record_quality_test(
            ctx["dye_lot"]["id"], shrinkage_pct_provisional=4.99, hand_score=5
        )
        assert test["grade"] == "FIRST_QUALITY", (
            "4.99 is below the 5.0 threshold and a hand_score of 5 clears the ladder"
        )


class TestApproveQualityGate:
    def test_approve_blocked_by_rejected_grade(self, api):
        """PRD §3.5: "A dye lot in `SHADE_PENDING` can be approved by the inspector only when a quality test exists whose grade is `FIRST_QUALITY` or `SECOND_QUALITY`; approval of a lot whose test graded `REJECTED` is blocked by the quality gate with `ERR_QUALITY_GATE_FAILED`."

        Design: Difficulty/cross_entity_state_dependency/dye_lot_approve_requires_passing_quality_test
        """
        ctx = setup_dye_lot_shade_pending(
            shrinkage_pct_provisional=9.0, hand_score=2, shrinkage_pct_final=None,
            requested_yards=1000.0,
        )
        resp = api.approve_dye_lot(ctx["dye_lot"]["id"], INSPECTOR)
        validate_error(resp, ApiErrorId.ERR_QUALITY_GATE_FAILED)

        after = validate_success(api.get_dye_lot(ctx["dye_lot"]["id"], INSPECTOR))
        assert after["status"] == "SHADE_PENDING", (
            "A blocked approval leaves the dye lot SHADE_PENDING"
        )

    def test_approve_passes_with_second_quality_grade(self, api):
        """PRD §3.5: "A dye lot in `SHADE_PENDING` can be approved by the inspector only when a quality test exists whose grade is `FIRST_QUALITY` or `SECOND_QUALITY`; approval of a lot whose test graded `REJECTED` is blocked by the quality gate with `ERR_QUALITY_GATE_FAILED`."

        Design: Difficulty/cross_entity_state_dependency/dye_lot_approve_requires_passing_quality_test
        """
        ctx = setup_dye_lot_shade_pending(
            shrinkage_pct_provisional=6.0, hand_score=4, shrinkage_pct_final=6.0,
            requested_yards=1000.0,
        )
        assert ctx["quality_test"]["grade"] == "SECOND_QUALITY"
        approved = approve_dye_lot(ctx["dye_lot"]["id"])
        assert approved["status"] == "APPROVED", (
            "SECOND_QUALITY satisfies the gate and the dye lot approves"
        )


class TestCascadeOrdering:
    def test_state_masks_quality_gate_submitted(self, api):
        """PRD §2.10: "Every mutating request passes through a fixed validation cascade, evaluated in this exact order so that earlier failures mask later ones deterministically:"
        PRD §2.10: "State legality — the target entity's current state permits the requested transition (`ERR_INVALID_STATE`)."
        PRD §2.10: "Quality gates — dye-lot approval is blocked while its quality test graded `REJECTED`, and a yarn lot cannot enter dyeing under a recipe that is not `APPROVED` (`ERR_QUALITY_GATE_FAILED`)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_dye_approve
        """
        # Dye lot is SUBMITTED (wrong state for approve) AND has no quality test
        # (would also fail the quality gate): state legality masks the gate.
        fresh = setup_yarn_lot()
        dye_lot = create_dye_lot(
            fresh["yarn_lot"]["id"], fresh["shade_band"]["id"],
            requested_yards=5000.0,
        )
        assert dye_lot["status"] == "SUBMITTED"

        resp = api.approve_dye_lot(dye_lot["id"], INSPECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_state_masks_quality_gate_dyeing_with_rejected_grade(self, api):
        """PRD §2.10: "Every mutating request passes through a fixed validation cascade, evaluated in this exact order so that earlier failures mask later ones deterministically:"
        PRD §2.10: "State legality — the target entity's current state permits the requested transition (`ERR_INVALID_STATE`)."
        PRD §2.10: "Quality gates — dye-lot approval is blocked while its quality test graded `REJECTED`, and a yarn lot cannot enter dyeing under a recipe that is not `APPROVED` (`ERR_QUALITY_GATE_FAILED`)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_dye_approve
        """
        # Dye lot DYEING (not SHADE_PENDING) with a REJECTED-graded test on file:
        # both checks fail; the state check (earlier) must surface.
        ctx = setup_dye_lot_in_dyeing(
            shrinkage_pct_provisional=9.0, hand_score=2, requested_yards=1000.0
        )
        assert ctx["quality_test"]["grade"] == "REJECTED"
        assert ctx["dye_lot"]["status"] == "DYEING"

        resp = api.approve_dye_lot(ctx["dye_lot"]["id"], INSPECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
