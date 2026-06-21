"""Dispatch/version, manifest read, not-found errors, RBAC, OCC, immediate consistency.

Queue B (Corner): sections endpoints, errors, rbac, cross_cutting_complexity_layers,
consistency_model.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, build_user_headers,
    ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx

DM = TEST_USERS["dispatch_manager_headers"]
SA = TEST_USERS["sort_associate_headers"]
CSA = TEST_USERS["customer_service_agent_headers"]


# --- endpoints ---

def test_dispatch_with_correct_version_increments_version(api):
    """PRD §3.3: "When all checks pass, every `PENDING` stop on the route
    transitions automatically to `OUT_FOR_DELIVERY` and the route's `version` is
    incremented by one."

    Design: Corner/endpoints/dispatch_with_correct_version_increments_version
    """
    center = fx.create_center(name="HubC26", sort_capacity=10)
    driver = fx.create_driver(name="Dvi", vehicle_capacity_kg=50)
    parcel = fx.create_sorted_parcel(center["id"], weight_kg=1.0)
    route = fx.create_route(driver["id"], center["id"], service_date="2026-07-24")
    fx.add_stop(route["id"], parcel["id"])
    rv = fx.current_route_version(route["id"])
    data = validate_success(api.dispatch_route(route["id"], {"expected_route_version": rv}, DM))
    assert data["status"] == "DISPATCHED"
    assert data["version"] == rv + 1, f"version must bump to {rv + 1}, got {data['version']}"


def test_manifest_computed_read(api):
    """PRD §3.8: "compute that line's raw fee as a base of 50 cents plus the
    parcel's `weight_kg` multiplied by 12.5 cents per kilogram, then round that
    raw fee half up to a whole number of cents to obtain the line fee. The
    `total_handling_fee_cents` is the sum of those already-rounded per-line fees."

    Design: Corner/endpoints/manifest_computed_read
    """
    center = fx.create_center(name="HubC27", sort_capacity=10)
    driver = fx.create_driver(name="Dmf", vehicle_capacity_kg=50)
    parcel = fx.create_sorted_parcel(center["id"], weight_kg=2.0)
    route = fx.create_route(driver["id"], center["id"], service_date="2026-07-25")
    fx.add_stop(route["id"], parcel["id"])
    data = validate_success(api.get_route_manifest(route["id"], DM))
    # round(50 + 2.0*12.5) = 75
    assert data["total_handling_fee_cents"] == 75, (
        f"expected 75, got {data['total_handling_fee_cents']}")
    assert data["stop_count"] == 1


# --- errors ---

def test_center_not_found_on_sort(api):
    """PRD §2.6: "A path identifier that does not resolve to an existing resource
    is rejected first, with the not-found error for that resource type ...
    Only after all path identifiers resolve does the server check that required
    foreign keys in the body refer to existing resources, again returning the
    matching not-found error."

    Design: Corner/errors/center_not_found_on_sort
    """
    parcel = fx.create_parcel(weight_kg=1.0)
    resp = api.sort_parcel(
        parcel["id"], {"center_id": "00000000-0000-4000-8000-000000000001"}, SA
    )
    validate_error(resp, ApiErrorId.ERR_CENTER_NOT_FOUND)


def test_driver_not_found_on_route_create(api):
    """PRD §2.6: "Only after all path identifiers resolve does the server check
    that required foreign keys in the body refer to existing resources, again
    returning the matching not-found error."

    Design: Corner/errors/driver_not_found_on_route_create
    """
    center = fx.create_center(name="HubC28", sort_capacity=10)
    resp = api.create_route(
        {"driver_id": "00000000-0000-4000-8000-000000000002",
         "origin_center_id": center["id"], "service_date": "2026-07-26", "max_stops": 5}, DM,
    )
    validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_FOUND)


# --- rbac ---

def test_driver_cannot_create_route(api):
    """PRD §2.1: "When the headers are present but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/driver_cannot_create_route
    """
    center = fx.create_center(name="HubC29", sort_capacity=10)
    driver = fx.create_driver(name="Drb", vehicle_capacity_kg=50)
    resp = api.create_route(
        {"driver_id": driver["id"], "origin_center_id": center["id"],
         "service_date": "2026-07-27", "max_stops": 5},
        fx.make_driver_headers(driver["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_dispatch_manager_cannot_log_attempt(api):
    """PRD §2.1: "When the headers are present but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/dispatch_manager_cannot_log_attempt
    """
    s = fx.setup_dispatched_route_with_stop(name_suffix="rb", service_date="2026-07-28")
    resp = api.create_attempt(s["stop"]["id"], {"outcome": "NO_ONE_HOME"}, DM)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "Every request must carry two mandatory HTTP headers:
    `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the
    operational capacity under which they act. If either header is missing or
    invalid, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    resp = api.create_parcel({"tracking_code": "P-NOAUTH", "weight_kg": 1.0}, {})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


# --- cross_cutting_complexity_layers ---

def test_occ_stale_version_dispatch_rejected(api):
    """PRD §2.8: "A dispatch request must carry `expected_route_version`, a
    non-optional field that must equal the target route's current `version`. If
    another writer has advanced the route's `version` since the client last read
    it — by adding or cancelling a stop, or by applying an appointment that moved
    one of its stops — the dispatch is rejected with `ERR_STALE_ROUTE_VERSION`
    and HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_dispatch_rejected
    """
    center = fx.create_center(name="HubC31", sort_capacity=10)
    driver = fx.create_driver(name="Docc", vehicle_capacity_kg=50)
    parcel = fx.create_sorted_parcel(center["id"], weight_kg=1.0)
    route = fx.create_route(driver["id"], center["id"], service_date="2026-07-29")
    stop = fx.add_stop(route["id"], parcel["id"])
    rv_stale = fx.current_route_version(route["id"])
    appt = fx.create_appointment(stop["id"], requested_start_min=700, requested_end_min=760)
    get_success_data(api.apply_appointment(appt["id"], CSA))  # bumps route version

    resp = api.dispatch_route(route["id"], {"expected_route_version": rv_stale}, DM)
    validate_error(resp, ApiErrorId.ERR_STALE_ROUTE_VERSION)
    route_d = validate_success(api.get_route(route["id"], DM))
    assert route_d["status"] == "PLANNING"


# --- consistency_model ---

def test_immediate_visibility_of_routed_parcel(api):
    """PRD §3.3: "On success, the new stop starts in `PENDING`, the parcel moves
    from `SORTED` to `ROUTED`, the origin center's `sorted_count` is recomputed
    downward".

    Design: Corner/consistency_model/immediate_visibility_of_routed_parcel
    """
    s = fx.setup_planning_route_with_stop(name_suffix="imm", service_date="2026-07-30")
    parcel_d = validate_success(api.get_parcel(s["parcel"]["id"], DM))
    assert parcel_d["status"] == "ROUTED"
