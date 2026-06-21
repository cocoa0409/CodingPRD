"""Fuel-order pricing engine: dual-variant (volume vs tankered), marginal cross-tier,
and the cumulative-gallon tier boundary (PRD §3.2, §3.6).

Difficulty queue (A) instances:
  - dual_variant_calc / fuel_cost_volume_vs_tankered
  - combinatorial_formula / fuel_marginal_cross_tier
  - boundary_precision_check / fuel_tier_boundary_at_five_thousand_gallons
"""
import pytest

from test_helpers import (
    api_client as api,
    get_success_data,
    setup_operator_aircraft_contract,
    setup_on_ground_visit,
    create_requested_fuel_order,
    create_fueled_fuel_order,
    TEST_USERS,
)

FUEL = TEST_USERS["fuel_tech_headers"]
OPS = TEST_USERS["ops_dispatcher_headers"]


def test_volume_discounted_order_prices_3115000_cents():
    """PRD §3.2: "The order's `priced_amount_cents` is the sum of those per-gallon
    prices, so a single order can cross a tier boundary mid-order and pay different
    per-gallon rates within the same uplift."
    PRD §3.2: "A gallon whose cumulative index is below 5,000 receives no discount;
    a gallon whose cumulative index is at least 5,000 but below 20,000 is discounted
    by 5 cents; a gallon at cumulative index 20,000 or above is discounted by 12 cents."

    A 6000-gal non-tankering order at cumulative 0: 5000 gal at 520 + 1000 gal at 515
    = 3,115,000 cents.

    Design: Difficulty/dual_variant_calc/fuel_cost_volume_vs_tankered
    """
    operator, aircraft, contract = setup_operator_aircraft_contract()
    visit = setup_on_ground_visit(operator["id"], aircraft["id"])
    order = create_requested_fuel_order(visit["id"], aircraft["id"], contract["id"],
                                        ordered_gallons=6000, tankering=False)
    dispatched = get_success_data(api.dispatch_fuel_order(order["id"], FUEL))
    assert dispatched["priced_amount_cents"] == 3_115_000, (
        f"volume-discounted 6000-gal order should price 3115000, got {dispatched['priced_amount_cents']}"
    )


def test_tankered_order_prices_flat_fee_180000_cents():
    """PRD §3.2: "For a **tankering** order, the FBO is merely handling fuel uplifted
    off-field: the priced amount is simply the order's `ordered_gallons` multiplied by
    the contract's `tankering_fee_cents_per_gal`, with no product cost, no volume
    discount, and no movement of the operator's tier."

    A 6000-gal tankering order at tankering_fee 30 prices 6000 * 30 = 180,000 cents,
    diverging from the volume-discounted variant on the same FuelOrder entity.

    Design: Difficulty/dual_variant_calc/fuel_cost_volume_vs_tankered
    """
    operator, aircraft, contract = setup_operator_aircraft_contract()
    visit = setup_on_ground_visit(operator["id"], aircraft["id"])
    order = create_requested_fuel_order(visit["id"], aircraft["id"], contract["id"],
                                        ordered_gallons=6000, tankering=True)
    dispatched = get_success_data(api.dispatch_fuel_order(order["id"], FUEL))
    assert dispatched["priced_amount_cents"] == 180_000, (
        f"tankered 6000-gal order should price 180000, got {dispatched['priced_amount_cents']}"
    )


def test_marginal_pricing_crosses_tier2_into_tier3():
    """PRD §3.2: "a single order can cross a tier boundary mid-order and pay different
    per-gallon rates within the same uplift."
    PRD §3.2: "A gallon whose cumulative index is below 5,000 receives no discount;
    a gallon whose cumulative index is at least 5,000 but below 20,000 is discounted
    by 5 cents; a gallon at cumulative index 20,000 or above is discounted by 12 cents."

    With cumulative at 6000 (one FUELED 6000-gal order), a second 16000-gal order spans
    indices 6000..21999: 14000 gal at 515 + 2000 gal at 508 = 8,226,000 cents.

    Design: Difficulty/combinatorial_formula/fuel_marginal_cross_tier
    """
    operator, aircraft, contract = setup_operator_aircraft_contract()
    # First order FUELED to advance cumulative to 6000.
    v1 = setup_on_ground_visit(operator["id"], aircraft["id"])
    create_fueled_fuel_order(v1["id"], aircraft["id"], contract["id"],
                             ordered_gallons=6000, tankering=False)
    operator_after = get_success_data(api.get_operator(operator["id"], TEST_USERS["billing_clerk_headers"]))
    assert operator_after["jeta_month_cumulative_gallons"] == 6000

    # Second order on a fresh ON_GROUND visit.
    v2 = setup_on_ground_visit(operator["id"], aircraft["id"],
                               visit_overrides={"arrival_utc": "2026-06-16T08:00:00.000Z",
                                                "departure_utc": "2026-06-17T08:00:00.000Z"})
    order2 = create_requested_fuel_order(v2["id"], aircraft["id"], contract["id"],
                                         ordered_gallons=16000, tankering=False)
    dispatched2 = get_success_data(api.dispatch_fuel_order(order2["id"], FUEL))
    assert dispatched2["priced_amount_cents"] == 8_226_000, (
        f"cross-tier 16000-gal order at cumulative 6000 should price 8226000, "
        f"got {dispatched2['priced_amount_cents']}"
    )


def test_tier_ceiling_uses_strict_less_than_at_five_thousand():
    """PRD §3.2: "A gallon whose cumulative index is below 5,000 receives no discount;
    a gallon whose cumulative index is at least 5,000 but below 20,000 is discounted
    by 5 cents"

    With cumulative exactly 4999, a 2-gal order prices gallon index 4999 at base 520
    (tier1, < 5000) and index 5000 at 515 (tier2, >= 5000) = 1035 cents.

    Design: Difficulty/boundary_precision_check/fuel_tier_boundary_at_five_thousand_gallons
    """
    operator, aircraft, contract = setup_operator_aircraft_contract()
    v1 = setup_on_ground_visit(operator["id"], aircraft["id"])
    create_fueled_fuel_order(v1["id"], aircraft["id"], contract["id"],
                             ordered_gallons=4999, tankering=False)
    operator_after = get_success_data(api.get_operator(operator["id"], TEST_USERS["billing_clerk_headers"]))
    assert operator_after["jeta_month_cumulative_gallons"] == 4999

    v2 = setup_on_ground_visit(operator["id"], aircraft["id"],
                               visit_overrides={"arrival_utc": "2026-06-16T08:00:00.000Z",
                                                "departure_utc": "2026-06-17T08:00:00.000Z"})
    order2 = create_requested_fuel_order(v2["id"], aircraft["id"], contract["id"],
                                         ordered_gallons=2, tankering=False)
    dispatched2 = get_success_data(api.dispatch_fuel_order(order2["id"], FUEL))
    assert dispatched2["priced_amount_cents"] == 1035, (
        f"2-gal order straddling the 5000-gal tier ceiling should price 1035, "
        f"got {dispatched2['priced_amount_cents']}"
    )
