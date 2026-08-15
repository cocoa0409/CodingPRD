"""Renal panel computation and renal dose adjustment (PRD §3.2, §3.4)."""
import pytest

from test_helpers import (
    assert_medication_order,
    assert_patient_profile,
    create_drug,
    create_patient,
    fixtures,
    make_pharmacist_headers,
    place_order,
    validate_success,
)


class TestPatientComputedRenalPanel:
    def test_patient_create_computes_renal_panel_values(self, api, admin_headers):
        """PRD §3.2: "The computed panel comprises six values. `age_years` is the whole-year floor between `date_of_birth` and the logical clock, with the birthday counting on the date itself. `bmi` is `weight_kg` divided by the square of `height_cm` expressed in meters, rounded half-up to 2 decimal places. `ibw_kg` is the ideal body weight: for a male, 50 plus 2.3 times the number of inches by which the patient's height exceeds 60 inches (height in inches being `height_cm` divided by 2.54); for a female, 45.5 plus the same 2.3-per-inch term; rounded half-up to 2 decimal places."
        PRD §3.2: "`crcl_ibw_ml_min` is the Cockcroft-Gault creatinine clearance computed with `ibw_kg`, and `crcl_abw_ml_min` the same computation with `abw_kg`, each rounded half-up to 2 decimal places, with `crcl_abw_ml_min` null whenever `bmi` is below 30."

        Design: Corner/entities/patient_create_computed_renal_fields
        """
        patient = validate_success(
            api.create_patient(
                {
                    "full_name": "Comp Pat",
                    "date_of_birth": "1986-08-01T00:00:00Z",
                    "sex": "M",
                    "height_cm": 180.0,
                    "weight_kg": 90.0,
                    "scr_mg_dl": 1.0,
                },
                admin_headers,
            ),
            201,
        )
        assert_patient_profile(patient)
        assert patient["age_years"] == 40
        assert patient["ibw_kg"] == pytest.approx(74.99, abs=0.005)
        assert patient["bmi"] == pytest.approx(27.78, abs=0.005)
        assert patient["crcl_ibw_ml_min"] == pytest.approx(104.15, abs=0.005)

    def test_patient_abw_null_when_bmi_below_30(self, api, admin_headers):
        """PRD §3.2: "`abw_kg` is the adjusted body weight — `ibw_kg` plus 0.4 times the excess of `weight_kg` over `ibw_kg`, at 2 decimal places — and is null whenever `bmi` is below 30."
        PRD §3.2: "`crcl_ibw_ml_min` is the Cockcroft-Gault creatinine clearance computed with `ibw_kg`, and `crcl_abw_ml_min` the same computation with `abw_kg`, each rounded half-up to 2 decimal places, with `crcl_abw_ml_min` null whenever `bmi` is below 30."

        Design: Corner/entities/patient_create_computed_renal_fields
        """
        patient = validate_success(
            api.create_patient(
                {
                    "full_name": "Comp Pat",
                    "date_of_birth": "1986-08-01T00:00:00Z",
                    "sex": "M",
                    "height_cm": 180.0,
                    "weight_kg": 90.0,
                    "scr_mg_dl": 1.0,
                },
                admin_headers,
            ),
            201,
        )
        assert patient["bmi"] == pytest.approx(27.78, abs=0.005)
        assert patient["bmi"] < 30
        assert patient.get("abw_kg") is None
        assert patient.get("crcl_abw_ml_min") is None


