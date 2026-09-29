"""Multi-input formulas whose pinned evaluation order decides the answer.

Per-leg rounding before summation, the forfeiture branch feeding a capped penalty,
and the administrative-fee tier chosen from the base total rather than from the
settlement it produces.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import assert_money, assert_percentage, assert_status
from test_helpers.factories import (
    make_agreement_payload,
    make_completion_payload,
    make_invoice_payload,
    make_reconcile_payload,
)
from test_helpers.fixtures import (
    add_leg,
    build_active_agreement,
    build_open_cycle,
    cancel_leg,
    close_cycle,
    complete_leg,
    create_cycle,
    cycle_version,
    file_pass_through_actual,
    open_cycle,
    open_pass_through,
    read_cycle,
    read_leg,
    reconcile_pass_through,
    scorecard_for_cycle,
)
from test_helpers.test_users import ADMIN_HEADERS, ADMIN_USER_ID


def _build_three_completed_legs(api):
    """A closed September month carrying three completed legs and nothing else."""
    scenario = build_open_cycle(
        api,
        agreement_payload=make_agreement_payload(),
        station_code="ORD",
        pilots_required_per_aircraft=1,
        aircraft_allocation_cap=4,
        line_qualified_pilots=1,
        tail_numbers=["N301RG"],
        cycle_month="2026-09",
        published_departures=100,
    )
    plan = (
        ("SM4201", "DSM", "2026-09-02T08:00:00Z", "2026-09-02T09:12:00Z", 1.200, 1.155, "2026-09-02T09:26:00Z", 120),
        ("SM4202", "MSP", "2026-09-04T08:00:00Z", "2026-09-04T10:00:00Z", 2.000, 2.007, "2026-09-04T10:14:00Z", 100),
        ("SM4203", "SBN", "2026-09-06T08:00:00Z", "2026-09-06T08:42:00Z", 0.700, 0.616, "2026-09-06T08:40:00Z", 80),
    )
    legs = []
    for number, destination, departure, arrival, planned, actual, actual_arrival, bags in plan:
        leg = add_leg(
            api,
            scenario,
            flight_number=number,
            origin="ORD",
            destination=destination,
            scheduled_departure_utc=departure,
            scheduled_arrival_utc=arrival,
            planned_block_hours=planned,
        )
        complete_leg(
            api,
            leg["id"],
            make_completion_payload(
                actual_block_hours=actual,
                actual_arrival_utc=actual_arrival,
                enplaned_bags=bags,
                mishandled_bags=0,
            ),
        )
        legs.append(leg)
    close_cycle(api, scenario.cycle_id)
    return scenario, legs


class TestVariableComponentRoundingOrder:
    """Each leg is rounded to cents and the rounded legs are then added."""

    def test_each_leg_is_rounded_to_cents_before_the_month_is_summed(self, api):
        """The three legs carry their own rounded earnings and the bill sums them.

        PRD 3.8: "The rounding order is pinned: each leg is rounded to cents and the
        rounded legs are then added. Summing the unrounded products and rounding once
        at the end is a different number in cents and is not what this contract
        specifies."

        Design: Difficulty/combinatorial_formula/variable_payment_rounds_per_leg_then_sums
        """
        scenario, legs = _build_three_completed_legs(api)

        assert_money(
            read_leg(api, legs[0]["id"])["leg_variable_payment_usd"], 1995.62, "first leg payment"
        )
        assert_money(
            read_leg(api, legs[1]["id"])["leg_variable_payment_usd"], 3231.66, "second leg payment"
        )
        assert_money(
            read_leg(api, legs[2]["id"])["leg_variable_payment_usd"], 1213.66, "third leg payment"
        )

        response = api.create_invoice(
            scenario.cycle_id,
            make_invoice_payload("FINAL", cycle_version(api, scenario.cycle_id)),
            headers=ADMIN_HEADERS,
        )
        invoice = validate_success(response, 201)
        assert_money(invoice["variable_component_usd"], 6440.94, "variable component")

    def test_the_month_total_combines_the_rounded_variable_sum_with_the_overlay(self, api):
        """The remaining components complete the bill on the actual basis.

        PRD 3.8: "`total_usd` is then the fixed component plus the variable component
        plus the pass-through component plus the incentive component, less the penalty
        component and less the brand penalty component."

        Design: Difficulty/combinatorial_formula/variable_payment_rounds_per_leg_then_sums
        """
        scenario, _legs = _build_three_completed_legs(api)

        response = api.create_invoice(
            scenario.cycle_id,
            make_invoice_payload("FINAL", cycle_version(api, scenario.cycle_id)),
            headers=ADMIN_HEADERS,
        )
        invoice = validate_success(response, 201)

        assert_money(invoice["passthrough_component_usd"], 0.00, "pass-through component")
        assert_money(invoice["incentive_component_usd"], 15922.05, "incentive component")
        assert_money(invoice["total_usd"], 334362.99, "invoice total")


def _build_forfeiting_month(api):
    """A month that cancelled one of twenty departures and flew the other on time."""
    scenario = build_open_cycle(
        api,
        agreement_payload=make_agreement_payload(penalty_cap_usd=30000.00),
        station_code="CLE",
        pilots_required_per_aircraft=1,
        aircraft_allocation_cap=2,
        line_qualified_pilots=1,
        tail_numbers=["N401RG"],
        cycle_month="2026-09",
        published_departures=20,
    )
    flown = add_leg(
        api,
        scenario,
        flight_number="SM4301",
        origin="CLE",
        destination="DTW",
        scheduled_departure_utc="2026-09-02T08:00:00Z",
        scheduled_arrival_utc="2026-09-02T09:00:00Z",
        planned_block_hours=1.000,
    )
    dropped = add_leg(
        api,
        scenario,
        flight_number="SM4302",
        origin="CLE",
        destination="PIT",
        scheduled_departure_utc="2026-09-04T08:00:00Z",
        scheduled_arrival_utc="2026-09-04T09:00:00Z",
        planned_block_hours=1.000,
    )
    complete_leg(
        api,
        flown["id"],
        make_completion_payload(
            actual_block_hours=1.000,
            actual_arrival_utc="2026-09-02T09:00:00Z",
            enplaned_bags=60,
            mishandled_bags=0,
        ),
    )
    cancel_leg(api, dropped["id"], cause_code="CREW_UNAVAILABLE")
    close_cycle(api, scenario.cycle_id)
    return scenario


class TestForfeitureThenPenaltyCap:
    """A negative completion factor voids the credit earned on the other metrics."""

    def test_a_negative_completion_factor_forfeits_the_other_two_positive_scores(self, api):
        """Punctuality and baggage credit are banked at zero, not at their bands.

        PRD 3.7: "Concretely, when `completion_factor_points` is −4, `on_time_points`
        becomes whichever is smaller, 0 or the banded on-time value, and `bag_points`
        likewise becomes whichever is smaller, 0 or the banded bag value; an operator
        that ran a superb on-time month while cancelling too much banks nothing for the
        punctuality."

        Design: Difficulty/combinatorial_formula/performance_points_forfeiture_then_penalty_cap
        """
        scenario = _build_forfeiting_month(api)

        scorecard = scorecard_for_cycle(api, scenario.cycle_id)
        assert_percentage(scorecard["completion_factor_pct"], 95.00, "completion factor")
        assert_percentage(scorecard["on_time_arrival_pct"], 100.00, "on-time arrival")
        assert_percentage(scorecard["mishandled_bags_per_1000"], 0.00, "mishandled bags per 1000")
        assert scorecard["completion_factor_points"] == -4
        assert scorecard["on_time_points"] == 0, (
            "a perfect on-time month banks nothing once the completion floor is missed"
        )
        assert scorecard["bag_points"] == 0, (
            "a perfect baggage month banks nothing once the completion floor is missed"
        )
        assert scorecard["performance_points"] == -4

    def test_the_gross_shortfall_is_clamped_by_the_agreement_penalty_cap(self, api):
        """The signed gross becomes a capped, non-negative penalty magnitude.

        PRD 3.7: "When `gross_performance_usd` is negative, `incentive_usd` is 0.00 and
        `penalty_usd` is the smaller of the magnitude of the gross figure and the
        agreement's `penalty_cap_usd`; it is stored as a non-negative magnitude, not as
        a negative number."

        Design: Difficulty/combinatorial_formula/performance_points_forfeiture_then_penalty_cap
        """
        scenario = _build_forfeiting_month(api)

        scorecard = scorecard_for_cycle(api, scenario.cycle_id)
        assert_money(scorecard["gross_performance_usd"], -48000.00, "gross performance")
        assert_money(scorecard["penalty_usd"], 30000.00, "penalty")
        assert_money(scorecard["incentive_usd"], 0.00, "incentive")
        assert_status(scorecard, "PUBLISHED")


def _build_tier_boundary_month(api):
    """An open month with a fuel claim and an airport-fee claim awaiting adjudication."""
    scenario = build_active_agreement(
        api,
        agreement_payload=make_agreement_payload(),
        station_code="STL",
        pilots_required_per_aircraft=1,
        aircraft_allocation_cap=1,
    )
    cycle = create_cycle(api, scenario.agreement_id, cycle_month="2026-09", published_departures=5)
    cycle = open_cycle(api, cycle["id"])

    fuel = open_pass_through(api, cycle["id"], category="FUEL", estimated_amount_usd=90000.00)
    fees = open_pass_through(
        api, cycle["id"], category="AIRPORT_FEES", estimated_amount_usd=1900.00
    )
    file_pass_through_actual(api, fuel["id"], 98000.00, supporting_doc_ref="FUEL-TIER-01")
    file_pass_through_actual(api, fees["id"], 2000.00, supporting_doc_ref="FEES-TIER-01")
    reconcile_pass_through(api, fuel["id"])
    return cycle, fuel, fees


class TestPassThroughAdminFeeTier:
    """The fee tier is read off the base total, never off the settlement."""

    def test_fuel_passes_through_uncapped_while_airport_fees_meet_their_tolerance(self, api):
        """Step one allows each category on its own tolerance rule.

        PRD 3.6: "Fuel is passed through uncapped: for `category` `FUEL`,
        `allowed_amount_usd` is simply `actual_amount_usd`."

        Design: Difficulty/combinatorial_formula/passthrough_admin_fee_tier_pinned_to_step2_base
        """
        _cycle, fuel, fees = _build_tier_boundary_month(api)

        reconciled_fees = validate_success(
            api.reconcile_pass_through(fees["id"], make_reconcile_payload(), headers=ADMIN_HEADERS)
        )

        settled_fuel = validate_success(api.get_pass_through_claim(fuel["id"], headers=ADMIN_HEADERS))
        assert_money(settled_fuel["allowed_amount_usd"], 98000.00, "fuel allowed amount")
        assert_money(settled_fuel["variance_usd"], 8000.00, "fuel variance")
        assert_money(reconciled_fees["allowed_amount_usd"], 2000.00, "airport fee allowed amount")
        assert_money(reconciled_fees["variance_usd"], 100.00, "airport fee variance")
        assert_status(reconciled_fees, "RECONCILED")
        assert reconciled_fees["reconciled_by_user_id"] == ADMIN_USER_ID, (
            "the adjudicator's identifier should be recorded on the claim"
        )

    def test_the_tier_is_taken_from_the_base_total_not_from_the_settlement(self, api):
        """A base total exactly on the boundary keeps the three percent rate.

        PRD 3.6: "The pinned order matters at exactly one point, and it is a trap worth
        stating plainly: the tier is chosen from the step-two base total and is never
        re-derived from the step-five result."

        Design: Difficulty/combinatorial_formula/passthrough_admin_fee_tier_pinned_to_step2_base
        """
        cycle, _fuel, fees = _build_tier_boundary_month(api)

        validate_success(
            api.reconcile_pass_through(fees["id"], make_reconcile_payload(), headers=ADMIN_HEADERS)
        )

        settled = read_cycle(api, cycle["id"])
        assert_money(
            settled["passthrough_settlement_usd"], 103000.00, "pass-through settlement"
        )
        assert float(settled["passthrough_settlement_usd"]) != 102060.00, (
            "re-deriving the tier from the fee-inclusive total is the wrong answer"
        )
