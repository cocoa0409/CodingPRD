"""SKU and location configuration: creation, defaults, type/enum validation,
uniqueness, listing, and the access-control gate that fronts every mutation.

Covers queue-B corner instances under entities, validations (duplicate code),
and rbac.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    assert_sku, assert_location, assert_outbound_order,
    create_sku_payload, create_location_payload, create_outbound_order_payload,
    create_wave_payload, add_order_to_wave_payload, release_wave_payload,
    create_order_line_payload,
    NON_EXISTENT_UUID,
)
import test_helpers as th

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK = TEST_USERS["receiving_clerk_headers"]
PLANNER = TEST_USERS["wave_planner_headers"]


def test_create_sku_returns_201_with_initialized_computed_fields(api):
    """PRD 3.1: "A newly created SKU starts with on_hand_qty at zero, available_qty
    at zero, and cycle_count_due set to true."

    Design: Corner/entities/create_sku_returns_201_with_all_fields
    """
    resp = api.create_sku(
        create_sku_payload(sku_code="SKU-NEW", abc_class="C", each_volume_cm3=2.5, min_qty=3, max_qty=30),
        ADMIN,
    )
    data = validate_success(resp, 201)
    assert_sku(data)
    assert data["abc_class"] == "C"
    assert data["on_hand_qty"] == 0
    assert data["available_qty"] == 0
    assert data["cycle_count_due"] is True


def test_get_sku_not_found_returns_404(api):
    """PRD 2.5: "a parent that does not resolve to an existing entity produces
    ERR_NOT_FOUND (HTTP 404) before any child segment is examined".

    Design: Corner/entities/get_sku_not_found_returns_404
    """
    resp = api.get_sku(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_create_sku_missing_required_field_returns_422(api):
    """PRD 2.11: "fourth, request-body well-formedness — required fields present and
    correctly typed, and any enum value within its declared set (ERR_INVALID_REQUEST)".

    Design: Corner/entities/create_sku_missing_required_field_returns_422
    """
    payload = create_sku_payload(sku_code="SKU-BAD")
    payload.pop("abc_class")
    resp = api.create_sku(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_create_sku_invalid_enum_abc_class_returns_422(api):
    """PRD 2.11: "fourth, request-body well-formedness — required fields present and
    correctly typed, and any enum value within its declared set (ERR_INVALID_REQUEST)".

    Design: Corner/entities/create_sku_invalid_enum_abc_class_returns_422
    """
    resp = api.create_sku(create_sku_payload(sku_code="SKU-ENUM", abc_class="Z"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_create_location_defaults_status_available(api):
    """PRD 3.1: "A location's operational status is either AVAILABLE or BLOCKED and
    defaults to AVAILABLE. Its consumed-capacity figure used_volume_cm3 initializes
    to zero".

    Design: Corner/entities/create_location_default_status_available
    """
    resp = api.create_location(create_location_payload(location_code="RS-DEF", zone="RESERVE", max_volume_cm3=100), ADMIN)
    data = validate_success(resp, 201)
    assert_location(data)
    assert data["status"] == "AVAILABLE"
    assert data["used_volume_cm3"] == 0


def test_create_order_defaults_priority_five(api):
    """PRD 3.6: "an optional priority integer that defaults to 5 and must be at least
    1". PRD 3.6: "A new order begins in status OPEN".

    Design: Corner/entities/order_default_priority_applied
    """
    payload = create_outbound_order_payload(order_number="ORD-DEF")
    payload.pop("priority")
    resp = api.create_outbound_order(payload, PLANNER)
    data = validate_success(resp, 201)
    assert_outbound_order(data)
    assert data["priority"] == 5
    assert data["status"] == "OPEN"


def test_sku_on_hand_is_computed_from_stored_plates(api):
    """PRD 3.1: "The on_hand_qty is the total eaches across every license plate of
    that SKU whose disposition is STORED, ALLOCATED, or PICKED_STAGED". PRD 2.6:
    "the server recomputes the derived fields on that read so the returned values
    are current."

    Design: Corner/entities/lpn_computed_onhand_ignores_input
    """
    sku, loc, lpn = th.setup_stored_lpn(sku_overrides={"abc_class": "C", "each_volume_cm3": 1}, qty=7)
    data = validate_success(api.get_sku(sku["id"], TEST_USERS["inventory_controller_headers"]))
    assert data["on_hand_qty"] == 7


def test_list_skus_returns_array_with_pagination_meta(api):
    """PRD 2.3: "The meta block of a list response reports limit, offset, total_count
    (the full number of records matching the query before pagination), and has_more
    (true when records remain beyond the current page)."

    Design: Corner/entities/list_skus_pagination_envelope
    """
    th.create_sku(sku_code="SKU-L1", abc_class="A")
    th.create_sku(sku_code="SKU-L2", abc_class="B")
    resp = api.list_skus(ADMIN)
    data, meta = validate_paginated(resp)
    body = resp.json()
    assert body["response_type"] == "array"
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_duplicate_sku_code_returns_conflict(api):
    """PRD 3.1: "The sku_code must be unique across all SKUs and non-empty; a
    collision is rejected with ERR_DUPLICATE_CODE."

    Design: Corner/validations/duplicate_sku_code_returns_conflict
    """
    th.create_sku(sku_code="SKU-DUP", abc_class="A")
    resp = api.create_sku(create_sku_payload(sku_code="SKU-DUP", abc_class="B"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CODE.value, 409)


# ── RBAC / auth gate ──────────────────────────────────────────────────────────

def test_picker_cannot_create_sku_returns_forbidden(api):
    """PRD 2.1: "If the headers are well-formed but the named role is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE
    (HTTP 403)." PRD 4: POST /warehouse/skus authorized role is PlatformAdmin.

    Design: Corner/rbac/picker_cannot_create_sku_returns_forbidden
    """
    resp = api.create_sku(create_sku_payload(sku_code="SKU-RB1", abc_class="A"), TEST_USERS["picker_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_receiving_clerk_cannot_release_wave_returns_forbidden(api):
    """PRD 2.1: "If the headers are well-formed but the named role is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE
    (HTTP 403)." PRD 4: POST /warehouse/waves/{id}/release authorized role is WavePlanner.

    Design: Corner/rbac/receiving_clerk_cannot_release_wave_returns_forbidden
    """
    sku = th.create_sku(sku_code="SKU-RB2", abc_class="A")
    order, line = th.create_order_with_line(sku["id"], 5)
    wave = th.create_planning_wave()
    th.get_success_data(api.add_order_to_wave(wave["id"], add_order_to_wave_payload(order["id"]), PLANNER))
    wave = th.get_success_data(api.get_wave(wave["id"], PLANNER))
    resp = api.release_wave(wave["id"], release_wave_payload(wave["version"]), CLERK)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD 2.1: "On any mutating request, if either header is missing or malformed,
    the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api._request("POST", "/warehouse/skus",
                        create_sku_payload(sku_code="SKU-NA1", abc_class="A"),
                        {"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
