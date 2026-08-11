"""Mobile routing: dispatch, mobile final pricing, and the trip surcharge."""
from test_helpers import (
    ApiErrorId, TEST_USERS, add_car_with_inspection, add_price_entry, api_client,
    build_work_order, create_brc_for_current_wo, make_repair_foreman_headers,
    scenario_completed_wo, setup_shop_ctx, submit_current_brc,
    validate_error, validate_success,
)

ADMIN = TEST_USERS["shop_admin"]
FOREMAN = "foreman-1"


def test_mobile_routing_dispatch_and_surcharge_on_brc():
    """PRD §2.7: "the labor rate is the entry's
    `mobile_labor_rate_cents_per_hour` when the work order's `routing` is
    `MOBILE`, otherwise its `labor_rate_cents_per_hour`."
    PRD §3.7: "For a `MOBILE`-routed work order, the card's
    `mobile_surcharge_cents` is the `mobile_trip_surcharge_cents` of the price
    entry used by the earliest-created repair line — ties broken by line
    creation order — and is zero for `SHOP` routing. The `submitted_total_cents`
    is the sum of line final amounts plus the surcharge."
    PRD §3.5: "mobile starts carry no slot or car cascade"

    Design: Corner/state_machines/mobile_routing_dispatch_and_surcharge_on_brc
    """
    ctx = scenario_completed_wo(
        routing="MOBILE", actual_hours=2.0,
        part={"part_number": "H-100", "unit_price_cents": 4500, "on_hand_qty": 10,
              "reorder_threshold": 2})
    car = validate_success(api_client.get_railcar(ctx["car"]["id"], ADMIN))
    assert car["status"] == "ARRIVED", "mobile work never moves the car into the shop"

    line = validate_success(api_client.get_repair_line(ctx["wo_lines"][0]["id"], ADMIN))
    assert line["final_labor_cents"] == 22000, "2.0 actual hours at the 11000 mobile rate"
    assert line["final_total_cents"] == 26500, "22000 labor + 4500 material"

    create_brc_for_current_wo(ctx)
    submit_current_brc(ctx)
    brc = ctx["brc"]
    assert brc["mobile_surcharge_cents"] == 25000, "trip surcharge applied once per mobile order"
    assert brc["submitted_total_cents"] == 51500, "26500 line + 25000 surcharge"


def test_mobile_route_with_wheelset_job_rejected():
    """PRD §3.3: "a `MOBILE`-routed work order requires every line's price
    entry to be `mobile_eligible`, else `ERR_MOBILE_ROUTE_NOT_ELIGIBLE`".

    Design: Corner/state_machines/mobile_route_with_wheelset_job_rejected
    """
    ctx = setup_shop_ctx()
    add_price_entry(ctx, job_code="J-WHEEL-REPL", description="Wheelset replacement",
                    labor_rate_cents_per_hour=12000, mobile_labor_rate_cents_per_hour=15000,
                    standard_labor_hours=4.0, mobile_trip_surcharge_cents=25000,
                    mobile_eligible=False)
    add_car_with_inspection(
        ctx, car_number="4006",
        defects=[{"aar_defect_code": "AAR-2001", "defect_group": "WHEELSET",
                  "cause_code": "WEAR", "severity": "CONDEMNABLE", "location": "L1"}])
    build_work_order(ctx, routing="MOBILE", lines=[{"job_code": "J-WHEEL-REPL"}])
    resp = api_client.submit_work_order(ctx["wo"]["id"],
                                        make_repair_foreman_headers(FOREMAN))
    validate_error(resp, ApiErrorId.ERR_MOBILE_ROUTE_NOT_ELIGIBLE, expected_status=409)
    wo = validate_success(api_client.get_work_order(ctx["wo"]["id"], ADMIN))
    assert wo["auth_status"] == "DRAFT", "rejected submit leaves the order in DRAFT"
