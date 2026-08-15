"""Combustion efficiency (input-output vs heat-loss variants) and steam-trap
loss projection (Napier vs Grashof variants)."""
import pytest

from test_helpers import (
    create_and_verify_log_entry,
    create_boiler,
    create_leaking_trap,
    create_plant,
    deliver_fuel,
    get_boiler,
    setup_plant_with_operators,
    validate_success,
)

# Identical metered interval used across both efficiency variants:
# steam=10000 lb, fuel=80 gal, feedwater=1300 gal, blowdown=100 gal.
#
# Input-output (non-MA), PRD §3.5:
#   (10000 * (1190.0 - 180.0)) / (80 * 140000.0) * 100 = 90.178571... -> 90.18
# Heat-loss (MA), PRD §3.5:
#   100 - (6.5 + 4.0 + (100 / 1300) * 100.0 + 1.5) = 80.307692... -> 80.31
EFF_INPUT_OUTPUT = 90.18
EFF_HEAT_LOSS = 80.31

# Steam-trap figures for orifice 0.25 in, design pressure 144 psi (PRD §3.7):
#   Napier:  51.45 * 0.25^2 * 144        = 463.05 lb/hr
#   Grashof: 24.24 * 0.25^2 * sqrt(144)  = 18.18 lb/hr
NAPIER_LEAK = 463.05
GRASHOF_LEAK = 18.18


def _boiler_with_verified_entry(plant, ops, fuel_burned_gal=80):
    """Boiler with one VERIFIED entry (steam 10000 / fuel 80 / feedwater 1300
    / blowdown 100) and enough delivered fuel to keep the ledger non-negative."""
    boiler = create_boiler(plant["id"], tag="B-EFF")
    deliver_fuel(plant["id"], 500)
    create_and_verify_log_entry(
        plant["id"], boiler["id"], ops[0]["id"], ops[1]["id"],
        steam_generated_lb=10000, fuel_burned_gal=fuel_burned_gal,
        feedwater_intake_gal=1300, blowdown_gal=100,
    )
    return boiler


class TestCombustionEfficiency:
    def test_combustion_efficiency_correct_result(self, api, plant_manager_headers):
        """PRD §3.5: "the boiler's cumulative `total_steam_lb` over verified,
        non-voided entries is multiplied by the difference between the steam
        enthalpy constant of 1,190.0 BTU per pound and the feedwater enthalpy
        constant of 180.0 BTU per pound to yield the steam enthalpy output;
        the cumulative `total_fuel_burned_gal` is multiplied by the fuel's
        higher heating value of 140,000.0 BTU per gallon to yield the fuel
        energy input; the efficiency percentage is the output divided by the
        input, multiplied by one hundred, rounded half-up to 2 decimal
        places."

        Design: Corner/calculations/combustion_efficiency_correct_result
        """
        plant, ops = setup_plant_with_operators(name="Calc Plant", count=2)
        boiler = _boiler_with_verified_entry(plant, ops)
        state = get_boiler(plant["id"], boiler["id"])
        assert state["efficiency_pct"] == pytest.approx(EFF_INPUT_OUTPUT, abs=0.005)

    def test_input_output_method_applies_outside_massachusetts(
        self, api, plant_manager_headers
    ):
        """PRD §3.5: "Outside Massachusetts, the input-output method applies".
        A Texas plant with the standard metered interval reports 90.18.

        Design: Difficulty/dual_variant_calc/combustion_efficiency_input_output_vs_heat_loss
        """
        plant, ops = setup_plant_with_operators(name="TX Plant", state_code="TX")
        boiler = _boiler_with_verified_entry(plant, ops)
        state = get_boiler(plant["id"], boiler["id"])
        assert state["efficiency_pct"] == pytest.approx(EFF_INPUT_OUTPUT, abs=0.005)

    def test_heat_loss_method_applies_in_massachusetts(
        self, api, plant_manager_headers
    ):
        """PRD §3.5: "In Massachusetts (`state_code` `MA`), the ASME PTC 4.1
        heat-loss method applies instead: the efficiency is one hundred minus
        the sum of four loss terms — a fixed dry-gas loss of 6.5 percent, a
        fixed moisture loss of 4.0 percent, a blowdown loss equal to the
        cumulative `total_blowdown_gal` divided by the cumulative
        `total_feedwater_gal` ... the ratio multiplied by 100.0, and a fixed
        radiation loss of 1.5 percent — again rounded half-up to 2 decimal
        places. The two methods deliberately disagree on identical inputs,
        because the heat-loss method charges blowdown independently of steam
        metering".

        Design: Difficulty/dual_variant_calc/combustion_efficiency_input_output_vs_heat_loss
        """
        ma_plant, ma_ops = setup_plant_with_operators(
            name="MA Plant", state_code="MA"
        )
        ma_boiler = _boiler_with_verified_entry(ma_plant, ma_ops)
        ma_state = get_boiler(ma_plant["id"], ma_boiler["id"])
        assert ma_state["efficiency_pct"] == pytest.approx(EFF_HEAT_LOSS, abs=0.005)

        # Identical inputs under the default variant produce a different
        # cached efficiency — the variants deliberately disagree.
        tx_plant, tx_ops = setup_plant_with_operators(
            name="TX Twin", state_code="TX"
        )
        tx_boiler = _boiler_with_verified_entry(tx_plant, tx_ops)
        tx_state = get_boiler(tx_plant["id"], tx_boiler["id"])
        assert tx_state["efficiency_pct"] == pytest.approx(EFF_INPUT_OUTPUT, abs=0.005)
        assert ma_state["efficiency_pct"] != tx_state["efficiency_pct"]


