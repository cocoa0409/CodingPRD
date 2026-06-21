"""Depth tests: dual-variant calculations and combinatorial formulas.

Covers queue A rules: dual_variant_calc, combinatorial_formula.
"""
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    make_crew_headers,
    fixtures as fx,
)


# =====================================================================
# dual_variant_calc / invoice_finalized_vs_provisional_diverges_on_contract
# =====================================================================

def test_provisional_balance_and_finalized_invoice_diverge(api):
    """PRD §3.6: "This provisional balance is an incremental running figure — base seeded at activation, then surcharges added on each completion and credits subtracted on each skip approval — and it deliberately omits the final tax pass and the wallet and deposit application."
    PRD §3.9: "Tax is applied once on that subtotal: `tax_cents` is the subtotal multiplied by a tax rate of 7 percent (0.07), rounded half up a single time on the whole subtotal — never per line."

    Setup: contract price 30000, deposit 5000; a SNOW visit depth 4.0 (surcharge
    floor(2.0)*500 = 1000) and a FERTILIZATION visit (surcharge 2500), both COMPLETED.
    Provisional accrued_balance = 30000 + 1000 + 2500 = 33500.
    Finalized subtotal = 33500; tax = round(33500*0.07) = 2345;
    total_due = 33500 + 2345 - 0 wallet - 5000 deposit = 30845.

    Design: Difficulty/dual_variant_calc/invoice_finalized_vs_provisional_diverges_on_contract
    """
    cust = fx.make_customer(service_zip="10001")
    prop = fx.make_property(cust["id"], zip="10001")
    fx.make_preference(cust["id"], prop["id"], grass_height_mm=40, fertilization_enabled=False)
    con = fx.make_contract(cust["id"], prop["id"], season="WINTER",
                           contract_price_cents=30000, term_months=3,
                           prepaid_deposit_cents=5000)
    fx.activate(cust["id"], con["id"])
    route = fx.make_route(region_zip="10001")
    stop = fx.make_route_stop(route["id"], prop["id"], base_service_minutes=30, travel_minutes=10)
    crew = fx.make_crew(route["id"])
    fx.make_equipment(route_id=route["id"], equipment_type="PLOW", age_months=12)

    snow_visit = fx.make_visit(con["id"], stop["id"], service_type="SNOW",
                               snow_depth_in=4.0, runtime_hours=2)
    fx.dispatch(snow_visit["id"])
    fx.complete(snow_visit["id"], crew["id"])

    fert_visit = fx.make_visit(con["id"], stop["id"], service_type="FERTILIZATION",
                               runtime_hours=1)
    fx.dispatch(fert_visit["id"])
    fx.complete(fert_visit["id"], crew["id"])

    con_before = fx.get_contract(con["id"])
    assert con_before["accrued_balance_cents"] == 33500, \
        f"provisional balance should be 33500, got {con_before['accrued_balance_cents']}"

    closed = validate_success(api.close_season(con["id"], TEST_USERS["dispatcher_headers"]))
    assert closed["status"] == "CLOSED"

    invoices = get_success_data(
        api.list_contract_invoices(con["id"], TEST_USERS["dispatcher_headers"])
    )
    inv = invoices[0]
    assert inv["subtotal_cents"] == 33500, f"subtotal should be 33500, got {inv['subtotal_cents']}"
    assert inv["tax_cents"] == 2345, f"tax should be 2345, got {inv['tax_cents']}"
    assert inv["total_due_cents"] == 30845, f"total_due should be 30845, got {inv['total_due_cents']}"


