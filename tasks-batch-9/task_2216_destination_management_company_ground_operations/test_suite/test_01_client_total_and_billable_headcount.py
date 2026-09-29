"""Billable head counts, per-line markup rounding and the tiered management fee."""

from test_helpers import (
    TEST_USERS,
    advance_to_in_execution,
    approve_line,
    confirm_program,
    deliver,
    issue_invoice,
    lock_design,
    mark_ready,
    open_reconciliation,
    read_program,
    set_clock,
    setup_invoiced_program,
    setup_multi_element_program,
    setup_program_with_contracted_element,
    validate_success,
)

PD = TEST_USERS["program_director_headers"]
CTRL = TEST_USERS["controller_headers"]

REGATTA = {
    "element_type": "ACTIVITY",
    "title": "Harbor Sail Regatta",
    "starts_at": "2026-09-11T09:00:00Z",
    "ends_at": "2026-09-11T13:00:00Z",
    "planned_headcount": 110,
    "guaranteed_headcount": 100,
    "per_person_cost_cents": 20_000,
}
REGATTA_CONTRACT = {"contract_value_cents": 2_200_000}
ATTRITION_NOTE = (
    "Attrition floor applied; 30 guests dropped after client-side agenda change."
)


class TestEstimateVersusFinalBillableHeadCount:
    def test_estimate_variant_bills_the_planned_head_count_at_confirmation(self):
        """PRD §3.9: "The **estimate** variant, run when the programme is confirmed,
        walks the programme's elements in `PLANNED` or `READY` — no element can be
        `PERMIT_BLOCKED` at that point, and cancelled, weather-switched and delivered
        elements are excluded — and for each derives a supplier cost as the estimate
        billable head count multiplied by that element's `per_person_cost_cents`, plus
        a markup as that cost multiplied by the programme's `markup_pct` rounded half
        up per element, summing only after each element has been rounded."

        Design: Difficulty/dual_variant_calc/billable_headcount_estimate_vs_final_divergence
        """
        ctx = setup_program_with_contracted_element(
            element_overrides=REGATTA, contract_overrides=REGATTA_CONTRACT
        )
        lock_design(ctx["program"]["id"])
        program = confirm_program(ctx["program"]["id"])

        assert program["execution_status"] == "CONFIRMED"
        assert program["estimated_client_total_cents"] == 2_777_720
        # The estimate variant writes nothing to the final figures.
        assert program["final_subtotal_cents"] == 0
        assert program["disclosed_markup_cents"] == 0
        assert program["management_fee_cents"] == 0
        assert program["final_client_total_cents"] == 0

    def test_final_variant_bills_the_attrition_floor_rather_than_the_turnout(self):
        """PRD §3.8: "For one and the same element with a planned count of 110, a
        guaranteed count of 100 and an actual turnout of 70, the estimate variant
        yields 110 and the final variant yields 85."

        Design: Difficulty/dual_variant_calc/billable_headcount_estimate_vs_final_divergence
        """
        ctx = setup_invoiced_program(
            actual_headcount=70,
            variance_reason=ATTRITION_NOTE,
            deliver_clock="2026-09-11T13:30:00Z",
            element_overrides=REGATTA,
            contract_overrides=REGATTA_CONTRACT,
        )
        line = ctx["lines"][0]

        assert line["guaranteed_headcount"] == 100
        assert line["actual_headcount"] == 70
        assert line["billed_headcount"] == 85
        assert line["supplier_cost_cents"] == 1_700_000
        assert line["markup_cents"] == 306_000
        assert line["client_charge_cents"] == 2_006_000

    def test_issued_invoice_diverges_from_the_frozen_estimate_by_the_attrition_gap(self):
        """PRD §3.8: "This is deliberately different from the **estimate** variant used
        before execution, which takes simply the larger of the element's
        `planned_headcount` and its `guaranteed_headcount` and ignores the attrition
        floor entirely."

        Design: Difficulty/dual_variant_calc/billable_headcount_estimate_vs_final_divergence
        """
        ctx = setup_invoiced_program(
            actual_headcount=70,
            variance_reason=ATTRITION_NOTE,
            deliver_clock="2026-09-11T13:30:00Z",
            element_overrides=REGATTA,
            contract_overrides=REGATTA_CONTRACT,
        )
        program = ctx["program"]

        assert program["settlement_status"] == "CLIENT_INVOICED"
        assert program["estimated_client_total_cents"] == 2_777_720
        assert program["final_subtotal_cents"] == 1_700_000
        assert program["disclosed_markup_cents"] == 306_000
        assert program["management_fee_cents"] == 140_420
        assert program["final_client_total_cents"] == 2_146_420
        assert (
            program["estimated_client_total_cents"] - program["final_client_total_cents"]
            == 631_300
        )


