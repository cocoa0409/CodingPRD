"""Composite setup helpers.

Every test starts against an empty database and a logical clock sitting at its startup
default, so every fixture here builds its preconditions from scratch using only the
endpoints the PRD declares. Setup calls go through `get_success_data()` so a broken
precondition surfaces as a clear "setup failed" rather than a confusing assertion.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_CLOCK, TEST_DEFAULTS
from .factories import (
    create_battery_payload,
    create_customer_payload,
    create_drone_payload,
    create_geofence_zone_payload,
    create_incident_payload,
    create_maintenance_log_payload,
    create_nest_payload,
    create_order_payload,
    create_service_area_payload,
    create_weather_observation_payload,
    dispatch_order_payload,
    drop_payload,
    file_authorization_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_dispatch_operator_headers,
    make_flight_director_headers,
    make_maintenance_tech_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPERATOR = TEST_USERS["dispatch_operator_headers"]
DIRECTOR = TEST_USERS["flight_director_headers"]
TECH = TEST_USERS["maintenance_tech_headers"]


# =============================================================== single-step steps
def set_clock(to_iso8601: str) -> None:
    """Move the logical mission clock (PRD §2.4)."""
    get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_service_area(**overrides) -> dict:
    return get_success_data(
        api_client.create_service_area(create_service_area_payload(**overrides), ADMIN)
    )


def suspend_service_area(service_area_id: str) -> dict:
    return get_success_data(api_client.suspend_service_area(service_area_id, ADMIN))


def create_nest(service_area_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_nest(create_nest_payload(service_area_id, **overrides), ADMIN)
    )


def create_battery(nest_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_battery(create_battery_payload(nest_id, **overrides), TECH)
    )


def charge_battery(battery_id: str, target_charge_pct=100) -> dict:
    return get_success_data(
        api_client.charge_battery(battery_id, target_charge_pct, TECH)
    )


def create_ready_battery(nest_id: str, target_charge_pct=None, **overrides) -> dict:
    """Register a pack and drive it to READY at the requested set-point."""
    battery = create_battery(nest_id, **overrides)
    target = (
        target_charge_pct
        if target_charge_pct is not None
        else overrides.get("charge_pct", TEST_DEFAULTS["BATTERY_CHARGE_PCT"])
    )
    return charge_battery(battery["id"], target)


def create_drone(home_nest_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_drone(create_drone_payload(home_nest_id, **overrides), ADMIN)
    )


def install_battery(drone_id: str, battery_id: str) -> dict:
    return get_success_data(api_client.install_battery(drone_id, battery_id, TECH))


def read_drone(drone_id: str) -> dict:
    return get_success_data(api_client.get_drone(drone_id, TECH))


def read_battery(battery_id: str) -> dict:
    return get_success_data(api_client.get_battery(battery_id, TECH))


def read_nest(nest_id: str) -> dict:
    return get_success_data(api_client.get_nest(nest_id, ADMIN))


def read_customer(customer_id: str) -> dict:
    return get_success_data(api_client.get_customer(customer_id, ADMIN))


def read_order(order_id: str) -> dict:
    return get_success_data(api_client.get_order(order_id, OPERATOR))


def read_flight(flight_id: str) -> dict:
    return get_success_data(api_client.get_flight(flight_id, OPERATOR))


def read_incident(incident_id: str) -> dict:
    return get_success_data(api_client.get_incident(incident_id, TECH))


def read_maintenance_log(log_id: str) -> dict:
    return get_success_data(api_client.get_maintenance_log(log_id, TECH))


def read_authorization(authorization_id: str) -> dict:
    return get_success_data(
        api_client.get_airspace_authorization(authorization_id, ADMIN)
    )


def create_customer(**overrides) -> dict:
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), ADMIN)
    )


def create_order(customer_id: str, service_area_id: str, operator_id="op-1", **overrides) -> dict:
    return get_success_data(
        api_client.create_order(
            create_order_payload(customer_id, service_area_id, **overrides),
            make_dispatch_operator_headers(operator_id),
        )
    )


def dispatch_order(order_id: str, nest_id: str, expected_order_version=None, operator_id="op-1") -> dict:
    """Dispatch and return the created Flight. Re-reads the order's version when omitted."""
    if expected_order_version is None:
        expected_order_version = read_order(order_id)["version"]
    return get_success_data(
        api_client.dispatch_order(
            order_id,
            dispatch_order_payload(nest_id, expected_order_version),
            make_dispatch_operator_headers(operator_id),
        )
    )


