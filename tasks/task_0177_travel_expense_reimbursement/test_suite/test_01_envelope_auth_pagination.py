"""Envelope, auth header validation, pagination defaults / bounds.

Covers PRD §2.1 (X-User-ID / X-User-Role header rules),
PRD §2.2 (standard envelope), PRD §2.3 (pagination), PRD §2.5 (path
parameter resolution / not-found).
"""
from __future__ import annotations

import uuid

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_MAX_LIMIT,
    TEST_DEFAULTS,
    TEST_USERS,
    admin_headers as default_admin_headers,
    api_client,
    build_user_headers,
    create_employee_payload,
    create_per_diem_rate_payload,
    create_trip_payload,
    make_traveler_headers,
    seed_default_boston_rate,
    seed_manager,
    seed_traveler,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Envelope shape — PRD §2.2
# ===========================================================================
def test_success_response_envelope_has_meta_and_data(api):
    """PRD §2.2: "All successful API responses (those with 2xx status
    codes) follow this standard envelope format in their JSON body".

    Claim: success body carries meta { api_request_id, api_request_timestamp }
    plus response_type and data.
    """
    res = api.create_per_diem_rate(
        create_per_diem_rate_payload(city=f"City-{uuid.uuid4().hex[:6]}"),
        default_admin_headers(),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert "meta" in body and "data" in body
    assert "api_request_id" in body["meta"]
    assert body["meta"]["api_request_id"].startswith("req_")
    assert "api_request_timestamp" in body["meta"]
    assert body["response_type"] in ("object", "array")


def test_error_response_envelope_has_error_id_and_message(api,
                                                          traveler_headers):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format ... the `error_id` is a unique,
    machine-readable string ... the `message` provides a human-readable
    explanation".
    """
    res = api.get_trip(NON_EXISTENT_UUID, traveler_headers)
    assert res.status_code == 404, res.text
    body = res.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]


# ===========================================================================
# Auth header validation — PRD §2.1
# ===========================================================================
def test_missing_both_auth_headers_returns_missing_auth(api):
    """PRD §2.1: "Every request to the API must carry two headers:
    `X-User-ID`, a UUID that identifies the calling principal, and
    `X-User-Role`, a string identifying the principal's functional role.
    When either header is missing, empty, or `X-User-ID` is not a
    well-formed UUID, the request is rejected with `ERR_MISSING_AUTH`."
    """
    res = api.create_per_diem_rate(create_per_diem_rate_payload(), {})
    validate_error(res, "ERR_MISSING_AUTH")


def test_missing_user_id_header_returns_missing_auth(api):
    """PRD §2.1: "When either header is missing, empty, or `X-User-ID`
    is not a well-formed UUID, the request is rejected with
    `ERR_MISSING_AUTH`."
    """
    res = api.create_per_diem_rate(
        create_per_diem_rate_payload(),
        {"X-User-Role": "ADMIN"},
    )
    validate_error(res, "ERR_MISSING_AUTH")


def test_missing_role_header_returns_missing_auth(api):
    """PRD §2.1: "When either header is missing, empty, or `X-User-ID`
    is not a well-formed UUID, the request is rejected with
    `ERR_MISSING_AUTH`."
    """
    res = api.create_per_diem_rate(
        create_per_diem_rate_payload(),
        {"X-User-ID": str(uuid.uuid4())},
    )
    validate_error(res, "ERR_MISSING_AUTH")


def test_malformed_uuid_user_id_returns_missing_auth(api):
    """PRD §2.1: "When either header is missing, empty, or `X-User-ID`
    is not a well-formed UUID, the request is rejected with
    `ERR_MISSING_AUTH`."
    """
    res = api.create_per_diem_rate(
        create_per_diem_rate_payload(),
        {"X-User-ID": "not-a-uuid", "X-User-Role": "ADMIN"},
    )
    validate_error(res, "ERR_MISSING_AUTH")


def test_unrecognized_role_returns_invalid_role(api):
    """PRD §2.1: "When `X-User-Role` does not match a known role, or
    when the supplied `X-User-ID` does not resolve to an `Employee`
    carrying that role, the request is rejected with `ERR_INVALID_ROLE`."
    """
    res = api.create_per_diem_rate(
        create_per_diem_rate_payload(),
        build_user_headers(str(uuid.uuid4()), "SUPER_ADMIN"),
    )
    validate_error(res, "ERR_INVALID_ROLE")


def test_traveler_user_id_does_not_resolve_to_employee_returns_invalid_role(
    api,
):
    """PRD §2.1: "When `X-User-Role` does not match a known role, or
    when the supplied `X-User-ID` does not resolve to an `Employee`
    carrying that role, the request is rejected with `ERR_INVALID_ROLE`."

    Use a fresh well-formed UUID that no Employee owns; role is TRAVELER
    (entity_backed), so the binding check must fail.
    """
    fresh_id = str(uuid.uuid4())
    payload = create_trip_payload(traveler_id=fresh_id)
    res = api.create_trip(
        payload, build_user_headers(fresh_id, "TRAVELER"),
    )
    validate_error(res, "ERR_INVALID_ROLE")


def test_wrong_role_for_endpoint_returns_invalid_role(api):
    """PRD §2.1: "an authenticated principal whose role is not on the
    endpoint's authorized list receives `ERR_INVALID_ROLE` as well."

    /per-diem-rates POST is ADMIN-only; a TRAVELER call must fail.
    """
    manager = seed_manager()
    traveler = seed_traveler(manager_id=manager["id"])
    res = api.create_per_diem_rate(
        create_per_diem_rate_payload(city=f"City-{uuid.uuid4().hex[:6]}"),
        make_traveler_headers(traveler["id"]),
    )
    validate_error(res, "ERR_INVALID_ROLE")


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
def test_pagination_default_limit_is_ten(api):
    """PRD §2.3: "`limit` defaults to 10 when omitted"."""
    # Seed at least 11 trips so we can detect the default limit cleanly.
    cast = {"manager": seed_manager()}
    cast["traveler"] = seed_traveler(manager_id=cast["manager"]["id"])
    seed_default_boston_rate()
    for _ in range(11):
        api.create_trip(
            create_trip_payload(traveler_id=cast["traveler"]["id"]),
            make_traveler_headers(cast["traveler"]["id"]),
        )
    data, meta = validate_paginated(
        api.list_trips(make_traveler_headers(cast["traveler"]["id"])),
    )
    assert meta["limit"] == PAGINATION_DEFAULT_LIMIT
    assert len(data) <= PAGINATION_DEFAULT_LIMIT


def test_pagination_meta_has_total_count_and_has_more(api):
    """PRD §2.3: "the response `meta` block carries the four pagination
    keys `limit`, `offset`, `total_count`, and `has_more`. `total_count`
    is the count of records matching the filter before pagination is
    applied; `has_more` is true when `offset + limit < total_count`."
    """
    cast = {"manager": seed_manager()}
    cast["traveler"] = seed_traveler(manager_id=cast["manager"]["id"])
    seed_default_boston_rate()
    for _ in range(3):
        api.create_trip(
            create_trip_payload(traveler_id=cast["traveler"]["id"]),
            make_traveler_headers(cast["traveler"]["id"]),
        )
    data, meta = validate_paginated(
        api.list_trips(
            make_traveler_headers(cast["traveler"]["id"]),
            params={"limit": 1, "traveler_id": cast["traveler"]["id"]},
        ),
    )
    assert meta["total_count"] >= 3
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0


def test_pagination_offset_past_end_yields_empty(api):
    """PRD §2.3: "`has_more` is true when `offset + limit < total_count`"
    — therefore at offsets well past total_count, the page is empty and
    has_more is false.
    """
    cast = {"manager": seed_manager()}
    cast["traveler"] = seed_traveler(manager_id=cast["manager"]["id"])
    seed_default_boston_rate()
    api.create_trip(
        create_trip_payload(traveler_id=cast["traveler"]["id"]),
        make_traveler_headers(cast["traveler"]["id"]),
    )
    data, meta = validate_paginated(
        api.list_trips(
            make_traveler_headers(cast["traveler"]["id"]),
            params={"offset": 99999, "traveler_id": cast["traveler"]["id"]},
        ),
    )
    assert data == []
    assert meta["has_more"] is False


def test_pagination_limit_above_max_rejected(api):
    """PRD §2.3: "`limit` ... may not exceed 100"."""
    cast = {"manager": seed_manager()}
    cast["traveler"] = seed_traveler(manager_id=cast["manager"]["id"])
    res = api.list_trips(
        make_traveler_headers(cast["traveler"]["id"]),
        params={"limit": PAGINATION_MAX_LIMIT + 1},
    )
    assert res.status_code >= 400, res.text


def test_pagination_limit_below_min_rejected(api):
    """PRD §2.3: "`limit` ... may not be less than 1"."""
    cast = {"manager": seed_manager()}
    cast["traveler"] = seed_traveler(manager_id=cast["manager"]["id"])
    res = api.list_trips(
        make_traveler_headers(cast["traveler"]["id"]),
        params={"limit": 0},
    )
    assert res.status_code >= 400, res.text


def test_pagination_negative_offset_rejected(api):
    """PRD §2.3: "`offset` defaults to 0 and may not be negative"."""
    cast = {"manager": seed_manager()}
    cast["traveler"] = seed_traveler(manager_id=cast["manager"]["id"])
    res = api.list_trips(
        make_traveler_headers(cast["traveler"]["id"]),
        params={"offset": -1},
    )
    assert res.status_code >= 400, res.text


# ===========================================================================
# Path resolution — PRD §2.5
# ===========================================================================
def test_get_nonexistent_trip_returns_not_found(api, traveler_headers):
    """PRD §2.5: "A miss at any segment yields `ERR_NOT_FOUND`."""
    res = api.get_trip(NON_EXISTENT_UUID, traveler_headers)
    validate_error(res, "ERR_NOT_FOUND")


def test_get_nonexistent_expense_report_returns_not_found(api,
                                                          traveler_headers):
    """PRD §2.5: "Path parameter resolution proceeds left-to-right ... A
    miss at any segment yields `ERR_NOT_FOUND`."
    """
    res = api.get_expense_report(NON_EXISTENT_UUID, traveler_headers)
    validate_error(res, "ERR_NOT_FOUND")


def test_get_nonexistent_employee_returns_not_found(api, admin_headers):
    """PRD §2.5: A miss on a path segment yields `ERR_NOT_FOUND`."""
    res = api.get_employee(NON_EXISTENT_UUID, admin_headers)
    validate_error(res, "ERR_NOT_FOUND")
