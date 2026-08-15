"""Resin lots, formulations, blend composition and batch QC (PRD §3.3, §2.9)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_quality_inspector_headers,
    create_customer, create_profile, create_formulation, create_lot, pass_lot,
    qc_passed_lot, create_batch, plant_base, material_scene,
    get_lot, get_batch, assert_mass_balance,
)

PM = TEST_USERS["plant_manager_headers"]
PE = TEST_USERS["process_engineer_headers"]
LO = TEST_USERS["line_operator_headers"]
QI = TEST_USERS["quality_inspector_headers"]


class TestResinLotConstraints:
    def test_virgin_lot_must_be_natural(self, api):
        """PRD §3.3: "One structural rule applies at the door: a `VIRGIN` lot must
        be `NATURAL` — any other colour on a virgin lot is rejected with
        `ERR_BAD_REQUEST`."

        Design: Corner/entities/virgin_lot_color_constraint_rejected
        """
        resp = api.create_resin_lot(
            {"lot_kind": "VIRGIN", "resin_type": "PVC", "color_family": "RED",
             "received_kg": 100}, LO)
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST)

    def test_qc_rejected_lot_is_terminal(self, api):
        """PRD §3.3: "`PASS` moves a `RECEIVED` lot to `QC_PASSED`; `FAIL` moves
        a `RECEIVED` lot to `QC_REJECTED`, which is terminal."

        Design: Corner/state_machines/resin_lot_terminal_qc_rejected
        """
        lot = create_lot("VIRGIN", "PVC", "NATURAL", 100)
        validate_success(api.qc_resin_lot(lot["id"], {"outcome": "FAIL"}, QI), 200)
        resp = api.qc_resin_lot(lot["id"], {"outcome": "PASS"}, QI)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_lot(lot["id"])["status"] == "QC_REJECTED"


class TestFormulationRanges:
    def test_let_down_ratio_and_regrind_boundaries(self, api):
        """PRD §3.3: "`let_down_ratio`, the base-to-colorant ratio — a value of
        25.0 means twenty-five parts base to one part colorant — which must lie
        inclusively between 10.0 and 50.0, and `max_regrind_pct`, the maximum
        regrind share of the base material as a percentage, which must lie
        inclusively between 0 and 40. A value outside either range is rejected
        with `ERR_LET_DOWN_RANGE`."

        Design: Corner/validations/let_down_ratio_boundaries
        """
        cust = create_customer()
        prof = create_profile(cust["id"])

        too_low = api.create_formulation(
            {"profile_id": prof["id"], "formula_code": "F-LOW", "base_resin_type": "PVC",
             "color_family": "RED", "let_down_ratio": 9.9, "max_regrind_pct": 20}, PE)
        validate_error(too_low, ApiErrorId.ERR_LET_DOWN_RANGE)

        at_min = api.create_formulation(
            {"profile_id": prof["id"], "formula_code": "F-MIN", "base_resin_type": "PVC",
             "color_family": "RED", "let_down_ratio": 10.0, "max_regrind_pct": 20}, PE)
        assert validate_success(at_min, 201)["let_down_ratio"] == pytest.approx(10.0)

        at_max = api.create_formulation(
            {"profile_id": prof["id"], "formula_code": "F-MAX", "base_resin_type": "PVC",
             "color_family": "RED", "let_down_ratio": 50.0, "max_regrind_pct": 40}, PE)
        assert validate_success(at_max, 201)["let_down_ratio"] == pytest.approx(50.0)

        too_high = api.create_formulation(
            {"profile_id": prof["id"], "formula_code": "F-HIGH", "base_resin_type": "PVC",
             "color_family": "RED", "let_down_ratio": 50.1, "max_regrind_pct": 20}, PE)
        validate_error(too_high, ApiErrorId.ERR_LET_DOWN_RANGE)


class TestBlendComposition:
    def test_nested_rounding_order_pinned(self, api):
        """PRD §3.3: "First, `colorant_kg` is `target_batch_kg` divided by one
        plus the formulation's `let_down_ratio`, rounded half-up to one decimal
        of a kilogram."
        PRD §3.3: "Fourth, the actual `regrind_kg` is the smaller of the
        requested draw and the regrind lot's `available_kg` — when no regrind lot
        was supplied, availability counts as zero, so `regrind_kg` is zero — and
        any shortfall against the request is absorbed by the virgin stream, never
        raised as an error."
        PRD §3.3: "Fifth, `virgin_kg` is the base total minus `regrind_kg`,
        again an exact remainder with no further rounding."

        Design: Difficulty/combinatorial_formula/blend_nested_rounding
        """
        base = plant_base()
        lot_v = qc_passed_lot("VIRGIN", "PVC", "NATURAL", 3000, "SUP-V1")
        lot_c = qc_passed_lot("COLORANT", "PVC", "RED", 100, "SUP-C1")
        lot_r = qc_passed_lot("REGRIND", "PVC", "RED", 100, "SUP-R1")
        resp = api.create_blend_batch(
            {"formulation_id": base["form"]["id"], "virgin_lot_id": lot_v["id"],
             "regrind_lot_id": lot_r["id"], "colorant_lot_id": lot_c["id"],
             "target_batch_kg": 1000}, LO)
        batch = validate_success(resp, 201)
        # colorant = round_half_up(1000 / 26, 1) = 38.5 (rounded FIRST)
        # base_total = 961.5; request = round(961.5 * 0.20, 1) = 192.3
        # regrind = min(192.3, 100 available) = 100.0; virgin = 961.5 - 100.0 = 861.5
        assert batch["colorant_kg"] == pytest.approx(38.5, abs=0.001)
        assert batch["regrind_kg"] == pytest.approx(100.0, abs=0.001)
        assert batch["virgin_kg"] == pytest.approx(861.5, abs=0.001)
        # actual_regrind_pct = round_half_up(100 * 100.0 / 961.5, 2) = 10.40
        assert batch["actual_regrind_pct"] == pytest.approx(10.40, abs=0.001)

    def test_blend_draws_update_lots_and_deplete_at_zero(self, api):
        """PRD §3.3: "A successful creation draws the three quantities into the
        component lots' `consumed_kg`, drops their `available_kg` accordingly —
        flipping any lot that reaches exactly zero to `DEPLETED` — and leaves the
        new batch in `BLENDED` status."

        Design: Difficulty/combinatorial_formula/blend_nested_rounding
        """
        base = plant_base()
        lot_v = qc_passed_lot("VIRGIN", "PVC", "NATURAL", 3000, "SUP-V1")
        lot_c = qc_passed_lot("COLORANT", "PVC", "RED", 100, "SUP-C1")
        lot_r = qc_passed_lot("REGRIND", "PVC", "RED", 100, "SUP-R1")
        resp = api.create_blend_batch(
            {"formulation_id": base["form"]["id"], "virgin_lot_id": lot_v["id"],
             "regrind_lot_id": lot_r["id"], "colorant_lot_id": lot_c["id"],
             "target_batch_kg": 1000}, LO)
        batch = validate_success(resp, 201)
        assert batch["status"] == "BLENDED"

        virgin = get_lot(lot_v["id"])
        assert virgin["consumed_kg"] == pytest.approx(861.5, abs=0.001)
        assert_mass_balance(virgin)
        regrind = get_lot(lot_r["id"])
        assert regrind["consumed_kg"] == pytest.approx(100.0, abs=0.001)
        assert regrind["available_kg"] == pytest.approx(0, abs=0.001)
        assert regrind["status"] == "DEPLETED", "available_kg hitting exactly 0 flips DEPLETED"
        colorant = get_lot(lot_c["id"])
        assert colorant["consumed_kg"] == pytest.approx(38.5, abs=0.001)
        assert_mass_balance(colorant)

    def test_regrind_absent_variant_absorbs_into_virgin(self, api):
        """PRD §3.3: "Fourth, the actual `regrind_kg` is the smaller of the
        requested draw and the regrind lot's `available_kg` — when no regrind lot
        was supplied, availability counts as zero, so `regrind_kg` is zero — and
        any shortfall against the request is absorbed by the virgin stream, never
        raised as an error."

        Design: Corner/calculations/blend_regrind_absent_variant
        """
        base = plant_base()
        lot_v = qc_passed_lot("VIRGIN", "PVC", "NATURAL", 3000, "SUP-V1")
        lot_c = qc_passed_lot("COLORANT", "PVC", "RED", 100, "SUP-C1")
        resp = api.create_blend_batch(
            {"formulation_id": base["form"]["id"], "virgin_lot_id": lot_v["id"],
             "colorant_lot_id": lot_c["id"], "target_batch_kg": 1000}, LO)
        batch = validate_success(resp, 201)
        assert batch["regrind_kg"] == pytest.approx(0.0, abs=0.001)
        assert batch.get("regrind_lot_id") is None
        assert batch["virgin_kg"] == pytest.approx(961.5, abs=0.001)
        assert batch["actual_regrind_pct"] == pytest.approx(0.0, abs=0.001)

    def test_create_response_carries_computed_composition(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.3: "First, `colorant_kg` is `target_batch_kg` divided by one plus
        the formulation's `let_down_ratio`, rounded half-up to one decimal of a
        kilogram."

        Design: Corner/consistency_model/immediate_computed_on_create
        """
        base = plant_base()
        lot_v = qc_passed_lot("VIRGIN", "PVC", "NATURAL", 3000, "SUP-V1")
        lot_c = qc_passed_lot("COLORANT", "PVC", "RED", 100, "SUP-C1")
        lot_r = qc_passed_lot("REGRIND", "PVC", "RED", 100, "SUP-R1")
        resp = api.create_blend_batch(
            {"formulation_id": base["form"]["id"], "virgin_lot_id": lot_v["id"],
             "regrind_lot_id": lot_r["id"], "colorant_lot_id": lot_c["id"],
             "target_batch_kg": 1000}, LO)
        data = validate_success(resp, 201)
        assert data["colorant_kg"] == pytest.approx(38.5, abs=0.001)
        assert data["regrind_kg"] == pytest.approx(100.0, abs=0.001)
        assert data["virgin_kg"] == pytest.approx(861.5, abs=0.001)


