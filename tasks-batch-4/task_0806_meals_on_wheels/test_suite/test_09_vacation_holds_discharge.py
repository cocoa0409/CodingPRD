"""Vacation-hold suspension cascade, inclusive-interval overlap, field validation,
and discharge terminal-state behavior."""
from test_helpers import (
    validate_success, validate_error,
    create_vacation_hold_payload,
    TEST_USERS,
)
from test_helpers.fixtures import (
    setup_active_client_with_scheduled_delivery,
    setup_active_client_with_plan,
    intake_client,
    create_assessed_client,
)

INTAKE = TEST_USERS["intake_coordinator_headers"]
ROUTE_MGR = TEST_USERS["route_manager_headers"]


# ---------------------------------------------------------------------------
# Vacation-hold transitive cascade (client -> plan -> in-window deliveries)
# ---------------------------------------------------------------------------
def test_vacation_hold_suspends_client_and_plan(api):
    """PRD §3.7: "The client moves `ACTIVE → ON_HOLD`; the client's `ACTIVE` meal plan moves
    `ACTIVE → SUSPENDED`; every one of that plan's `SCHEDULED` deliveries whose
    `scheduled_date` falls within the hold window (from `start_date` through `end_date`,
    inclusive) moves `SCHEDULED → CANCELLED`; and the client's `version` is incremented by 1".

    Design: Difficulty/transitive_cascade/vacation_hold_transitive_cascade
    """
    scenario = setup_active_client_with_scheduled_delivery(api, scheduled_date="2026-03-02")
    hold = validate_success(
        api.create_vacation_hold(scenario["client"]["id"], create_vacation_hold_payload("2026-03-01", "2026-03-31"), INTAKE), 201
    )
    assert hold["status"] == "ACTIVE"
    client = validate_success(api.get_client(scenario["client"]["id"], ROUTE_MGR), 200)
    assert client["enrollment_status"] == "ON_HOLD"
    plan = validate_success(api.get_meal_plan(scenario["meal_plan"]["id"], ROUTE_MGR), 200)
    assert plan["status"] == "SUSPENDED"


def test_vacation_hold_cancels_in_window_scheduled_delivery(api):
    """PRD §3.7: "every one of that plan's `SCHEDULED` deliveries whose `scheduled_date`
    falls within the hold window (from `start_date` through `end_date`, inclusive) moves
    `SCHEDULED → CANCELLED`".

    Design: Difficulty/transitive_cascade/vacation_hold_transitive_cascade
    """
    scenario = setup_active_client_with_scheduled_delivery(api, scheduled_date="2026-03-02")
    validate_success(
        api.create_vacation_hold(scenario["client"]["id"], create_vacation_hold_payload("2026-03-01", "2026-03-31"), INTAKE), 201
    )
    delivery = validate_success(api.get_delivery(scenario["delivery"]["id"], ROUTE_MGR), 200)
    assert delivery["status"] == "CANCELLED", "delivery on 2026-03-02 lies within [2026-03-01, 2026-03-31]"


# ---------------------------------------------------------------------------
# Inclusive (touching) interval overlap
# ---------------------------------------------------------------------------
def test_touching_vacation_hold_windows_overlap_rejected(api):
    """PRD §3.7: "two windows overlap — including when they merely touch at an endpoint —
    exactly when the new start is on or before the existing end and the existing start is on
    or before the new end. An overlap yields `ERR_HOLD_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/vacation_hold_inclusive_touching_overlap
    """
    scenario = setup_active_client_with_plan(api)
    client_id = scenario["client"]["id"]
    first = validate_success(
        api.create_vacation_hold(client_id, create_vacation_hold_payload("2026-06-01", "2026-06-10"), INTAKE), 201
    )
    validate_success(api.end_vacation_hold(first["id"], INTAKE), 200)  # first hold now COMPLETED, client ACTIVE
    # New window starts on 2026-06-10, the exact endpoint of the completed hold -> touch counts as overlap.
    resp = api.create_vacation_hold(client_id, create_vacation_hold_payload("2026-06-10", "2026-06-15"), INTAKE)
    validate_error(resp, "ERR_HOLD_OVERLAP", 409)


def test_non_touching_vacation_hold_window_allowed(api):
    """PRD §3.7: "two windows overlap — including when they merely touch at an endpoint —
    exactly when the new start is on or before the existing end and the existing start is on
    or before the new end. An overlap yields `ERR_HOLD_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/vacation_hold_inclusive_touching_overlap
    """
    scenario = setup_active_client_with_plan(api)
    client_id = scenario["client"]["id"]
    first = validate_success(
        api.create_vacation_hold(client_id, create_vacation_hold_payload("2026-06-01", "2026-06-10"), INTAKE), 201
    )
    validate_success(api.end_vacation_hold(first["id"], INTAKE), 200)
    # New start 2026-06-11 is after the existing end 2026-06-10 -> no overlap -> permitted.
    created = validate_success(
        api.create_vacation_hold(client_id, create_vacation_hold_payload("2026-06-11", "2026-06-15"), INTAKE), 201
    )
    assert created["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Corner: field validation and discharge terminal state
# ---------------------------------------------------------------------------
def test_vacation_hold_end_before_start_rejected(api):
    """PRD §2.8: "A value that is present and correctly typed but out of its allowed range or
    not a valid enum member yields `ERR_INVALID_FIELD_VALUE`; this covers ... an end date
    earlier than its start date".

    Design: Corner/validations/vacation_hold_end_before_start_returns_invalid_field_value
    """
    client = intake_client(api)
    resp = api.create_vacation_hold(client["id"], create_vacation_hold_payload("2026-06-10", "2026-06-01"), INTAKE)
    validate_error(resp, "ERR_INVALID_FIELD_VALUE", 422)


def test_discharged_client_cannot_be_activated(api):
    """PRD §3.1: "This activation is permitted only when the client is currently in
    `ASSESSED` status — any other status yields `ERR_CLIENT_NOT_ASSESSED` (HTTP 409)".

    Design: Corner/state_machines/discharged_client_cannot_activate
    """
    ac = create_assessed_client(api)
    client_id = ac["client"]["id"]
    discharged = validate_success(api.discharge_client(client_id, INTAKE), 200)
    assert discharged["enrollment_status"] == "DISCHARGED"
    resp = api.activate_client(client_id, INTAKE)
    validate_error(resp, "ERR_CLIENT_NOT_ASSESSED", 409)
