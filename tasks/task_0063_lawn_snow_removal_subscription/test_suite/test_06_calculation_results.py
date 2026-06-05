"""Breadth tests: surcharge, skip credit, route load, opt-out filtering.

Covers queue B section: calculations.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    TEST_USERS,
    fixtures as fx,
)


def test_snow_surcharge_floor_whole_inches(api):
    """PRD §3.6: "the platform takes the whole inches of snow over the 2.0-inch baseline — that is, the floor of (`snow_depth_in` minus 2.0) — and, only when that whole-inch overage is positive, adds 500 cents per whole inch over baseline."

    Depth 5.5: floor(5.5 - 2.0) = floor(3.5) = 3; surcharge = 3 * 500 = 1500.

    Design: Corner/calculations/snow_surcharge_floor_whole_inches
    """
    ctx, visit = fx.setup_dispatched_visit(
        zip="40001",
        contract_overrides={"contract_price_cents": 10000, "term_months": 3},
        visit_overrides={"service_type": "SNOW", "snow_depth_in": 5.5, "runtime_hours": 2},
        equipment_overrides={"equipment_type": "PLOW", "age_months": 2},
    )
    completed = validate_success(
        api.complete_visit(visit["id"], fx.make_crew_headers(ctx["crew"]["id"]))
    )
    assert completed["surcharge_cents"] == 1500, \
        f"snow surcharge should be 1500, got {completed['surcharge_cents']}"


def test_snow_skip_credit_flat(api):
    """PRD §3.7: "A skipped `SNOW` visit earns a flat credit of 1500 cents."

    Design: Corner/calculations/snow_skip_credit_flat
    """
    ctx, visit, skip = fx.setup_pending_skip(
        zip="40002",
        contract_overrides={"contract_price_cents": 40000, "term_months": 5},
        visit_overrides={"service_type": "SNOW", "snow_depth_in": 3.0, "runtime_hours": 2},
    )
    approved = validate_success(
        api.approve_skip_request(skip["id"], TEST_USERS["dispatcher_headers"])
    )
    assert approved["credit_cents"] == 1500
    assert fx.get_customer(ctx["customer"]["id"])["wallet_credit_cents"] == 1500


def test_fertilization_addon_on_lawn_when_preference_enabled(api):
    """PRD §3.6: "A fertilization component of 2500 cents applies to any visit whose `service_type` is `FERTILIZATION`, and also to any `LAWN` visit whose property preference has `fertilization_enabled` true."

    Design: Corner/calculations/fertilization_addon_on_lawn_when_preference_enabled
    """
    cust = fx.make_customer(service_zip="40003")
    prop = fx.make_property(cust["id"], zip="40003")
    fx.make_preference(cust["id"], prop["id"], grass_height_mm=40, fertilization_enabled=True)
    con = fx.make_contract(cust["id"], prop["id"], season="SUMMER",
                           contract_price_cents=10000, term_months=3)
    fx.activate(cust["id"], con["id"])
    route = fx.make_route(region_zip="40003")
    stop = fx.make_route_stop(route["id"], prop["id"], base_service_minutes=30)
    crew = fx.make_crew(route["id"])
    fx.make_equipment(route_id=route["id"], equipment_type="SPREADER", age_months=2)
    visit = fx.make_visit(con["id"], stop["id"], service_type="LAWN", runtime_hours=1)
    fx.dispatch(visit["id"])
    completed = validate_success(
        api.complete_visit(visit["id"], fx.make_crew_headers(crew["id"]))
    )
    assert completed["surcharge_cents"] == 2500


def test_route_load_no_overtime_under_capacity(api):
    """PRD §3.3: "a `daily_capacity_minutes` ceiling greater than zero, above which an
    overtime tier applies during load computation."

    Two stops (base 100 travel 10; base 120 travel 20) at depth 3.0 (1.5x):
    round(100*1.5)+10 = 160; round(120*1.5)+20 = 200; raw = 360 <= 480 -> load 360.

    Design: Corner/calculations/route_load_no_overtime_under_capacity
    """
    cust = fx.make_customer(service_zip="40004")
    prop1 = fx.make_property(cust["id"], zip="40004", address="Q4a", lawn_area_sqft=5000)
    prop2 = fx.make_property(cust["id"], zip="40004", address="Q4b", lawn_area_sqft=6000)
    con1 = fx.make_contract(cust["id"], prop1["id"], season="WINTER",
                            contract_price_cents=10000, term_months=3)
    fx.activate(cust["id"], con1["id"])
    con2 = fx.make_contract(cust["id"], prop2["id"], season="WINTER",
                            contract_price_cents=10000, term_months=3)
    fx.activate(cust["id"], con2["id"])
    route = fx.make_route(region_zip="40004", daily_capacity_minutes=480)
    fx.make_route_stop(route["id"], prop1["id"], sequence=1,
                       base_service_minutes=100, travel_minutes=10)
    fx.make_route_stop(route["id"], prop2["id"], sequence=2,
                       base_service_minutes=120, travel_minutes=20)
    fx.make_crew(route["id"])
    fx.make_equipment(route_id=route["id"], equipment_type="PLOW", age_months=2)
    wr = fx.make_weather_reading(region_zip="40004", snow_depth_in=3.0,
                                 observed_at="2026-01-14T06:00:00Z")
    result = validate_success(
        api.process_weather_reading(wr["id"], {"route_id": route["id"]},
                                    TEST_USERS["dispatcher_headers"])
    )
    assert result["last_dispatch_load_minutes"] == 360, \
        f"load should be 360, got {result['last_dispatch_load_minutes']}"
    assert result["status"] == "DISPATCHED"


def test_snow_optout_property_excluded_from_dispatch(api):
    """PRD §3.4: "For every active route stop on the route whose property is not snow-opted-out, the platform creates a `SNOW` service visit ... Stops belonging to opted-out properties (those whose preference has `snow_opt_out` true) are skipped entirely in this fan-out."

    The only stop is opted out: load == 0 and no SNOW visit is created.

    Design: Corner/calculations/snow_optout_property_excluded_from_dispatch
    """
    cust = fx.make_customer(service_zip="40005")
    prop = fx.make_property(cust["id"], zip="40005", lawn_area_sqft=5000)
    fx.make_preference(cust["id"], prop["id"], grass_height_mm=40, snow_opt_out=True)
    con = fx.make_contract(cust["id"], prop["id"], season="WINTER",
                           contract_price_cents=10000, term_months=3)
    fx.activate(cust["id"], con["id"])
    route = fx.make_route(region_zip="40005", daily_capacity_minutes=480)
    fx.make_route_stop(route["id"], prop["id"], sequence=1,
                       base_service_minutes=100, travel_minutes=10)
    fx.make_equipment(route_id=route["id"], equipment_type="PLOW", age_months=2)
    wr = fx.make_weather_reading(region_zip="40005", snow_depth_in=3.0,
                                 observed_at="2026-01-15T06:00:00Z")
    result = validate_success(
        api.process_weather_reading(wr["id"], {"route_id": route["id"]},
                                    TEST_USERS["dispatcher_headers"])
    )
    assert result["last_dispatch_load_minutes"] == 0
    assert result["status"] == "DISPATCHED"
    visits = get_success_data(
        api.list_contract_visits(con["id"], TEST_USERS["dispatcher_headers"])
    )
    assert visits == [], f"no SNOW visit should be created, got {visits}"