def file_authorization(flight_id: str, operator_id="op-1", **overrides) -> dict:
    return get_success_data(
        api_client.file_authorization(
            flight_id,
            file_authorization_payload(**overrides),
            make_dispatch_operator_headers(operator_id),
        )
    )


def decide_authorization(authorization_id: str, outcome: str) -> dict:
    return get_success_data(
        api_client.laanc_decision(
            {"authorization_id": authorization_id, "outcome": outcome}, ADMIN
        )
    )


def approve_authorization(authorization_id: str) -> dict:
    return decide_authorization(authorization_id, "APPROVED")


def deny_authorization(authorization_id: str) -> dict:
    return decide_authorization(authorization_id, "DENIED")


def release_flight(flight_id: str, director_id="fd-1") -> dict:
    return get_success_data(
        api_client.release_flight(flight_id, make_flight_director_headers(director_id))
    )


def launch_flight(flight_id: str, operator_id="op-1") -> dict:
    return get_success_data(
        api_client.launch_flight(flight_id, make_dispatch_operator_headers(operator_id))
    )


def arrive_flight(flight_id: str, operator_id="op-1") -> dict:
    return get_success_data(
        api_client.arrive_flight(flight_id, make_dispatch_operator_headers(operator_id))
    )


def drop_flight(flight_id: str, operator_id="op-1", **overrides) -> dict:
    return get_success_data(
        api_client.drop_flight(
            flight_id, drop_payload(**overrides), make_dispatch_operator_headers(operator_id)
        )
    )


def recover_flight(flight_id: str, actual_route_km=11.100, operator_id="op-1") -> dict:
    return get_success_data(
        api_client.recover_flight(
            flight_id, actual_route_km, make_dispatch_operator_headers(operator_id)
        )
    )


def abort_flight(flight_id: str, actual_route_km=None, operator_id="op-1") -> dict:
    payload = {} if actual_route_km is None else {"actual_route_km": actual_route_km}
    return get_success_data(
        api_client.abort_flight(
            flight_id, make_dispatch_operator_headers(operator_id), payload
        )
    )


def create_weather_observation(service_area_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_weather_observation(
            create_weather_observation_payload(service_area_id, **overrides), ADMIN
        )
    )


def create_geofence_zone(service_area_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_geofence_zone(
            create_geofence_zone_payload(service_area_id, **overrides), DIRECTOR
        )
    )


def lift_geofence_zone(zone_id: str) -> dict:
    return get_success_data(api_client.lift_geofence_zone(zone_id, DIRECTOR))


def create_incident(drone_id: str, tech_id="mt-1", **overrides) -> dict:
    return get_success_data(
        api_client.create_incident(
            create_incident_payload(drone_id, **overrides),
            make_maintenance_tech_headers(tech_id),
        )
    )


def review_incident(incident_id: str, tech_id="mt-1") -> dict:
    return get_success_data(
        api_client.review_incident(incident_id, make_maintenance_tech_headers(tech_id))
    )


def record_incident_outcome(incident_id: str, outcome: str, tech_id="mt-1") -> dict:
    return get_success_data(
        api_client.record_incident_outcome(
            incident_id, outcome, make_maintenance_tech_headers(tech_id)
        )
    )


def create_maintenance_log(drone_id: str, expected_drone_version=None, tech_id="mt-1", **overrides) -> dict:
    if expected_drone_version is None:
        expected_drone_version = read_drone(drone_id)["version"]
    return get_success_data(
        api_client.create_maintenance_log(
            create_maintenance_log_payload(drone_id, expected_drone_version, **overrides),
            make_maintenance_tech_headers(tech_id),
        )
    )


def complete_maintenance_log(log_id: str, tech_id="mt-1") -> dict:
    return get_success_data(
        api_client.complete_maintenance_log(log_id, make_maintenance_tech_headers(tech_id))
    )


def list_maintenance_logs(**params) -> list:
    return get_success_data(api_client.list_maintenance_logs(TECH, params=params))


def list_flights(**params) -> list:
    return get_success_data(api_client.list_flights(OPERATOR, params=params))


