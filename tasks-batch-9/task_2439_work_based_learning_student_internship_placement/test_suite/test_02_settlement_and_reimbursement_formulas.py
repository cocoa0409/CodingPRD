"""Two money formulas whose intermediate rounding order and whose tier lookup are
both easy to get subtly wrong: wage settlement (which of the two variants gets
frozen, and what reaches the employer's books) and the reimbursement roll-up
(whose administrative fee tier is keyed on the pre-fee subtotal).
"""

import pytest

from test_helpers import (
    COORDINATOR,
    api_client,
    close_all_required_cycles,
    log_shifts,
    read_partner,
    read_placement,
    set_clock,
    settle_wages_payload,
    setup_active_placement,
    setup_completed_placement,
    validate_success,
)

RIDGEVIEW = {
    "legal_name": "Ridgeview Manufacturing",
    "naics_code": "332710",
    "industry_sector": "MANUFACTURING",
}
ANA_PIKE = {
    "full_name": "Ana Pike",
    "birth_date": "2009-05-14",
    "student_learner_certificate": True,
}
CEDAR_GRID = {
    "legal_name": "Cedar Grid Utilities",
    "naics_code": "221122",
    "industry_sector": "PUBLIC_ADMINISTRATION",
}
RAVI_SEN = {
    "full_name": "Ravi Sen",
    "birth_date": "2008-01-10",
    "student_learner_certificate": False,
}


def _completed_learner_wage_placement():
    """A completed learner-wage placement whose three shifts make the two wage
    variants disagree by one cent."""
    return setup_completed_placement(
        clock="2026-09-07T08:00:00Z",
        course_code="CTE-410",
        credit_hours_target=60.00,
        shift_clock="2026-09-14T08:00:00Z",
        shifts=[
            ("2026-09-08", "08:00", "11:20"),
            ("2026-09-09", "08:00", "11:20"),
            ("2026-09-10", "08:00", "11:20"),
        ],
        partner_overrides=RIDGEVIEW,
        student_overrides=ANA_PIKE,
        permit_class="MINOR_16_17",
        placement_overrides={
            "pay_classification": "PAID",
            "hourly_wage_cents": 1275,
            "stipend_total_cents": 0,
            "scheduled_weekly_hours": 12.00,
            "start_on": "2026-09-07",
            "end_on": "2026-12-18",
            "credit_target_credits": 0.50,
            "credit_award_mode": "HOURS_BASED",
            "required_evaluation_cycles": 1,
            "transportation_mode": "PUBLIC_TRANSIT",
            "commute_round_trip_miles": 0.00,
        },
    )


def _self_transport_placement_with_two_closed_cycles():
    """A self-transport placement with 120 round-trip miles over three logged days
    and two closed cycles, which lands the pre-fee subtotal in the middle tier."""
    scenario = setup_active_placement(
        clock="2026-09-07T08:00:00Z",
        course_code="CTE-330",
        credit_hours_target=100.00,
        partner_overrides=CEDAR_GRID,
        student_overrides=RAVI_SEN,
        permit_class="ADULT_18_PLUS",
        placement_overrides={
            "pay_classification": "PAID",
            "hourly_wage_cents": 1500,
            "stipend_total_cents": 0,
            "scheduled_weekly_hours": 16.00,
            "start_on": "2026-09-07",
            "end_on": "2026-12-18",
            "credit_target_credits": 1.00,
            "credit_award_mode": "HOURS_BASED",
            "required_evaluation_cycles": 2,
            "transportation_mode": "SELF",
            "commute_round_trip_miles": 120.00,
        },
    )
    set_clock("2026-10-20T08:00:00Z")
    log_shifts(
        scenario,
        [
            ("2026-09-08", "08:00", "16:30", 30, False),
            ("2026-09-09", "08:00", "16:30", 30, False),
            ("2026-09-10", "08:00", "16:30", 30, False),
        ],
    )
    close_all_required_cycles(scenario)
    return scenario


