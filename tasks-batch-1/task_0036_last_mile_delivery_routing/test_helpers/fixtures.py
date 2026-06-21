"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, since the server database is reset before every test. Setup calls use
the lenient get_success_data() validator so setup failures surface clearly.

Identity threading: the Driver role is entity_backed. After creating a Driver,
any driver-owned call (logging a delivery attempt on a stop of that driver's
route) uses make_driver_headers(driver["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_driver_headers
from .factories import (
    create_transit_center_payload,
    create_driver_payload,
    create_parcel_payload,
    create_route_payload,
    create_stop_payload,
    create_attempt_payload,
    create_appointment_payload,
)

DM = TEST_USERS["dispatch_manager_headers"]
SA = TEST_USERS["sort_associate_headers"]
CSA = TEST_USERS["customer_service_agent_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity builders
# ---------------------------------------------------------------------------

def create_center(name="Hub", hazmat_certified=None, sort_capacity=10):
    payload = create_transit_center_payload(name=name, sort_capacity=sort_capacity)
    if hazmat_certified is not None:
        payload["hazmat_certified"] = hazmat_certified
    return get_success_data(api_client.create_transit_center(payload, DM))


def create_driver(name="Driver", hazmat_certified=None, vehicle_capacity_kg=50.0):
    payload = create_driver_payload(name=name, vehicle_capacity_kg=vehicle_capacity_kg)
    if hazmat_certified is not None:
        payload["hazmat_certified"] = hazmat_certified
    return get_success_data(api_client.create_driver(payload, DM))


def create_parcel(tracking_code=None, weight_kg=1.0, **extra):
    payload = create_parcel_payload(weight_kg=weight_kg, **extra)
    if tracking_code is not None:
        payload["tracking_code"] = tracking_code
    return get_success_data(api_client.create_parcel(payload, SA))


def sort_parcel(parcel_id, center_id):
    return get_success_data(api_client.sort_parcel(parcel_id, {"center_id": center_id}, SA))


def create_sorted_parcel(center_id, weight_kg=1.0, **extra):
    """Register a parcel and sort it into center_id. Returns the sorted parcel."""
    parcel = create_parcel(weight_kg=weight_kg, **extra)
    sort_parcel(parcel["id"], center_id)
    return get_success_data(api_client.get_parcel(parcel["id"], DM))


def create_route(driver_id, origin_center_id, service_date="2026-06-01", max_stops=5):
    payload = create_route_payload(
        driver_id, origin_center_id, service_date=service_date, max_stops=max_stops
    )
    return get_success_data(api_client.create_route(payload, DM))


def add_stop(route_id, parcel_id, sequence=1, window_start_min=540, window_end_min=600):
    payload = create_stop_payload(
        route_id, parcel_id, sequence=sequence,
        window_start_min=window_start_min, window_end_min=window_end_min,
    )
    return get_success_data(api_client.create_stop(payload, DM))


def current_route_version(route_id):
    return get_success_data(api_client.get_route(route_id, DM))["version"]


def dispatch_route(route_id, expected_route_version=None):
    if expected_route_version is None:
        expected_route_version = current_route_version(route_id)
    payload = {"expected_route_version": expected_route_version}
    return get_success_data(api_client.dispatch_route(route_id, payload, DM))


def cancel_route(route_id):
    """Cancel a PLANNING route as the owning DispatchManager (PRD §3.3)."""
    return get_success_data(api_client.cancel_route(route_id, DM))


# ---------------------------------------------------------------------------
# Tier 2/3: composite scenarios (most recurring chain prefixes)
# ---------------------------------------------------------------------------

def setup_planning_route_with_stop(
    parcel_overrides=None, weight_kg=1.0, sequence=1,
    window_start_min=540, window_end_min=600,
    driver_overrides=None, center_overrides=None, service_date="2026-06-01",
    max_stops=5, name_suffix="",
):
    """OPEN center + ACTIVE driver + one SORTED parcel routed onto a PLANNING route.

    Returns dict: center, driver, parcel, route, stop.
    """
    center = create_center(
        name=f"Hub{name_suffix}",
        **(center_overrides or {}),
    )
    driver = create_driver(name=f"Drv{name_suffix}", **(driver_overrides or {}))
    parcel = create_sorted_parcel(center["id"], weight_kg=weight_kg, **(parcel_overrides or {}))
    route = create_route(driver["id"], center["id"], service_date=service_date, max_stops=max_stops)
    stop = add_stop(
        route["id"], parcel["id"], sequence=sequence,
        window_start_min=window_start_min, window_end_min=window_end_min,
    )
    return {
        "center": center, "driver": driver, "parcel": parcel,
        "route": route, "stop": stop,
    }


def setup_dispatched_route_with_stop(
    parcel_overrides=None, weight_kg=1.0, driver_overrides=None,
    center_overrides=None, service_date="2026-06-01",
    window_start_min=540, window_end_min=600, name_suffix="",
):
    """Dispatched route with one OUT_FOR_DELIVERY stop. Returns the same dict
    as setup_planning_route_with_stop plus refreshed route/stop."""
    s = setup_planning_route_with_stop(
        parcel_overrides=parcel_overrides, weight_kg=weight_kg,
        driver_overrides=driver_overrides, center_overrides=center_overrides,
        service_date=service_date, window_start_min=window_start_min,
        window_end_min=window_end_min, name_suffix=name_suffix,
    )
    dispatch_route(s["route"]["id"])
    s["route"] = get_success_data(api_client.get_route(s["route"]["id"], DM))
    s["stop"] = get_success_data(api_client.get_stop(s["stop"]["id"], DM))
    return s


def log_attempt(stop_id, driver_id, outcome, **extra):
    """Log a delivery attempt as the owning driver. Returns the DeliveryAttempt."""
    headers = make_driver_headers(driver_id)
    payload = create_attempt_payload(outcome, **extra)
    return get_success_data(api_client.create_attempt(stop_id, payload, headers))


def reschedule(stop_id):
    return get_success_data(api_client.reschedule_stop(stop_id, DM))


def setup_attempted_stop(
    parcel_overrides=None, driver_overrides=None, center_overrides=None,
    weight_kg=1.0, outcome="NO_ONE_HOME", service_date="2026-06-01", name_suffix="",
):
    """Dispatched route, one stop with one failed attempt -> ATTEMPTED.
    Returns the scenario dict with refreshed stop and driver id."""
    s = setup_dispatched_route_with_stop(
        parcel_overrides=parcel_overrides, driver_overrides=driver_overrides,
        center_overrides=center_overrides, weight_kg=weight_kg,
        service_date=service_date, name_suffix=name_suffix,
    )
    log_attempt(s["stop"]["id"], s["driver"]["id"], outcome)
    s["stop"] = get_success_data(api_client.get_stop(s["stop"]["id"], DM))
    return s


def setup_redelivery_scheduled_stop(
    parcel_overrides=None, driver_overrides=None, center_overrides=None,
    weight_kg=1.0, service_date="2026-06-01", name_suffix="",
):
    """Dispatched route, one stop: failed attempt then reschedule ->
    REDELIVERY_SCHEDULED. Returns scenario dict with refreshed stop."""
    s = setup_attempted_stop(
        parcel_overrides=parcel_overrides, driver_overrides=driver_overrides,
        center_overrides=center_overrides, weight_kg=weight_kg,
        service_date=service_date, name_suffix=name_suffix,
    )
    reschedule(s["stop"]["id"])
    s["stop"] = get_success_data(api_client.get_stop(s["stop"]["id"], DM))
    return s


def create_appointment(stop_id, requested_start_min=700, requested_end_min=760):
    payload = create_appointment_payload(
        stop_id, requested_start_min=requested_start_min, requested_end_min=requested_end_min
    )
    return get_success_data(api_client.create_appointment(payload, CSA))