class TestSteamTrapLossProjection:
    def test_get_loss_projection_computed_read(self, api, plant_manager_headers):
        """PRD §3.7: "Outside New York, the Napier theoretical method applies
        — reported as `napier_theoretical`: the leak rate in pounds per hour
        is the Napier coefficient 51.45, multiplied by the square of
        `orifice_diameter_in`, multiplied by `design_pressure_psi`." And "the
        annual steam loss is the leak rate multiplied by 8,760 hours per year,
        and the annual cost is that annual loss multiplied by the fuel price
        per gallon divided by the fuel's higher heating value of 140,000.0 BTU
        per gallon, then multiplied by the enthalpy difference of 1,190.0
        minus 180.0 BTU per pound"; with no deliveries "a default of 3.50 per
        gallon applies."

        Design: Corner/endpoints/get_loss_projection_computed_read
        """
        plant, ops = setup_plant_with_operators(name="CR Plant", count=1)
        trap = create_leaking_trap(
            plant["id"], ops[0]["id"], tag="ST-CR",
            orifice_diameter_in=0.25, design_pressure_psi=144,
        )
        resp = api.get_loss_projection(plant["id"], trap["id"], plant_manager_headers)
        projection = validate_success(resp, expected_status=200)
        assert projection["method"] == "napier_theoretical"
        assert projection["leak_rate_lb_hr"] == pytest.approx(NAPIER_LEAK, abs=0.005)
        assert projection["annual_steam_loss_lb"] == pytest.approx(
            NAPIER_LEAK * 8760, abs=0.005
        )
        # 4,056,318 lb * (3.50 / 140,000) $/BTU-gal * 1010 BTU/lb = 102,422.03
        assert projection["annual_cost_usd"] == pytest.approx(102422.03, abs=0.01)

    def test_napier_variant_for_non_ny_plant(self, api, plant_manager_headers):
        """PRD §3.7: "Outside New York, the Napier theoretical method applies
        — reported as `napier_theoretical`". For orifice 0.25 in and pressure
        144 psi the leak rate is 51.45 * 0.0625 * 144 = 463.05 lb/hr.

        Design: Difficulty/dual_variant_calc/steam_trap_loss_napier_vs_grashof
        """
        plant, ops = setup_plant_with_operators(name="TX Plant 2", state_code="TX")
        trap = create_leaking_trap(plant["id"], ops[0]["id"], tag="ST-TX")
        projection = validate_success(
            api.get_loss_projection(plant["id"], trap["id"], plant_manager_headers)
        )
        assert projection["method"] == "napier_theoretical"
        assert projection["leak_rate_lb_hr"] == pytest.approx(NAPIER_LEAK, abs=0.005)

    def test_grashof_variant_for_ny_plant(self, api, plant_manager_headers):
        """PRD §3.7: "In New York (`state_code` `NY`), the empirical Grashof
        correlation applies — reported as `grashof_empirical`: the coefficient
        24.24, multiplied by the square of `orifice_diameter_in`, multiplied
        by the square root of `design_pressure_psi`. Grashof therefore prices
        high-pressure traps lower and low-pressure traps higher than Napier
        does for identical hardware."

        Design: Difficulty/dual_variant_calc/steam_trap_loss_napier_vs_grashof
        """
        ny_plant, ny_ops = setup_plant_with_operators(
            name="NY Plant 2", state_code="NY"
        )
        ny_trap = create_leaking_trap(ny_plant["id"], ny_ops[0]["id"], tag="ST-NY")
        ny_projection = validate_success(
            api.get_loss_projection(
                ny_plant["id"], ny_trap["id"], plant_manager_headers
            )
        )
        assert ny_projection["method"] == "grashof_empirical"
        assert ny_projection["leak_rate_lb_hr"] == pytest.approx(GRASHOF_LEAK, abs=0.005)

        # Identical hardware under Napier yields a different leak rate.
        tx_plant, tx_ops = setup_plant_with_operators(
            name="TX Twin 2", state_code="TX"
        )
        tx_trap = create_leaking_trap(tx_plant["id"], tx_ops[0]["id"], tag="ST-TX2")
        tx_projection = validate_success(
            api.get_loss_projection(
                tx_plant["id"], tx_trap["id"], plant_manager_headers
            )
        )
        assert tx_projection["leak_rate_lb_hr"] == pytest.approx(NAPIER_LEAK, abs=0.005)
        assert ny_projection["leak_rate_lb_hr"] != tx_projection["leak_rate_lb_hr"]