def test_finalized_total_differs_from_provisional_number(api):
    """PRD §3.9: "The invoice's `total_due_cents` is the subtotal plus tax, minus that applied wallet amount, minus the contract's `prepaid_deposit_cents`, with the result floored at zero so a fully-prepaid season never produces a negative amount due."

    Asserts the finalized total_due (30845) is a different number than the provisional
    accrued_balance_cents (33500) for identical visit data.

    Design: Difficulty/dual_variant_calc/invoice_finalized_vs_provisional_diverges_on_contract
    """
    cust = fx.make_customer(service_zip="10001")
    prop = fx.make_property(cust["id"], zip="10001")
    con = fx.make_contract(cust["id"], prop["id"], season="WINTER",
                           contract_price_cents=30000, term_months=3,
                           prepaid_deposit_cents=5000)
    fx.activate(cust["id"], con["id"])
    route = fx.make_route(region_zip="10001")
    stop = fx.make_route_stop(route["id"], prop["id"], base_service_minutes=30, travel_minutes=10)
    crew = fx.make_crew(route["id"])
    fx.make_equipment(route_id=route["id"], equipment_type="PLOW", age_months=12)

    snow_visit = fx.make_visit(con["id"], stop["id"], service_type="SNOW",
                               snow_depth_in=4.0, runtime_hours=2)
    fx.dispatch(snow_visit["id"])
    fx.complete(snow_visit["id"], crew["id"])
    fert_visit = fx.make_visit(con["id"], stop["id"], service_type="FERTILIZATION",
                               runtime_hours=1)
    fx.dispatch(fert_visit["id"])
    fx.complete(fert_visit["id"], crew["id"])

    provisional = fx.get_contract(con["id"])["accrued_balance_cents"]
    fx.api_client.close_season(con["id"], TEST_USERS["dispatcher_headers"])
    inv = get_success_data(api.list_contract_invoices(con["id"], TEST_USERS["dispatcher_headers"]))[0]
    assert provisional == 33500
    assert inv["total_due_cents"] == 30845
    assert inv["total_due_cents"] != provisional, \
        "finalized total must differ from provisional accrued balance"


# =====================================================================
# dual_variant_calc / equipment_wear_estimated_vs_actual_diverges
# =====================================================================

def test_wear_estimate_forecasts_inflight_visit_above_actual(api):
    """PRD §3.5: "It is computed exactly like the actual score but on projected counters: it adds the in-flight visit's projected `runtime_hours` to the hours-since-service term and adds one more dispatch to the dispatch term, before completion is applied."
    PRD §3.5: "The read returns the asset's `equipment_id`, its forecast `estimated_wear_score`, and its current `actual_wear_score` side by side."

    Equipment age 24, one COMPLETED 20h visit -> actual = round(2*20 + 5*1 + 0.5*24)
    = round(40 + 5 + 12) = 57. A second visit DISPATCHED with runtime 10:
    estimated = round(2*(20+10) + 5*(1+1) + 0.5*24) = round(60 + 10 + 12) = 82.

    Design: Difficulty/dual_variant_calc/equipment_wear_estimated_vs_actual_diverges
    """
    cust = fx.make_customer(service_zip="20002")
    prop = fx.make_property(cust["id"], zip="20002")
    con = fx.make_contract(cust["id"], prop["id"], season="WINTER",
                           contract_price_cents=20000, term_months=4)
    fx.activate(cust["id"], con["id"])
    route = fx.make_route(region_zip="20002")
    stop = fx.make_route_stop(route["id"], prop["id"], base_service_minutes=30)
    crew = fx.make_crew(route["id"])
    eq = fx.make_equipment(route_id=route["id"], equipment_type="MOWER", age_months=24)

    v1 = fx.make_visit(con["id"], stop["id"], service_type="LAWN", runtime_hours=20)
    fx.dispatch(v1["id"])
    fx.complete(v1["id"], crew["id"])

    v2 = fx.make_visit(con["id"], stop["id"], service_type="LAWN", runtime_hours=10)
    fx.dispatch(v2["id"])

    est = validate_success(api.get_wear_estimate(eq["id"], TEST_USERS["dispatcher_headers"]))
    assert est["actual_wear_score"] == 57, f"actual should be 57, got {est['actual_wear_score']}"
    assert est["estimated_wear_score"] == 82, f"estimated should be 82, got {est['estimated_wear_score']}"