# ================================================== Tier 1/2: the geography + fleet
def setup_world(
    clock=TEST_CLOCK,
    pad_count=None,
    nest_status="OPEN",
    max_range_km=None,
    max_payload_g=None,
    battery_charge_pct=None,
    battery_cycle_count=None,
    battery_serial=None,
    battery_target_charge_pct=None,
    tail_number=None,
    airframe_class=None,
    drone_max_payload_g=None,
    cruise_speed_kmh=None,
    hours_since_service=None,
    dropoff_lat=None,
    dropoff_lon=None,
    with_battery=True,
    install=True,
) -> dict:
    """Bay service area + nest N1 + pack B-1 (READY) + airframe N101 + customer Ann.

    This is the preamble almost every sortie test needs. Returns a mutable dict with
    keys: sa, nest, battery (or None), drone, customer.
    """
    if clock is not None:
        set_clock(clock)

    sa = create_service_area(
        **_present(max_range_km=max_range_km, max_payload_g=max_payload_g)
    )
    nest = create_nest(
        sa["id"], status=nest_status, **_present(pad_count=pad_count)
    )

    battery = None
    if with_battery:
        battery = create_ready_battery(
            nest["id"],
            target_charge_pct=battery_target_charge_pct,
            **_present(
                serial=battery_serial,
                charge_pct=battery_charge_pct,
                cycle_count=battery_cycle_count,
            ),
        )

    drone = create_drone(
        nest["id"],
        **_present(
            tail_number=tail_number,
            airframe_class=airframe_class,
            max_payload_g=drone_max_payload_g,
            cruise_speed_kmh=cruise_speed_kmh,
            hours_since_service=hours_since_service,
        ),
    )
    if battery is not None and install:
        drone = install_battery(drone["id"], battery["id"])

    customer = create_customer(
        **_present(dropoff_lat=dropoff_lat, dropoff_lon=dropoff_lon)
    )

    return {"sa": sa, "nest": nest, "battery": battery, "drone": drone, "customer": customer}


def add_airframe(world: dict, tail_number: str, battery_serial: str, **overrides) -> dict:
    """Register an extra pack + airframe at the world's nest. Returns (drone, battery) dict."""
    battery_kwargs = {
        k[len("battery_") :]: v for k, v in overrides.items() if k.startswith("battery_")
    }
    drone_kwargs = {k: v for k, v in overrides.items() if not k.startswith("battery_")}
    target = battery_kwargs.pop("target_charge_pct", None)
    battery = create_ready_battery(
        world["nest"]["id"],
        target_charge_pct=target,
        serial=battery_serial,
        **battery_kwargs,
    )
    drone = create_drone(world["nest"]["id"], tail_number=tail_number, **drone_kwargs)
    drone = install_battery(drone["id"], battery["id"])
    return {"drone": drone, "battery": battery}


# ==================================================== Tier 3: sortie lifecycle steps
def setup_quoted_order(world=None, payload_weight_g=None, priority=None, **world_kw) -> dict:
    """World + one QUOTED order for the world's customer. Adds key: order."""
    w = world if world is not None else setup_world(**world_kw)
    w["order"] = create_order(
        w["customer"]["id"],
        w["sa"]["id"],
        **_present(payload_weight_g=payload_weight_g, priority=priority),
    )
    return w


def setup_planned_flight(world=None, payload_weight_g=None, priority=None, **world_kw) -> dict:
    """Dispatched sortie: Flight(ops_state=PLANNED, clearance_state=UNFILED). Adds: flight."""
    w = setup_quoted_order(
        world=world, payload_weight_g=payload_weight_g, priority=priority, **world_kw
    )
    w["flight"] = dispatch_order(
        w["order"]["id"], w["nest"]["id"], w["order"]["version"]
    )
    return w


def setup_filed_flight(world=None, operator_id="op-1", **kw) -> dict:
    """PLANNED flight with a PENDING authorization (clearance_state FILED). Adds: auth."""
    w = setup_planned_flight(world=world, **kw)
    w["auth"] = file_authorization(w["flight"]["id"], operator_id=operator_id)
    return w


def setup_approved_flight(world=None, operator_id="op-1", **kw) -> dict:
    """PLANNED / FILED flight whose authorization has been APPROVED by the LAANC authority."""
    w = setup_filed_flight(world=world, operator_id=operator_id, **kw)
    w["auth"] = approve_authorization(w["auth"]["id"])
    return w