class TestBlendGates:
    def test_insufficient_virgin_quantity_rejected(self, api):
        """PRD §3.3: "After composition, one availability gate remains: the
        virgin lot's `available_kg` must be at least `virgin_kg` and the colorant
        lot's `available_kg` must be at least `colorant_kg`, failing which the
        creation is rejected with `ERR_INSUFFICIENT_LOT_QUANTITY`."

        Design: Corner/validations/insufficient_virgin_quantity_rejected
        """
        base = plant_base()
        lot_v = qc_passed_lot("VIRGIN", "PVC", "NATURAL", 800, "SUP-V8")
        lot_c = qc_passed_lot("COLORANT", "PVC", "RED", 100, "SUP-C1")
        lot_r = qc_passed_lot("REGRIND", "PVC", "RED", 100, "SUP-R1")
        resp = api.create_blend_batch(
            {"formulation_id": base["form"]["id"], "virgin_lot_id": lot_v["id"],
             "regrind_lot_id": lot_r["id"], "colorant_lot_id": lot_c["id"],
             "target_batch_kg": 1000}, LO)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_LOT_QUANTITY)
        # Composition needs virgin 861.5 (regrind capped at 100) > available 800.
        assert get_lot(lot_v["id"])["consumed_kg"] == pytest.approx(0, abs=0.001), (
            "A rejected creation must draw nothing")

    def test_colorant_color_mismatch_rejected(self, api):
        """PRD §3.3: "Then component compatibility: the virgin lot must be of
        `lot_kind` `VIRGIN` with a `resin_type` equal to the formulation's
        `base_resin_type`, and the colorant lot must be of `lot_kind` `COLORANT`
        whose `resin_type` equals the formulation's `base_resin_type` and whose
        `color_family` equals the formulation's `color_family`; violations are
        rejected with `ERR_LOT_INCOMPATIBLE`."

        Design: Corner/validations/lot_incompatible_colorant_rejected
        """
        base = plant_base()
        lot_v = qc_passed_lot("VIRGIN", "PVC", "NATURAL", 3000, "SUP-V1")
        lot_c_blue = qc_passed_lot("COLORANT", "PVC", "BLUE", 100, "SUP-C2")
        resp = api.create_blend_batch(
            {"formulation_id": base["form"]["id"], "virgin_lot_id": lot_v["id"],
             "colorant_lot_id": lot_c_blue["id"], "target_batch_kg": 1000}, LO)
        validate_error(resp, ApiErrorId.ERR_LOT_INCOMPATIBLE)