class TestMarkupRoundingOrder:
    HALBERD = {
        "client_name": "Halberd Capital",
        "group_name": "Partner Offsite",
        "guaranteed_count": 60,
        "markup_pct": 0.175,
    }
    ELEMENT_SPECS = [
        {
            "element_type": "ACTIVITY",
            "title": "Morning Kayak Clinic",
            "starts_at": "2026-09-11T09:00:00Z",
            "ends_at": "2026-09-11T11:00:00Z",
            "planned_headcount": 20,
            "guaranteed_headcount": 20,
            "per_person_cost_cents": 2_001,
        },
        {
            "element_type": "ACTIVITY",
            "title": "Afternoon Studio Tour",
            "starts_at": "2026-09-11T12:30:00Z",
            "ends_at": "2026-09-11T14:30:00Z",
            "planned_headcount": 20,
            "guaranteed_headcount": 20,
            "per_person_cost_cents": 2_001,
        },
        {
            "element_type": "ACTIVITY",
            "title": "Evening Rooftop Tasting",
            "starts_at": "2026-09-11T16:00:00Z",
            "ends_at": "2026-09-11T18:00:00Z",
            "planned_headcount": 20,
            "guaranteed_headcount": 20,
            "per_person_cost_cents": 2_001,
        },
    ]

    def _run_three_line_programme(self):
        ctx = setup_multi_element_program(
            self.ELEMENT_SPECS,
            program_overrides=self.HALBERD,
            venue_overrides={"name": "Old Customs House"},
            supplier_overrides={"legal_name": "Coastline Experiences Inc"},
            contract_overrides={"contract_value_cents": 120_060},
        )
        advance_to_in_execution(ctx["program"]["id"])
        for element in ctx["elements"]:
            mark_ready(element["id"])
        set_clock("2026-09-11T18:30:00Z")
        for element in ctx["elements"]:
            deliver(element["id"], 20)
        ctx["lines"] = open_reconciliation(ctx["program"]["id"])
        return ctx

    def test_each_line_rounds_its_own_markup_half_up(self):
        """PRD §3.8: "The `markup_cents` figure is `supplier_cost_cents` multiplied by
        the parent programme's `markup_pct`, read at reconcile time, and rounded half up
        to whole cents — rounded per line, as §2.6 insists, and only summed afterwards."

        Design: Difficulty/combinatorial_formula/markup_rounded_per_line_not_on_program_total
        """
        ctx = self._run_three_line_programme()

        assert len(ctx["lines"]) == 3
        for line in ctx["lines"]:
            assert line["supplier_cost_cents"] == 40_020
            assert line["markup_cents"] == 7_004
            assert line["client_charge_cents"] == 47_024

    def test_disclosed_markup_sums_the_rounded_lines_and_not_the_rounded_total(self):
        """PRD §2.6: "**Markup is rounded per reconciliation line and only then
        summed.** Rounding each line's markup separately and adding the rounded results
        gives a different total from summing the raw supplier costs first and rounding
        once; the per-line order is the correct one."

        Design: Difficulty/combinatorial_formula/markup_rounded_per_line_not_on_program_total
        """
        ctx = self._run_three_line_programme()
        for line in ctx["lines"]:
            approve_line(line["id"])
        program = issue_invoice(ctx["program"]["id"])

        assert program["final_subtotal_cents"] == 120_060
        assert program["disclosed_markup_cents"] == 21_012
        assert program["disclosed_markup_cents"] != 21_011
        assert program["management_fee_cents"] == 16_929
        assert program["final_client_total_cents"] == 158_001


class TestManagementFeeTier:
    ALDERCREST = {
        "client_name": "Aldercrest Foods",
        "group_name": "Leadership Retreat",
        "guaranteed_count": 30,
        "markup_pct": 0.25,
    }
    CHEF_TABLE = {
        "element_type": "ACTIVITY",
        "title": "Chef Table Experience",
        "starts_at": "2026-09-12T10:00:00Z",
        "ends_at": "2026-09-12T14:00:00Z",
        "planned_headcount": 30,
        "guaranteed_headcount": 30,
        "per_person_cost_cents": 14_000,
    }

    def _invoiced_programme(self):
        return setup_invoiced_program(
            actual_headcount=30,
            deliver_clock="2026-09-12T14:30:00Z",
            program_overrides=self.ALDERCREST,
            element_overrides=self.CHEF_TABLE,
            venue_overrides={"name": "Granary Loft"},
            supplier_overrides={"legal_name": "Tidewater Event Partners"},
            contract_overrides={"contract_value_cents": 420_000},
        )

    def test_fee_tier_is_selected_on_the_marked_up_base_not_on_the_subtotal(self):
        """PRD §3.9: "Step four selects the fee rate from the base and from the base
        alone, never from the grand total: a base below 500,000 cents — that is, below
        5,000.00 in the billing currency — attracts a fee of 12 hundredths; a base below
        2,000,000 cents (20,000.00) attracts 9 hundredths; and any larger base attracts
        7 hundredths."

        Design: Difficulty/combinatorial_formula/management_fee_tier_keyed_on_marked_up_base_not_subtotal
        """
        program = self._invoiced_programme()["program"]

        assert program["final_subtotal_cents"] == 420_000
        assert program["disclosed_markup_cents"] == 105_000
        assert program["management_fee_cents"] == 47_250
        assert program["management_fee_cents"] != 63_000
        assert program["final_client_total_cents"] == 572_250

    def test_cost_summary_discloses_the_fee_rate_actually_selected(self, api):
        """PRD §3.9: "The markup-transparency read the client is entitled to see
        exposes, for one programme, its `program_id`, the frozen
        `estimated_client_total_cents`, and then the final picture:
        `final_subtotal_cents`, `disclosed_markup_cents`, `management_fee_cents`, the
        `fee_pct_applied` rate actually selected by the tier test,
        `final_client_total_cents`, and the three supplier-side figures
        `supplier_gross_payable_cents`, `supplier_settled_cents` and
        `supplier_open_payable_cents`."

        Design: Difficulty/combinatorial_formula/management_fee_tier_keyed_on_marked_up_base_not_subtotal
        """
        program = self._invoiced_programme()["program"]

        summary = validate_success(api.get_program_cost_summary(program["id"], CTRL))

        assert summary["program_id"] == program["id"]
        assert summary["fee_pct_applied"] == 0.09
        assert summary["management_fee_cents"] == 47_250
        assert summary["final_client_total_cents"] == 572_250
        assert read_program(program["id"], PD)["management_fee_cents"] == 47_250
