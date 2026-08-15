"""Batch testing, positive release, rejection compensation, terminal-state
lockdown, and shelf-life computation (PRD §2.7, §3.4)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_active_formula, create_qualified_supplier, create_qc_passed_lot,
    create_planned_batch, advance_batch_to_testing, advance_batch_to_hold,
    create_released_batch_scenario, set_clock,
)

PROTEIN_INFANT_SPEC = [{
    "nutrient_code": "PROTEIN", "unit": "g",
    "min_per_100kcal": 1.80, "max_per_100kcal": 3.50,
    "target_per_100kcal": 2.50,
}]
PROTEIN_TODDLER_SPEC = [{
    "nutrient_code": "PROTEIN", "unit": "g",
    "min_per_100kcal": 1.50, "max_per_100kcal": 3.00,
    "target_per_100kcal": 2.20,
}]
NO_PATHOGEN = [{"pathogen_code": "SALMONELLA", "detected": False, "cfu_per_g": 0}]


def _batch_at_hold(users, profile_code, nutrient_specs, measured,
                   formula_code, batch_size_kg=100.000):
    """ACTIVE formula + QC-passed lots + batch driven to POSITIVE_RELEASE_HOLD
    with the given measured nutrient value. Returns (scenario, hold_batch)."""
    scenario = create_active_formula(
        users, formula_code=formula_code, profile_code=profile_code,
        nutrient_specs=nutrient_specs)
    supplier = create_qualified_supplier(
        users, f"SUP-{formula_code}", ["DAIRY_BASE", "CARBOHYDRATE"])
    create_qc_passed_lot(users, scenario["ing_a"]["id"], supplier["id"],
                         f"{formula_code}-A", quantity_kg=500.000)
    create_qc_passed_lot(users, scenario["ing_b"]["id"], supplier["id"],
                         f"{formula_code}-B", quantity_kg=300.000)
    batch = create_planned_batch(users, scenario["formula"]["id"],
                                 batch_size_kg=batch_size_kg)
    hold = advance_batch_to_hold(
        users, batch["id"],
        [{"nutrient_code": nutrient_specs[0]["nutrient_code"],
          "measured_per_100kcal": measured}],
        NO_PATHOGEN)
    return scenario, hold


class TestNutrientComplianceVariants:
    def test_infant_profile_borderline_variant_fails_at_raw_minimum(self, api, users):
        """PRD §3.4: "For `INF-0-6M`, a stricter borderline variant applies.
        The effective minimum is the spec's `min_per_100kcal` multiplied by
        1.02 — a two-percent upward safety margin — and the effective maximum
        is the spec's `max_per_100kcal` multiplied by 0.98 — a two-percent
        downward safety margin. The measured value passes if and only if it
        lies within the closed interval from the effective minimum to the
        effective maximum." A measured 1.80 against min 1.80 fails the
        effective minimum 1.8360. The batch still enters the hold: "On accepted
        submission the system transitions `TESTING → POSITIVE_RELEASE_HOLD`".

        Design: Difficulty/dual_variant_calc/nutrient_compliance_standard_vs_borderline_infant
        """
        set_clock(users)
        _scenario, hold = _batch_at_hold(
            users, "INF-0-6M", PROTEIN_INFANT_SPEC, 1.80, "IF-START-1")
        assert hold["status"] == "POSITIVE_RELEASE_HOLD"
        result = hold["nutrient_results"][0]
        assert result["nutrient_code"] == "PROTEIN"
        assert result["pass"] is False, (
            "1.80 must fail the borderline_infant effective minimum "
            "1.80 * 1.02 = 1.8360")

    def test_toddler_profile_standard_variant_passes_at_raw_minimum(self, api, users):
        """PRD §3.4: "For any profile other than `INF-0-6M`, the standard
        variant applies. Each measured value passes if and only if it lies
        within the closed interval from that spec's `min_per_100kcal` to its
        `max_per_100kcal`." A measured 1.80 against [1.80, 3.50] lies on the
        closed lower bound and passes. "On accepted submission the system
        transitions `TESTING → POSITIVE_RELEASE_HOLD`".

        Design: Difficulty/dual_variant_calc/nutrient_compliance_standard_vs_borderline_infant
        """
        set_clock(users)
        _scenario, hold = _batch_at_hold(
            users, "TODDLER-12-36M", PROTEIN_TODDLER_SPEC, 1.80, "IF-TODDLER-3")
        assert hold["status"] == "POSITIVE_RELEASE_HOLD"
        result = hold["nutrient_results"][0]
        assert result["nutrient_code"] == "PROTEIN"
        assert result["pass"] is True, (
            "1.80 must pass the standard closed-interval [1.80, 3.00...] check")


class TestReleaseStateGate:
    def test_release_rejected_from_testing(self, api, users):
        """PRD §2.7: "When a state-machine transition is invoked against a
        resource that is not in a state from which that transition is defined,
        the request is rejected with `ERR_INVALID_STATE` (HTTP 409)." Release
        is defined only from `POSITIVE_RELEASE_HOLD` (PRD §3.4: "Release
        transitions `POSITIVE_RELEASE_HOLD → RELEASED`"), not from `TESTING`.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_batch_release
        """
        scenario = create_active_formula(users, formula_code="IF-VAL-1")
        supplier = create_qualified_supplier(
            users, "SUP-VAL", ["DAIRY_BASE", "CARBOHYDRATE"])
        create_qc_passed_lot(users, scenario["ing_a"]["id"], supplier["id"],
                             "LOT-VAL-A", quantity_kg=500.000)
        create_qc_passed_lot(users, scenario["ing_b"]["id"], supplier["id"],
                             "LOT-VAL-B", quantity_kg=300.000)
        batch = create_planned_batch(users, scenario["formula"]["id"])
        testing = advance_batch_to_testing(users, batch["id"])
        assert testing["status"] == "TESTING"
        res = api.release_batch(batch["id"], users["qm"]["headers"])
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_release_rejected_from_planned(self, api, users):
        """PRD §2.7: "When a state-machine transition is invoked against a
        resource that is not in a state from which that transition is defined,
        the request is rejected with `ERR_INVALID_STATE` (HTTP 409)." Release
        is defined only from `POSITIVE_RELEASE_HOLD` (PRD §3.4), not from
        `PLANNED`.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_batch_release
        """
        scenario = create_active_formula(users, formula_code="IF-VAL-2")
        batch = create_planned_batch(users, scenario["formula"]["id"])
        assert batch["status"] == "PLANNED"
        res = api.release_batch(batch["id"], users["qm"]["headers"])
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestTerminalStateLockdown:
    def test_released_batch_cannot_restart_production(self, api, users):
        """PRD §3.4: "`RELEASED`, `REJECTED`, and `RECALLED` are the batch's
        three terminal states." Starting production is defined only from
        `PLANNED` (PRD §3.4: "Starting production — `PLANNED → IN_PRODUCTION`"),
        so invoking it on a RELEASED batch is rejected per PRD §2.7: "When a
        state-machine transition is invoked against a resource that is not in a
        state from which that transition is defined, the request is rejected
        with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/batch_terminal_state_lockdown
        """
        scenario = create_released_batch_scenario(users)
        assert scenario["batch"]["status"] == "RELEASED"
        res = api.start_production(scenario["batch"]["id"], users["ps"]["headers"])
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestRejectCompensation:
    def _rejected_batch_scenario(self, users):
        """Batch at HOLD with a failing nutrient result, ready to reject."""
        scenario = create_active_formula(
            users, formula_code="IF-INV-1", profile_code="TODDLER-12-36M",
            nutrient_specs=PROTEIN_TODDLER_SPEC)
        supplier = create_qualified_supplier(
            users, "SUP-INV", ["DAIRY_BASE", "CARBOHYDRATE"])
        lot_a = create_qc_passed_lot(
            users, scenario["ing_a"]["id"], supplier["id"], "LOT-INV-A",
            quantity_kg=500.000)
        lot_b = create_qc_passed_lot(
            users, scenario["ing_b"]["id"], supplier["id"], "LOT-INV-B",
            quantity_kg=300.000)
        batch = create_planned_batch(
            users, scenario["formula"]["id"], batch_size_kg=200.000)
        hold = advance_batch_to_hold(
            users, batch["id"],
            [{"nutrient_code": "PROTEIN", "measured_per_100kcal": 0.50}],
            NO_PATHOGEN, actual_yield_kg=195.000)
        return scenario, lot_a, lot_b, hold

    def test_reject_restores_consumed_remaining_kg(self, api, users):
        """PRD §3.4: "on rejection the system sets `release_decision` to
        `REJECTED` and restores `remaining_kg` on every lot in the batch's
        `ingredient_consumptions` by the exact `consumed_kg` amounts originally
        recorded, undoing the FIFO consumption in full." The recipe is 60/40,
        so a 200.000 kg batch consumes 120.000 kg of ingredient A and 80.000 kg
        of ingredient B.

        Design: Difficulty/compensating_invariant/batch_reject_restores_ingredient_lot_remaining
        """
        scenario, lot_a, lot_b, hold = self._rejected_batch_scenario(users)
        assert hold["status"] == "POSITIVE_RELEASE_HOLD"

        after_start_a = validate_success(api.get_ingredient_lot(
            lot_a["id"], users["qa"]["headers"]))
        after_start_b = validate_success(api.get_ingredient_lot(
            lot_b["id"], users["qa"]["headers"]))
        assert after_start_a["remaining_kg"] == 500.000 - 120.000
        assert after_start_b["remaining_kg"] == 300.000 - 80.000

        validate_success(api.reject_batch(
            hold["id"],
            {"rejection_reason": "Protein content below minimum specification"},
            users["qm"]["headers"]))
        restored_a = validate_success(api.get_ingredient_lot(
            lot_a["id"], users["qa"]["headers"]))
        restored_b = validate_success(api.get_ingredient_lot(
            lot_b["id"], users["qa"]["headers"]))
        assert restored_a["remaining_kg"] == 500.000, (
            f"Lot A must be restored to 500.000, got {restored_a['remaining_kg']}")
        assert restored_b["remaining_kg"] == 300.000, (
            f"Lot B must be restored to 300.000, got {restored_b['remaining_kg']}")

    def test_rejected_batch_sets_decision_and_status(self, api, users):
        """PRD §3.4: "Rejection transitions `POSITIVE_RELEASE_HOLD → REJECTED`,
        requires a `rejection_reason` in the body, and requires that at least
        one nutrient result has `pass` false or at least one pathogen result
        has `detected` true; on rejection the system sets `release_decision` to
        `REJECTED`". Here the protein result failed (0.50 below the 1.50
        minimum), satisfying the rejection precondition.

        Design: Difficulty/compensating_invariant/batch_reject_restores_ingredient_lot_remaining
        """
        _scenario, _lot_a, _lot_b, hold = self._rejected_batch_scenario(users)
        rejected = validate_success(api.reject_batch(
            hold["id"],
            {"rejection_reason": "Protein content below minimum specification"},
            users["qm"]["headers"]))
        assert rejected["status"] == "REJECTED"
        assert rejected["release_decision"] == "REJECTED"


class TestBatchExpiryComputation:
    def test_dry_blend_infant_formula_gets_27_month_shelf_life(self, api, users):
        """PRD §3.4: "The base shelf-life in calendar months is 24 for
        `INF-0-6M`" and "If `process_type` is `DRY_BLEND`, three additional
        calendar months are added on top of the base. The expiry is
        `production_date` plus that many calendar months." Production date
        2026-08-01 + 27 calendar months = 2028-11-01. On release, "the system
        sets `release_decision` to `RELEASED`, computes the batch's
        `expiry_date`".

        Design: Corner/calculations/batch_expiry_calculation_dry_blend_bonus
        """
        scenario = create_released_batch_scenario(
            users, profile_code="INF-0-6M",
            nutrient_specs=PROTEIN_INFANT_SPEC,
            process_type="DRY_BLEND", production_date="2026-08-01T00:00:00Z")
        batch = scenario["batch"]
        assert batch["status"] == "RELEASED"
        assert batch["release_decision"] == "RELEASED"
        assert batch["expiry_date"] is not None, "expiry_date must be computed on release"
        assert str(batch["expiry_date"]).startswith("2028-11-01"), (
            f"Expected expiry 2028-11-01 (2026-08-01 + 24 + 3 calendar months), "
            f"got {batch['expiry_date']}")
