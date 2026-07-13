"""Composite setup helpers.

Each helper builds its preconditions from scratch using only PRD-declared
endpoints (the test harness restarts the server with an empty database before
every test). Setup calls use the lenient get_success_data() validator so that a
broken precondition surfaces as a clear "Setup step failed" error.

Identity threading: the Operator role is entity-backed. Any ownership-gated call
(applications, avl-ping, callout complete) MUST use make_operator_headers(op_id)
with the acting operator's real id — never the shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_operator_headers
from . import factories as f

DISPATCH = TEST_USERS["dispatch_headers"]
YARD = TEST_USERS["yard_headers"]
CITIZEN = TEST_USERS["citizen_headers"]


# --- Granular single-entity creators --------------------------------------

def new_depot(**overrides) -> dict:
    return get_success_data(api_client.create_depot(f.create_depot_payload(**overrides), YARD))


def new_vehicle(depot_id, **overrides) -> dict:
    return get_success_data(api_client.create_vehicle(
        f.create_vehicle_payload(depot_id, **overrides), YARD))


def new_operator(**overrides) -> dict:
    return get_success_data(api_client.create_operator(f.create_operator_payload(**overrides), YARD))


def new_route(**overrides) -> dict:
    return get_success_data(api_client.create_route(f.create_route_payload(**overrides), DISPATCH))


def new_storm(**overrides) -> dict:
    return get_success_data(api_client.create_storm_event(
        f.create_storm_event_payload(**overrides), DISPATCH))


def new_callout(storm_id, operator_id, **overrides) -> dict:
    return get_success_data(api_client.create_callout(
        storm_id, f.create_callout_payload(operator_id, **overrides), DISPATCH))


def activate_storm(storm_id) -> dict:
    return get_success_data(api_client.activate_storm_event(storm_id, DISPATCH))


def close_storm(storm_id) -> dict:
    return get_success_data(api_client.close_storm_event(storm_id, DISPATCH))


def get_storm_version(storm_id) -> int:
    return get_success_data(api_client.get_storm_event(storm_id, DISPATCH))["version"]


def new_assignment(storm_id, route_id, vehicle_id, operator_id, version=None, **overrides) -> dict:
    if version is None:
        version = get_storm_version(storm_id)
    payload = f.create_assignment_payload(route_id, vehicle_id, operator_id, version, **overrides)
    return get_success_data(api_client.create_assignment(storm_id, payload, DISPATCH))


def start_assignment(assignment_id) -> dict:
    return get_success_data(api_client.start_assignment(assignment_id, DISPATCH))


def new_application(assignment_id, operator_id, depot_id, **overrides) -> dict:
    payload = f.create_application_payload(depot_id, **overrides)
    return get_success_data(api_client.create_application(
        assignment_id, payload, make_operator_headers(operator_id)))


def complete_callout(callout_id, operator_id, hours_worked) -> dict:
    return get_success_data(api_client.complete_callout(
        callout_id, {"hours_worked": hours_worked}, make_operator_headers(operator_id)))


# --- Composite scene builders ---------------------------------------------

def setup_storm_scene(severity="SEVERE", salt_tons_on_hand=100, brine_gallons_on_hand=1000,
                      hourly_rate_cents=4000, tier="ARTERIAL", lane_miles=2.0,
                      vehicle_type="COMBO", vehicle_status=None,
                      callout_start="2026-02-10T00:00:00Z",
                      callout_end="2026-02-10T08:00:00Z",
                      issue_callout=True, activate=False) -> dict:
    """Depot + vehicle + operator + route + storm, and (by default) one ISSUED
    callout for the operator under the storm. Optionally activates the storm.

    Returns a dict of the created resources keyed by entity name.
    """
    depot = new_depot(salt_tons_on_hand=salt_tons_on_hand, brine_gallons_on_hand=brine_gallons_on_hand)
    veh_overrides = {"vehicle_type": vehicle_type}
    if vehicle_status is not None:
        veh_overrides["status"] = vehicle_status
    vehicle = new_vehicle(depot["id"], **veh_overrides)
    operator = new_operator(hourly_rate_cents=hourly_rate_cents)
    route = new_route(tier=tier, lane_miles=lane_miles)
    storm = new_storm(severity=severity)
    callout = None
    if issue_callout:
        callout = new_callout(storm["id"], operator["id"],
                              window_start_at=callout_start, window_end_at=callout_end)
    if activate:
        storm = activate_storm(storm["id"])
    return {
        "depot": depot,
        "vehicle": vehicle,
        "operator": operator,
        "route": route,
        "storm": storm,
        "callout": callout,
    }


def setup_planned_assignment(planned_material_tons=2.0, assignment_type="PLOWING",
                             window_start_at="2026-02-10T01:00:00Z",
                             window_end_at="2026-02-10T05:00:00Z",
                             activate=True, **scene_overrides) -> dict:
    """A PLANNED assignment under a (by default ACTIVE) storm, operator on-call.
    Returns the scene dict plus 'assignment'."""
    scene = setup_storm_scene(activate=activate, **scene_overrides)
    assignment = new_assignment(
        scene["storm"]["id"], scene["route"]["id"], scene["vehicle"]["id"],
        scene["operator"]["id"],
        assignment_type=assignment_type,
        window_start_at=window_start_at, window_end_at=window_end_at,
        planned_material_tons=planned_material_tons)
    scene["assignment"] = assignment
    return scene


def setup_started_assignment(planned_material_tons=2.0, **overrides) -> dict:
    """An IN_PROGRESS assignment (started) under an ACTIVE storm; vehicle ASSIGNED.
    Returns the scene dict plus 'assignment' (IN_PROGRESS)."""
    scene = setup_planned_assignment(planned_material_tons=planned_material_tons,
                                     activate=True, **overrides)
    scene["assignment"] = start_assignment(scene["assignment"]["id"])
    return scene


def setup_recorded_application(salt_tons=10.0, planned_material_tons=None,
                               lane_miles_treated=2.0, pavement_temp_f=15,
                               material_type="SALT", **overrides) -> dict:
    """An IN_PROGRESS assignment with one RECORDED SALT application.
    Returns the scene dict plus 'assignment' and 'application'."""
    if planned_material_tons is None:
        planned_material_tons = salt_tons
    scene = setup_started_assignment(planned_material_tons=planned_material_tons, **overrides)
    app_kwargs = {"material_type": material_type,
                  "lane_miles_treated": lane_miles_treated,
                  "pavement_temp_f": pavement_temp_f}
    if material_type == "SALT":
        app_kwargs["salt_tons"] = salt_tons
    else:
        app_kwargs["brine_gallons"] = salt_tons
    scene["application"] = new_application(
        scene["assignment"]["id"], scene["operator"]["id"], scene["depot"]["id"], **app_kwargs)
    return scene


def setup_completed_callout(severity="MODERATE", hourly_rate_cents=4000, hours_worked=10) -> dict:
    """An operator with one COMPLETED callout under a storm of the given severity.
    Returns {operator, storm, callout} with callout COMPLETED."""
    operator = new_operator(hourly_rate_cents=hourly_rate_cents)
    storm = new_storm(severity=severity)
    callout = new_callout(storm["id"], operator["id"])
    callout = complete_callout(callout["id"], operator["id"], hours_worked)
    return {"operator": operator, "storm": storm, "callout": callout}


def setup_closed_storm() -> dict:
    """A storm activated then closed (operational CLOSED, billing OPEN)."""
    storm = new_storm(severity="LIGHT")
    activate_storm(storm["id"])
    storm = close_storm(storm["id"])
    return {"storm": storm}


def setup_open_complaint(complaint_type="MISSED_STREET") -> dict:
    """A route + storm + one OPEN complaint. Returns {route, storm, complaint}."""
    route = new_route(tier="RESIDENTIAL", lane_miles=1.0, name="Elm St", zone="Z2")
    storm = new_storm(severity="LIGHT")
    complaint = get_success_data(api_client.create_complaint(
        f.create_complaint_payload(route["id"], storm["id"], complaint_type=complaint_type), CITIZEN))
    return {"route": route, "storm": storm, "complaint": complaint}
