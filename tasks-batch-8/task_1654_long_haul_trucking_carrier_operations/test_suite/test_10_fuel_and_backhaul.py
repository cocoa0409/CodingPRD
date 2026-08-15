"""Fuel purchasing (route membership, costing, tank capacity) and the
fuel-plan / backhaul selectors (PRD §3.3, §3.7)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_driver,
    create_fuel_rate,
    create_lane,
    create_tractor,
    get_tractor,
    make_dispatcher_headers,
    make_driver_headers,
    make_load_planner_headers,
    plan_trip,
    post_fuel_purchase,
    screen_load,
    set_clock,
    setup_dispatched_trip,
    setup_planned_trip,
    setup_refdata,
    tender_load,
    validate_error,
    validate_paginated,
    validate_success,
)

DISPATCHER = make_dispatcher_headers()
LOAD_PLANNER = make_load_planner_headers()


def test_fuel_purchase_off_route_rejected(api):
    """PRD §3.7: "The purchase state must lie on the trip's planned route: a
    `state_code` absent from the trip's `route_states` is rejected with
    `ERR_STATE_NOT_ON_ROUTE`."

    Design: Corner/validations/fuel_purchase_off_route_rejected
    """
    ctx = setup_dispatched_trip(cdl_number="CDL-V5", unit_number="T-V5")
    create_fuel_rate(state_code="GA", tax_cents_per_gallon=30,
                     avg_pump_price_cents=430)
    set_clock("2026-08-02T12:00:00Z")
    resp = api_client.create_trip_fuel_purchase(
        ctx["trip"]["id"],
        {"driver_id": ctx["driver"]["id"], "state_code": "GA", "gallons": 10,
         "pump_price_cents": 400, "purchased_at": "2026-08-02T12:00:00Z"},
        make_driver_headers(ctx["driver"]["id"]))
    validate_error(resp, ApiErrorId.ERR_STATE_NOT_ON_ROUTE)


def test_fuel_purchase_tank_capacity_boundary(api):
    """PRD §3.7: "The recorded figures are then `total_cost_cents`, the
    `gallons` multiplied by the `pump_price_cents`; `tax_paid_cents`, the
    `gallons` multiplied by the row's `tax_cents_per_gallon`; and
    `net_effective_price_cents`, the `pump_price_cents` minus the row's
    `tax_cents_per_gallon`."
    PRD §3.7: "The purchase also lands in the tank: the tractor's
    `current_fuel_gallons` increases by the `gallons` bought, and a purchase
    that would push the level above the tractor's `tank_capacity_gallons` is
    rejected with `ERR_TANK_CAPACITY_EXCEEDED`."
    (150 + 50 == 200 == capacity is allowed; one more gallon is not.)

    Design: Corner/validations/fuel_purchase_tank_capacity_boundary
    """
    ctx = setup_dispatched_trip(cdl_number="CDL-V6", unit_number="T-V6")
    create_fuel_rate(state_code="TX", tax_cents_per_gallon=20,
                     avg_pump_price_cents=400)
    set_clock("2026-08-02T12:00:00Z")
    purchase = post_fuel_purchase(
        ctx["trip"]["id"], ctx["driver"]["id"], state_code="TX", gallons=50,
        pump_price_cents=400, purchased_at="2026-08-02T12:00:00Z")
    assert purchase["total_cost_cents"] == 20000
    assert purchase["tax_paid_cents"] == 1000
    assert purchase["net_effective_price_cents"] == 380
    assert get_tractor(ctx["tractor"]["id"])["current_fuel_gallons"] == 200

    # purchased_at stays at the logical now (12:00) so the §3.7 future-timestamp
    # rule does not pre-empt the tank-capacity gate under test (pipeline order
    # §2.9: body validation precedes constraint rules).
    resp = api_client.create_trip_fuel_purchase(
        ctx["trip"]["id"],
        {"driver_id": ctx["driver"]["id"], "state_code": "TX", "gallons": 1,
         "pump_price_cents": 400, "purchased_at": "2026-08-02T12:00:00Z"},
        make_driver_headers(ctx["driver"]["id"]))
    validate_error(resp, ApiErrorId.ERR_TANK_CAPACITY_EXCEEDED)


def test_fuel_purchase_on_planned_trip_rejected(api):
    """PRD §3.7: "A purchase may be recorded by the trip's `Driver` or by a
    `Dispatcher`, but only while the trip is between `DISPATCHED` and
    `AT_DELIVERY` inclusive — a purchase against a `PLANNED`, `COMPLETED`, or
    `CANCELLED` trip is rejected with `ERR_TRIP_NOT_FUELABLE`."

    Design: Corner/errors/fuel_purchase_on_planned_trip_rejected
    """
    ctx = setup_planned_trip(cdl_number="CDL-R13", unit_number="T-R13")
    create_fuel_rate(state_code="TX", tax_cents_per_gallon=20,
                     avg_pump_price_cents=400)
    set_clock("2026-08-02T12:00:00Z")
    resp = api_client.create_trip_fuel_purchase(
        ctx["trip"]["id"],
        {"driver_id": ctx["driver"]["id"], "state_code": "TX", "gallons": 10,
         "pump_price_cents": 400, "purchased_at": "2026-08-02T12:00:00Z"},
        make_driver_headers(ctx["driver"]["id"]))
    validate_error(resp, ApiErrorId.ERR_TRIP_NOT_FUELABLE)


def test_fuel_plan_tie_breaks_toward_higher_tax(api):
    """PRD §3.7: "Each eligible state's effective price is its
    `avg_pump_price_cents` minus its `tax_cents_per_gallon`. The plan ranks
    eligible states by effective price ascending; a tie breaks toward the
    higher `tax_cents_per_gallon`, since tax paid there is recovered through
    equalization; a further tie breaks toward the state earlier in the route
    order."
    (TX 400-20 = 380 ties MS 405-25 = 380; the higher tax wins -> MS. AL has
    no current rate row and is not eligible.)

    Design: Corner/calculations/fuel_plan_tie_break_higher_tax
    """
    ctx = setup_refdata()
    create_fuel_rate(state_code="TX", tax_cents_per_gallon=20,
                     avg_pump_price_cents=400)
    create_fuel_rate(state_code="LA", tax_cents_per_gallon=30,
                     avg_pump_price_cents=415)
    create_fuel_rate(state_code="MS", tax_cents_per_gallon=25,
                     avg_pump_price_cents=405)
    create_fuel_rate(state_code="GA", tax_cents_per_gallon=35,
                     avg_pump_price_cents=430)
    driver = create_driver(cdl_number="CDL-C33")
    tractor = create_tractor(unit_number="T-C33")
    load = tender_load(ctx["customer"]["id"], ctx["lane"]["id"])
    screen_load(load["id"])
    validate_success(api_client.accept_load(load["id"], LOAD_PLANNER))
    trip = plan_trip(load["id"], driver["id"], tractor["id"], route_states=[
        {"state_code": "TX", "miles": 300}, {"state_code": "LA", "miles": 280},
        {"state_code": "MS", "miles": 120}, {"state_code": "AL", "miles": 120},
        {"state_code": "GA", "miles": 200}])
    plan = validate_success(api_client.get_trip_fuel_plan(trip["id"], DISPATCHER))
    assert plan["recommended_state"] == "MS"
    assert plan["effective_price_cents"] == 380
    states = [c.get("state_code") if isinstance(c, dict) else c
              for c in plan["candidates"]]
    assert "AL" not in states, "no current rate row -> not eligible"
    assert len(plan["candidates"]) == 4


def test_fuel_plan_empty_route_infeasible(api):
    """PRD §3.7: "A trip with an empty `route_states` list, or one whose
    reachable states all lack a current rate, has no plan and the query is
    rejected with `ERR_FUEL_PLAN_INFEASIBLE`."

    Design: Corner/calculations/fuel_plan_empty_route_infeasible
    """
    ctx = setup_planned_trip(cdl_number="CDL-C34", unit_number="T-C34",
                             trip_overrides={"route_states": []})
    resp = api_client.get_trip_fuel_plan(ctx["trip"]["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_FUEL_PLAN_INFEASIBLE)


def test_backhaul_ranked_by_effective_rpm_descending(api):
    """PRD §3.3: "Eligible candidates are loads in `SCREENED` or `ACCEPTED` —
    an `ACCEPTED` load by construction has no non-terminal trip, since
    assignment would have moved it to `ASSIGNED` — and loads still `TENDERED`
    never appear, because they carry no fuel surcharge until screened."
    PRD §3.3: "Candidates rank by that effective rate per mile descending;
    ties break toward the earlier `pickup_appt_at`, then toward the earlier
    load `created_at`."

    Design: Corner/calculations/backhaul_ranking_rpm_descending
    """
    ctx = setup_refdata(lane_overrides={"origin_state": "GA",
                                        "destination_state": "FL",
                                        "loaded_miles": 400,
                                        "rpm_floor_cents": 100})
    lane2 = create_lane(origin_state="GA", destination_state="TX",
                        loaded_miles=900, rpm_floor_cents=100)
    tractor = create_tractor(unit_number="T-C35", home_terminal="ATL",
                             current_state_code="GA")
    l_hi = tender_load(ctx["customer"]["id"], ctx["lane"]["id"],
                       rate_cents=200000, weight_lbs=40000,
                       pickup_appt_at="2026-08-04T08:00:00Z",
                       delivery_appt_at="2026-08-05T18:00:00Z")
    screen_load(l_hi["id"])  # FSC round_half_up(400*150/6.5) = 9231
    l_lo = tender_load(ctx["customer"]["id"], lane2["id"], rate_cents=100000,
                       weight_lbs=40000, pickup_appt_at="2026-08-04T08:00:00Z",
                       delivery_appt_at="2026-08-06T18:00:00Z")
    screen_load(l_lo["id"])
    tender_load(ctx["customer"]["id"], lane2["id"], rate_cents=100000,
                weight_lbs=40000, pickup_appt_at="2026-08-04T08:00:00Z",
                delivery_appt_at="2026-08-06T18:00:00Z")  # stays TENDERED

    rows, meta = validate_paginated(
        api_client.get_backhaul_candidates(DISPATCHER,
                                           params={"tractor_id": tractor["id"]}))
    assert meta["total_count"] == 2, "TENDERED loads never appear"
    assert rows[0]["id"] == l_hi["id"], "rpm round_half_up(209231/400) = 523"
    assert rows[1]["id"] == l_lo["id"], "rpm round_half_up(120769/900) = 134"


def test_backhaul_tie_breaks_toward_earlier_pickup(api):
    """PRD §3.3: "Candidates rank by that effective rate per mile descending;
    ties break toward the earlier `pickup_appt_at`, then toward the earlier
    load `created_at`."
    (Both loads carry rate 53077 on a 300-mile lane with FSC 6923 -> effective
    rpm exactly 200 for both; the earlier pickup wins despite being created
    second.)

    Design: Corner/calculations/backhaul_pickup_tie_break
    """
    ctx = setup_refdata(lane_overrides={"origin_state": "GA",
                                        "destination_state": "AL",
                                        "loaded_miles": 300,
                                        "rpm_floor_cents": 100})
    tractor = create_tractor(unit_number="T-C36", home_terminal="ATL",
                             current_state_code="GA")
    l_a = tender_load(ctx["customer"]["id"], ctx["lane"]["id"],
                      rate_cents=53077, weight_lbs=30000,
                      pickup_appt_at="2026-08-05T08:00:00Z",
                      delivery_appt_at="2026-08-06T18:00:00Z")
    screen_load(l_a["id"])
    l_b = tender_load(ctx["customer"]["id"], ctx["lane"]["id"],
                      rate_cents=53077, weight_lbs=30000,
                      pickup_appt_at="2026-08-04T08:00:00Z",
                      delivery_appt_at="2026-08-05T18:00:00Z")
    screen_load(l_b["id"])

    rows, meta = validate_paginated(
        api_client.get_backhaul_candidates(DISPATCHER,
                                           params={"tractor_id": tractor["id"]}))
    assert meta["total_count"] == 2
    assert rows[0]["id"] == l_b["id"], "earlier pickup wins the rpm tie"
    assert rows[1]["id"] == l_a["id"]
