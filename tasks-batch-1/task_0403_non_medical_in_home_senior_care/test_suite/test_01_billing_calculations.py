"""Billing calculation depth tests (queue A: Difficulty).

Covers the two billing variants and the combinatorial labor/mileage formulas:
provisional per-visit charge vs final chronological overtime, the percentage-vs-cap
claim coverage, the nested min/max overtime branch, and per-entry mileage rounding.
"""
import pytest

from test_helpers import (
    validate_success,
    setup_six_visit_overtime_invoice,
    setup_issued_invoice_single_visit,
    set_clock, setup_schedulable_scenario, create_completed_visit,
    open_invoice, finalize_invoice, get_invoice,
    assign_claim, submit_claim,
    create_in_progress_visit, clock_out_visit,
    TEST_USERS,
)

BILLING = TEST_USERS["billing_clerk_headers"]


class TestDualVariantLaborOvertime:
    """rule_id: dual_variant_calc / invoice_labor_provisional_vs_final_overtime."""

    def test_provisional_visit_charges_sum_without_overtime(self, api):
        """PRD §2.10: "The first is the provisional (forward) charge computed on a
        single visit at clock-out: the visit is priced in isolation, with no awareness
        of any other visit, and every hour is billed at the agency's base hourly rate."
        PRD §3.6: "For an HOURLY visit, the charge is the billable_minutes divided by 60
        and multiplied by the agency's base_hourly_rate, rounded half-up to 2 decimal
        places, with no awareness of overtime — every hour is billed at the base rate."

        Design: Difficulty/dual_variant_calc/invoice_labor_provisional_vs_final_overtime
        """
        s = setup_six_visit_overtime_invoice(finalize=False)
        visits = s["visits"]
        charges = []
        for v in visits:
            fresh = validate_success(api.get_visit(v["id"], BILLING))
            charges.append(fresh["visit_charge"])
        # Five 8h visits at base 30 = 240.00 each; one 6h visit = 180.00.
        assert charges[0] == pytest.approx(240.00, abs=0.01)
        assert charges[5] == pytest.approx(180.00, abs=0.01)
        assert sum(charges) == pytest.approx(1380.00, abs=0.01), \
            f"Provisional charges should sum to 1380.00, got {sum(charges)}"

    def test_finalized_labor_total_applies_overtime(self, api):
        """PRD §2.10: "any hours beyond the weekly overtime threshold are billed at the
        overtime rate. The two variants deliberately diverge — the provisional charge
        never applies overtime, so an invoice's final labor figure is greater than or
        equal to the plain sum of the provisional visit charges it covers."
        PRD §3.9: "the overtime portion is whatever hours remain beyond that ... an
        OVERTIME line is emitted at the base_hourly_rate multiplied by the
        overtime_multiplier ... The labor_total is the plain sum of all the
        already-rounded REGULAR, OVERTIME, and LIVE_IN line amounts."

        Design: Difficulty/dual_variant_calc/invoice_labor_provisional_vs_final_overtime
        """
        s = setup_six_visit_overtime_invoice(finalize=False)
        inv = validate_success(api.finalize_invoice(s["invoice"]["id"], BILLING))
        # 46 hours total: 40 regular at 30 = 1200, 6 overtime at 45 = 270 -> 1470.
        assert inv["labor_total"] == pytest.approx(1470.00, abs=0.01), \
            f"labor_total should be 1470.00, got {inv['labor_total']}"
        assert inv["invoice_total"] == pytest.approx(1470.00, abs=0.01)


class TestClaimCoveragePercentageVsCap:
    """rule_id: dual_variant_calc / claim_covered_percentage_vs_cap."""

    def test_percentage_binds_when_below_cap(self, api):
        """PRD §3.11: "The coverage figure is the smaller of two quantities: the
        percentage coverage, which is the invoice's invoice_total multiplied by
        covered_pct and rounded half-up to 2 decimal places; and the benefit cap, which
        is daily_benefit_max multiplied by covered_days. The covered_amount is whichever
        of those two is smaller, so the cap binds whenever the cap is below the rounded
        percentage figure."

        Design: Difficulty/dual_variant_calc/claim_covered_percentage_vs_cap
        """
        s = setup_issued_invoice_single_visit()
        inv = s["invoice"]
        assert inv["invoice_total"] == pytest.approx(240.00, abs=0.01)
        # 80% of 240 = 192.00; cap 300*6=1800 -> percentage binds.
        claim = assign_claim(s["client"]["id"], inv["id"], inv["version"],
                             insurer_name="PctCo", policy_number="P-PCT",
                             covered_pct=0.80, daily_benefit_max=300, covered_days=6)
        submitted = submit_claim(claim["id"])
        assert submitted["covered_amount"] == pytest.approx(192.00, abs=0.01), \
            f"percentage-bound covered_amount should be 192.00, got {submitted['covered_amount']}"

    def test_cap_binds_when_below_percentage(self, api):
        """PRD §3.11: "The covered_amount is whichever of those two is smaller, so the
        cap binds whenever the cap is below the rounded percentage figure."

        Design: Difficulty/dual_variant_calc/claim_covered_percentage_vs_cap
        """
        s = setup_issued_invoice_single_visit()
        inv = s["invoice"]
        # 80% of 240 = 192.00; cap 25*6 = 150 -> cap binds at 150.00.
        claim = assign_claim(s["client"]["id"], inv["id"], inv["version"],
                             insurer_name="CapCo", policy_number="P-CAP",
                             covered_pct=0.80, daily_benefit_max=25, covered_days=6)
        submitted = submit_claim(claim["id"])
        assert submitted["covered_amount"] == pytest.approx(150.00, abs=0.01), \
            f"cap-bound covered_amount should be 150.00, got {submitted['covered_amount']}"