class TestRenalDosingPolicyDivergence:
    def _setup_obese_patient_two_drugs(self):
        prescriber, _ = fixtures.make_prescriber()
        pharmacist, _ = fixtures.make_pharmacist()
        patient = create_patient(
            full_name="Obese Pat",
            date_of_birth="1956-08-01T00:00:00Z",
            sex="M",
            height_cm=175.0,
            weight_kg=100.0,
            scr_mg_dl=1.5,
        )
        drug_ibw = create_drug(name="DrugA IBW", renal_dosing_policy="IBW")
        drug_abw = create_drug(name="DrugB ABW", renal_dosing_policy="ABW_WHEN_OBESE")
        order_a = place_order(patient, drug_ibw, prescriber, route="PO",
                              ordered_dose_mg=1000.0, frequency_per_day=2)
        order_b = place_order(patient, drug_abw, prescriber, route="PO",
                              ordered_dose_mg=1000.0, frequency_per_day=2)
        order_a = fixtures.verify_order(order_a["id"], pharmacist)
        order_b = fixtures.verify_order(order_b["id"], pharmacist)
        return patient, order_a, order_b

    def test_ibw_policy_uses_ideal_weight_regardless_of_bmi(self, api):
        """PRD §3.4: "Under the `IBW` policy the ideal body weight is used regardless of BMI — this is the `IBW`-variant behavior, in which identical inputs always yield the ideal-weight clearance."
        PRD §3.4: "The dose factor tiers off that rounded clearance: a clearance of at least 50 maps to a factor of 1.00; at least 30 but below 50 maps to 0.75; at least 10 but below 30 maps to 0.50; and below 10 maps to 0.25. The `renal_adjusted_dose_mg` is the `ordered_dose_mg` times the tier factor, rounded half-up to 2 decimal places."

        Design: Difficulty/dual_variant_calc/renal_dosing_ibw_vs_abw_divergence
        """
        patient, order_a, _ = self._setup_obese_patient_two_drugs()
        assert patient["bmi"] >= 30  # obese: 32.65
        assert_medication_order(order_a)
        # IBW 70.46 -> CrCl 45.67 -> 0.75 tier -> 750.0 mg -> 75.0 mL at 10 mg/mL
        assert order_a["crcl_used_ml_min"] == pytest.approx(45.67, abs=0.005)
        assert order_a["renal_adjusted_dose_mg"] == pytest.approx(750.0, abs=0.005)
        assert order_a["final_dose_ml"] == pytest.approx(75.0, abs=0.005)

    def test_abw_when_obese_policy_yields_higher_clearance(self, api):
        """PRD §3.4: "Under the `ABW_WHEN_OBESE` policy the choice turns on obesity: when `bmi` is at least 30, the weight used is the adjusted body weight — ideal plus 0.4 times the excess of actual over ideal, itself at 2 decimal places — and otherwise the actual `weight_kg` is used; for an obese patient the adjusted weight is higher than the ideal, so identical inputs yield a higher creatinine clearance and potentially a higher tier than the `IBW` policy would."

        Design: Difficulty/dual_variant_calc/renal_dosing_ibw_vs_abw_divergence
        """
        _, order_a, order_b = self._setup_obese_patient_two_drugs()
        assert_medication_order(order_b)
        # ABW 82.28 -> CrCl 53.33 -> 1.00 tier -> 1000.0 mg -> 100.0 mL
        assert order_b["crcl_used_ml_min"] == pytest.approx(53.33, abs=0.005)
        assert order_b["renal_adjusted_dose_mg"] == pytest.approx(1000.0, abs=0.005)
        assert order_b["final_dose_ml"] == pytest.approx(100.0, abs=0.005)
        assert order_b["renal_adjusted_dose_mg"] != order_a["renal_adjusted_dose_mg"]


class TestCrclTierBoundary:
    def _setup_boundary_patient_order(self):
        prescriber, _ = fixtures.make_prescriber()
        pharmacist, _ = fixtures.make_pharmacist()
        patient = create_patient(
            full_name="Pat Boundary",
            date_of_birth="1958-08-01T00:00:00Z",
            sex="M",
            height_cm=156.82,
            weight_kg=54.0,
            scr_mg_dl=1.8,
        )
        drug = create_drug(name="DrugBnd", renal_dosing_policy="IBW")
        order = place_order(patient, drug, prescriber, route="PO",
                            ordered_dose_mg=800.0)
        order = fixtures.verify_order(order["id"], pharmacist)
        return patient, order

    def test_crcl_rounds_to_exactly_30(self, api, admin_headers):
        """PRD §3.4: "Creatinine clearance is then 140 minus age, times the chosen weight, times 0.85 for a female patient or 1.0 for a male, divided by 72 times `scr_mg_dl`, rounded half-up to 2 decimal places; the rounded value is stored on the order as `crcl_used_ml_min`."

        Design: Difficulty/boundary_precision_check/crcl_exactly_30_inclusive_band
        """
        patient, order = self._setup_boundary_patient_order()
        fetched = validate_success(api.get_patient(patient["id"], admin_headers), 200)
        assert fetched["age_years"] == 68
        assert fetched["ibw_kg"] == pytest.approx(54.0, abs=0.005)
        # (140-68) * 54.00 / (72 * 1.8) == 30.00 exactly
        assert order["crcl_used_ml_min"] == pytest.approx(30.0, abs=0.005)

    def test_crcl_30_uses_inclusive_mid_tier(self, api):
        """PRD §3.4: "The dose factor tiers off that rounded clearance: a clearance of at least 50 maps to a factor of 1.00; at least 30 but below 50 maps to 0.75; at least 10 but below 30 maps to 0.50; and below 10 maps to 0.25. The `renal_adjusted_dose_mg` is the `ordered_dose_mg` times the tier factor, rounded half-up to 2 decimal places."

        Design: Difficulty/boundary_precision_check/crcl_exactly_30_inclusive_band
        """
        _, order = self._setup_boundary_patient_order()
        # "at least 30" is inclusive: 30.00 -> 0.75 tier -> 800 * 0.75 == 600.0 mg
        assert order["renal_adjusted_dose_mg"] == pytest.approx(600.0, abs=0.005)
        assert order["final_dose_ml"] == pytest.approx(60.0, abs=0.005)
