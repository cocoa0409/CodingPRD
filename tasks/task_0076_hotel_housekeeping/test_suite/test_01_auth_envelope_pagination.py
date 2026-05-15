"""Auth, envelope, pagination, and RBAC negative-path coverage.

These tests exercise rules that gate every request before any
domain-specific work (PRD §2.1, §2.2, §2.3, §2.5).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    create_cleaning_task_payload,
    create_housekeeper_payload,
    create_room_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    create_housekeeper_on_shift,
    create_room,
    setup_room_hk_task,
)


# ===========================================================================
# Header presence (PRD §2.1)
# ===========================================================================
@pytest.mark.parametrize("missing_header", ["X-User-ID", "X-User-Role"])
def test_missing_user_context_header_rejected(api, missing_header):
    """PRD §2.1: "A request that omits either header, or sends one of
    them empty, is rejected with ERR_MISSING_USER_CONTEXT."

    Claim: omitting X-User-ID or X-User-Role yields
    ERR_MISSING_USER_CONTEXT (HTTP 400).
    """
    headers = dict(TEST_USERS["frontdesk_headers"])
    headers.pop(missing_header)
    res = api.create_room(create_room_payload(), headers)
    validate_error(res, ApiErrorId.ERR_MISSING_USER_CONTEXT.value)


@pytest.mark.parametrize("empty_header", ["X-User-ID", "X-User-Role"])
def test_empty_user_context_header_rejected(api, empty_header):
    """PRD §2.1: "A request that omits either header, or sends one of
    them empty, is rejected with ERR_MISSING_USER_CONTEXT."
    """
    headers = dict(TEST_USERS["frontdesk_headers"])
    headers[empty_header] = ""
    res = api.create_room(create_room_payload(), headers)
    validate_error(res, ApiErrorId.ERR_MISSING_USER_CONTEXT.value)


# ===========================================================================
# RBAC — wrong role rejected (PRD §2.1, §4)
# ===========================================================================
def test_create_room_rejected_for_non_frontdesk(api):
    """PRD §4 (Endpoint Definitions table): POST /rooms is authorized
    for FrontDesk only.

    PRD §2.1: "A request whose role is not permitted for the requested
    endpoint is rejected with ERR_INSUFFICIENT_PERMISSIONS."
    """
    res = api.create_room(
        create_room_payload(), TEST_USERS["housekeeper_headers"],
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_create_housekeeper_rejected_for_frontdesk(api):
    """PRD §4: POST /housekeepers is authorized for Supervisor only.

    PRD §2.1: "A request whose role is not permitted for the requested
    endpoint is rejected with ERR_INSUFFICIENT_PERMISSIONS."
    """
    res = api.create_housekeeper(
        create_housekeeper_payload(), TEST_USERS["frontdesk_headers"],
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_dispatch_maintenance_rejected_for_housekeeper(api):
    """PRD §4: POST /maintenance-tickets/{ticketId}/dispatch is
    authorized for Supervisor only.

    PRD §2.1: "A request whose role is not permitted for the requested
    endpoint is rejected with ERR_INSUFFICIENT_PERMISSIONS."
    """
    res = api.dispatch_maintenance_ticket(
        NON_EXISTENT_UUID, {"engineering_assignee": "eng-1"},
        TEST_USERS["housekeeper_headers"],
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_post_minibar_consumption_rejected_for_supervisor(api):
    """PRD §4: POST /minibar-consumptions/{id}/post is exclusive to
    FrontDesk.

    PRD §2.1: "A request whose role is not permitted for the requested
    endpoint is rejected with ERR_INSUFFICIENT_PERMISSIONS."
    """
    res = api.post_minibar_consumption(
        NON_EXISTENT_UUID, TEST_USERS["supervisor_headers"],
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


# ===========================================================================
# Not-found errors (PRD §2.5)
# ===========================================================================
def test_get_room_not_found(api):
    """PRD §2.5: "The first identifier that fails to resolve emits its
    specific not-found error (ERR_ROOM_NOT_FOUND, ..."
    """
    res = api.get_room(NON_EXISTENT_UUID, TEST_USERS["frontdesk_headers"])
    validate_error(res, ApiErrorId.ERR_ROOM_NOT_FOUND.value)


def test_get_cleaning_task_not_found(api):
    """PRD §2.5: "The first identifier that fails to resolve emits its
    specific not-found error (ERR_ROOM_NOT_FOUND, ERR_TASK_NOT_FOUND,
    ERR_TICKET_NOT_FOUND, ERR_CONSUMPTION_NOT_FOUND,
    ERR_MOVEMENT_NOT_FOUND, ERR_HOUSEKEEPER_NOT_FOUND,
    ERR_MINIBAR_ITEM_NOT_FOUND, ERR_LINEN_TYPE_NOT_FOUND, or
    ERR_INSPECTION_NOT_FOUND)."

    Claim: GET on a missing CleaningTask id surfaces
    ERR_TASK_NOT_FOUND.
    """
    res = api.get_cleaning_task(
        NON_EXISTENT_UUID, TEST_USERS["frontdesk_headers"],
    )
    validate_error(res, ApiErrorId.ERR_TASK_NOT_FOUND.value)


def test_get_maintenance_ticket_not_found(api):
    """PRD §2.5: "The first identifier that fails to resolve emits its
    specific not-found error (... ERR_TICKET_NOT_FOUND ...)."
    """
    res = api.get_maintenance_ticket(
        NON_EXISTENT_UUID, TEST_USERS["frontdesk_headers"],
    )
    validate_error(res, ApiErrorId.ERR_TICKET_NOT_FOUND.value)


def test_get_minibar_consumption_not_found(api):
    """PRD §2.5: "The first identifier that fails to resolve emits its
    specific not-found error (... ERR_CONSUMPTION_NOT_FOUND ...)."
    """
    res = api.get_minibar_consumption(
        NON_EXISTENT_UUID, TEST_USERS["frontdesk_headers"],
    )
    validate_error(res, ApiErrorId.ERR_CONSUMPTION_NOT_FOUND.value)


def test_get_housekeeper_not_found(api):
    """PRD §2.5: "The first identifier that fails to resolve emits its
    specific not-found error (... ERR_HOUSEKEEPER_NOT_FOUND ...)."
    """
    res = api.get_housekeeper(
        NON_EXISTENT_UUID, TEST_USERS["supervisor_headers"],
    )
    validate_error(res, ApiErrorId.ERR_HOUSEKEEPER_NOT_FOUND.value)


def test_create_cleaning_task_unknown_room_id(api):
    """PRD §2.5: "Foreign-key references inside a request body ... are
    validated with the same not-found error codes."
    """
    payload = create_cleaning_task_payload(
        room_id=NON_EXISTENT_UUID, task_source="SCHEDULED",
    )
    res = api.create_cleaning_task(
        payload, TEST_USERS["supervisor_headers"],
    )
    validate_error(res, ApiErrorId.ERR_ROOM_NOT_FOUND.value)


# ===========================================================================
# Pagination (PRD §2.3)
# ===========================================================================
def test_default_pagination_envelope(api):
    """PRD §2.3: "The meta block of every list response carries limit,
    offset, total_count, and has_more."
    """
    # Seed at least one room so the list is non-empty.
    create_room()
    res = api.list_rooms(TEST_USERS["supervisor_headers"])
    data, meta = validate_paginated(res)
    assert isinstance(data, list)
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta, f"meta must contain {key!r}, got {meta!r}"
    # PRD §2.3: "limit defaults to 10"
    assert meta["limit"] == 10


@pytest.mark.parametrize("limit", [0, -1, 101, 1000])
def test_pagination_limit_out_of_range_rejected(api, limit):
    """PRD §2.3: "A request with limit outside that inclusive range, or
    with offset below zero, is rejected with ERR_INVALID_PAGINATION."
    Range is [1, 100] (PRD §2.3).
    """
    res = api.list_rooms(
        TEST_USERS["supervisor_headers"], params={"limit": limit},
    )
    validate_error(res, ApiErrorId.ERR_INVALID_PAGINATION.value)


def test_pagination_offset_negative_rejected(api):
    """PRD §2.3: "with offset below zero, is rejected with
    ERR_INVALID_PAGINATION."
    """
    res = api.list_rooms(
        TEST_USERS["supervisor_headers"], params={"offset": -1},
    )
    validate_error(res, ApiErrorId.ERR_INVALID_PAGINATION.value)


def test_pagination_boundary_values_accepted(api):
    """PRD §2.3: "limit defaults to 10, has a minimum of 1, and a
    maximum of 100; offset defaults to 0 and has a minimum of 0."
    """
    create_room()
    res = api.list_rooms(
        TEST_USERS["supervisor_headers"],
        params={"limit": 1, "offset": 0},
    )
    data, meta = validate_paginated(res)
    assert meta["limit"] == 1
    assert meta["offset"] == 0

    res = api.list_rooms(
        TEST_USERS["supervisor_headers"], params={"limit": 100},
    )
    data, meta = validate_paginated(res)
    assert meta["limit"] == 100


# ===========================================================================
# Standard success envelope (PRD §2.2)
# ===========================================================================
def test_success_envelope_shape(api):
    """PRD §2.2: "All successful API responses (those with 2xx status
    codes) follow this standard envelope format in their JSON body" —
    includes meta.api_request_id, meta.api_request_timestamp, and
    response_type plus data.
    """
    room = create_room()
    res = api.get_room(room["id"], TEST_USERS["frontdesk_headers"])
    data = validate_success(res)
    body = res.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_"), (
        "PRD §2.2: 'a server-generated unique identifier for the request "
        "that starts with req_'"
    )
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert data["id"] == room["id"]