class TestBlendCheckPrecedence:
    def test_purity_and_compatibility_both_broken_reports_purity(self, api):
        """PRD §3.3: "The checks fire in a fixed order. After existence, every
        referenced lot must be `QC_PASSED` — any lot in any other status rejects
        the creation with `ERR_MATERIAL_NOT_RELEASED`. Next comes lot purity for
        the regrind stream: when a regrind lot is supplied it must be of
        `lot_kind` `REGRIND`, its `resin_type` must equal the formulation's
        `base_resin_type`, and its `color_family` must equal the formulation's
        `color_family`; any deviation is `ERR_REGRIND_PURITY_VIOLATION`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_blend
        """
        base = plant_base()
        lot_v_abs = qc_passed_lot("VIRGIN", "ABS", "NATURAL", 3000, "SUP-V2")
        lot_r_blue = qc_passed_lot("REGRIND", "PVC", "BLUE", 100, "SUP-R2")
        lot_c = qc_passed_lot("COLORANT", "PVC", "RED", 100, "SUP-C1")
        resp = api.create_blend_batch(
            {"formulation_id": base["form"]["id"], "virgin_lot_id": lot_v_abs["id"],
             "regrind_lot_id": lot_r_blue["id"], "colorant_lot_id": lot_c["id"],
             "target_batch_kg": 1000}, LO)
        validate_error(resp, ApiErrorId.ERR_REGRIND_PURITY_VIOLATION)
        for lot in (lot_v_abs, lot_r_blue, lot_c):
            assert get_lot(lot["id"])["consumed_kg"] == pytest.approx(0, abs=0.001), (
                "A rejected creation must draw nothing")

    def test_each_violation_fires_in_isolation(self, api):
        """PRD §3.3: "Next comes lot purity for the regrind stream: when a
        regrind lot is supplied it must be of `lot_kind` `REGRIND`, its
        `resin_type` must equal the formulation's `base_resin_type`, and its
        `color_family` must equal the formulation's `color_family`; any deviation
        is `ERR_REGRIND_PURITY_VIOLATION`."
        PRD §3.3: "Then component compatibility: the virgin lot must be of
        `lot_kind` `VIRGIN` with a `resin_type` equal to the formulation's
        `base_resin_type`, and the colorant lot must be of `lot_kind` `COLORANT`
        whose `resin_type` equals the formulation's `base_resin_type` and whose
        `color_family` equals the formulation's `color_family`; violations are
        rejected with `ERR_LOT_INCOMPATIBLE`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_blend
        """
        base = plant_base()
        lot_v = qc_passed_lot("VIRGIN", "PVC", "NATURAL", 3000, "SUP-V1")
        lot_v_abs = qc_passed_lot("VIRGIN", "ABS", "NATURAL", 3000, "SUP-V2")
        lot_r_blue = qc_passed_lot("REGRIND", "PVC", "BLUE", 100, "SUP-R2")
        lot_c = qc_passed_lot("COLORANT", "PVC", "RED", 100, "SUP-C1")

        # Purity alone (virgin compatible, regrind wrong color).
        purity_only = api.create_blend_batch(
            {"formulation_id": base["form"]["id"], "virgin_lot_id": lot_v["id"],
             "regrind_lot_id": lot_r_blue["id"], "colorant_lot_id": lot_c["id"],
             "target_batch_kg": 1000}, LO)
        validate_error(purity_only, ApiErrorId.ERR_REGRIND_PURITY_VIOLATION)

        # Compatibility alone (virgin wrong resin family, no regrind supplied).
        compat_only = api.create_blend_batch(
            {"formulation_id": base["form"]["id"], "virgin_lot_id": lot_v_abs["id"],
             "colorant_lot_id": lot_c["id"], "target_batch_kg": 1000}, LO)
        validate_error(compat_only, ApiErrorId.ERR_LOT_INCOMPATIBLE)


