"""Energy settlement on a climate window and the twice-valued commitment week.

Both ledgers in this file hold two figures side by side on one row: a climate
window carries the projected cost derived from its setpoints alongside the
settled cost derived from metered actuals, and a commitment week carries the
provisional figures derived from allocated pounds alongside the final figures
derived from shipped pounds.
"""

import pytest

from test_helpers import (
    CLOCK_EPOCH,
    TEST_USERS,
    api_client,
    assert_money,
    cold_chain_event,
    create_climate_strategy,
    create_commitment_week,
    create_harvest_worker,
    create_retail_program,
    create_zone,
    find_allocations,
    grade_lot,
    read_allocation,
    read_climate_strategy,
    read_program,
    read_week,
    record_climate_actuals_payload,
    register_lot,
    run_allocation,
    set_clock,
    setup_production_cycle,
    validate_success,
)

GM = TEST_USERS["grower_manager_headers"]
QI = TEST_USERS["quality_inspector_headers"]
QI2 = TEST_USERS["second_quality_inspector_headers"]

# Metered figures posted against the day window under test.
ACTUALS = {
    "gas_consumed_m3": 1840.0,
    "chp_generated_kwh": 4200.0,
    "grid_import_kwh": 350.0,
    "screen_deployed_hours": 4.8,
}


def _zone_with_day_window():
    """A CHP-connected compartment plus one ACTIVE 12-hour DAY window on it."""
    set_clock(CLOCK_EPOCH)
    zone = create_zone(
        code="ZA-01",
        area_sqft=9450,
        has_thermal_screen=True,
        has_supplemental_lighting=True,
        chp_connected=True,
    )
    strategy = create_climate_strategy(
        zone["id"],
        zone["version"],
        regime="DAY",
        window_start="2026-08-05T06:00:00Z",
        window_end="2026-08-05T18:00:00Z",
        temp_setpoint_c=21.5,
        rh_setpoint_pct=80,
        co2_setpoint_ppm=900,
        lighting_hours=6,
        screen_position_pct=40,
    )
    return zone, strategy


def _record_actuals(strategy_id):
    """Post the metered actuals for the window and settle its cost."""
    return validate_success(
        api_client.record_climate_actuals(
            strategy_id, record_climate_actuals_payload(**ACTUALS), GM
        ),
        200,
    )


class TestClimateWindowEnergyLedger:
    """The projected and settled halves of one window's energy ledger."""

    def test_window_hours_is_the_elapsed_span_of_the_half_open_window(self, api):
        """PRD §3.4: "`window_hours` is the elapsed time from `window_start` to `window_end` expressed in hours and rounded half up to two decimal places."

        Design: Difficulty/dual_variant_calc/energy_cost_projected_and_settled_with_chp_diverge_on_one_strategy
        """
        _zone, strategy = _zone_with_day_window()

        assert strategy["window_hours"] == pytest.approx(12.00, abs=0.01), (
            f"a 06:00 to 18:00 window spans 12.00 hours, got {strategy['window_hours']}"
        )

    def test_planning_variant_values_the_window_from_its_setpoints_alone(self, api):
        """PRD §3.4: "Finally `projected_energy_cost_usd` is `planned_heat_kwh` valued at 0.045 US dollars per kilowatt-hour of boiler gas, plus `planned_light_kwh` valued at the grid purchase price of 0.14 US dollars per kilowatt-hour, plus `planned_co2_kg` valued at 0.09 US dollars per kilogram, with the sum rounded half up to two decimal places."

        Design: Difficulty/dual_variant_calc/energy_cost_projected_and_settled_with_chp_diverge_on_one_strategy
        """
        _zone, strategy = _zone_with_day_window()

        assert strategy["planned_heat_kwh"] == pytest.approx(552.96, abs=0.01), (
            f"expected planned_heat_kwh 552.96, got {strategy['planned_heat_kwh']}"
        )
        assert strategy["planned_light_kwh"] == pytest.approx(680.40, abs=0.01), (
            f"expected planned_light_kwh 680.40, got {strategy['planned_light_kwh']}"
        )
        assert strategy["planned_co2_kg"] == pytest.approx(97.98, abs=0.01), (
            f"expected planned_co2_kg 97.98, got {strategy['planned_co2_kg']}"
        )
        assert_money(
            strategy["projected_energy_cost_usd"], 128.96, "projected_energy_cost_usd"
        )

    def test_settled_variant_shares_the_engine_gas_bill_and_credits_the_export(self, api):
        """PRD §3.4: "`settled_energy_cost_usd` is then the allocated heat cost plus the grid cost plus the carbon dioxide purchase cost minus the export credit, rounded half up to two decimal places."

        Design: Difficulty/dual_variant_calc/energy_cost_projected_and_settled_with_chp_diverge_on_one_strategy
        """
        _zone, strategy = _zone_with_day_window()

        settled = _record_actuals(strategy["id"])

        assert_money(
            settled["settled_energy_cost_usd"], 251.19, "settled_energy_cost_usd"
        )
        assert settled["settled_energy_cost_usd"] != pytest.approx(
            settled["projected_energy_cost_usd"], abs=0.01
        ), "the settled figure must not collapse onto the projected figure"

    def test_cost_variance_is_the_settled_figure_minus_the_projected_figure(self, api):
        """PRD §3.4: "Either way, `cost_variance_usd` is `settled_energy_cost_usd` minus `projected_energy_cost_usd`, rounded half up to two decimal places, and it stays null until actuals are recorded."

        Design: Difficulty/dual_variant_calc/energy_cost_projected_and_settled_with_chp_diverge_on_one_strategy
        """
        _zone, strategy = _zone_with_day_window()
        assert strategy["cost_variance_usd"] is None, (
            "cost_variance_usd stays null until actuals are recorded"
        )

        _record_actuals(strategy["id"])
        after = read_climate_strategy(strategy["id"])

        assert_money(after["cost_variance_usd"], 122.23, "cost_variance_usd")
        assert_money(
            after["projected_energy_cost_usd"],
            128.96,
            "projected_energy_cost_usd after settlement",
        )