def test_wear_estimate_does_not_mutate_stored_score(api):
    """PRD §3.5: "The estimate is purely a read; it is never written back to the equipment's stored `wear_score`."

    After reading the estimate (82), the persisted Equipment.wear_score stays at the
    actual value (57).

    Design: Difficulty/dual_variant_calc/equipment_wear_estimated_vs_actual_diverges
    """
    cust = fx.make_customer(service_zip="20002")
    prop = fx.make_property(cust["id"], zip="20002")
    con = fx.make_contract(cust["id"], prop["id"], season="WINTER",
                           contract_price_cents=20000, term_months=4)
    fx.activate(cust["id"], con["id"])
    route = fx.make_route(region_zip="20002")
    stop = fx.make_route_stop(route["id"], prop["id"], base_service_minutes=30)
    crew = fx.make_crew(route["id"])
    eq = fx.make_equipment(route_id=route["id"], equipment_type="MOWER", age_months=24)

    v1 = fx.make_visit(con["id"], stop["id"], service_type="LAWN", runtime_hours=20)
    fx.dispatch(v1["id"])
    fx.complete(v1["id"], crew["id"])
    v2 = fx.make_visit(con["id"], stop["id"], service_type="LAWN", runtime_hours=10)
    fx.dispatch(v2["id"])

    api.get_wear_estimate(eq["id"], TEST_USERS["dispatcher_headers"])
    persisted = fx.get_equipment(eq["id"])
    assert persisted["wear_score"] == 57, \
        f"stored wear_score must remain 57 after estimate read, got {persisted['wear_score']}"


# =====================================================================
# combinatorial_formula / route_load_overtime_tier_nonlinear
# =====================================================================

def test_route_load_overtime_tier_nonlinear(api):
    """PRD §3.5/§3.3: "a `daily_capacity_minutes` ceiling greater than zero, above which an overtime tier applies during load computation."
    PRD §2.5 / §3.5 wear-and-load rounding: minutes are an integer.

    Capacity 480, one stop base 300 travel 0, reading depth 5.0 (>=4.0 tier -> 2.0x):
    stop minutes = round(300*2.0) + 0 = 600. raw 600 > 480, so
    load = 480 + round((600-480)*1.5) = 480 + 180 = 660.

    Design: Difficulty/combinatorial_formula/route_load_overtime_tier_nonlinear
    """
    cust = fx.make_customer(service_zip="30003")
    prop = fx.make_property(cust["id"], zip="30003", lawn_area_sqft=9000)
    con = fx.make_contract(cust["id"], prop["id"], season="WINTER",
                           contract_price_cents=50000, term_months=5)
    fx.activate(cust["id"], con["id"])
    route = fx.make_route(region_zip="30003", daily_capacity_minutes=480)
    fx.make_route_stop(route["id"], prop["id"], sequence=1,
                       base_service_minutes=300, travel_minutes=0)
    fx.make_crew(route["id"])
    fx.make_equipment(route_id=route["id"], equipment_type="PLOW", age_months=6)
    wr = fx.make_weather_reading(region_zip="30003", snow_depth_in=5.0,
                                 observed_at="2026-01-10T06:00:00Z")

    result = validate_success(
        api.process_weather_reading(wr["id"], {"route_id": route["id"]},
                                    TEST_USERS["dispatcher_headers"])
    )
    assert result["last_dispatch_load_minutes"] == 660, \
        f"load should be 660, got {result['last_dispatch_load_minutes']}"
    assert result["status"] == "DISPATCHED"
    reading = fx.get_weather_reading(wr["id"])
    assert reading["processed"] is True