class TestWageSettlementRoundingOrder:
    def test_final_settlement_freezes_the_sum_then_round_figure(self):
        """The **final** variant rounds late: add the `hours_worked` values of the same
        entries together and round that sum half-up to two decimal places, multiply the
        single total by the effective hourly rate, and round that one product half-up to
        a whole number of cents. Settlement itself takes a `mode` of `PROVISIONAL` or
        `FINAL` and copies the corresponding figure into `settled_wage_cents`, recording
        the choice in `wage_settlement_mode`.

        Design: Difficulty/combinatorial_formula/wage_settlement_pins_nested_rounding_order_sum_then_round
        """
        scenario = _completed_learner_wage_placement()

        settled = validate_success(
            api_client.settle_placement_wages(
                scenario.placement_id, settle_wages_payload("FINAL"), COORDINATOR
            )
        )

        assert settled["settled_wage_cents"] == 12737
        assert settled["wage_settlement_mode"] == "FINAL"
        assert settled["provisional_wage_cents"] == 12738
        assert settled["final_wage_cents"] == 12737

    def test_only_the_final_figure_reaches_the_employers_wage_liability(self):
        """Only `FINAL` settlement feeds the employer's books: when `mode` is `FINAL`,
        the frozen `settled_wage_cents` is added to the employer partner's
        `wage_liability_cents`, which is at all times the sum of `settled_wage_cents`
        over that partner's placements whose `wage_settlement_mode` is `FINAL`.

        Design: Difficulty/combinatorial_formula/wage_settlement_pins_nested_rounding_order_sum_then_round
        """
        scenario = _completed_learner_wage_placement()
        assert read_partner(scenario.partner_id)["wage_liability_cents"] == 0

        validate_success(
            api_client.settle_placement_wages(
                scenario.placement_id, settle_wages_payload("FINAL"), COORDINATOR
            )
        )

        partner = read_partner(scenario.partner_id)
        assert partner["wage_liability_cents"] == 12737

        placement = read_placement(scenario.placement_id)
        assert placement["settled_wage_cents"] == 12737
        assert placement["wage_settlement_mode"] == "FINAL"


class TestReimbursementFeeTier:
    def test_travel_and_stipend_components_price_from_logged_days_and_closed_cycles(self):
        """`SELF` transport pays mileage: multiply 50 cents per mile by
        `commute_round_trip_miles` and then by `logged_days`, rounding the single product
        half-up to whole cents. The supervisor honorarium, `stipend_cents`, is 7500 cents
        for each of the placement's closed evaluation cycles, that is, 7500 multiplied by
        `closed_cycle_count`.

        Design: Difficulty/combinatorial_formula/reimbursement_admin_fee_tier_keyed_on_pre_fee_subtotal
        """
        scenario = _self_transport_placement_with_two_closed_cycles()

        reimbursement = validate_success(
            api_client.get_reimbursement(scenario.placement_id, COORDINATOR)
        )

        assert reimbursement["logged_days"] == 3
        assert reimbursement["transport_cents"] == 18000
        assert reimbursement["stipend_cents"] == 15000
        assert reimbursement["subtotal_cents"] == 33000

    def test_admin_fee_tier_is_chosen_by_the_pre_fee_subtotal(self):
        """The pre-fee `subtotal_cents` is `transport_cents` plus `stipend_cents`, and
        **the fee tier is keyed on that pre-fee subtotal and never on the total**: a
        subtotal of at most 20000 cents falls in `TIER_1` at a rate of 0.10, a subtotal
        above that but at most 50000 cents falls in `TIER_2` at a rate of 0.075, and
        anything above 50000 cents falls in `TIER_3` at a rate of 0.05. The
        `admin_fee_cents` is the subtotal multiplied by the tier rate, rounded half-up to
        whole cents, and `total_cents` is the subtotal plus the fee.

        Design: Difficulty/combinatorial_formula/reimbursement_admin_fee_tier_keyed_on_pre_fee_subtotal
        """
        scenario = _self_transport_placement_with_two_closed_cycles()

        reimbursement = validate_success(
            api_client.get_reimbursement(scenario.placement_id, COORDINATOR)
        )

        assert reimbursement["tier"] == "TIER_2"
        assert reimbursement["admin_fee_cents"] == 2475
        assert reimbursement["total_cents"] == 35475
        assert (
            reimbursement["total_cents"]
            == reimbursement["subtotal_cents"] + reimbursement["admin_fee_cents"]
        )
        assert float(reimbursement["admin_fee_cents"]) == pytest.approx(
            round(reimbursement["subtotal_cents"] * 0.075)
        )
