"""Delivery scheduling: active-client precondition, per-date route capacity, and
delivery-day membership."""
from test_helpers import (
    validate_success, validate_error,
    create_delivery_payload,
    TEST_USERS,
)
from test_helpers.fixtures import (
    setup_assessed_client_with_plan,
    setup_active_client_with_plan,
    schedule_delivery,
)

INTAKE = TEST_USERS["intake_coordinator_headers"]
ROUTE_MGR = TEST_USERS["route_manager_headers"]


# ---------------------------------------------------------------------------
# Scheduling requires an ACTIVE client (cross-entity Delivery -> Client)
# ---------------------------------------------------------------------------
def test_schedule_delivery_for_assessed_client_rejected(api):
    """PRD §3.5: "The client must be `ACTIVE`, else `ERR_CLIENT_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/delivery_scheduling_requires_active_client
    """
    scenario = setup_assessed_client_with_plan(api)  # client left ASSESSED
    resp = api.create_delivery(create_delivery_payload(scenario["meal_plan"]["id"], "2026-03-02"), ROUTE_MGR)
    validate_error(resp, "ERR_CLIENT_NOT_ACTIVE", 409)


def test_schedule_delivery_succeeds_after_client_activated(api):
    """PRD §3.5: "The client must be `ACTIVE`, else `ERR_CLIENT_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/delivery_scheduling_requires_active_client
    """
    scenario = setup_assessed_client_with_plan(api)
    plan_id = scenario["meal_plan"]["id"]
    # Blocked while client is only ASSESSED.
    validate_error(api.create_delivery(create_delivery_payload(plan_id, "2026-03-02"), ROUTE_MGR),
                   "ERR_CLIENT_NOT_ACTIVE", 409)
    # Activate the client; the identical scheduling call now succeeds.
    validate_success(api.activate_client(scenario["client"]["id"], INTAKE), 200)
    created = validate_success(api.create_delivery(create_delivery_payload(plan_id, "2026-03-02"), ROUTE_MGR), 201)
    assert created["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Per-date route capacity boundary
# ---------------------------------------------------------------------------
def test_delivery_at_route_capacity_boundary_succeeds(api):
    """PRD §3.5: "the sum of `meal_count` over the existing `SCHEDULED` deliveries already
    on that route for that same `scheduled_date`, plus this delivery's own `meal_count`,
    must not exceed the route's `max_meals_per_run`; if it would, the request is rejected
    with `ERR_ROUTE_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/route_capacity_boundary_at_max
    """
    # meals_per_day 1 -> meal_count 1; route capacity 2. First two deliveries reach sum 2 == cap.
    scenario = setup_active_client_with_plan(api, meals_per_day=1, route_overrides={"max_meals_per_run": 2})
    plan_id = scenario["meal_plan"]["id"]
    first = validate_success(api.create_delivery(create_delivery_payload(plan_id, "2026-03-02"), ROUTE_MGR), 201)
    assert first["meal_count"] == 1
    second = validate_success(api.create_delivery(create_delivery_payload(plan_id, "2026-03-02"), ROUTE_MGR), 201)
    assert second["status"] == "SCHEDULED", "the 2nd delivery (aggregate 2 == cap) is admitted"


def test_delivery_exceeding_route_capacity_rejected(api):
    """PRD §3.5: "the sum of `meal_count` over the existing `SCHEDULED` deliveries already
    on that route for that same `scheduled_date`, plus this delivery's own `meal_count`,
    must not exceed the route's `max_meals_per_run`; if it would, the request is rejected
    with `ERR_ROUTE_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/route_capacity_boundary_at_max
    """
    scenario = setup_active_client_with_plan(api, meals_per_day=1, route_overrides={"max_meals_per_run": 2})
    plan_id = scenario["meal_plan"]["id"]
    schedule_delivery(api, plan_id, "2026-03-02")  # aggregate 1
    schedule_delivery(api, plan_id, "2026-03-02")  # aggregate 2 == cap
    resp = api.create_delivery(create_delivery_payload(plan_id, "2026-03-02"), ROUTE_MGR)  # would be 3 > 2
    validate_error(resp, "ERR_ROUTE_CAPACITY_EXCEEDED", 409)


# ---------------------------------------------------------------------------
# Delivery-day membership
# ---------------------------------------------------------------------------
def test_schedule_delivery_on_non_service_weekday_rejected(api):
    """PRD §3.5: "The weekday of `scheduled_date` must be one of the plan's `delivery_days`,
    else `ERR_DELIVERY_DAY_MISMATCH` (HTTP 422)."

    Design: Corner/validations/delivery_day_mismatch_rejected
    """
    scenario = setup_active_client_with_plan(api, delivery_days=["MON", "WED", "FRI"])
    # 2026-03-03 is a Tuesday, not in [MON, WED, FRI].
    resp = api.create_delivery(create_delivery_payload(scenario["meal_plan"]["id"], "2026-03-03"), ROUTE_MGR)
    validate_error(resp, "ERR_DELIVERY_DAY_MISMATCH", 422)