def test_route_load_dispatch_marks_reading_processed(api):
    """PRD §3.4: "The reading's `processed` flag is set to true, and the route's `status` becomes `DISPATCHED`."

    Same overtime-tier scenario; asserts the route transitions to DISPATCHED on the
    over-capacity load.

    Design: Difficulty/combinatorial_formula/route_load_overtime_tier_nonlinear
    """
    cust = fx.make_customer(service_zip="30003")
    prop = fx.make_property(cust["id"], zip="30003", lawn_area_sqft=9000)
    con = fx.make_contract(cust["id"], prop["id"], season="WINTER",
                           contract_price_cents=50000, term_months=5)
    fx.activate(cust["id"], con["id"])
    route = fx.make_route(region_zip="30003", daily_capacity_minutes=480)
    fx.make_route_stop(route["id"], prop["id"], sequence=1,
                       base_service_minutes=300, travel_minutes=0)
    fx.make_crew(route["id"])
    fx.make_equipment(route_id=route["id"], equipment_type="PLOW", age_months=6)
    wr = fx.make_weather_reading(region_zip="30003", snow_depth_in=5.0)

    validate_success(
        api.process_weather_reading(wr["id"], {"route_id": route["id"]},
                                    TEST_USERS["dispatcher_headers"])
    )
    assert fx.get_route(route["id"])["status"] == "DISPATCHED"
    assert fx.get_weather_reading(wr["id"])["processed"] is True


# =====================================================================
# combinatorial_formula / lawn_skip_credit_round_per_day_before_multiply
# =====================================================================

def test_lawn_skip_credit_rounds_per_day_before_multiply(api):
    """PRD §3.7: "the platform first derives a monthly equivalent of the seasonal base by dividing the contract's `contract_price_cents` by its `term_months`, then derives a daily rate by dividing that monthly figure across 30 billing days and rounding the daily rate half up to the cent, and finally multiplies that rounded daily rate by 3 days — the number of days one lawn skip represents."
    PRD §3.7: "The rounding happens per day, before the multiplication by three; the platform must not sum first and round once."

    price 40000, term 5: monthly = 8000; daily = round(8000/30) = round(266.67) = 267;
    credit = 267 * 3 = 801 (sum-then-round would give round(8000/30*3)=800).

    Design: Difficulty/combinatorial_formula/lawn_skip_credit_round_per_day_before_multiply
    """
    ctx, visit, skip = fx.setup_pending_skip(
        zip="40004",
        contract_overrides={"season": "SUMMER", "contract_price_cents": 40000,
                            "term_months": 5},
        visit_overrides={"service_type": "LAWN", "runtime_hours": 1},
    )
    approved = validate_success(
        api.approve_skip_request(skip["id"], TEST_USERS["dispatcher_headers"])
    )
    assert approved["credit_cents"] == 801, \
        f"LAWN skip credit should be 801 (round-per-day), got {approved['credit_cents']}"
    assert approved["status"] == "APPROVED"


def test_lawn_skip_credit_lands_in_wallet_and_skips_visit(api):
    """PRD §3.7: "Approval is a coupled transition: it moves the visit from `SCHEDULED` to `SKIPPED`, computes the request's `credit_cents`, sets the request's `status` to `APPROVED`, adds that credit to the customer's `wallet_credit_cents`, and subtracts the same credit from the contract's provisional `accrued_balance_cents`."

    Asserts the 801-cent LAWN credit reaches the wallet and the visit becomes SKIPPED.

    Design: Difficulty/combinatorial_formula/lawn_skip_credit_round_per_day_before_multiply
    """
    ctx, visit, skip = fx.setup_pending_skip(
        zip="40004",
        contract_overrides={"season": "SUMMER", "contract_price_cents": 40000,
                            "term_months": 5},
        visit_overrides={"service_type": "LAWN", "runtime_hours": 1},
    )
    fx.approve_skip(skip["id"])
    assert fx.get_visit(visit["id"])["status"] == "SKIPPED"
    assert fx.get_customer(ctx["customer"]["id"])["wallet_credit_cents"] == 801
