"""Insured contracted pricing, benefit accumulation, bundling, and GFE contrast."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_estimate,
    create_case,
    create_charge_item,
    create_contract_with_rates,
    create_estimate,
    create_patient,
    create_snapshot,
    price_estimate,
    set_clock,
    setup_gfe_scenario,
    setup_insured_scenario,
    validate_error,
)

COUNSELOR = TEST_USERS["counselor_headers"]


class TestDualVariantPricing:
    """One line set, two pricing algorithms (PRD §3.4)."""

    def _setup_both_modes(self):
        insured = setup_insured_scenario(mrn="MRN-I-1", requires_auth_prior=True)
        # The charge item is shared; only the patient/case/estimate differ.
        gfe = setup_gfe_scenario(mrn="MRN-U-1", cpt_code="27447",
                                 list_price_cents=5000000,
                                 requires_auth_prior=True,
                                 with_charge_item=False)
        return insured, gfe

    def test_insured_variant_computes_contracted_responsibility(self, api):
        """PRD §3.4: "The out-of-pocket cap applies last: the remaining
        out-of-pocket room is `oop_max_cents` minus `oop_met_cents`, floored at
        zero, and `patient_responsibility_cents` is the smaller of the
        deductible-plus-coinsurance total and that remaining room."
        PRD §3.4: "Identical lines priced under the two modes therefore
        legitimately produce different patient responsibilities."

        Design: Difficulty/dual_variant_calc/insured_contract_vs_uninsured_gfe_same_lines
        """
        insured, _gfe = self._setup_both_modes()
        priced = price_estimate(insured["estimate"]["id"])
        assert_estimate(priced)
        assert priced["allowed_amount_cents"] == 3000000
        assert priced["patient_responsibility_cents"] == 500000, (
            "insured variant: 100000 deductible + 580000 coinsurance, "
            "OOP-capped at 500000")

    def test_gfe_variant_produces_different_responsibility_for_same_lines(self, api):
        """PRD §3.4: "In `UNINSURED_GFE` mode the same lines price off the
        charge master instead of a contract ... The patient responsibility
        equals `gfe_total_cents`, `allowed_amount_cents` records the
        undiscounted list subtotal, and `deductible_applied_cents`,
        `coinsurance_cents`, and `insurance_pays_cents` are all zero."
        PRD §3.4: "Identical lines priced under the two modes therefore
        legitimately produce different patient responsibilities."

        Design: Difficulty/dual_variant_calc/insured_contract_vs_uninsured_gfe_same_lines
        """
        insured, gfe = self._setup_both_modes()
        priced_insured = price_estimate(insured["estimate"]["id"])
        priced_gfe = price_estimate(gfe["estimate"]["id"])
        assert priced_gfe["patient_responsibility_cents"] == priced_gfe["gfe_total_cents"]
        assert priced_gfe["allowed_amount_cents"] == 5000000, (
            "GFE allowed_amount_cents records the undiscounted list subtotal")
        assert priced_gfe["deductible_applied_cents"] == 0
        assert priced_gfe["coinsurance_cents"] == 0
        assert priced_gfe["insurance_pays_cents"] == 0
        assert (priced_insured["patient_responsibility_cents"]
                != priced_gfe["patient_responsibility_cents"]), (
            "identical lines under the two pricing modes must produce "
            "different patient responsibilities")


class TestInsuredBenefitAccumulator:
    def test_allowed_deductible_and_coinsurance_components(self, api):
        """PRD §3.4: "For each line in order: the portion sent to deductible is
        the smaller of the line's amount and the remaining deductible; the
        remainder is decremented accordingly; and the line's coinsurance is the
        line amount minus its deductible portion, multiplied by
        `coinsurance_pct` percent, rounded half up to a whole cent per line."

        Design: Difficulty/combinatorial_formula/insured_responsibility_nested_min_max_oop_cap
        """
        ctx = setup_insured_scenario(mrn="MRN-C-1")
        priced = price_estimate(ctx["estimate"]["id"])
        assert priced["allowed_amount_cents"] == 3000000
        assert priced["deductible_applied_cents"] == 100000, (
            "min(3000000, 150000 - 50000)")
        assert priced["coinsurance_cents"] == 580000, "20% of 2900000"

    def test_oop_cap_applies_last_and_caps_responsibility(self, api):
        """PRD §3.4: "The out-of-pocket cap applies last: the remaining
        out-of-pocket room is `oop_max_cents` minus `oop_met_cents`, floored at
        zero, and `patient_responsibility_cents` is the smaller of the
        deductible-plus-coinsurance total and that remaining room."
        PRD §3.4: "`insurance_pays_cents` is the allowed amount minus the
        patient responsibility."

        Design: Difficulty/combinatorial_formula/insured_responsibility_nested_min_max_oop_cap
        """
        ctx = setup_insured_scenario(mrn="MRN-C-2")
        priced = price_estimate(ctx["estimate"]["id"])
        # Raw deductible+coinsurance = 680000; OOP room = 600000-100000 = 500000.
        assert priced["patient_responsibility_cents"] == 500000, (
            "cap branch fires: min(680000, 500000)")
        assert priced["insurance_pays_cents"] == 2500000


class TestBundling:
    def test_mpr_tie_break_ranks_by_cpt_code_not_input_order(self, api):
        """PRD §3.4: "When the rule is `MULTIPLE_PROCEDURE_REDUCTION`, the lines
        are first ranked: highest `unit_rate_cents` first, ties broken by
        `cpt_code` in ascending alphabetical order, remaining ties broken by
        input line order — never by any record id."
        PRD §3.4: "Every lower-ranked line is a secondary procedure whose
        adjusted unit rate is its unit rate times the contract's
        `reduction_pct` percent, rounded half up to a whole cent — this
        rounding happens per line, before the quantity is multiplied in — and
        each line's `line_amount_cents` is then its quantity times its adjusted
        rate."

        Design: Corner/calculations/bundling_mpr_tie_break_by_cpt_and_quantity
        """
        set_clock("2026-08-03T09:00:00Z")
        create_charge_item(cpt_code="90001", list_price_cents=1200000,
                           description="Proc One")
        create_charge_item(cpt_code="90002", list_price_cents=1200000,
                           description="Proc Two")
        create_contract_with_rates(
            bundling_rule="MULTIPLE_PROCEDURE_REDUCTION", reduction_pct=50,
            rates=[{"cpt_code": "90001", "rate_cents": 1000000,
                    "effective_from": "2026-01-01"},
                   {"cpt_code": "90002", "rate_cents": 1000000,
                    "effective_from": "2026-01-01"}])
        patient = create_patient(mrn="MRN-CA-1")
        snapshot = create_snapshot(patient["id"], deductible_total_cents=0,
                                   deductible_met_cents=0, oop_max_cents=5000000,
                                   oop_met_cents=0, coinsurance_pct=0)
        case = create_case(patient["id"])
        estimate = create_estimate(
            case["id"], pricing_mode="INSURED",
            eligibility_snapshot_id=snapshot["id"],
            lines=[{"cpt_code": "90002", "quantity": 3},
                   {"cpt_code": "90001", "quantity": 1}])
        priced = price_estimate(estimate["id"])
        # 90001 (cpt ASC on the rate tie) is primary at 100%; 90002 secondary
        # at 50% per unit before quantity: 1000000 + 3*500000.
        assert priced["allowed_amount_cents"] == 2500000
        lines_by_cpt = {line["cpt_code"]: line for line in priced["lines"]}
        assert lines_by_cpt["90001"]["line_amount_cents"] == 1000000
        assert lines_by_cpt["90002"]["line_amount_cents"] == 1500000
        assert lines_by_cpt["90001"]["unit_rate_cents"] == 1000000
        assert lines_by_cpt["90002"]["unit_rate_cents"] == 1000000

    def test_bundling_none_pays_full_sum(self, api):
        """PRD §3.4: "When the contract's `bundling_rule` is `NONE`, every
        line's `line_amount_cents` is simply its quantity times its unit rate."

        Design: Corner/calculations/bundling_none_pays_full_sum
        """
        set_clock("2026-08-03T09:00:00Z")
        create_charge_item(cpt_code="27447", list_price_cents=5000000,
                           description="Knee")
        create_charge_item(cpt_code="29881", list_price_cents=2000000,
                           description="Arthroscopy")
        create_contract_with_rates(
            bundling_rule="NONE",
            rates=[{"cpt_code": "27447", "rate_cents": 3000000,
                    "effective_from": "2026-01-01"},
                   {"cpt_code": "29881", "rate_cents": 1000000,
                    "effective_from": "2026-01-01"}])
        patient = create_patient(mrn="MRN-CA-2")
        snapshot = create_snapshot(patient["id"], deductible_total_cents=0,
                                   deductible_met_cents=0, oop_max_cents=5000000,
                                   oop_met_cents=0, coinsurance_pct=0)
        case = create_case(patient["id"], service_description="Knee + scope")
        estimate = create_estimate(
            case["id"], pricing_mode="INSURED",
            eligibility_snapshot_id=snapshot["id"],
            lines=[{"cpt_code": "27447", "quantity": 1},
                   {"cpt_code": "29881", "quantity": 1}])
        priced = price_estimate(estimate["id"])
        assert priced["allowed_amount_cents"] == 4000000

    def test_coinsurance_rounded_per_line_before_sum(self, api):
        """PRD §3.4: "the line's coinsurance is the line amount minus its
        deductible portion, multiplied by `coinsurance_pct` percent, rounded
        half up to a whole cent per line."
        PRD §2.11: "Under insured benefit application, coinsurance is rounded
        per line and only then summed — rounding coinsurance once on the
        aggregate base is a documented trap and is not canonical."

        Design: Corner/calculations/coinsurance_rounded_per_line_before_sum
        """
        set_clock("2026-08-03T09:00:00Z")
        create_charge_item(cpt_code="90010", list_price_cents=200000,
                           description="Proc Ten")
        create_charge_item(cpt_code="90011", list_price_cents=200000,
                           description="Proc Eleven")
        create_contract_with_rates(
            bundling_rule="NONE",
            rates=[{"cpt_code": "90010", "rate_cents": 100005,
                    "effective_from": "2026-01-01"},
                   {"cpt_code": "90011", "rate_cents": 100005,
                    "effective_from": "2026-01-01"}])
        patient = create_patient(mrn="MRN-CA-3")
        snapshot = create_snapshot(patient["id"], deductible_total_cents=0,
                                   deductible_met_cents=0, oop_max_cents=99999999,
                                   oop_met_cents=0, coinsurance_pct=10)
        case = create_case(patient["id"], service_description="Rounding probes")
        estimate = create_estimate(
            case["id"], pricing_mode="INSURED",
            eligibility_snapshot_id=snapshot["id"],
            lines=[{"cpt_code": "90010", "quantity": 1},
                   {"cpt_code": "90011", "quantity": 1}])
        priced = price_estimate(estimate["id"])
        # Per line: round_half_up(100005 * 10 / 100) = round_half_up(10000.5)
        # = 10001; summed twice = 20002 (aggregate rounding would give 20001).
        assert priced["coinsurance_cents"] == 20002
        assert priced["patient_responsibility_cents"] == 20002


class TestRateWindowLookup:
    def test_service_date_on_effective_to_is_not_covered(self, api):
        """PRD §3.4: "every line's CPT code must have a contract rate whose
        half-open window covers the case's `service_date` (`ERR_RATE_NOT_FOUND`,
        HTTP 422)."
        PRD §3.1: "Rate windows are half-open: the window starts on
        `effective_from` inclusively and ends on `effective_to` exclusively,
        and a null `effective_to` leaves the window open-ended."

        Design: Corner/calculations/rate_effective_window_half_open_lookup
        """
        ctx_a = setup_insured_scenario(
            mrn="MRN-CA-9", bundling_rule="NONE", reduction_pct=None,
            service_date="2026-08-20", effective_from="2026-01-01",
            effective_to="2026-08-20", deductible_total_cents=0,
            deductible_met_cents=0, oop_max_cents=5000000, oop_met_cents=0,
            coinsurance_pct=20)
        # Same patient, second case one day earlier — inside the window.
        case_b = create_case(ctx_a["patient"]["id"], service_date="2026-08-19",
                             service_description="Inside the window")
        est_b = create_estimate(case_b["id"], pricing_mode="INSURED",
                                eligibility_snapshot_id=ctx_a["snapshot"]["id"],
                                lines=[{"cpt_code": "27447", "quantity": 1}])
        res_a = api.price_estimate(ctx_a["estimate"]["id"], COUNSELOR)
        validate_error(res_a, ApiErrorId.ERR_RATE_NOT_FOUND)
        priced_b = price_estimate(est_b["id"])
        assert priced_b["allowed_amount_cents"] == 3000000


class TestComputedFieldsServerOwned:
    def test_estimate_create_computed_input_ignored(self, api):
        """PRD §2.10: "The general principle is that no client ever writes
        these fields; they are always the server's own projection of the case's
        children."
        PRD §3.4: "The out-of-pocket cap applies last: the remaining
        out-of-pocket room is `oop_max_cents` minus `oop_met_cents`, floored at
        zero, and `patient_responsibility_cents` is the smaller of the
        deductible-plus-coinsurance total and that remaining room."

        Design: Corner/entities/estimate_create_computed_input_ignored
        """
        set_clock("2026-08-03T09:00:00Z")
        create_charge_item(cpt_code="27447", list_price_cents=5000000)
        create_contract_with_rates(
            bundling_rule="MULTIPLE_PROCEDURE_REDUCTION", reduction_pct=50,
            rates=[{"cpt_code": "27447", "rate_cents": 3000000,
                    "effective_from": "2026-01-01"}])
        patient = create_patient(mrn="MRN-E-2")
        snapshot = create_snapshot(patient["id"])
        case = create_case(patient["id"])
        estimate = create_estimate(
            case["id"], pricing_mode="INSURED",
            eligibility_snapshot_id=snapshot["id"],
            lines=[{"cpt_code": "27447", "quantity": 1}],
            extra_fields={"patient_responsibility_cents": 1})
        priced = price_estimate(estimate["id"])
        assert priced["patient_responsibility_cents"] == 500000, (
            "client-supplied computed value is ignored; pricing reflects the "
            "benefit calculation")
