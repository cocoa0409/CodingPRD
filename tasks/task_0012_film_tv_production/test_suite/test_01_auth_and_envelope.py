"""Auth, authorization, existence, response envelope, and pagination.

Covers PRD §2.1 (auth), §2.2 (envelope), §2.3 (pagination), §2.5 (path
existence), §2.10 (priority order).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    NON_EXISTENT_UUID,
    build_user_headers,
    TEST_USERS,
    create_production_payload,
    create_actor_payload,
    setup_production_with_categories,
    create_actor,
    EXEC,
    LP,
    FC,
    CD,
    PC,
)


# ─── §2.1 auth headers ────────────────────────────────────────────────────────

def test_create_production_missing_user_id_header(api):
    """PRD §2.1: "If either header is missing or blank, the request is rejected
    with `ERR_AUTH_REQUIRED` and HTTP 401."

    Claim: missing X-User-ID → ERR_AUTH_REQUIRED (401).
    """
    headers = {"X-User-Role": "ExecutiveProducer", "Content-Type": "application/json"}
    res = api.create_production(create_production_payload(), headers)
    validate_error(res, "ERR_AUTH_REQUIRED", expected_status=401)


def test_create_production_missing_user_role_header(api):
    """PRD §2.1: "If either header is missing or blank, the request is rejected
    with `ERR_AUTH_REQUIRED` and HTTP 401."

    Claim: missing X-User-Role → ERR_AUTH_REQUIRED (401).
    """
    headers = {"X-User-ID": "test-user", "Content-Type": "application/json"}
    res = api.create_production(create_production_payload(), headers)
    validate_error(res, "ERR_AUTH_REQUIRED", expected_status=401)


def test_create_production_blank_user_id_header(api):
    """PRD §2.1: "If either header is missing or blank, the request is rejected
    with `ERR_AUTH_REQUIRED` and HTTP 401."

    Claim: blank X-User-ID → ERR_AUTH_REQUIRED (401).
    """
    headers = {"X-User-ID": "", "X-User-Role": "ExecutiveProducer",
               "Content-Type": "application/json"}
    res = api.create_production(create_production_payload(), headers)
    validate_error(res, "ERR_AUTH_REQUIRED", expected_status=401)


def test_create_production_wrong_role_returns_forbidden(api):
    """PRD §2.1: "If the supplied role is not authorized for the endpoint, the
    request is rejected with `ERR_FORBIDDEN` and HTTP 403."

    Claim: LineProducer attempting POST /productions → ERR_FORBIDDEN.
    """
    res = api.create_production(create_production_payload(), LP)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


@pytest.mark.parametrize("role", [
    "FinanceController",
    "CastingDirector",
    "ProductionCoordinator",
])
def test_only_executive_producer_can_create_production(api, role):
    """PRD §2.1 / §4: POST /productions is exclusive to ExecutiveProducer.

    Claim: any other role yields ERR_FORBIDDEN.
    """
    headers = build_user_headers(f"test-{role}-1", role)
    res = api.create_production(create_production_payload(), headers)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


# ─── §2.5 path existence (left-to-right) ─────────────────────────────────────

def test_get_nonexistent_production(api):
    """PRD §2.10: "Existence — every path-parameter resource (...) resolved
    left-to-right; first-missing yields `ERR_NOT_FOUND`."

    Claim: GET on a non-existent production id → ERR_NOT_FOUND (404).
    """
    res = api.get_production(NON_EXISTENT_UUID, EXEC)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_scene_under_wrong_production_returns_not_found(api):
    """PRD §2.5: "A scene that exists in the database but is parented to a
    different production yields `ERR_NOT_FOUND` against the supplied `{pid}`,
    not `ERR_REFERENCE_MISMATCH`, because path resolution is treated as an
    existence question first."

    Claim: scene-under-wrong-production at GET /productions/{pid}/scenes-style
    nested path → ERR_NOT_FOUND, not ERR_REFERENCE_MISMATCH.
    """
    # Create production A and a scene under A.
    prod_a, _ = setup_production_with_categories(api)
    res_scene = api.create_scene(
        prod_a["id"],
        {
            "scene_number": "S-test",
            "int_ext": "INT",
            "planned_duration_minutes": 60,
            "required_actor_role_ids": [],
            "required_equipment_categories": [],
            "weather_dependent": False,
        },
        LP,
    )
    scene = validate_success(res_scene, 201)

    # Now create production B and try to schedule that scene under B's path.
    prod_b, _ = setup_production_with_categories(api)
    res = api.schedule_scene(
        prod_b["id"], scene["id"],
        {"reservation_id": NON_EXISTENT_UUID},
        LP,
    )
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_get_nonexistent_actor(api):
    """PRD §2.10: path-parameter existence resolves to ERR_NOT_FOUND.

    Claim: GET /actors/<non-existent-uuid> → ERR_NOT_FOUND (404).
    """
    res = api.get_actor(NON_EXISTENT_UUID, CD)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# ─── §2.2 response envelope ──────────────────────────────────────────────────

def test_success_envelope_shape(api):
    """PRD §2.2: success response envelope carries `meta.api_request_id`,
    `meta.api_request_timestamp`, `response_type`, and `data`.

    Claim: a 201 create returns a well-formed success envelope.
    """
    res = api.create_actor(create_actor_payload(legal_name="EnvCheck"), CD)
    actor = validate_success(res, 201)
    body = res.json()
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["response_type"] == "object"
    assert body["data"]["legal_name"] == "EnvCheck"
    assert isinstance(actor["id"], str)


# ─── §2.3 pagination ─────────────────────────────────────────────────────────

def test_list_productions_pagination(api):
    """PRD §2.3: list endpoints return `limit`, `offset`, `total_count`,
    `has_more` in `meta`.

    Claim: a paginated list response carries the four pagination fields.
    """
    # Seed at least one production.
    api.create_production(create_production_payload(), EXEC)

    res = api.list_productions(EXEC, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert isinstance(data, list)
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert isinstance(meta["total_count"], int) and meta["total_count"] >= 1
    assert isinstance(meta["has_more"], bool)


@pytest.mark.parametrize("limit", [0, -1, 101, 1000])
def test_invalid_pagination_limit(api, limit):
    """PRD §2.3: "valid values are integers from 1 through 100 inclusive (...)
    Out-of-bounds values are rejected with `ERR_INVALID_PAGINATION` (HTTP 422)."

    Claim: a limit outside [1, 100] → ERR_INVALID_PAGINATION (422).
    """
    res = api.list_productions(EXEC, params={"limit": limit})
    validate_error(res, "ERR_INVALID_PAGINATION", expected_status=422)


def test_invalid_pagination_negative_offset(api):
    """PRD §2.3: "any non-negative integer is accepted. Out-of-bounds values
    are rejected with `ERR_INVALID_PAGINATION` (HTTP 422)."

    Claim: a negative offset → ERR_INVALID_PAGINATION (422).
    """
    res = api.list_productions(EXEC, params={"offset": -1})
    validate_error(res, "ERR_INVALID_PAGINATION", expected_status=422)


# ─── §2.10 priority: auth (1) before existence (3) ───────────────────────────

def test_auth_check_precedes_existence_check(api):
    """PRD §2.10: priority order is 1) Authentication, 2) Authorization,
    3) Existence — "The earliest failing rule in this list determines the
    response; lower-priority rules are not evaluated."

    Claim: missing auth headers on a non-existent resource still surface
    ERR_AUTH_REQUIRED, not ERR_NOT_FOUND.
    """
    headers = {"Content-Type": "application/json"}
    res = api.get_production(NON_EXISTENT_UUID, headers)
    validate_error(res, "ERR_AUTH_REQUIRED", expected_status=401)