def _setup_week_with_one_confirmed_allocation():
    """A fully allocated 3000 lb week of which only 1200 lb are confirmed.

    Two cold-held lots carry 1200.00 and 1800.00 grade A pounds against an
    A_ONLY program committed for exactly 3000.00 pounds, so the allocation run
    fills the week completely; only the first lot's row is then confirmed.
    """
    state = setup_production_cycle()
    worker = create_harvest_worker()
    lot1 = register_lot(
        state["cycle"]["id"],
        worker["id"],
        harvest_date="2026-08-24",
        gross_weight_lbs=2000.00,
    )
    lot2 = register_lot(
        state["cycle"]["id"],
        worker["id"],
        harvest_date="2026-08-25",
        gross_weight_lbs=3000.00,
    )
    grade_lot(
        lot1["id"], worker["id"], grade_a_lbs=1200.00, grade_b_lbs=700.00, cull_lbs=100.00
    )
    grade_lot(
        lot2["id"],
        worker["id"],
        grade_a_lbs=1800.00,
        grade_b_lbs=1000.00,
        cull_lbs=200.00,
    )
    for lot in (lot1, lot2):
        cold_chain_event(lot["id"], "PRECOOLED", 10.0)
        cold_chain_event(lot["id"], "COLD_HELD", 6.0)

    program = create_retail_program(
        retailer_name="Northmart",
        program_code="NM-A1",
        grade_spec="A_ONLY",
        weekly_commitment_lbs=3000.00,
        price_per_lb_usd=1.85,
        shortfall_penalty_per_lb_usd=0.40,
        priority_rank=1,
    )
    week = create_commitment_week(
        program["id"],
        iso_week="2026-W35",
        week_start_date="2026-08-24",
        committed_lbs=3000.00,
    )
    run_allocation("2026-08-24")

    rows = find_allocations(commitment_week_id=week["id"], lot_id=lot1["id"])
    assert rows, "the allocation run must have minted a row against the first lot"
    confirmed = validate_success(
        api_client.transition_lot_allocation(
            rows[0]["id"], {"to_status": "CONFIRMED"}, QI
        ),
        200,
    )
    return {
        "program": program,
        "week": week,
        "lot1": lot1,
        "lot2": lot2,
        "confirmed_row": confirmed,
    }


def _ship_week(week_id):
    """Sign the week's shipment as an inspector who released no lot from cold storage."""
    return validate_success(
        api_client.transition_commitment_week(
            week_id,
            {"to_status": "SHIPPED", "shipped_at": "2026-08-28T10:00:00Z"},
            QI2,
        ),
        200,
    )


def _close_week(week_id):
    """Close the week out; the terminal state it lands in follows shipped pounds."""
    return validate_success(
        api_client.transition_commitment_week(
            week_id, {"to_status": "CLOSED_SHORT"}, GM
        ),
        200,
    )