class TestMassBalanceQuarantine:
    def test_quarantine_credits_back_and_rerelease_redraws(self, api):
        """PRD §3.3: "Against a `BLENDED` or `QC_RELEASED` batch — whether
        invoked by an inspector or fired by the system during a lot `REVERSE` —
        it captures the current status in `pre_quarantine_status`, credits the
        drawn kilograms back to the virgin, regrind, and colorant lots, and moves
        the batch to `QUARANTINED`."
        PRD §3.3: "A batch quarantined from `BLENDED` or `QC_RELEASED` returns
        to that captured status, its `pre_quarantine_status` is cleared, and its
        draws are re-applied to the component lots; a batch quarantined from
        `CONSUMED` returns straight to `CONSUMED` with no lot re-draw."

        Design: Difficulty/compensating_invariant/mass_balance_quarantine_rerelease
        """
        scene = material_scene(release=False)
        batch, lot_v, lot_r, lot_c = scene["batch"], scene["lot_v"], scene["lot_r"], scene["lot_c"]
        assert get_lot(lot_v["id"])["consumed_kg"] == pytest.approx(861.5, abs=0.001)
        assert get_lot(lot_r["id"])["consumed_kg"] == pytest.approx(100.0, abs=0.001)
        assert get_lot(lot_c["id"])["consumed_kg"] == pytest.approx(38.5, abs=0.001)

        insp1 = make_quality_inspector_headers("insp-1")
        insp2 = make_quality_inspector_headers("insp-2")
        quarantined = validate_success(
            api.qc_blend_batch(batch["id"], {"action": "QUARANTINE"}, insp1), 200)
        assert quarantined["status"] == "QUARANTINED"
        assert quarantined["pre_quarantine_status"] == "BLENDED"
        for lot in (lot_v, lot_r, lot_c):
            after = get_lot(lot["id"])
            assert after["consumed_kg"] == pytest.approx(0.0, abs=0.001), (
                "Quarantined batch's draws must be credited back")
            assert_mass_balance(after)

        restored = validate_success(
            api.qc_blend_batch(batch["id"], {"action": "RE_RELEASE"}, insp2), 200)
        assert restored["status"] == "BLENDED", "pre_quarantine_status BLENDED must be restored"
        assert restored.get("pre_quarantine_status") is None
        assert get_lot(lot_v["id"])["consumed_kg"] == pytest.approx(861.5, abs=0.001)
        assert get_lot(lot_r["id"])["consumed_kg"] == pytest.approx(100.0, abs=0.001)
        assert get_lot(lot_c["id"])["consumed_kg"] == pytest.approx(38.5, abs=0.001)

    def test_rerelease_by_same_inspector_violates_sod(self, api):
        """PRD §3.3: "the releasing inspector's `X-User-ID` must differ from the
        batch's `last_qc_user_id`, or the request is rejected with
        `ERR_SOD_VIOLATION`."

        Design: Difficulty/compensating_invariant/mass_balance_quarantine_rerelease
        """
        scene = material_scene(release=False)
        batch, lot_v = scene["batch"], scene["lot_v"]
        insp1 = make_quality_inspector_headers("insp-1")
        insp2 = make_quality_inspector_headers("insp-2")
        validate_success(api.qc_blend_batch(batch["id"], {"action": "QUARANTINE"}, insp1), 200)

        same = api.qc_blend_batch(batch["id"], {"action": "RE_RELEASE"}, insp1)
        validate_error(same, ApiErrorId.ERR_SOD_VIOLATION)
        assert get_batch(batch["id"])["status"] == "QUARANTINED"
        assert get_lot(lot_v["id"])["consumed_kg"] == pytest.approx(0.0, abs=0.001), (
            "A rejected re-release must not re-apply draws")

        ok = api.qc_blend_batch(batch["id"], {"action": "RE_RELEASE"}, insp2)
        assert validate_success(ok, 200)["status"] == "BLENDED"
        assert get_lot(lot_v["id"])["consumed_kg"] == pytest.approx(861.5, abs=0.001)
