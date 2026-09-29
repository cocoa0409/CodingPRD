"""Composite setup helpers.

Every test starts against an empty database, so each helper below builds the
state it needs from scratch through the public API. Setup calls use the lenient
``get_success_data`` validator so a broken preamble reports "Setup failed"
rather than an opaque assertion deep inside a test.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK
from .factories import (
    create_backhaul_offer_payload,
    create_domicile_payload,
    create_driver_payload,
    create_order_payload,
    create_pay_plan_payload,
    create_route_posting_payload,
    create_store_payload,
    create_telematics_event_payload,
    create_tractor_payload,
    create_trailer_payload,
    create_trip_payload,
    create_work_order_payload,
    delivery_stop_payload,
    non_delivery_stop_payload,
)
from .test_users import TEST_USERS, make_driver_headers

PLANNER = TEST_USERS["fleet_planner_headers"]
MANAGER = TEST_USERS["transport_manager_headers"]
PAYROLL = TEST_USERS["payroll_analyst_headers"]
SAFETY = TEST_USERS["safety_manager_headers"]
MAINTENANCE = TEST_USERS["maintenance_coordinator_headers"]


# ---------------------------------------------------------------- clock ----


def set_clock(instant: str = DEFAULT_CLOCK, headers=None) -> dict:
    """Move the logical clock. Any role may do this."""
    return get_success_data(
        api_client.set_current_utc({"current_utc": instant}, headers or PLANNER)
    )


# ------------------------------------------------- single-entity builders ----


def new_store(**overrides) -> dict:
    return get_success_data(api_client.create_store(create_store_payload(**overrides), PLANNER))


def new_domicile(**overrides) -> dict:
    return get_success_data(
        api_client.create_domicile(create_domicile_payload(**overrides), PLANNER)
    )


def new_pay_plan(**overrides) -> dict:
    return get_success_data(
        api_client.create_pay_plan(create_pay_plan_payload(**overrides), PAYROLL)
    )


def new_driver(domicile_id: str, pay_plan_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_driver(
            create_driver_payload(domicile_id, pay_plan_id, **overrides), MANAGER
        )
    )


def new_tractor(domicile_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_tractor(create_tractor_payload(domicile_id, **overrides), MAINTENANCE)
    )


def new_trailer(domicile_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_trailer(create_trailer_payload(domicile_id, **overrides), MAINTENANCE)
    )


def new_order(store_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_order(create_order_payload(store_id, **overrides), PLANNER)
    )


def new_trip(domicile_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_trip(create_trip_payload(domicile_id, **overrides), PLANNER)
    )


def new_backhaul_offer(dest_store_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_backhaul_offer(
            create_backhaul_offer_payload(dest_store_id, **overrides), headers or PLANNER
        )
    )


def new_work_order(headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_work_order(create_work_order_payload(**overrides), headers or MAINTENANCE)
    )


def new_route_posting(domicile_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_route_posting(
            create_route_posting_payload(domicile_id, **overrides), headers or MANAGER
        )
    )


def new_telematics_event(driver_id: str, event_type: str, severity: int,
                         occurred_at: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_telematics_event(
            create_telematics_event_payload(
                driver_id, event_type, severity, occurred_at, **overrides
            ),
            SAFETY,
        )
    )


def coach_event(event_id: str, note: str = "Reviewed with driver") -> dict:
    return get_success_data(
        api_client.coach_telematics_event(event_id, {"coaching_note": note}, SAFETY)
    )


# ------------------------------------------------------------- stop builders ----


def add_delivery_stop(trip_id: str, store_id: str, order_id: str, sequence: int,
                      arrival: str, departure: str, drive_minutes: int, miles: int,
                      cases: int, segment_loaded: bool = True, **overrides) -> dict:
    return get_success_data(
        api_client.add_trip_stop(
            trip_id,
            delivery_stop_payload(
                sequence, store_id, order_id, arrival, departure, drive_minutes, miles,
                cases, segment_loaded, **overrides
            ),
            PLANNER,
        )
    )


def add_other_stop(trip_id: str, stop_type: str, sequence: int, arrival: str, departure: str,
                   drive_minutes: int, miles: int, segment_loaded: bool = False,
                   **overrides) -> dict:
    return get_success_data(
        api_client.add_trip_stop(
            trip_id,
            non_delivery_stop_payload(
                sequence, stop_type, arrival, departure, drive_minutes, miles,
                segment_loaded, **overrides
            ),
            PLANNER,
        )
    )


# ---------------------------------------------------------- trip lifecycle ----


def assign_resources(trip_id: str, driver_id: str, tractor_id: str, trailer_id: str) -> dict:
    return get_success_data(
        api_client.assign_trip_resources(
            trip_id,
            {"driver_id": driver_id, "tractor_id": tractor_id, "trailer_id": trailer_id},
            MANAGER,
        )
    )


def plan_trip(trip_id: str) -> dict:
    return get_success_data(api_client.plan_trip(trip_id, PLANNER))


def dispatch_trip(trip_id: str) -> dict:
    return get_success_data(api_client.dispatch_trip(trip_id, MANAGER))


def run_stop(stop_id: str, driver_id: str, cases_handled=None) -> dict:
    """Arrive at a stop and complete it as its owning driver."""
    get_success_data(api_client.arrive_at_stop(stop_id, make_driver_headers(driver_id)))
    payload = {} if cases_handled is None else {"cases_handled": cases_handled}
    return get_success_data(
        api_client.complete_stop(stop_id, payload, make_driver_headers(driver_id))
    )


def close_out_trip(trip_id: str, actual_drive_minutes: int, actual_duty_minutes: int) -> dict:
    return get_success_data(
        api_client.complete_trip(
            trip_id,
            {
                "actual_drive_minutes": actual_drive_minutes,
                "actual_duty_minutes": actual_duty_minutes,
            },
            MANAGER,
        )
    )


def link_offer(trip_id: str, offer_id: str, expected_trip_version: int) -> dict:
    return get_success_data(
        api_client.link_backhaul_offer(
            trip_id,
            {"backhaul_offer_id": offer_id, "expected_trip_version": expected_trip_version},
            MANAGER,
        )
    )


def review_offer(offer_id: str, headers=None) -> dict:
    return get_success_data(api_client.submit_offer_review(offer_id, headers or PLANNER))


def accept_offer(offer_id: str, headers=None, margin_exception_approved=None) -> dict:
    payload = {} if margin_exception_approved is None else {
        "margin_exception_approved": margin_exception_approved
    }
    return get_success_data(api_client.accept_offer(offer_id, headers or MANAGER, payload))


def place_bid(driver_id: str, posting_id: str, expected_posting_version: int) -> dict:
    return get_success_data(
        api_client.create_route_bid(
            {
                "route_posting_id": posting_id,
                "expected_posting_version": expected_posting_version,
            },
            make_driver_headers(driver_id),
        )
    )


def read_trip(trip_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_trip(trip_id, headers or MANAGER))


def read_driver(driver_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_driver(driver_id, headers or MANAGER))


def read_tractor(tractor_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_tractor(tractor_id, headers or MAINTENANCE))


def read_store(store_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_store(store_id, headers or PLANNER))


def read_offer(offer_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_backhaul_offer(offer_id, headers or PLANNER))


def read_posting(posting_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_route_posting(posting_id, headers or MANAGER))


def adjust_duty_log(driver_id: str, **counters) -> dict:
    return get_success_data(api_client.adjust_duty_log(driver_id, dict(counters), MANAGER))


def charge_penalty_events(driver_id: str, specs) -> list:
    """Create one telematics event per (event_type, severity, occurred_at) triple."""
    return [
        new_telematics_event(driver_id, event_type, severity, occurred_at)
        for event_type, severity, occurred_at in specs
    ]


# ------------------------------------------------------ composite: base fleet ----


def setup_base_fleet(suffix: str = "1", store_overrides=None, domicile_overrides=None,
                     pay_plan_overrides=None, driver_overrides=None, tractor_overrides=None,
                     trailer_overrides=None, order_overrides=None, set_default_clock: bool = True):
    """Store + domicile + pay plan + driver + tractor + trailer + one open order.

    The codes are suffixed so a single test can build several disjoint rosters
    without tripping the uniqueness rules.
    """
    if set_default_clock:
        set_clock()
    store = new_store(**{"store_code": "S-90" + suffix, **(store_overrides or {})})
    domicile = new_domicile(**{"domicile_code": "DOM-90" + suffix, **(domicile_overrides or {})})
    pay_plan = new_pay_plan(**{"plan_code": "PLAN-90" + suffix, **(pay_plan_overrides or {})})
    driver = new_driver(
        domicile["id"], pay_plan["id"], **{"driver_code": "D-90" + suffix, **(driver_overrides or {})}
    )
    tractor = new_tractor(domicile["id"], **{"unit_code": "TR-90" + suffix, **(tractor_overrides or {})})
    trailer = new_trailer(
        domicile["id"], **{"trailer_code": "VAN-90" + suffix, **(trailer_overrides or {})}
    )
    order = new_order(store["id"], **(order_overrides or {}))
    return {
        "store": store,
        "domicile": domicile,
        "pay_plan": pay_plan,
        "driver": driver,
        "tractor": tractor,
        "trailer": trailer,
        "order": order,
    }


# -------------------------------------------------- composite: canonical trip ----

F1_PLAN = {
    "plan_code": "MILE-A",
    "mileage_cents_per_mile": 78,
    "stop_cents_per_stop": 2200,
    "drop_hook_cents": 1500,
    "hourly_cents_per_minute": 42,
    "minimum_daily_cents": 24000,
    "backhaul_bonus_pct": 0.05,
}

F1_STORE = {
    "store_code": "S-1001",
    "region_code": "MIDWEST",
    "dock_count": 2,
    "cases_per_hour_unload_rate": 600,
    "dock_open_minute": 240,
    "dock_close_minute": 1320,
}

F1_DOMICILE = {
    "domicile_code": "DOM-CHI",
    "region_code": "MIDWEST",
    "tractor_capacity": 40,
    "driver_headcount_target": 20,
    "fixed_ownership_cents_per_day": 12000,
    "overhead_cents_per_day": 4000,
    "dedicated_rate_cents_per_mile": 285,
    "dedicated_rate_cents_per_case": 210,
}

F1_ORDER = {
    "cases": 900,
    "weight_lbs": 21000,
    "requested_window_start": "2026-08-03T08:00:00Z",
    "requested_window_end": "2026-08-03T12:00:00Z",
    "temperature_mode": "DRY",
    "priority": 2,
}


def setup_f1(stage: str = "completed", pay_plan_overrides=None, store_overrides=None,
             domicile_overrides=None, driver_overrides=None, tractor_overrides=None,
             trailer_overrides=None, order_overrides=None, trip_overrides=None,
             actual_drive_minutes: int = 340, actual_duty_minutes: int = 560,
             offer=None, offer_headers=None, accept_headers=None):
    """The canonical three-stop dedicated trip.

    Stops: a 900-case delivery at S-1001, a vendor pickup, and a drop-off.
    Distances add up to 273 miles (205 loaded / 68 empty) and 335 drive minutes.

    ``stage`` stops the build at ``assigned``, ``planned``, ``dispatched``,
    ``stops_done`` or ``completed``. When ``offer`` is a payload dict the offer is
    created, sent for review, linked to the planned trip and only then accepted --
    acceptance requires a trip to already link the offer.
    """
    set_clock()
    store = new_store(**{**F1_STORE, **(store_overrides or {})})
    domicile = new_domicile(**{**F1_DOMICILE, **(domicile_overrides or {})})
    pay_plan = new_pay_plan(**{**F1_PLAN, **(pay_plan_overrides or {})})
    driver = new_driver(
        domicile["id"],
        pay_plan["id"],
        **{"driver_code": "D-77", "seniority_date": "2019-03-04", **(driver_overrides or {})},
    )
    tractor = new_tractor(
        domicile["id"],
        **{
            "unit_code": "TR-501",
            "odometer_miles": 124800,
            "pm_interval_miles": 25000,
            "pm_last_service_odometer": 100000,
            **(tractor_overrides or {}),
        },
    )
    trailer = new_trailer(
        domicile["id"],
        **{
            "trailer_code": "VAN-900",
            "trailer_type": "DRY_VAN",
            "capacity_cases": 1800,
            "inspection_due_at": "2026-12-01T00:00:00Z",
            **(trailer_overrides or {}),
        },
    )
    order = new_order(store["id"], **{**F1_ORDER, **(order_overrides or {})})
    trip = new_trip(
        domicile["id"],
        **{
            "trip_code": "TRIP-1",
            "planned_start_at": "2026-08-03T07:00:00Z",
            **(trip_overrides or {}),
        },
    )
    stop1 = add_delivery_stop(
        trip["id"], store["id"], order["id"], 1,
        "2026-08-03T09:00:00Z", "2026-08-03T10:45:00Z", 150, 150, 900, True,
    )
    stop2 = add_other_stop(
        trip["id"], "VENDOR_PICKUP", 2,
        "2026-08-03T12:00:00Z", "2026-08-03T12:45:00Z", 80, 68, False, cases=400,
    )
    stop3 = add_other_stop(
        trip["id"], "DROP_OFF", 3,
        "2026-08-03T14:30:00Z", "2026-08-03T14:50:00Z", 105, 55, True, cases=400,
    )
    ctx = {
        "store": store,
        "domicile": domicile,
        "pay_plan": pay_plan,
        "driver": driver,
        "tractor": tractor,
        "trailer": trailer,
        "order": order,
        "trip": trip,
        "stops": [stop1, stop2, stop3],
    }
    assign_resources(trip["id"], driver["id"], tractor["id"], trailer["id"])
    if stage == "assigned":
        ctx["trip"] = read_trip(trip["id"])
        return ctx

    planned = plan_trip(trip["id"])
    ctx["planned_trip"] = planned
    if offer is not None:
        created = new_backhaul_offer(store["id"], headers=offer_headers, **offer)
        ctx["reviewed_offer"] = review_offer(created["id"], offer_headers)
        link_offer(trip["id"], created["id"], planned["version"])
        accept_offer(created["id"], accept_headers)
        ctx["offer"] = read_offer(created["id"])
    if stage == "planned":
        ctx["trip"] = read_trip(trip["id"])
        return ctx

    dispatch_trip(trip["id"])
    if stage == "dispatched":
        ctx["trip"] = read_trip(trip["id"])
        return ctx

    for stop in (stop1, stop2, stop3):
        run_stop(stop["id"], driver["id"])
    if stage == "stops_done":
        ctx["trip"] = read_trip(trip["id"])
        return ctx

    close_out_trip(trip["id"], actual_drive_minutes, actual_duty_minutes)
    ctx["trip"] = read_trip(trip["id"])
    return ctx
