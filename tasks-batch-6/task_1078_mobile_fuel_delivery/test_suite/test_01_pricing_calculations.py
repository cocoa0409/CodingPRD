"""Pricing engine and monetary calculations.

Queue A: dual_variant_calc (fuel cost + membership charge), combinatorial_formula
(service fee tiers + per-line add-on rounding).
Queue B: fuel-price selection, no-price rejection, non-member add-on, dispense>requested.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, get_success_data,
    make_member_headers, make_driver_headers,
    setup_dual_variant_fuel_cost_arrived, setup_membership_unused_credit,
    setup_member_order_arrived, setup_member_order_with_carwash,
    post_fuel_price, new_customer, new_vehicle, new_membership, new_order,
    new_truck, new_compartment, new_route, drive_order_to_arrived, get_order,
)


# ─── Queue A: dual_variant_calc / order_fuel_cost_estimated_vs_final_diverge ──

def test_order_fuel_cost_estimated_and_final_values_diverge(api):
    """PRD §3.4: "The provisional `estimated_fuel_cost_cents` is the requested gallons
    multiplied by that locked per-gallon price, rounded to whole cents half-up."
    PRD §3.6: "for a member order whose membership has `price_lock_enabled` set to true,
    the effective price is the order's `locked_price_per_gallon_cents` captured at creation;"
    PRD §3.6: "The final fuel cost is the dispensed gallons multiplied by that effective
    price, rounded to whole cents half-up."

    Design: Difficulty/dual_variant_calc/order_fuel_cost_estimated_vs_final_diverge
    """
    ctx = setup_dual_variant_fuel_cost_arrived()
    res = api.deliver_order(ctx["order_id"], {"dispensed_gallons": 10},
                            make_driver_headers(ctx["driver_id"]))
    order = validate_success(res, 200)
    assert order["estimated_fuel_cost_cents"] == 5028, "12 gal * 419 = 5028"
    assert order["final_fuel_cost_cents"] == 4190, "10 gal * locked 419 = 4190"


def test_order_fuel_cost_estimate_differs_from_final_and_delivered(api):
    """PRD §3.4: "The provisional `estimated_fuel_cost_cents` is the requested gallons
    multiplied by that locked per-gallon price, rounded to whole cents half-up."
    PRD §3.6: "The final fuel cost is the dispensed gallons multiplied by that effective
    price, rounded to whole cents half-up."

    Design: Difficulty/dual_variant_calc/order_fuel_cost_estimated_vs_final_diverge
    """
    ctx = setup_dual_variant_fuel_cost_arrived()
    api.deliver_order(ctx["order_id"], {"dispensed_gallons": 10},
                      make_driver_headers(ctx["driver_id"]))
    order = get_order(ctx["order_id"])
    assert order["status"] == "DELIVERED"
    assert order["estimated_fuel_cost_cents"] != order["final_fuel_cost_cents"], \
        "dispensed (10) != requested (12) makes the two variants diverge"


# ─── Queue A: dual_variant_calc / membership_period_charge diverge ───────────

def test_membership_provisional_charge_is_full_fee(api):
    """PRD §3.8: "At all times before a period is settled, the provisional
    `estimated_next_charge_cents` bills the full recurring `monthly_fee_cents` and
    ignores any unused-delivery credit."

    Design: Difficulty/dual_variant_calc/membership_period_charge_provisional_vs_final_diverge
    """
    _, mem = setup_membership_unused_credit()
    assert mem["estimated_next_charge_cents"] == 3999, "provisional bills full fee 3999"


def test_membership_final_settlement_subtracts_unused_credit(api):
    """PRD §3.8: "its `final_settlement_charge_cents` is computed as the fee minus the
    unused-delivery credit, exactly as at renewal."
    PRD §3.8: "each unused delivery is worth an `UNUSED_DELIVERY_CREDIT_CENTS` credit of
    400 cents."

    Design: Difficulty/dual_variant_calc/membership_period_charge_provisional_vs_final_diverge
    """
    cust_id, mem = setup_membership_unused_credit()
    res = api.cancel_membership(mem["id"], make_member_headers(cust_id))
    cancelled = validate_success(res, 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["final_settlement_charge_cents"] == 1999, "3999 - 5*400 = 1999"


# ─── Queue A: combinatorial_formula / service_fee tiered conditional ─────────

def test_service_fee_member_overage_plus_priority(api):
    """PRD §3.7: "For a member order, the fee's base is 0 when the membership's
    `deliveries_used_this_period` is strictly less than its `included_deliveries` (the
    delivery is covered by the plan) and is a `MEMBER_OVERAGE_FEE_CENTS` of 600 cents once
    the plan quota is exhausted (that is, when used deliveries have reached the included
    count)."
    PRD §3.7: "On top of the base, a priority order (`is_priority` set to true) adds a
    `PRIORITY_SURCHARGE_CENTS` surcharge of 500 cents, while a non-priority order adds
    nothing. The service fee is the base plus the surcharge."

    Design: Difficulty/combinatorial_formula/service_fee_tiered_conditional_member_overage_priority
    """
    ctx = setup_member_order_arrived(driver_id="driver-2", included_deliveries=0,
                                     is_priority=True, requested_gallons=5)
    res = api.deliver_order(ctx["order_id"], {"dispensed_gallons": 5},
                            make_driver_headers(ctx["driver_id"]))
    order = validate_success(res, 200)
    assert order["service_fee_cents"] == 1100, "overage base 600 + priority 500 = 1100"


def test_service_fee_overage_priority_persists_after_delivery(api):
    """PRD §3.7: "For a member order, the fee's base is 0 when the membership's
    `deliveries_used_this_period` is strictly less than its `included_deliveries` (the
    delivery is covered by the plan) and is a `MEMBER_OVERAGE_FEE_CENTS` of 600 cents once
    the plan quota is exhausted (that is, when used deliveries have reached the included
    count)."
    PRD §3.7: "The service fee is the base plus the surcharge."

    Design: Difficulty/combinatorial_formula/service_fee_tiered_conditional_member_overage_priority
    """
    ctx = setup_member_order_arrived(driver_id="driver-2", included_deliveries=0,
                                     is_priority=True, requested_gallons=5)
    api.deliver_order(ctx["order_id"], {"dispensed_gallons": 5},
                      make_driver_headers(ctx["driver_id"]))
    order = get_order(ctx["order_id"])
    assert order["status"] == "DELIVERED"
    assert order["service_fee_cents"] == 1100


# ─── Queue A: combinatorial_formula / addon per-line rounding ────────────────

def test_addon_charged_prices_rounded_per_line(api):
    """PRD §3.7: "The catalog price is 1595 cents for a `CAR_WASH` and 6495 cents for an
    `OIL_CHANGE`. For an order tied to a membership, the charged price applies a 10 percent
    member discount, computed as the list price multiplied by nine-tenths and rounded to
    whole cents half-up; for a non-member order, the charged price equals the list price
    with no discount."

    Design: Difficulty/combinatorial_formula/addon_total_round_per_line_not_round_once
    """
    ctx = setup_member_order_with_carwash()
    assert ctx["car_wash"]["charged_price_cents"] == 1436, "round(1595*0.9)=1436"
    res = api.add_addon(ctx["order_id"], {"addon_type": "OIL_CHANGE"},
                        make_member_headers(ctx["customer_id"]))
    oil = validate_success(res, 201)
    assert oil["charged_price_cents"] == 5846, "round(6495*0.9)=5846"


def test_addon_total_is_sum_of_per_line_rounded_charges(api):
    """PRD §3.7: "This discount is applied and rounded per add-on line — each line is
    rounded to whole cents on its own and only then are the lines summed — never by
    discounting the summed catalog total once."
    PRD §3.7: "Attaching an add-on recomputes the order's `addon_total_cents` (the sum of
    the per-line charged prices)"

    Design: Difficulty/combinatorial_formula/addon_total_round_per_line_not_round_once
    """
    ctx = setup_member_order_with_carwash()
    api.add_addon(ctx["order_id"], {"addon_type": "OIL_CHANGE"},
                  make_member_headers(ctx["customer_id"]))
    order = get_order(ctx["order_id"])
    assert order["addon_total_cents"] == 7282, "1436 + 5846 = 7282 (not round(8090*0.9)=7281)"


# ─── Queue B: calculations ───────────────────────────────────────────────────

def test_fuel_price_selection_latest_effective_wins(api):
    """PRD §3.3: "Candidates are ranked by `effective_date` from newest to oldest, so the
    most recent applicable price is preferred; when two candidates share the same effective
    date, the tie is broken in favor of the one with the later `created_at` (the more
    recently registered price wins)."

    Design: Corner/calculations/fuel_price_selection_latest_effective_wins
    """
    post_fuel_price(price_per_gallon_cents=419, effective_date="2026-04-01T00:00:00Z")
    post_fuel_price(price_per_gallon_cents=429, effective_date="2026-04-20T00:00:00Z")
    cust = new_customer(name="Wes", email="wes@x.com")
    veh = new_vehicle(cust["id"], make_model="Arteon")
    order = new_order(cust["id"], veh["id"], requested_gallons=10, delivery_address="Price St")
    assert order["locked_price_per_gallon_cents"] == 429, "later effective 2026-04-20 wins"
    assert order["estimated_fuel_cost_cents"] == 4290, "10 gal * 429 = 4290"


def test_order_rejected_when_no_price_effective_at_clock(api):
    """PRD §3.3: "the candidate set is every `FuelPrice` row whose `fuel_type` matches the
    order's fuel type and whose `zone` matches the order's zone and whose `effective_date`
    is at or before the current logical clock."
    PRD §3.3: "If the candidate set is empty — no price has been posted for that fuel type
    and zone at or before the clock — the operation is rejected with
    `ERR_NO_FUEL_PRICE_AVAILABLE`."

    Design: Corner/calculations/no_fuel_price_available_rejects_order
    """
    post_fuel_price(price_per_gallon_cents=419, effective_date="2026-06-01T00:00:00Z")
    cust = new_customer(name="Xan", email="xan@x.com")
    veh = new_vehicle(cust["id"], make_model="T-Cross")
    res = api.create_order(
        {"customer_id": cust["id"], "vehicle_id": veh["id"], "zone": "ZONE_A",
         "delivery_address": "NoPrice St", "requested_gallons": 10,
         "delivery_window_start": "2026-05-02T09:00:00Z",
         "delivery_window_end": "2026-05-02T11:00:00Z"},
        make_member_headers(cust["id"]))
    validate_error(res, "ERR_NO_FUEL_PRICE_AVAILABLE", expected_status=422)


def test_non_member_addon_charged_full_price(api):
    """PRD §3.7: "for a non-member order, the charged price equals the list price with no
    discount."
    PRD §3.7: "The catalog price is 1595 cents for a `CAR_WASH` and 6495 cents for an
    `OIL_CHANGE`."

    Design: Corner/calculations/non_member_addon_full_price_no_discount
    """
    post_fuel_price()
    cust = new_customer(name="Yas", email="yas@x.com")
    veh = new_vehicle(cust["id"], make_model="Taos")
    order = new_order(cust["id"], veh["id"], requested_gallons=8, delivery_address="Wash St")
    res = api.add_addon(order["id"], {"addon_type": "CAR_WASH"},
                        make_member_headers(cust["id"]))
    addon = validate_success(res, 201)
    assert addon["charged_price_cents"] == 1595, "non-member CAR_WASH billed full 1595"
    refreshed = get_order(order["id"])
    assert refreshed["addon_total_cents"] == 1595


def test_deliver_rejects_dispense_over_requested(api):
    """PRD §3.6: "The dispensed amount must not exceed the `requested_gallons` booked on the
    order, or the delivery is rejected with `ERR_DISPENSE_EXCEEDS_REQUESTED`;"

    Design: Corner/calculations/dispense_exceeds_requested_rejected
    """
    post_fuel_price()
    cust = new_customer(name="Zed", email="zed@x.com")
    veh = new_vehicle(cust["id"], make_model="Tiguan")
    truck = new_truck(plate="TRK-Z")
    new_compartment(truck["id"])
    route = new_route(truck["id"], assigned_driver_id="driver-z")
    order = new_order(cust["id"], veh["id"], requested_gallons=8, delivery_address="Disp St")
    drive_order_to_arrived(order["id"], route["id"], "driver-z")
    res = api.deliver_order(order["id"], {"dispensed_gallons": 9},
                            make_driver_headers("driver-z"))
    validate_error(res, "ERR_DISPENSE_EXCEEDS_REQUESTED", expected_status=422)
    assert get_order(order["id"])["status"] == "ARRIVED"
