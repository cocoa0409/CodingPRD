"""Parcel/route/attempt creation, retrieval, listing, defaults, and validation.

Queue B (Corner): section entities.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx

DM = TEST_USERS["dispatch_manager_headers"]
SA = TEST_USERS["sort_associate_headers"]


def test_create_parcel_returns_201_with_fields(api):
    """PRD §3.1: "A freshly registered parcel begins in `RECEIVED` status with
    its `sorted_at_center_id` null."
    PRD §2.4: "`version`: an integer that starts at its initial value and
    increments by one on every mutation."

    Design: Corner/entities/create_parcel_returns_201_with_fields
    """
    resp = api.create_parcel({"tracking_code": "P-NEW", "weight_kg": 3.5}, SA)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "RECEIVED"
    assert data["service_level"] == "GROUND"
    assert data["version"] == 1


def test_get_parcel_returns_stored(api):
    """PRD §2.2: "the `data` field contains the resource object or an array of
    resource objects."

    Design: Corner/entities/get_parcel_returns_stored
    """
    parcel = fx.create_parcel(tracking_code="P-GET", weight_kg=1.0)
    data = validate_success(api.get_parcel(parcel["id"], DM))
    assert data["tracking_code"] == "P-GET"


def test_list_routes_paginated_envelope(api):
    """PRD §2.3: "List responses populate the `limit`, `offset`, `total_count`,
    and `has_more` fields in the `meta` object of the envelope."

    Design: Corner/entities/list_routes_paginated_envelope
    """
    resp = api.list_routes(DM)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


def test_get_parcel_nonexistent_returns_not_found(api):
    """PRD §2.6: "A path identifier that does not resolve to an existing resource
    is rejected first, with the not-found error for that resource type —
    `ERR_CENTER_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`, `ERR_PARCEL_NOT_FOUND`,
    `ERR_ROUTE_NOT_FOUND`, `ERR_STOP_NOT_FOUND`, or `ERR_APPOINTMENT_NOT_FOUND`
    as appropriate."

    Design: Corner/entities/get_parcel_nonexistent_returns_not_found
    """
    resp = api.get_parcel("00000000-0000-4000-8000-000000000000", DM)
    validate_error(resp, ApiErrorId.ERR_PARCEL_NOT_FOUND)


def test_create_parcel_missing_weight_invalid_request(api):
    """PRD §3.1: "A `Parcel` is registered with a `tracking_code`, a `weight_kg`,
    and four optional descriptors". PRD §3.1: "The `weight_kg` must be greater
    than zero."

    Design: Corner/entities/create_parcel_missing_weight_invalid_request
    """
    resp = api.create_parcel({"tracking_code": "P-NOW"}, SA)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_parcel_default_service_level_applied(api):
    """PRD §3.1: "four optional descriptors: `service_level` (one of `GROUND`,
    `EXPRESS`, or `PRIORITY`, defaulting to `GROUND`), `signature_required`
    (defaulting to false), `hazmat_class` (one of `NONE`, `CLASS_3`, or
    `CLASS_8`, defaulting to `NONE`), and `driver_release_authorized` (defaulting
    to false, indicating whether the shipper pre-authorized leaving the parcel
    without a signature)."

    Design: Corner/entities/create_parcel_default_service_level_applied
    """
    data = validate_success(
        api.create_parcel({"tracking_code": "P-DEF", "weight_kg": 1.0}, SA),
        expected_status=201,
    )
    assert data["service_level"] == "GROUND"
    assert data["signature_required"] is False
    assert data["hazmat_class"] == "NONE"


def test_parcel_status_system_field_input_ignored(api):
    """PRD §3.1: "A freshly registered parcel begins in `RECEIVED` status with
    its `sorted_at_center_id` null."

    Design: Corner/entities/parcel_status_system_field_input_ignored
    """
    data = validate_success(
        api.create_parcel({"tracking_code": "P-SYS", "weight_kg": 1.0}, SA),
        expected_status=201,
    )
    assert data["status"] == "RECEIVED"


def test_create_parcel_invalid_enum_service_level(api):
    """PRD §3.1: "`service_level` (one of `GROUND`, `EXPRESS`, or `PRIORITY`,
    defaulting to `GROUND`)".

    Design: Corner/entities/create_parcel_invalid_enum_service_level
    """
    resp = api.create_parcel(
        {"tracking_code": "P-ENUM", "weight_kg": 1.0, "service_level": "OVERNIGHT"}, SA
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_stop_window_end_le_start_invalid(api):
    """PRD §3.3: "`window_start_min` lies in the range 0 through 1440 inclusive,
    and `window_end_min` must be greater than `window_start_min` and at most 1440."

    Design: Corner/entities/create_stop_window_end_le_start_invalid
    """
    center = fx.create_center(name="HubC1", sort_capacity=10)
    driver = fx.create_driver(name="Dx", vehicle_capacity_kg=50)
    parcel = fx.create_sorted_parcel(center["id"], weight_kg=1.0)
    route = fx.create_route(driver["id"], center["id"], service_date="2026-07-01")

    resp = api.create_stop(
        {"route_id": route["id"], "parcel_id": parcel["id"], "sequence": 1,
         "window_start_min": 600, "window_end_min": 600}, DM,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_duplicate_tracking_code_rejected(api):
    """PRD §3.1: "The `tracking_code` must be unique across all parcels;
    registering a parcel whose code already exists is rejected with
    `ERR_DUPLICATE_TRACKING_CODE`."

    Design: Corner/entities/duplicate_tracking_code_rejected
    """
    fx.create_parcel(tracking_code="P-DUP", weight_kg=1.0)
    resp = api.create_parcel({"tracking_code": "P-DUP", "weight_kg": 2.0}, SA)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_TRACKING_CODE)


def test_delivery_attempt_immutable_no_version(api):
    """PRD §2.4: "The `DeliveryAttempt` resource is an exception. It is an
    append-only event record and carries only `id` and `created_at`; it has
    neither an `updated_at` field nor a `version` field."

    Design: Corner/entities/delivery_attempt_immutable_no_version
    """
    s = fx.setup_dispatched_route_with_stop(name_suffix="im", service_date="2026-07-02")
    resp = api.create_attempt(
        s["stop"]["id"], {"outcome": "NO_ONE_HOME"},
        fx.make_driver_headers(s["driver"]["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["attempt_index"] == 1
    assert "version" not in data, "DeliveryAttempt must not carry a version field"
    assert "updated_at" not in data, "DeliveryAttempt must not carry an updated_at field"