class TestCommitmentWeekPayoutVariants:
    """The provisional and final valuations of one commitment week."""

    def test_provisional_variant_scores_the_week_on_allocated_pounds(self, api):
        """PRD §3.10: "A program committed for 3000 pounds at 1.85 US dollars a pound with a 0.40 US dollar penalty rate shows, after a full allocation, a `fill_rate_pct` of 100.00, a `provisional_shortfall_lbs` of 0 and a `provisional_penalty_usd` of `0.00`."

        Design: Difficulty/dual_variant_calc/commitment_payout_provisional_and_final_diverge_when_pounds_go_unconfirmed
        """
        state = _setup_week_with_one_confirmed_allocation()

        week = read_week(state["week"]["id"])

        assert week["allocated_lbs"] == pytest.approx(3000.00, abs=0.01), (
            f"expected allocated_lbs 3000.00, got {week['allocated_lbs']}"
        )
        assert week["fill_rate_pct"] == pytest.approx(100.00, abs=0.01), (
            f"expected fill_rate_pct 100.00, got {week['fill_rate_pct']}"
        )
        assert week["provisional_shortfall_lbs"] == pytest.approx(0.00, abs=0.01), (
            f"expected provisional_shortfall_lbs 0.00, got "
            f"{week['provisional_shortfall_lbs']}"
        )
        assert_money(week["provisional_penalty_usd"], 0.00, "provisional_penalty_usd")

    def test_shipping_recomputes_the_week_from_released_pounds_only(self, api):
        """PRD §3.10: "It then recomputes `shipped_lbs` from the `RELEASED` rows only and recomputes `fill_rate_pct` from `shipped_lbs`, and records `shipped_at` and `shipped_by_user_id`."

        Design: Difficulty/dual_variant_calc/commitment_payout_provisional_and_final_diverge_when_pounds_go_unconfirmed
        """
        state = _setup_week_with_one_confirmed_allocation()
        set_clock("2026-08-28T10:00:00Z")

        shipped = _ship_week(state["week"]["id"])

        assert shipped["shipped_lbs"] == pytest.approx(1200.00, abs=0.01), (
            f"only the confirmed 1200.00 lb row ships, got {shipped['shipped_lbs']}"
        )
        assert shipped["fill_rate_pct"] == pytest.approx(40.00, abs=0.01), (
            f"expected fill_rate_pct 40.00 from shipped pounds, got "
            f"{shipped['fill_rate_pct']}"
        )
        assert shipped["shipped_by_user_id"] == QI2["X-User-ID"], (
            "shipped_by_user_id records the signing inspector"
        )
        row = read_allocation(state["confirmed_row"]["id"])
        assert row["status"] == "RELEASED", (
            f"the confirmed row must be promoted to RELEASED, got {row['status']}"
        )

    def test_final_variant_scores_the_closed_week_on_shipped_pounds(self, api):
        """PRD §3.10: "If only 1200 of those pounds were ever confirmed and therefore shipped, closing restates `fill_rate_pct` to 40.00 and yields a `final_shortfall_lbs` of 1800, a `final_penalty_usd` of 720.00, a `gross_revenue_usd` of 2220.00 and a `net_payout_usd` of 1500.00."

        Design: Difficulty/dual_variant_calc/commitment_payout_provisional_and_final_diverge_when_pounds_go_unconfirmed
        """
        state = _setup_week_with_one_confirmed_allocation()
        set_clock("2026-08-28T10:00:00Z")
        _ship_week(state["week"]["id"])

        closed = _close_week(state["week"]["id"])

        assert closed["fill_rate_pct"] == pytest.approx(40.00, abs=0.01), (
            f"expected fill_rate_pct restated to 40.00, got {closed['fill_rate_pct']}"
        )
        assert closed["final_shortfall_lbs"] == pytest.approx(1800.00, abs=0.01), (
            f"expected final_shortfall_lbs 1800.00, got {closed['final_shortfall_lbs']}"
        )
        assert_money(closed["final_penalty_usd"], 720.00, "final_penalty_usd")
        assert_money(closed["gross_revenue_usd"], 2220.00, "gross_revenue_usd")
        assert_money(closed["net_payout_usd"], 1500.00, "net_payout_usd")
        assert closed["status"] == "CLOSED_SHORT", (
            f"a week short of its commitment closes CLOSED_SHORT, got {closed['status']}"
        )

    def test_only_the_final_penalty_posts_to_the_program_ledger(self, api):
        """PRD §3.10: "Closing then posts `final_penalty_usd` to the program's `penalty_accrued_usd`."

        Design: Difficulty/dual_variant_calc/commitment_payout_provisional_and_final_diverge_when_pounds_go_unconfirmed
        """
        state = _setup_week_with_one_confirmed_allocation()
        set_clock("2026-08-28T10:00:00Z")
        _ship_week(state["week"]["id"])
        before = read_program(state["program"]["id"])
        assert_money(
            before["penalty_accrued_usd"], 0.00, "penalty_accrued_usd before closing"
        )

        _close_week(state["week"]["id"])

        after = read_program(state["program"]["id"])
        assert_money(
            after["penalty_accrued_usd"], 720.00, "penalty_accrued_usd after closing"
        )
