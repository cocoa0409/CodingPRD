"""Route creation, driver assignment (driver-day exclusivity), and route-activation
cross-entity driver-state guard tests."""
from test_helpers import (
    validate_success, validate_error,
    create_route_payload, create_driver_payload, assign_driver_payload,
    TEST_USERS,
)
from test_helpers.fixtures import create_active_driver

ADMIN = TEST_USERS["program_admin_headers"]
ROUTE_MGR = TEST_USERS["route_manager_headers"]


# ---------------------------------------------------------------------------
# Route activation requires an ACTIVE assigned driver (cross-entity dependency)
# ---------------------------------------------------------------------------
def test_route_activation_with_pending_driver_rejected(api):
    """PRD §3.3: "a route whose assigned driver is not yet `ACTIVE` is rejected with
    `ERR_DRIVER_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/route_activation_requires_active_driver
    """
    driver = validate_success(api.create_driver(create_driver_payload(), ADMIN), 201)  # PENDING
    route = validate_success(api.create_route(create_route_payload(), ROUTE_MGR), 201)
    validate_success(api.assign_driver(route["id"], assign_driver_payload(driver["id"]), ROUTE_MGR), 200)
    resp = api.activate_route(route["id"], ROUTE_MGR)
    validate_error(resp, "ERR_DRIVER_NOT_ACTIVE", 409)


def test_route_activation_succeeds_after_driver_activated(api):
    """PRD §3.3: "Activating a route advances it from `DRAFT` to `ACTIVE` and increments the
    route's `version`. Activation has two preconditions evaluated in order: the route must
    have a driver assigned, and that assigned driver must itself be `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/route_activation_requires_active_driver
    """
    driver = validate_success(api.create_driver(create_driver_payload(), ADMIN), 201)  # PENDING
    route = validate_success(api.create_route(create_route_payload(), ROUTE_MGR), 201)
    validate_success(api.assign_driver(route["id"], assign_driver_payload(driver["id"]), ROUTE_MGR), 200)
    # Route activation blocked while driver is PENDING.
    validate_error(api.activate_route(route["id"], ROUTE_MGR), "ERR_DRIVER_NOT_ACTIVE", 409)
    # Activate the driver, then the identical route activation succeeds.
    validate_success(api.activate_driver(driver["id"], ADMIN), 200)
    activated = validate_success(api.activate_route(route["id"], ROUTE_MGR), 200)
    assert activated["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Driver-day exclusivity (discrete weekday-set intersection)
# ---------------------------------------------------------------------------
def test_driver_day_conflict_on_shared_weekday_rejected(api):
    """PRD §3.3: "the driver may not already be assigned to another route — one in either
    `DRAFT` or `ACTIVE` status — whose `service_days` share at least one weekday with this
    route's `service_days`. If such an overlap exists, the assignment is rejected with
    `ERR_DRIVER_DAY_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/driver_day_discrete_weekday_conflict
    """
    driver = create_active_driver(api)
    route1 = validate_success(
        api.create_route(create_route_payload(name="R1", service_days=["MON", "WED"]), ROUTE_MGR), 201
    )
    validate_success(api.assign_driver(route1["id"], assign_driver_payload(driver["id"]), ROUTE_MGR), 200)
    route2 = validate_success(
        api.create_route(create_route_payload(name="R2", service_days=["WED", "FRI"]), ROUTE_MGR), 201
    )
    resp = api.assign_driver(route2["id"], assign_driver_payload(driver["id"]), ROUTE_MGR)
    validate_error(resp, "ERR_DRIVER_DAY_CONFLICT", 409)


def test_driver_assignment_allowed_when_weekdays_disjoint(api):
    """PRD §3.3: "the driver may not already be assigned to another route — one in either
    `DRAFT` or `ACTIVE` status — whose `service_days` share at least one weekday with this
    route's `service_days`. If such an overlap exists, the assignment is rejected with
    `ERR_DRIVER_DAY_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/driver_day_discrete_weekday_conflict
    """
    driver = create_active_driver(api)
    route1 = validate_success(
        api.create_route(create_route_payload(name="R1", service_days=["MON", "WED"]), ROUTE_MGR), 201
    )
    validate_success(api.assign_driver(route1["id"], assign_driver_payload(driver["id"]), ROUTE_MGR), 200)
    # Disjoint weekdays [SAT, SUN] share nothing with [MON, WED] -> assignment permitted.
    route2 = validate_success(
        api.create_route(create_route_payload(name="R2", service_days=["SAT", "SUN"]), ROUTE_MGR), 201
    )
    assigned = validate_success(api.assign_driver(route2["id"], assign_driver_payload(driver["id"]), ROUTE_MGR), 200)
    assert assigned["driver_id"] == driver["id"]
