"""Waste/melt logging: the dual COGS and RETAIL valuations for mix and toppings."""
from test_helpers import (
    validate_success, TEST_USERS,
    setup_machine_flavor, make_topping,
)

SHIFTLEAD = TEST_USERS["shiftlead_headers"]


def test_mix_waste_cogs_valuation(api):
    """PRD §3.7: "For mix waste, the cost basis `cogs_value_cents` is the
    `waste_weight_oz` multiplied by the flavor's `cost_per_oz_cents`, rounded
    half up to whole cents, and the retail basis `retail_value_cents` is the
    `waste_weight_oz` multiplied by the flavor's `price_per_oz_cents`, rounded
    half up."

    Design: Difficulty/dual_variant_calc/waste_cogs_vs_retail_valuation
    """
    machine, flavor = setup_machine_flavor(api, price_per_oz_cents=55, cost_per_oz_cents=20)
    resp = api.create_waste_event(
        {"machine_id": machine["id"], "flavor_id": flavor["id"], "waste_weight_oz": 12.0, "reason": "MELT"},
        SHIFTLEAD)
    data = validate_success(resp, expected_status=201)
    assert data["cogs_value_cents"] == 240, \
        f"mix waste COGS must be 12*20=240, got {data['cogs_value_cents']}"


def test_mix_waste_retail_valuation(api):
    """PRD §3.7: "For mix waste, the cost basis `cogs_value_cents` is the
    `waste_weight_oz` multiplied by the flavor's `cost_per_oz_cents`, rounded
    half up to whole cents, and the retail basis `retail_value_cents` is the
    `waste_weight_oz` multiplied by the flavor's `price_per_oz_cents`, rounded
    half up."

    Design: Difficulty/dual_variant_calc/waste_cogs_vs_retail_valuation
    """
    machine, flavor = setup_machine_flavor(api, price_per_oz_cents=55, cost_per_oz_cents=20)
    resp = api.create_waste_event(
        {"machine_id": machine["id"], "flavor_id": flavor["id"], "waste_weight_oz": 12.0, "reason": "MELT"},
        SHIFTLEAD)
    data = validate_success(resp, expected_status=201)
    assert data["retail_value_cents"] == 660, \
        f"mix waste RETAIL must be 12*55=660, got {data['retail_value_cents']}"


def test_topping_waste_cogs_and_retail_valuation(api):
    """PRD §3.7: "For topping waste, `cogs_value_cents` is `waste_units`
    multiplied by the fixed per-unit topping cost of 12 cents, and
    `retail_value_cents` is `waste_units` multiplied by the topping's
    `surcharge_cents`."

    Design: Corner/calculations/waste_topping_cogs_retail_valuation
    """
    topping = make_topping(api, surcharge_cents=40, initial_units=50)
    resp = api.create_waste_event(
        {"topping_id": topping["id"], "waste_units": 3, "reason": "SPILL"}, SHIFTLEAD)
    data = validate_success(resp, expected_status=201)
    assert data["cogs_value_cents"] == 36, f"topping waste COGS must be 3*12=36, got {data['cogs_value_cents']}"
    assert data["retail_value_cents"] == 120, f"topping waste RETAIL must be 3*40=120, got {data['retail_value_cents']}"