class TestCombinatorialLaborOvertimeBranch:
    """rule_id: combinatorial_formula / labor_overtime_nested_min_max_branch."""

    def test_single_overtime_line_amount(self, api):
        """PRD §3.9: "the regular portion is the smaller of the visit's hours and the
        remaining headroom below the threshold, where the headroom is the agency's
        overtime_threshold_hours minus the running hours so far, never less than 0; the
        overtime portion is whatever hours remain beyond that. ... If the overtime
        portion is greater than 0, an OVERTIME line is emitted at the base_hourly_rate
        multiplied by the overtime_multiplier, with an amount of those overtime hours
        times that overtime rate, rounded half-up to 2 decimal places."

        Design: Difficulty/combinatorial_formula/labor_overtime_nested_min_max_branch
        """
        s = setup_six_visit_overtime_invoice(finalize=False)
        inv = validate_success(api.finalize_invoice(s["invoice"]["id"], BILLING))
        ot_lines = [ln for ln in inv["lines"] if ln["line_type"] == "OVERTIME"]
        assert len(ot_lines) == 1, \
            f"expected exactly one OVERTIME line, got {len(ot_lines)}"
        # 6 overtime hours at base 30 * 1.5 = 45 -> 270.00.
        assert ot_lines[0]["amount"] == pytest.approx(270.00, abs=0.01), \
            f"OVERTIME amount should be 270.00, got {ot_lines[0]['amount']}"

    def test_regular_line_amounts_sum_to_threshold_value(self, api):
        """PRD §3.9: "If the regular portion is greater than 0, a REGULAR line is emitted
        at the base_hourly_rate with an amount of those regular hours times the base
        rate, rounded half-up to 2 decimal places."

        Design: Difficulty/combinatorial_formula/labor_overtime_nested_min_max_branch
        """
        s = setup_six_visit_overtime_invoice(finalize=False)
        inv = validate_success(api.finalize_invoice(s["invoice"]["id"], BILLING))
        reg_total = sum(ln["amount"] for ln in inv["lines"]
                        if ln["line_type"] == "REGULAR")
        # 40 regular hours at base 30 = 1200.00.
        assert reg_total == pytest.approx(1200.00, abs=0.01), \
            f"REGULAR amounts should sum to 1200.00, got {reg_total}"


class TestMileagePerEntryRounding:
    """rule_id: combinatorial_formula / mileage_total_per_entry_round_then_sum."""

    def _setup_three_mileage_entries(self, api):
        set_clock("2026-06-01T07:00:00Z")
        s = setup_schedulable_scenario()
        cg, cl, plan = s["caregiver"], s["client"], s["plan"]
        v = create_in_progress_visit(
            cg["id"], cl["id"], plan["id"],
            "2026-06-01T09:00:00Z", "2026-06-01T11:00:00Z",
            "2026-06-01T09:00:00Z")
        from test_helpers import make_caregiver_headers
        cg_headers = make_caregiver_headers(cg["id"])
        me1 = validate_success(api.create_mileage(
            v["id"], {"miles": 1.45, "purpose": "Grocery 1"}, cg_headers),
            expected_status=201)
        validate_success(api.create_mileage(
            v["id"], {"miles": 1.45, "purpose": "Grocery 2"}, cg_headers),
            expected_status=201)
        validate_success(api.create_mileage(
            v["id"], {"miles": 1.45, "purpose": "Pharmacy"}, cg_headers),
            expected_status=201)
        clock_out_visit(v["id"], cg["id"], "2026-06-01T11:00:00Z")
        inv = open_invoice(s["agency"]["id"], cg["id"], cl["id"],
                           "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
        return me1, inv

    def test_per_entry_line_charge_rounded_at_creation(self, api):
        """PRD §3.8: "immediately receives a line_charge computed as the miles multiplied
        by the agency's mileage_rate, rounded half-up to 2 decimal places at the moment
        of creation."

        Design: Difficulty/combinatorial_formula/mileage_total_per_entry_round_then_sum
        """
        me1, _inv = self._setup_three_mileage_entries(api)
        # 1.45 * 0.70 = 1.015 -> 1.02.
        assert me1["line_charge"] == pytest.approx(1.02, abs=0.001), \
            f"line_charge should round to 1.02, got {me1['line_charge']}"

    def test_mileage_total_sums_already_rounded_charges(self, api):
        """PRD §2.8: "each component is rounded to 2 decimal places first, and the stored
        total is the plain sum of those already-rounded components, never a single
        rounding applied to the raw sum."
        PRD §3.8: "the invoice's mileage total is later assembled as the plain sum of
        these already-rounded line charges, not as a single rounding of the summed raw
        miles."

        Design: Difficulty/combinatorial_formula/mileage_total_per_entry_round_then_sum
        """
        _me1, inv = self._setup_three_mileage_entries(api)
        finalized = validate_success(api.finalize_invoice(inv["id"], BILLING))
        # Three entries of 1.02 each -> 3.06 (sum-then-round would give 3.05).
        assert finalized["mileage_total"] == pytest.approx(3.06, abs=0.001), \
            f"mileage_total should be 3.06 (per-entry rounding), got {finalized['mileage_total']}"
        # Labor: one 2h HOURLY visit -> 60.00; invoice_total 63.06.
        assert finalized["invoice_total"] == pytest.approx(63.06, abs=0.01)
