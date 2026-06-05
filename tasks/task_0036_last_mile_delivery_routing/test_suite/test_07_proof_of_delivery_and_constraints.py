"""Signature / Driver-Release proof-of-delivery rules, stop limits, hazmat gates.

Queue B (Corner): section validations (non-stub instances).
"""
import pytest
from test_helpers import validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS
from test_helpers import fixtures as fx

DM = TEST_USERS["dispatch_manager_headers"]
SA = TEST_USERS["sort_associate_headers"]


def test_signature_required_without_signature_rejected(api):
    """PRD §3.4: "If the parcel's `signature_required` is true and
    `used_driver_release` is not true, a non-empty `signature_name` must be
    supplied, otherwise the attempt is rejected with `ERR_SIGNATURE_REQUIRED`."

    Design: Corner/validations/signature_required_without_signature_rejected
    """
    s = fx.setup_dispatched_route_with_stop(
        parcel_overrides={"signature_required": True}, name_suffix="sig",
        service_date="2026-07-17",
    )
    resp = api.create_attempt(
        s["stop"]["id"], {"outcome": "DELIVERED"},
        fx.make_driver_headers(s["driver"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SIGNATURE_REQUIRED)
    stop_d = validate_success(api.get_stop(s["stop"]["id"], DM))
    assert stop_d["status"] == "OUT_FOR_DELIVERY"


def test_signature_required_with_signature_succeeds(api):
    """PRD §3.4: "If the parcel's `signature_required` is true and
    `used_driver_release` is not true, a non-empty `signature_name` must be
    supplied, otherwise the attempt is rejected with `ERR_SIGNATURE_REQUIRED`."

    Design: Corner/validations/signature_required_with_signature_succeeds
    """
    s = fx.setup_dispatched_route_with_stop(
        parcel_overrides={"signature_required": True}, name_suffix="sg2",
        service_date="2026-07-18",
    )
    fx.log_attempt(s["stop"]["id"], s["driver"]["id"], "DELIVERED", signature_name="J. Doe")
    stop_d = validate_success(api.get_stop(s["stop"]["id"], DM))
    assert stop_d["status"] == "DELIVERED"
    parcel_d = validate_success(api.get_parcel(s["parcel"]["id"], DM))
    assert parcel_d["status"] == "DELIVERED"


def test_driver_release_without_authorization_rejected(api):
    """PRD §3.4: "Setting `used_driver_release` to true is only allowed when the
    parcel's `driver_release_authorized` is true; using Driver Release on a
    parcel the shipper did not pre-authorize is rejected with
    `ERR_DRIVER_RELEASE_NOT_AUTHORIZED`."

    Design: Corner/validations/driver_release_without_authorization_rejected
    """
    s = fx.setup_dispatched_route_with_stop(
        parcel_overrides={"signature_required": True, "driver_release_authorized": False},
        name_suffix="dr", service_date="2026-07-19",
    )
    resp = api.create_attempt(
        s["stop"]["id"], {"outcome": "DELIVERED", "used_driver_release": True},
        fx.make_driver_headers(s["driver"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DRIVER_RELEASE_NOT_AUTHORIZED)


def test_driver_release_authorized_delivers_without_signature(api):
    """PRD §3.4: "Driver Release, when authorized, substitutes for the signature
    so that a signature-required parcel may be delivered without a captured
    `signature_name`."

    Design: Corner/validations/driver_release_authorized_delivers_without_signature
    """
    s = fx.setup_dispatched_route_with_stop(
        parcel_overrides={"signature_required": True, "driver_release_authorized": True},
        name_suffix="dr2", service_date="2026-07-20",
    )
    fx.log_attempt(s["stop"]["id"], s["driver"]["id"], "DELIVERED", used_driver_release=True)
    stop_d = validate_success(api.get_stop(s["stop"]["id"], DM))
    assert stop_d["status"] == "DELIVERED"
    parcel_d = validate_success(api.get_parcel(s["parcel"]["id"], DM))
    assert parcel_d["status"] == "DELIVERED"


def test_route_stop_limit_exceeded_rejected(api):
    """PRD §3.3: "Adding a stop must not push the route's `stop_count` above its
    `max_stops`, and the new `sequence` must not duplicate an existing
    non-`CANCELLED` stop's sequence; either violation is rejected with
    `ERR_ROUTE_STOP_LIMIT`."

    Design: Corner/validations/route_stop_limit_exceeded_rejected
    """
    center = fx.create_center(name="HubC22", sort_capacity=10)
    driver = fx.create_driver(name="Dsl", vehicle_capacity_kg=50)
    pa = fx.create_sorted_parcel(center["id"], weight_kg=1.0)
    pb = fx.create_sorted_parcel(center["id"], weight_kg=1.0)
    route = fx.create_route(driver["id"], center["id"], service_date="2026-07-21", max_stops=1)
    fx.add_stop(route["id"], pa["id"], sequence=1, window_start_min=540, window_end_min=600)
    resp = api.create_stop(
        {"route_id": route["id"], "parcel_id": pb["id"], "sequence": 2,
         "window_start_min": 660, "window_end_min": 720}, DM,
    )
    validate_error(resp, ApiErrorId.ERR_ROUTE_STOP_LIMIT)


def test_duplicate_sequence_on_route_rejected(api):
    """PRD §3.3: "Adding a stop must not push the route's `stop_count` above its
    `max_stops`, and the new `sequence` must not duplicate an existing
    non-`CANCELLED` stop's sequence; either violation is rejected with
    `ERR_ROUTE_STOP_LIMIT`."

    Design: Corner/validations/duplicate_sequence_on_route_rejected
    """
    center = fx.create_center(name="HubC25", sort_capacity=10)
    driver = fx.create_driver(name="Dds", vehicle_capacity_kg=50)
    pa = fx.create_sorted_parcel(center["id"], weight_kg=1.0)
    pb = fx.create_sorted_parcel(center["id"], weight_kg=1.0)
    route = fx.create_route(driver["id"], center["id"], service_date="2026-07-23")
    fx.add_stop(route["id"], pa["id"], sequence=1, window_start_min=540, window_end_min=600)
    resp = api.create_stop(
        {"route_id": route["id"], "parcel_id": pb["id"], "sequence": 1,
         "window_start_min": 660, "window_end_min": 720}, DM,
    )
    validate_error(resp, ApiErrorId.ERR_ROUTE_STOP_LIMIT)


def test_hazmat_sort_at_certified_hub_succeeds(api):
    """PRD §3.1: "If the parcel's `hazmat_class` is anything other than `NONE`,
    the target center's `hazmat_certified` must be true, or the request is
    rejected with `ERR_HAZMAT_HUB_NOT_CERTIFIED`."

    Design: Corner/validations/hazmat_sort_at_certified_hub_succeeds
    """
    center = fx.create_center(name="HubC23", hazmat_certified=True, sort_capacity=10)
    parcel = fx.create_parcel(weight_kg=1.0, hazmat_class="CLASS_8")
    data = validate_success(api.sort_parcel(parcel["id"], {"center_id": center["id"]}, SA))
    assert data["status"] == "SORTED"
    assert data["sorted_at_center_id"] == center["id"]


def test_dispatch_hazmat_route_non_certified_driver_rejected(api):
    """PRD §3.3: "If any stop's parcel has a `hazmat_class` other than `NONE`,
    the driver's `hazmat_certified` must be true, otherwise the dispatch is
    rejected with `ERR_DRIVER_NOT_HAZMAT_CERTIFIED`."

    Design: Corner/validations/dispatch_hazmat_route_non_certified_driver_rejected
    """
    center = fx.create_center(name="HubC24", hazmat_certified=True, sort_capacity=10)
    driver = fx.create_driver(name="Dnh", hazmat_certified=False, vehicle_capacity_kg=50)
    parcel = fx.create_sorted_parcel(center["id"], weight_kg=1.0, hazmat_class="CLASS_3")
    route = fx.create_route(driver["id"], center["id"], service_date="2026-07-22")
    fx.add_stop(route["id"], parcel["id"])
    rv = fx.current_route_version(route["id"])
    resp = api.dispatch_route(route["id"], {"expected_route_version": rv}, DM)
    validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_HAZMAT_CERTIFIED)
    route_d = validate_success(api.get_route(route["id"], DM))
    assert route_d["status"] == "PLANNING"
