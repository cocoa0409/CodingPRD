"""Dose, vial, and JW-waste arithmetic (PRD §2.7, §3.1, §3.7).

Queue A: dual_variant_calc, combinatorial_formula, boundary (JW waste).
Queue B: calculations section (calendar, JW true), patient BSA creation/recompute.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    assert_dose_waste_invariants,
    factories as f,
    fixtures as fx,
)
from test_helpers.test_users import TEST_USERS

PHARM = TEST_USERS["pharmacist_headers"]

# BSA item: dose_per_m2=175, vial 50 (no flat_dose_mg)
BSA_ITEM = dict(drug_name="DrugB", role="CHEMO", dosing_method="BSA",
                dose_per_m2=175, vial_size_mg=50, flat_dose_mg=None,
                day_offset=1, sequence_index=1)
# AUC item: target_auc=5, vial 150
AUC_ITEM = dict(drug_name="DrugA", role="CHEMO", dosing_method="AUC",
                target_auc=5, vial_size_mg=150, flat_dose_mg=None,
                day_offset=1, sequence_index=2)


def _make_item(env_protocol_id, **item):
    return fx.add_order_set_item(env_protocol_id, **item)


class TestDualVariantDose:
    def test_bsa_and_auc_methods_yield_different_ordered_doses(self):
        """PRD §3.7: "For a `BSA` item, the base is the item's `dose_per_m2`
        multiplied by the cycle's frozen `bsa_snapshot_m2`."
        PRD §3.7: "For an `AUC` item, the base follows the Calvert renal formula:
        the item's `target_auc` multiplied by the quantity formed by taking the
        smaller of the cycle's frozen `gfr_snapshot_ml_min` and 125, then adding 25"

        BSA (175*1.82=318.5 -> 319) vs AUC (5*(80+25)=525) on the same create
        endpoint give different ordered_dose_mg keyed on different snapshots.

        Design: Difficulty/dual_variant_calc/dual_variant_bsa_vs_auc_ordered_dose
        """
        env = fx.setup_active_cycle_two_items(
            bsa_item=dict(BSA_ITEM), auc_item=dict(AUC_ITEM),
            patient_overrides=dict(height_cm=170, weight_kg=70, gfr_ml_min=80),
            protocol_overrides=dict(total_cycles=2),
        )
        cyc = env["cycle"]["id"]
        do_bsa = validate_success(api_client.create_drug_order(
            f.create_drug_order_payload(cyc, env["item_a"]["id"]), PHARM), 201)
        do_auc = validate_success(api_client.create_drug_order(
            f.create_drug_order_payload(cyc, env["item_b"]["id"]), PHARM), 201)
        assert do_bsa["ordered_dose_mg"] == 319, f"BSA dose expected 319, got {do_bsa['ordered_dose_mg']}"
        assert do_auc["ordered_dose_mg"] == 525, f"AUC dose expected 525, got {do_auc['ordered_dose_mg']}"
        assert do_bsa["ordered_dose_mg"] != do_auc["ordered_dose_mg"]

    def test_dose_uses_frozen_snapshot_not_live_patient_bsa(self):
        """PRD §2.7: "every dose computed for that cycle reads those snapshots,
        so that later edits to the patient's height, weight, or renal function
        never retroactively change an active cycle's doses."
        PRD §3.1: "whenever height or weight changes, `bsa_m2` is recomputed by
        the same Mosteller rule"

        After activation freezes bsa_snapshot=1.82, a PATCH lifts live bsa to 2.0,
        but a post-PATCH order still doses off the frozen 1.82 -> 319 mg.

        Design: Difficulty/dual_variant_calc/dual_variant_frozen_snapshot_vs_live_patient_bsa
        """
        env = fx.setup_active_cycle(
            patient_overrides=dict(height_cm=170, weight_kg=70, gfr_ml_min=80),
            item_overrides=dict(BSA_ITEM),
        )
        patched = validate_success(api_client.update_patient(
            env["patient"]["id"], {"height_cm": 180, "weight_kg": 80}, PHARM), 200)
        assert patched["bsa_m2"] == 2.0, f"live bsa expected 2.0, got {patched['bsa_m2']}"
        order = validate_success(api_client.create_drug_order(
            f.create_drug_order_payload(env["cycle"]["id"], env["item"]["id"]), PHARM), 201)
        assert order["ordered_dose_mg"] == 319, (
            f"order should dose off frozen 1.82 -> 319, got {order['ordered_dose_mg']}")


class TestCombinatorialFormula:
    def test_reduction_applied_before_rounding_on_auc_base(self):
        """PRD §3.7: "The reduction is then applied to this unrounded base: the
        reduced dose is the base multiplied by the quantity one minus
        `dose_reduction_pct` divided by 100. The `ordered_dose_mg` is that reduced
        figure rounded half-up to a whole number of milligrams."

        AUC base 5*(80+25)=525; 20% reduction on the unrounded base -> 420;
        420/150 -> 3 vials, supplied 450, waste 30.

        Design: Difficulty/combinatorial_formula/combinatorial_dose_reduction_then_round_order_fixed
        """
        env = fx.setup_active_cycle(
            patient_overrides=dict(gfr_ml_min=80),
            item_overrides=dict(AUC_ITEM),
        )
        order = validate_success(api_client.create_drug_order(
            f.create_drug_order_payload(env["cycle"]["id"], env["item"]["id"],
                                        dose_reduction_pct=20), PHARM), 201)
        assert order["ordered_dose_mg"] == 420, f"expected 420, got {order['ordered_dose_mg']}"
        assert order["vials_drawn"] == 3, f"expected 3 vials, got {order['vials_drawn']}"
        assert order["waste_mg"] == 30, f"expected waste 30, got {order['waste_mg']}"
        assert_dose_waste_invariants(order)

    def test_calvert_gfr_capped_at_125(self):
        """PRD §3.7: "the item's `target_auc` multiplied by the quantity formed by
        taking the smaller of the cycle's frozen `gfr_snapshot_ml_min` and 125,
        then adding 25 — the glomerular filtration rate is capped at 125 before
        the addition"

        gfr_snapshot=140 clamps to 125 -> 5*(125+25)=750, NOT 5*(140+25)=825.

        Design: Difficulty/combinatorial_formula/combinatorial_auc_calvert_min_cap_nonlinear
        """
        env = fx.setup_active_cycle(
            patient_overrides=dict(gfr_ml_min=140),
            item_overrides=dict(AUC_ITEM),
        )
        order = validate_success(api_client.create_drug_order(
            f.create_drug_order_payload(env["cycle"]["id"], env["item"]["id"]), PHARM), 201)
        assert order["ordered_dose_mg"] == 750, f"expected capped 750, got {order['ordered_dose_mg']}"
        assert order["waste_mg"] == 0, f"expected waste 0, got {order['waste_mg']}"
        assert order["jw_modifier"] is False


class TestJwWasteBoundary:
    def test_zero_waste_clears_jw_modifier(self):
        """PRD §3.7: "The `jw_modifier` flag is true exactly when `waste_mg` is
        greater than zero, marking the discarded single-use-vial drug as
        JW-billable."

        FLAT 600 mg / 150 mg vials fills exactly 4 vials (supplied 600), so
        waste_mg==0 and jw_modifier==false.

        Design: Difficulty/boundary_precision_check/boundary_jw_waste_zero_no_modifier
        """
        env = fx.setup_active_cycle(
            item_overrides=dict(drug_name="DrugC", role="CHEMO", dosing_method="FLAT",
                                flat_dose_mg=600, vial_size_mg=150, day_offset=1, sequence_index=1),
        )
        order = validate_success(api_client.create_drug_order(
            f.create_drug_order_payload(env["cycle"]["id"], env["item"]["id"]), PHARM), 201)
        assert order["ordered_dose_mg"] == 600
        assert order["vials_drawn"] == 4, f"expected 4 vials, got {order['vials_drawn']}"
        assert order["waste_mg"] == 0
        assert order["jw_modifier"] is False
        assert_dose_waste_invariants(order)

    def test_positive_waste_sets_jw_modifier(self):
        """PRD §3.7: "The `jw_modifier` flag is true exactly when `waste_mg` is
        greater than zero, marking the discarded single-use-vial drug as
        JW-billable."

        FLAT 700 mg / 300 mg vials draws 3 vials (supplied 900), waste 200>0
        so jw_modifier==true.

        Design: Corner/calculations/jw_modifier_true_on_positive_waste
        """
        env = fx.setup_active_cycle(
            item_overrides=dict(drug_name="DrugC", role="CHEMO", dosing_method="FLAT",
                                flat_dose_mg=700, vial_size_mg=300, day_offset=1, sequence_index=1),
        )
        order = validate_success(api_client.create_drug_order(
            f.create_drug_order_payload(env["cycle"]["id"], env["item"]["id"]), PHARM), 201)
        assert order["vials_drawn"] == 3, f"expected 3 vials, got {order['vials_drawn']}"
        assert order["supplied_mg"] == 900
        assert order["waste_mg"] == 200
        assert order["jw_modifier"] is True
        assert_dose_waste_invariants(order)


class TestPatientBsa:
    def test_create_patient_computes_mosteller_bsa(self):
        """PRD §3.1: "the system immediately computes the Mosteller
        body-surface-area value `bsa_m2`: take the height in centimeters times the
        weight in kilograms, divide that product by 3600, take the square root,
        and round half-up to two decimal places."

        160*60/3600 = 2.6667, sqrt = 1.6330 -> 1.63; status ACTIVE on registration.

        Design: Corner/entities/create_patient_computes_bsa_and_returns_envelope
        """
        data = validate_success(api_client.create_patient(
            f.create_patient_payload(mrn="C1-uniq", full_name="Corner One",
                                     height_cm=160, weight_kg=60, gfr_ml_min=90), PHARM), 201)
        assert data["bsa_m2"] == 1.63, f"expected bsa 1.63, got {data['bsa_m2']}"
        assert data["status"] == "ACTIVE"
        assert data["version"] == 1

    def test_patch_recomputes_bsa_server_side(self):
        """PRD §3.1: "A pharmacist may update any of `height_cm`, `weight_kg`, or
        `gfr_ml_min`; whenever height or weight changes, `bsa_m2` is recomputed by
        the same Mosteller rule, and the patient's `version` increments."

        PATCH 180/80 recomputes bsa to 2.0 and bumps version to 2.

        Design: Corner/entities/patient_bsa_recomputed_on_patch_input_ignored
        """
        patient = fx.create_patient(height_cm=170, weight_kg=70, gfr_ml_min=80)
        patched = validate_success(api_client.update_patient(
            patient["id"], {"height_cm": 180, "weight_kg": 80}, PHARM), 200)
        assert patched["bsa_m2"] == 2.0, f"expected bsa 2.0, got {patched['bsa_m2']}"
        assert patched["version"] == 2, f"expected version 2, got {patched['version']}"


class TestCalendarProjection:
    def test_calendar_projects_cycle_day_offsets_to_dates(self):
        """PRD §3.6: "the scheduled date for cycle number n and an item with day
        offset d is the start date advanced by the quantity (n minus 1) times the
        cycle length, plus (d minus 1), days. For a start date of 2026-07-01, a
        cycle length of 21 days, an item with day offset 8, and cycle number 2,
        this is 2026-07-01 advanced by 21 plus 7, that is 28, days, giving
        2026-07-29."

        Design: Corner/calculations/calendar_projection_cycle2_day8_date
        """
        patient = fx.create_patient()
        protocol = fx.create_protocol(cycle_length_days=21, total_cycles=2)
        item = fx.add_order_set_item(protocol["id"], drug_name="DrugC", role="CHEMO",
                                     dosing_method="FLAT", flat_dose_mg=600,
                                     vial_size_mg=150, day_offset=8, sequence_index=1)
        fx.publish_protocol(protocol["id"])
        cycle = fx.create_cycle(patient["id"], protocol["id"],
                                treatment_start_date="2026-07-01")
        fx.activate_cycle(cycle["id"])
        rows = validate_success(api_client.get_treatment_cycle_calendar(cycle["id"], PHARM), 200)

        def find(cycle_number):
            for r in rows:
                if r["cycle_number"] == cycle_number and r["order_set_item_id"] == item["id"]:
                    return r
            raise AssertionError(f"no calendar row for cycle {cycle_number} item {item['id']}")

        assert find(2)["scheduled_date"] == "2026-07-29", find(2)
        assert find(1)["scheduled_date"] == "2026-07-08", find(1)
