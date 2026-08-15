"""Treatment-cycle execution, provisional vs final retention computation,
preservative gating at cycle start, and assay immutability
(PRD §2.4, §3.3, §3.6, §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_assay,
    create_assay_payload,
    create_cycle_payload,
    expected_final_retention_uniform,
    expected_provisional_retention,
    get_charge,
    get_cylinder,
    list_pieces,
    load_charge,
    piece_volume_cuft,
    record_assay_for_outcome,
    run_cycle_to_complete,
    setup_cycle_complete_charge,
    setup_shop,
    validate_error,
    validate_success,
)

OP = TEST_USERS["plant_operator_headers"]
LAB = TEST_USERS["lab_technician_headers"]

DOUG_FIR_PAIR = [
    {"piece_tag": "P-001", "length_ft": 16.0, "width_in": 5.5, "thickness_in": 1.5},
    {"piece_tag": "P-002", "length_ft": 16.0, "width_in": 5.5, "thickness_in": 1.5},
]
THREE_SYP_PIECES = [
    {"piece_tag": "R-1", "length_ft": 8.0, "width_in": 3.5, "thickness_in": 1.5},
    {"piece_tag": "R-2", "length_ft": 12.0, "width_in": 7.25, "thickness_in": 1.5},
    {"piece_tag": "R-3", "length_ft": 16.0, "width_in": 9.25, "thickness_in": 1.5},
]


def _load_doug_fir_with_one_incised(api, shop):
    """Load a DOUGLAS_FIR UC4B charge of two identical pieces and incise only
    the first piece while the charge is IN_CYLINDER (PRD §3.8 window)."""
    plant_id, cyl_id = shop["plant"]["id"], shop["cylinder"]["id"]
    charge = load_charge(
        plant_id, cyl_id, species_group="DOUGLAS_FIR", use_category="UC4B",
        volume_mbf=20.0, piece_manifest=[dict(p) for p in DOUG_FIR_PAIR],
    )
    first_piece = list_pieces(plant_id, charge["id"])[0]
    validate_success(api.incise_piece(plant_id, charge["id"], first_piece["id"], OP))
    return charge


class TestCycleCompletionCascade:
    def test_cycle_complete_side_effects_cascade_to_charge(self, api):
        """PRD §3.6: "the operator supplies the measured
        `gross_absorption_pcf` — solution uptake per cubic foot of wood — and
        completion moves the cycle to `COMPLETE`, the cylinder to
        `NEEDS_CLEANING` (where it must be cleaned before accepting another
        load), and the parent charge to `CYCLE_COMPLETE`."
        PRD §3.6: "the cycle's `gross_absorption_pcf` is multiplied by the
        working-solution strength expressed as a fraction —
        `solution_assay_at_start_pct` divided by one hundred — and by the
        species penetration factor, piece by piece."

        Design: Corner/state_machines/cycle_complete_side_effects_cascade_to_charge
        """
        shop = setup_shop()  # preservative assay 6.0
        plant_id, cyl_id = shop["plant"]["id"], shop["cylinder"]["id"]
        charge = load_charge(plant_id, cyl_id, volume_mbf=5.0)
        cycle = run_cycle_to_complete(
            plant_id, cyl_id, shop["preservative"]["id"], gross_absorption_pcf=0.85)

        assert cycle["status"] == "COMPLETE"
        assert get_cylinder(plant_id, cyl_id)["status"] == "NEEDS_CLEANING"
        after = get_charge(plant_id, charge["id"])
        assert after["status"] == "CYCLE_COMPLETE"
        # Single SYP piece: 0.85 * (6.0/100) * 0.92 = 0.04692 -> 0.047.
        assert after["provisional_retention_pcf"] == pytest.approx(0.047, abs=1e-9)

    def test_provisional_retention_constants_applied(self, api):
        """PRD §3.6: "The factor is 0.85 for `SPF`, 0.92 for `SYP`, 0.65 for
        `DOUGLAS_FIR`, 0.72 for `HEM_FIR`, and 0.78 for `PONDEROSA_PINE`".
        PRD §3.6: "The charge-level provisional figure is the average of the
        per-piece contributions, and the rounding to three decimal places,
        half-up, happens only after all multiplications are complete."

        Design: Corner/calculations/provisional_retention_constants_applied
        """
        # Preservative assay exactly 5.0; gross absorption 1.0; single SYP piece.
        shop = setup_shop(concentrate_assay_pct=5.0, min_working_assay_pct=5.0)
        charge, _cycle = setup_cycle_complete_charge(shop, gross_absorption_pcf=1.0)
        # 1.0 * (5.0/100) * 0.92 = 0.046 exactly.
        assert charge["provisional_retention_pcf"] == pytest.approx(0.046, abs=1e-9)


class TestProvisionalVsFinalDivergence:
    def test_incised_doug_fir_provisional_diverges_from_final(self, api):
        """PRD §3.6: "where the charge's `requires_incising` is true and the
        individual piece's `incised` flag is true, the higher incised factor
        applies to that piece's contribution instead — 0.95 for `DOUGLAS_FIR`
        and 0.93 for `HEM_FIR`."
        PRD §3.7: "Either way the charge's `final_retention_pcf` is fixed. It
        is anchored to the assay's `mean_retention_pcf`, but the stored
        charge-level value is recomputed as a volume-weighted mean across the
        charge's pieces".

        Design: Difficulty/dual_variant_calc/retention_provisional_vs_final_diverge_on_doug_fir_incised
        """
        shop = setup_shop()  # CCA assay 6.0
        plant_id, cyl_id = shop["plant"]["id"], shop["cylinder"]["id"]
        charge = _load_doug_fir_with_one_incised(api, shop)
        cycle = run_cycle_to_complete(
            plant_id, cyl_id, shop["preservative"]["id"], gross_absorption_pcf=1.0)

        after_cycle = get_charge(plant_id, charge["id"])
        # Provisional (forward-looking): average of per-piece contributions
        # 1.0 * 0.06 * 0.95 (incised) and 1.0 * 0.06 * 0.65 (base) -> 0.048.
        assert after_cycle["provisional_retention_pcf"] == pytest.approx(0.048, abs=1e-9)

        # Final (chronological): anchored to the recorded mean, which we drive
        # to a FAIL_GROSS value far from the provisional figure.
        assay = record_assay_for_outcome(plant_id, charge["id"], cycle["id"], "FAIL_GROSS")
        assert assay["outcome"] == "FAIL_GROSS"
        final = get_charge(plant_id, charge["id"])
        assert final["status"] == "ASSAYED_FAIL"
        assert final["final_retention_pcf"] != pytest.approx(
            final["provisional_retention_pcf"], abs=1e-9)
        assert final["final_retention_pcf"] == pytest.approx(
            assay["mean_retention_pcf"], abs=0.001)

    def test_incising_raises_provisional_retention(self, api):
        """PRD §3.6: "where the charge's `requires_incising` is true and the
        individual piece's `incised` flag is true, the higher incised factor
        applies to that piece's contribution instead — 0.95 for `DOUGLAS_FIR`
        and 0.93 for `HEM_FIR`."

        Design: Difficulty/dual_variant_calc/retention_provisional_vs_final_diverge_on_doug_fir_incised
        """
        # Identical charge twice: one piece incised vs none incised.
        shop_incised = setup_shop()
        charge_incised = _load_doug_fir_with_one_incised(api, shop_incised)
        run_cycle_to_complete(
            shop_incised["plant"]["id"], shop_incised["cylinder"]["id"],
            shop_incised["preservative"]["id"], gross_absorption_pcf=1.0)
        prov_incised = get_charge(
            shop_incised["plant"]["id"], charge_incised["id"])["provisional_retention_pcf"]

        shop_plain = setup_shop()
        charge_plain = load_charge(
            shop_plain["plant"]["id"], shop_plain["cylinder"]["id"],
            species_group="DOUGLAS_FIR", use_category="UC4B", volume_mbf=20.0,
            piece_manifest=[dict(p) for p in DOUG_FIR_PAIR],
        )
        run_cycle_to_complete(
            shop_plain["plant"]["id"], shop_plain["cylinder"]["id"],
            shop_plain["preservative"]["id"], gross_absorption_pcf=1.0)
        prov_plain = get_charge(
            shop_plain["plant"]["id"], charge_plain["id"])["provisional_retention_pcf"]

        # One piece incised: (0.95 + 0.65) / 2 * 0.06 = 0.048.
        assert prov_incised == pytest.approx(0.048, abs=1e-9)
        # None incised: 0.65 * 0.06 = 0.039.
        assert prov_plain == pytest.approx(0.039, abs=1e-9)
        assert prov_incised > prov_plain


class TestFinalRetentionRoundingOrder:
    def test_final_retention_per_piece_rounding_then_ratio(self, api):
        """PRD §3.7: "each per-piece contribution is rounded to four decimal
        places before the sum is taken, and the final ratio is then rounded
        half-up to three decimal places."
        PRD §3.7: "That rounding order is load-bearing — rounding per piece
        first yields a different figure than summing raw and rounding once".

        Design: Difficulty/combinatorial_formula/provisional_retention_nested_rounding_per_piece_then_charge
        """
        shop = setup_shop(concentrate_assay_pct=7.5, min_working_assay_pct=6.0,
                          chemical_family="ACQ")
        plant_id = shop["plant"]["id"]
        charge, cycle = setup_cycle_complete_charge(
            shop, species_group="SYP", use_category="UC3B", volume_mbf=5.0,
            piece_manifest=[dict(p) for p in THREE_SYP_PIECES],
            gross_absorption_pcf=0.95,
        )
        # Uniform SYP factor: each piece's retention equals the recorded mean.
        # Volumes: 3.5, 10.875, 18.5 cuft.
        # Per-piece r4: 0.9135, 2.8384, 4.8285 -> sum 8.5804 / 32.875 -> 0.261.
        resp = api.record_assay(
            plant_id, charge["id"],
            create_assay_payload(cycle["id"], 0.261, 0.245, assay_method="ASHING",
                                 sample_count=6), LAB)
        assay = validate_success(resp, 201)
        assert_assay(assay)
        final = get_charge(plant_id, charge["id"])
        expected = expected_final_retention_uniform(
            0.261, [piece_volume_cuft(p["length_ft"], p["width_in"], p["thickness_in"])
                    for p in THREE_SYP_PIECES])
        assert expected == pytest.approx(0.261, abs=1e-9)
        assert final["final_retention_pcf"] == pytest.approx(0.261, abs=1e-9)

    def test_provisional_rounds_once_after_multiplications(self, api):
        """PRD §3.6: "The charge-level provisional figure is the average of
        the per-piece contributions, and the rounding to three decimal places,
        half-up, happens only after all multiplications are complete."

        Design: Difficulty/combinatorial_formula/provisional_retention_nested_rounding_per_piece_then_charge
        """
        # Assay 8.0%, gross 0.9, three SYP pieces: 0.9 * 0.08 * 0.92 = 0.06624
        # per piece; average 0.06624; rounded half-up to 3 decimals -> 0.066.
        shop = setup_shop(concentrate_assay_pct=8.0, min_working_assay_pct=5.0)
        charge, _cycle = setup_cycle_complete_charge(
            shop, species_group="SYP", use_category="UC3B", volume_mbf=5.0,
            piece_manifest=[dict(p) for p in THREE_SYP_PIECES],
            gross_absorption_pcf=0.9,
        )
        expected = expected_provisional_retention(0.9, 8.0, [0.92, 0.92, 0.92])
        assert expected == pytest.approx(0.066, abs=1e-9)
        assert charge["provisional_retention_pcf"] == pytest.approx(0.066, abs=1e-9)


class TestCycleStartPreservativeGate:
    def test_quarantined_preservative_blocks_cycle_start(self, api):
        """PRD §3.3: "any `SCHEDULED` cycle that references the quarantined
        concentrate is blocked when an operator tries to start it, rejected
        with `ERR_PRESERVATIVE_QUARANTINED` (422)."

        Design: Difficulty/cross_entity_state_dependency/cycle_start_gated_by_preservative_status
        """
        shop = setup_shop()
        plant_id, cyl_id = shop["plant"]["id"], shop["cylinder"]["id"]
        pres_id = shop["preservative"]["id"]
        load_charge(plant_id, cyl_id, volume_mbf=5.0)
        cycle = validate_success(
            api.create_cycle(plant_id, cyl_id, create_cycle_payload(pres_id), OP), 201)

        validate_success(
            api.quarantine_preservative(plant_id, pres_id,
                                        {"reason": "Contamination detected"}, LAB))

        resp = api.start_cycle(plant_id, cyl_id, cycle["id"], OP)
        validate_error(resp, ApiErrorId.ERR_PRESERVATIVE_QUARANTINED.value)
        # The cycle and the cylinder remain in their pre-start states.
        assert api.get_cycle(plant_id, cyl_id, cycle["id"], OP).json()["data"]["status"] == "SCHEDULED"
        assert get_cylinder(plant_id, cyl_id)["status"] == "LOADED"

    def test_assay_below_working_minimum_blocks_cycle_start(self, api):
        """PRD §3.6: "the concentrate's `concentrate_assay_pct` must be at
        least its `min_working_assay_pct` — a weaker solution is rejected with
        `ERR_ASSAY_BELOW_WORKING_MINIMUM` (422)."

        Design: Difficulty/cross_entity_state_dependency/cycle_start_gated_by_preservative_status
        """
        shop = setup_shop(concentrate_assay_pct=6.0, min_working_assay_pct=5.0)
        plant_id, cyl_id = shop["plant"]["id"], shop["cylinder"]["id"]
        pres_id = shop["preservative"]["id"]

        # Re-assay below the working minimum: 4.0 < 5.0.
        validate_success(api.assay_preservative(plant_id, pres_id,
                                                {"new_assay_pct": 4.0}, LAB))
        load_charge(plant_id, cyl_id, volume_mbf=5.0)
        cycle = validate_success(
            api.create_cycle(plant_id, cyl_id, create_cycle_payload(pres_id), OP), 201)
        resp = api.start_cycle(plant_id, cyl_id, cycle["id"], OP)
        validate_error(resp, ApiErrorId.ERR_ASSAY_BELOW_WORKING_MINIMUM.value)

        # Re-assay to exactly the minimum: "at least" is inclusive, so a
        # fresh cycle on the same loaded charge may now start.
        validate_success(api.assay_preservative(plant_id, pres_id,
                                                {"new_assay_pct": 5.0}, LAB))
        cycle2 = validate_success(
            api.create_cycle(plant_id, cyl_id, create_cycle_payload(pres_id), OP), 201)
        started = validate_success(api.start_cycle(plant_id, cyl_id, cycle2["id"], OP))
        assert started["status"] == "RUNNING"


class TestRetentionAssayImmutability:
    def test_immutable_retention_assay_no_update_endpoint(self, api):
        """PRD §2.4: "a RetentionAssay, a DripPadLog, and a
        CylinderScheduleSlot each carry only `id` and `created_at`; both
        `updated_at` and `version` are absent from them, and nothing about
        them is mutable after creation."

        Design: Corner/entities/immutable_retention_assay_no_update_endpoint
        """
        shop = setup_shop()
        plant_id = shop["plant"]["id"]
        charge, cycle = setup_cycle_complete_charge(shop)
        assay = record_assay_for_outcome(plant_id, charge["id"], cycle["id"], "PASS")

        fetched = validate_success(
            api.get_assay(plant_id, charge["id"], assay["id"], LAB))
        assert_assay(fetched)
        assert "version" not in fetched
        assert "updated_at" not in fetched

        # No update endpoint exists for assays: PRD §4 defines only create
        # and read for /retention-assays.
        resp = api._request(
            "PUT",
            f"/treatment-plants/{plant_id}/charges/{charge['id']}/retention-assays/{assay['id']}",
            {"mean_retention_pcf": 9.9}, LAB)
        assert resp.status_code in (404, 405), (
            f"unexpected status for assay update attempt: {resp.status_code}")
