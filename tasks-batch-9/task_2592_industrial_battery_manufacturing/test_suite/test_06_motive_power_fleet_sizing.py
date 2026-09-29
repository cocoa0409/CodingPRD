"""Motive-power fleet sizing: per-candidate capacity, charger feasibility and counts."""

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers.assertions import assert_close
from test_helpers.factories import charger_payload, sizing_request_payload

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

LEAD_PACK = dict(
    code="CD-DA-800",
    nominal_capacity_ah=800.0,
    pack_weight_kg=1200.000,
    lead_content_kg=500.000,
    list_price_cents=700000,
)
LITHIUM_PACK = dict(
    code="CD-DB-900",
    nominal_capacity_ah=900.0,
    pack_weight_kg=1000.000,
    list_price_cents=900000,
)


def _sizing_payload(plant_id: str, **overrides):
    return sizing_request_payload(
        plant_id,
        application_name="Cold store pallet handling",
        forklift_count=6,
        shifts_per_day=2,
        shift_energy_kwh_per_shift=6.00,
        required_voltage_v=24.0,
        ambient_temp_c=5.0,
        compartment_max_kg=1500.000,
        charge_window_hours=6.00,
        **overrides,
    )


def test_the_selector_skips_the_smaller_pack_whose_only_charger_misses_the_window(
    make_world,
):
    """The 800 Ah lead pack is evaluated first and passed over for charger infeasibility.

    "the ordered pool is walked and the first design that can actually be charged wins." The lead
    pack needs 800.0 * 0.80 * 1.15 / 100 = 7.36 hours against a 6.00 hour window, so the walk
    continues to the 900 Ah lithium pack at 900.0 * 0.90 * 1.05 / 200 = 4.25 hours, whose own
    required capacity of 703 Ah is the figure persisted on the quote.

    Design: Difficulty/combinatorial_formula/motive_power_sizing_design_charger_circular_order_mode_c
    """
    world = make_world(with_design=False)
    lead_design = world.approved_lead_design(**LEAD_PACK)
    lithium_design = world.approved_lithium_design(**LITHIUM_PACK)

    validate_success(
        world.api.create_charger(
            charger_payload(
                "CHG-C1-100A",
                chemistry_compatibility=C.CHEMISTRY_LEAD_ACID,
                output_voltage_v=24.0,
                output_amps=100.0,
                price_cents=120000,
                charge_profile="FERRO",
            ),
            world.fleet,
        ),
        201,
    )
    lithium_charger = validate_success(
        world.api.create_charger(
            charger_payload(
                "CHG-C3-200A",
                chemistry_compatibility=C.CHEMISTRY_LITHIUM_LFP,
                output_voltage_v=24.0,
                output_amps=200.0,
                price_cents=250000,
                charge_profile="LITHIUM_CCCV",
            ),
            world.fleet,
        ),
        201,
    )

    quote = validate_success(
        world.api.create_sizing_request(_sizing_payload(world.plant_id), world.fleet), 201
    )

    assert_close(quote["daily_energy_kwh"], 12.00, "daily_energy_kwh", 2)
    assert_close(quote["temp_derate_factor"], 1.1000, "temp_derate_factor", 4)
    assert_close(quote["reserve_factor"], 1.15, "reserve_factor", 2)
    assert quote["evaluated_design_count"] == 2
    assert quote["selected_cell_design_id"] == lithium_design
    assert quote["selected_cell_design_id"] != lead_design
    assert quote["selected_charger_id"] == lithium_charger["id"]
    assert quote["required_ah"] == 703
    assert_close(quote["selected_charge_hours"], 4.25, "selected_charge_hours", 2)
    assert quote["request_state"] == C.SIZING_MATCHED


def test_a_lithium_selection_quotes_one_pack_and_one_charger_per_truck(make_world):
    """Lithium is opportunity-charged, so the counts and the capital follow the truck count.

    "`recommended_battery_count` is `forklift_count` for a lithium selection, because a lithium
    pack is opportunity-charged in the truck". Six trucks therefore quote six packs at 900000
    cents and six chargers at 250000 cents for 6900000 cents of capital.

    Design: Difficulty/combinatorial_formula/motive_power_sizing_design_charger_circular_order_mode_c
    """
    world = make_world(with_design=False)
    world.approved_lead_design(**LEAD_PACK)
    world.approved_lithium_design(**LITHIUM_PACK)
    for payload in (
        charger_payload(
            "CHG-C1-100A",
            chemistry_compatibility=C.CHEMISTRY_LEAD_ACID,
            output_amps=100.0,
            price_cents=120000,
        ),
        charger_payload(
            "CHG-C3-200A",
            chemistry_compatibility=C.CHEMISTRY_LITHIUM_LFP,
            output_amps=200.0,
            price_cents=250000,
            charge_profile="LITHIUM_CCCV",
        ),
    ):
        validate_success(world.api.create_charger(payload, world.fleet), 201)

    quote = validate_success(
        world.api.create_sizing_request(_sizing_payload(world.plant_id), world.fleet), 201
    )

    assert quote["recommended_battery_count"] == 6
    assert quote["recommended_charger_count"] == 6
    assert quote["fleet_capital_cents"] == 6900000


def test_eligible_designs_without_a_feasible_charger_persist_nothing(make_world):
    """When every eligible pack misses its charge window the quote is refused and not stored.

    "When designs were eligible but not one of them had a feasible charger, the request is refused
    with `ERR_NO_CHARGER_MATCH`. In both cases **no sizing request row is persisted**; a failed
    quote leaves no trace, so an engineer cannot list unmatched requests."

    Design: Difficulty/combinatorial_formula/motive_power_sizing_design_charger_circular_order_mode_c
    """
    world = make_world(with_design=False)
    world.approved_lead_design(**LEAD_PACK)
    validate_success(
        world.api.create_charger(
            charger_payload(
                "CHG-C1-100A",
                chemistry_compatibility=C.CHEMISTRY_LEAD_ACID,
                output_amps=100.0,
                price_cents=120000,
            ),
            world.fleet,
        ),
        201,
    )

    validate_error(
        world.api.create_sizing_request(_sizing_payload(world.plant_id), world.fleet),
        E.ERR_NO_CHARGER_MATCH,
    )

    rows, _ = validate_paginated(world.api.list_sizing_requests(world.fleet))
    assert rows == [], rows
