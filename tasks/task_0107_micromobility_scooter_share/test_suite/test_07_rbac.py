"""Role-based access control: forbidden cross-role operations, ownership checks
on rider- and technician-owned resources, and the unauthenticated gate.
"""
from test_helpers import (
    validate_success,
    validate_error,
    make_rider_headers,
    make_technician_headers,
    ApiErrorId,
    TEST_USERS,
    fixtures as fx,
)

_ADMIN = TEST_USERS["admin_headers"]


def test_rider_cannot_create_plan_forbidden(api):
    """PRD §2.1: "If the headers are well-formed but the named role is not
    permitted to invoke the endpoint, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    POST /api/plans is PlatformAdmin-only (per §4); a Rider calling it is rejected
    with ERR_FORBIDDEN_ROLE (403).

    Design: Corner/rbac/rider_cannot_create_plan_forbidden
    """
    plan = fx.create_standard_plan()
    rider = fx.create_rider(plan["id"])
    headers = make_rider_headers(rider["id"])
    resp = api.create_plan({
        "code": "LOW_INCOME", "unlock_fee_cents": 50, "per_minute_cents": 15,
        "daily_cap_cents": 500, "slow_zone_discount_pct": 0.50,
    }, headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_technician_cannot_complete_task_they_do_not_own(api):
    """PRD §2.1: "A technician may only complete a `RebalancingTask` whose
    `technician_id` equals their own `X-User-ID`."

    A task assigned to technician A cannot be completed by technician B; the call
    is rejected with ERR_NOT_RESOURCE_OWNER (403).

    Design: Corner/rbac/technician_cannot_complete_task_they_do_not_own
    """
    zone = fx.create_zone(zone_type="RIDE_OK", priority=5)
    tech_a = fx.create_technician(zone["id"], name="TechA")
    tech_b = fx.create_technician(zone["id"], name="TechB")
    vehicle = fx.create_vehicle(zone["id"], battery_pct=50)
    task, _ = fx.create_move_task(vehicle, zone["id"], "2026-07-17T10:00:00Z", "2026-07-17T11:00:00Z")
    fx.assign_task(task, tech_a)
    headers_b = make_technician_headers(tech_b["id"])
    resp = api.complete_rebalancing_task(task["id"], headers_b)
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing or malformed on a protected endpoint,
    the request is rejected with `ERR_UNAUTHENTICATED`."

    GET /api/riders requires PlatformAdmin (per §4); a call with no X-User-Role /
    X-User-ID is rejected at the auth layer with ERR_UNAUTHENTICATED (401).

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api._request("GET", "/api/riders", headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_rider_cannot_end_another_riders_trip(api):
    """PRD §2.1: "a `Rider` may only act on a `Trip`, `Fine`, or
    `LowIncomeApplication` whose `rider_id` equals their own `X-User-ID`, as well as
    on their own `Rider` record and its wallet ledger; acting on another rider's
    resource is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Rider B ending rider A's ACTIVE trip is rejected with ERR_NOT_RESOURCE_OWNER
    (403); the trip stays ACTIVE.

    Design: Corner/rbac/rider_cannot_end_another_riders_trip
    """
    plan, zone, vehicle, rider_a, trip = fx.setup_active_trip("2026-07-18T00:00:00Z")
    rider_b = fx.create_rider(plan["id"])
    headers_b = make_rider_headers(rider_b["id"])
    fx.set_clock("2026-07-18T00:02:00Z")
    resp = api.end_trip(trip["id"], {"end_zone_id": zone["id"]}, headers_b)
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    headers_a = make_rider_headers(rider_a["id"])
    after = validate_success(api.get_trip(trip["id"], headers_a))
    assert after["status"] == "ACTIVE", f"expected trip to stay ACTIVE, got {after['status']}"
