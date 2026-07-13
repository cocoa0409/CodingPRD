"""Device registration, computed fields, listing, and role denial."""
import test_helpers as th
from test_helpers import ApiErrorId


def test_device_create_returns_registered_with_computed_fields(api):
    """PRD §3.1: "On registration the device is placed in `REGISTERED` status and
    its `risk_class` is computed from its `category` via the authority's fixed
    risk-class map".
    PRD §3.1: "a `PASSENGER_ELEVATOR` maps to `HIGH`".
    PRD §3.1: "the system automatically creates a REGISTRATION fee invoice for
    the device, in PENDING status, whose due date is the device's install_period,
    and immediately reflects that charge in the device's conserved
    outstanding_balance_cents."
    PRD §2.4: "The version starts at 1 when the resource is created".

    Design: Corner/entities/device_create_returns_registered_with_computed_fields
    """
    owner = th.new_owner(api)
    resp = api.create_device(
        th.create_device_payload(owner["id"], category="PASSENGER_ELEVATOR", location_description="L1"),
        th.REG,
    )
    device = th.validate_success(resp, expected_status=201)
    th.assert_device(device)
    assert device["status"] == "REGISTERED"
    assert device["risk_class"] == "HIGH"
    assert device["outstanding_balance_cents"] == 10000
    assert device["version"] == 1


def test_get_nonexistent_device_returns_not_found(api):
    """PRD §2.9: "existence of every resource id named in the URL path, validated
    left to right ... each missing id yielding the corresponding not-found error
    such as ERR_DEVICE_NOT_FOUND".

    Design: Corner/entities/get_nonexistent_device_returns_not_found
    """
    resp = api.get_device(th.NON_EXISTENT_UUID, th.REG)
    th.validate_error(resp, ApiErrorId.ERR_DEVICE_NOT_FOUND.value)


def test_device_create_missing_category_returns_invalid_request(api):
    """PRD §2.9: "A malformed body — missing required field, unknown enum value,
    or a type mismatch — is rejected with ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/device_create_missing_category_returns_invalid_request
    """
    owner = th.new_owner(api)
    resp = api.create_device(
        {"owner_id": owner["id"], "location_description": "L2", "install_period": 0},
        th.REG,
    )
    th.validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_device_risk_class_computed_dumbwaiter_is_low(api):
    """PRD §3.1: "its `risk_class` is computed from its `category` via the
    authority's fixed risk-class map".
    PRD §3.1: "and a `DUMBWAITER` to `LOW`."

    Design: Corner/entities/device_risk_class_computed_dumbwaiter_is_low
    """
    owner = th.new_owner(api)
    resp = api.create_device(
        th.create_device_payload(owner["id"], category="DUMBWAITER", location_description="L3"),
        th.REG,
    )
    device = th.validate_success(resp, expected_status=201)
    assert device["risk_class"] == "LOW"


def test_devices_list_pagination_envelope(api):
    """PRD §2.3: "total_count reports the total number of matching records across
    all pages, and has_more is true when additional records remain beyond the
    current page."
    PRD §2.3: "The limit parameter defaults to 10, has a minimum of 1, and a
    maximum of 100."

    Design: Corner/entities/devices_list_pagination_envelope
    """
    owner = th.new_owner(api)
    th.new_device(api, owner["id"], category="PASSENGER_ELEVATOR", location_description="D1")
    th.new_device(api, owner["id"], category="ESCALATOR", location_description="D2")
    resp = api.list_devices(th.REG, params={"owner_id": owner["id"], "limit": 1, "offset": 0})
    data, meta = th.validate_paginated(resp)
    assert len(data) == 1, "limit=1 must return at most one device"
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_building_owner_cannot_register_device(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted
    to perform the requested operation, the request is rejected with
    ERR_INSUFFICIENT_PERMISSIONS (HTTP 403)."
    PRD §4 endpoint table: POST /devices is authorized for Registrar only.

    Design: Corner/rbac/building_owner_cannot_register_device
    """
    owner = th.new_owner(api)
    resp = api.create_device(
        th.create_device_payload(owner["id"], category="PASSENGER_ELEVATOR", location_description="F1"),
        th.make_building_owner_headers(owner["id"]),
    )
    th.validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)
