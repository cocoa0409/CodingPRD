"""Crewing a run: vehicle availability, driver windows, sanitation buffers, credentials."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    assign_route_payload,
    credential_payload,
    fixtures,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


# ---------------------------------------------------------------------------
# Route assignment depends on the Vehicle's state
# ---------------------------------------------------------------------------
def test_assigning_a_vehicle_already_in_use_is_rejected(api):
    """PRD §3.3: "The vehicle must be `AVAILABLE`, else `ERR_VEHICLE_NOT_AVAILABLE`."
    PRD §3.3: "On success the route's `driver_id` and `vehicle_id` are set and the
    vehicle transitions `AVAILABLE → IN_USE`."

    The second route uses a different driver and a non-overlapping window, so only the
    vehicle's IN_USE state can block it.

    Design: Difficulty/cross_entity_state_dependency/assign_requires_vehicle_available
    """
    ctx = fixtures.setup_vehicle_in_use_on_other_route()

    vehicle = validate_success(api.get_vehicle(ctx["vehicle"]["id"], DISPATCHER))
    assert vehicle["status"] == "IN_USE"

    resp = api.assign_route(
        ctx["route_2"]["id"],
        assign_route_payload(ctx["driver_2"]["id"], ctx["vehicle"]["id"]),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_VEHICLE_NOT_AVAILABLE.value)


def test_unassigning_frees_the_vehicle_for_another_route(api):
    """PRD §3.3: "Unassignment requires the route to be `ASSIGNED` (else
    `ERR_ROUTE_INVALID_STATE`), clears the route's `driver_id` and `vehicle_id`, and
    returns the vehicle `IN_USE → AVAILABLE`."
    PRD §3.3: "The vehicle must be `AVAILABLE`, else `ERR_VEHICLE_NOT_AVAILABLE`."

    Design: Difficulty/cross_entity_state_dependency/assign_requires_vehicle_available
    """
    ctx = fixtures.setup_vehicle_in_use_on_other_route()
    fixtures.unassign_route(ctx["route_1"]["id"])

    vehicle = validate_success(api.get_vehicle(ctx["vehicle"]["id"], DISPATCHER))
    assert vehicle["status"] == "AVAILABLE", "Unassignment returns the vehicle IN_USE -> AVAILABLE"

    assigned = validate_success(
        api.assign_route(
            ctx["route_2"]["id"],
            assign_route_payload(ctx["driver_2"]["id"], ctx["vehicle"]["id"]),
            DISPATCHER,
        )
    )
    assert assigned["status"] == "ASSIGNED"
    assert assigned["vehicle_id"] == ctx["vehicle"]["id"]


def test_unassignment_returns_the_route_to_planned(api):
    """PRD §3.3: "Unassignment requires the route to be `ASSIGNED` (else
    `ERR_ROUTE_INVALID_STATE`), clears the route's `driver_id` and `vehicle_id`, and
    returns the vehicle `IN_USE → AVAILABLE`."

    Design: Corner/state_machines/unassign_reverts_route_to_planned
    """
    ctx = fixtures.setup_scenario(assign=True)

    released = validate_success(api.unassign_route(ctx["route"]["id"], DISPATCHER))
    assert released["status"] == "PLANNED"
    assert released["driver_id"] is None
    assert released["vehicle_id"] is None

    vehicle = validate_success(api.get_vehicle(ctx["vehicle"]["id"], DISPATCHER))
    assert vehicle["status"] == "AVAILABLE"


# ---------------------------------------------------------------------------
# The driver's window is a half-open interval
# ---------------------------------------------------------------------------
def test_overlapping_driver_windows_are_rejected(api):
    """PRD §3.3: "First, the driver must not already hold another route in `ASSIGNED` or
    `DISPATCHED` state whose planned window overlaps this route's window; the windows are
    treated as half-open intervals `[scheduled_start, scheduled_end)`, so a route that
    begins exactly when another ends does not conflict, but any true overlap is rejected
    with `ERR_DRIVER_SCHEDULE_CONFLICT`."

    Route 1 spans [09:00, 11:00) and route 2 spans [10:00, 12:00) — a true overlap.

    Design: Difficulty/resource_temporal_overlap/driver_window_overlap_half_open
    """
    ctx = fixtures.setup_driver_with_overlapping_route()
    resp = api.assign_route(
        ctx["route_2"]["id"],
        assign_route_payload(ctx["driver"]["id"], ctx["vehicle_2"]["id"]),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_DRIVER_SCHEDULE_CONFLICT.value)


def test_adjacent_driver_windows_do_not_conflict(api):
    """PRD §3.3: "First, the driver must not already hold another route in `ASSIGNED` or
    `DISPATCHED` state whose planned window overlaps this route's window; the windows are
    treated as half-open intervals `[scheduled_start, scheduled_end)`, so a route that
    begins exactly when another ends does not conflict, but any true overlap is rejected
    with `ERR_DRIVER_SCHEDULE_CONFLICT`."

    Route 2 begins at 11:00 — exactly when route 1's [09:00, 11:00) window ends.

    Design: Difficulty/resource_temporal_overlap/driver_window_overlap_half_open
    """
    ctx = fixtures.setup_driver_with_overlapping_route(
        route_2_start="2026-05-05T11:00:00Z",
        route_2_end="2026-05-05T13:00:00Z",
    )
    assigned = validate_success(
        api.assign_route(
            ctx["route_2"]["id"],
            assign_route_payload(ctx["driver"]["id"], ctx["vehicle_2"]["id"]),
            DISPATCHER,
        )
    )
    assert assigned["status"] == "ASSIGNED", "Adjacency (end == start) is not an overlap"
    assert assigned["driver_id"] == ctx["driver"]["id"]


# ---------------------------------------------------------------------------
# The vehicle's sanitation buffer after a completed run
# ---------------------------------------------------------------------------
def test_assignment_inside_the_sanitation_buffer_is_rejected(api):
    """PRD §3.3: "Second, the vehicle must have cleared its sanitation gap: either its
    `last_released_at` is null, or this route's `scheduled_start` is at or later than
    `last_released_at` plus the vehicle's `sanitation_buffer_minutes`, else
    `ERR_VEHICLE_BUFFER_CONFLICT`."
    PRD §3.7: "On completion the vehicle is returned `IN_USE → AVAILABLE` and its
    `last_released_at` is set to the current clock, opening its next sanitation window."

    The vehicle is released at 12:00 with a 30-minute buffer; a route starting at 12:15
    falls inside the gap.

    Design: Difficulty/resource_temporal_overlap/vehicle_sanitation_buffer_gap
    """
    ctx = fixtures.setup_released_vehicle(
        release_clock="2026-05-05T12:00:00Z",
        next_start="2026-05-05T12:15:00Z",
    )
    resp = api.assign_route(
        ctx["route_2"]["id"],
        assign_route_payload(ctx["driver_2"]["id"], ctx["vehicle"]["id"]),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_VEHICLE_BUFFER_CONFLICT.value)


def test_assignment_exactly_at_the_end_of_the_sanitation_buffer_is_allowed(api):
    """PRD §3.3: "Second, the vehicle must have cleared its sanitation gap: either its
    `last_released_at` is null, or this route's `scheduled_start` is at or later than
    `last_released_at` plus the vehicle's `sanitation_buffer_minutes`, else
    `ERR_VEHICLE_BUFFER_CONFLICT`."

    Released at 12:00 with a 30-minute buffer, a route starting at exactly 12:30 is "at
    or later than" the gap's end.

    Design: Difficulty/resource_temporal_overlap/vehicle_sanitation_buffer_gap
    """
    ctx = fixtures.setup_released_vehicle(
        release_clock="2026-05-05T12:00:00Z",
        next_start="2026-05-05T12:30:00Z",
    )
    assigned = validate_success(
        api.assign_route(
            ctx["route_2"]["id"],
            assign_route_payload(ctx["driver_2"]["id"], ctx["vehicle"]["id"]),
            DISPATCHER,
        )
    )
    assert assigned["status"] == "ASSIGNED"
    assert assigned["vehicle_id"] == ctx["vehicle"]["id"]


# ---------------------------------------------------------------------------
# Credential validity outranks the scheduling guards
# ---------------------------------------------------------------------------
def test_lapsed_credential_is_reported_before_a_schedule_conflict(api):
    """PRD §2.8: "7. Then the business-safety, referential, constraint, and fiscal checks
    that guard individual workflows, each described where it applies: driver credential
    validity (`ERR_DRIVER_CREDENTIAL_INVALID`), credential-type sufficiency
    (`ERR_CREDENTIAL_TYPE_INSUFFICIENT`), vehicle refrigeration
    (`ERR_VEHICLE_REFRIGERATION_REQUIRED`), vehicle availability
    (`ERR_VEHICLE_NOT_AVAILABLE`), scan/stop matching (`ERR_SPECIMEN_STOP_MISMATCH`),
    driver schedule conflict (`ERR_DRIVER_SCHEDULE_CONFLICT`), vehicle sanitation buffer
    (`ERR_VEHICLE_BUFFER_CONFLICT`), route-has-stops (`ERR_ROUTE_HAS_NO_STOPS`),
    duplicate stop sequence (`ERR_DUPLICATE_STOP_SEQUENCE`), all-stops-resolved
    (`ERR_STOPS_NOT_RESOLVED`), and laboratory budget (`ERR_BUDGET_EXCEEDED`). Within
    this seventh tier the checks apply in the listed order, so that — for example — an
    invalid credential is reported before a credential-type shortfall, which is reported
    before a refrigeration shortfall, which is reported before the budget check."
    PRD §3.3: "The driver must be `ACTIVE` and hold a credential whose
    `credential_expiry` is strictly later than the current clock, else
    `ERR_DRIVER_CREDENTIAL_INVALID`."

    The driver's credential lapsed on 05-10 and the clock now reads 05-11, while the
    driver also holds an overlapping route: the credential failure is reported.

    Design: Difficulty/priority_pair_validation_conflict/assign_credential_beats_schedule_conflict
    """
    ctx = fixtures.setup_driver_with_overlapping_route(
        credential_expiry="2026-05-10T00:00:00Z",
        clock_after_setup="2026-05-11T00:00:00Z",
    )
    resp = api.assign_route(
        ctx["route_2"]["id"],
        assign_route_payload(ctx["driver"]["id"], ctx["vehicle_2"]["id"]),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_DRIVER_CREDENTIAL_INVALID.value)


def test_suspended_driver_is_reported_before_a_schedule_conflict(api):
    """PRD §2.8: "Within this seventh tier the checks apply in the listed order, so that
    — for example — an invalid credential is reported before a credential-type shortfall,
    which is reported before a refrigeration shortfall, which is reported before the
    budget check."
    PRD §3.6: "A `SUSPEND` action drives an `ACTIVE` driver `ACTIVE → SUSPENDED`, after
    which the driver is treated as credential-invalid on any subsequent assignment or
    dispatch."

    The suspended driver also holds an overlapping route; the credential failure wins.

    Design: Difficulty/priority_pair_validation_conflict/assign_credential_beats_schedule_conflict
    """
    ctx = fixtures.setup_driver_with_overlapping_route()
    fixtures.suspend_driver(ctx["driver"]["id"])

    resp = api.assign_route(
        ctx["route_2"]["id"],
        assign_route_payload(ctx["driver"]["id"], ctx["vehicle_2"]["id"]),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_DRIVER_CREDENTIAL_INVALID.value)


# ---------------------------------------------------------------------------
# Credential governance and referenced-resource existence
# ---------------------------------------------------------------------------
def test_suspending_an_already_suspended_driver_is_rejected(api):
    """PRD §3.6: "Each action requires the driver to be in the matching starting state,
    else `ERR_DRIVER_INVALID_STATE`."
    PRD §3.6: "A `SUSPEND` action drives an `ACTIVE` driver `ACTIVE → SUSPENDED`, after
    which the driver is treated as credential-invalid on any subsequent assignment or
    dispatch."

    Design: Corner/state_machines/suspend_already_suspended_driver_returns_409
    """
    driver = fixtures.create_driver()
    suspended = validate_success(
        api.driver_credential(driver["id"], credential_payload("SUSPEND"), COMPLIANCE)
    )
    assert suspended["status"] == "SUSPENDED"

    resp = api.driver_credential(driver["id"], credential_payload("SUSPEND"), COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_DRIVER_INVALID_STATE.value)


def test_assigning_a_non_existent_driver_is_rejected(api):
    """PRD §3.3: "The named driver and vehicle must exist."
    PRD §2.5: "When a path names a nested resource, the server validates identifiers left
    to right and returns the first failure it meets: a scan against a stop under a
    non-existent route surfaces `ERR_ROUTE_NOT_FOUND` before the stop is ever examined,
    and a missing stop surfaces `ERR_STOP_NOT_FOUND`, a missing specimen
    `ERR_SPECIMEN_NOT_FOUND`, and so on for `ERR_DRIVER_NOT_FOUND`,
    `ERR_VEHICLE_NOT_FOUND`, `ERR_LAB_CLIENT_NOT_FOUND`, `ERR_RATE_CARD_NOT_FOUND`,
    `ERR_TEMPLATE_NOT_FOUND`, `ERR_EXCEPTION_NOT_FOUND`, and `ERR_BILLING_NOT_FOUND`."

    Design: Corner/errors/assign_driver_not_found_returns_404
    """
    ctx = fixtures.setup_scenario(specimens=[])
    resp = api.assign_route(
        ctx["route"]["id"],
        assign_route_payload(NON_EXISTENT_UUID, ctx["vehicle"]["id"]),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_FOUND.value)