def setup_cleared_flight(world=None, operator_id="op-1", director_id="fd-1", **kw) -> dict:
    """Flight ready to launch: ops_state PLANNED, clearance_state CLEARED."""
    w = setup_approved_flight(world=world, operator_id=operator_id, **kw)
    w["flight"] = release_flight(w["flight"]["id"], director_id=director_id)
    return w


def setup_launched_flight(world=None, **kw) -> dict:
    """Airborne sortie: Flight LAUNCHED, Drone IN_FLIGHT, Battery IN_USE, Order IN_TRANSIT."""
    w = setup_cleared_flight(world=world, **kw)
    w["flight"] = launch_flight(w["flight"]["id"])
    return w


def setup_dropping_flight(world=None, **kw) -> dict:
    """Sortie hovering over the dropoff point: Flight DROPPING."""
    w = setup_launched_flight(world=world, **kw)
    w["flight"] = arrive_flight(w["flight"]["id"])
    return w


def setup_returning_flight(world=None, **kw) -> dict:
    """Payload released: Flight RETURNING, Order DELIVERED, funds captured. Adds: drop."""
    w = setup_dropping_flight(world=world, **kw)
    w["drop"] = drop_flight(w["flight"]["id"])
    w["flight"] = read_flight(w["flight"]["id"])
    return w


def setup_recovered_flight(world=None, actual_route_km=11.100, **kw) -> dict:
    """Sortie flown end to end: Flight RECOVERED and the recovery cascade has run."""
    w = setup_returning_flight(world=world, **kw)
    w["flight"] = recover_flight(w["flight"]["id"], actual_route_km)
    return w


# ============================== Tier 4: threshold / cascade targeting compositions
def setup_retired_pack_and_grounded_drone(**kw) -> dict:
    """Drive the retirement cascade: a pack imported at cycle_count 299 crosses 300 on
    recovery, retires, un-links from the airframe, grounds it and auto-schedules a
    BATTERY_SWAP work order. Adds: battery_swap_log."""
    w = setup_recovered_flight(
        battery_serial="B-9", battery_cycle_count=299, **kw
    )
    logs = list_maintenance_logs(drone_id=w["drone"]["id"])
    w["battery_swap_log"] = logs[0] if logs else None
    return w


def setup_grounding_cascade(world=None, severity="CRITICAL", category="AIRSPACE_DEVIATION", **kw) -> dict:
    """File an incident against the world's drone, review it and record
    outcome=MAINTENANCE_REQUIRED, firing the grounding cascade. Adds: incident."""
    w = world if world is not None else setup_launched_flight(**kw)
    extra = {"flight_id": w["flight"]["id"]} if "flight" in w else {}
    incident = create_incident(
        w["drone"]["id"],
        severity=severity,
        category=category,
        narrative="Drifted outside the authorized grid cell",
        **extra,
    )
    review_incident(incident["id"])
    w["incident"] = record_incident_outcome(incident["id"], "MAINTENANCE_REQUIRED")
    return w


def setup_open_incident(world=None, severity="MINOR", category="HARD_LANDING", **kw) -> dict:
    """World + one OPEN incident on the world's airframe. Adds: incident."""
    w = world if world is not None else setup_world(**kw)
    w["incident"] = create_incident(
        w["drone"]["id"], severity=severity, category=category
    )
    return w


def setup_reviewed_incident(world=None, severity="MINOR", category="HARD_LANDING", **kw) -> dict:
    """World + one UNDER_REVIEW incident on the world's airframe."""
    w = setup_open_incident(world=world, severity=severity, category=category, **kw)
    w["incident"] = review_incident(w["incident"]["id"])
    return w


def setup_scheduled_maintenance(world=None, **kw) -> dict:
    """World + one SCHEDULED INSPECTION window on the world's airframe. Adds: log."""
    w = world if world is not None else setup_world(**kw)
    w["log"] = create_maintenance_log(w["drone"]["id"])
    return w


# --------------------------------------------------------------------- internals
def _present(**kwargs) -> dict:
    """Drop the keys whose value is None so factory defaults survive."""
    return {k: v for k, v in kwargs.items() if v is not None}
