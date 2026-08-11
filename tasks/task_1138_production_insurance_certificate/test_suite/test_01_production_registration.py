"""Production registration: creation, retrieval, listing, and input validation."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    is_valid_uuid, NON_EXISTENT_UUID,
    create_production_payload, assert_production,
    set_logical_clock, create_production,
    TEST_USERS,
)

BROKER = TEST_USERS["broker_headers"]


def test_production_create_returns_201_with_server_minted_id(api):
    """PRD §3.1: "A newly registered production is born in `DRAFT` status, and
    its `coverage_posture` initializes to `UNBOUND`."
    PRD §2.4: "The `version` starts at 1 when the resource is created and
    increments by one on every mutation of that resource"
    PRD §3.1: "optionally `requires_completion_bond`, which defaults to false
    and records that the budget or a financier mandates a completion bond."

    Design: Corner/entities/production_create_returns_201_with_server_minted_id
    """
    set_logical_clock()
    payload = create_production_payload(production_type="FEATURE")
    del payload["requires_completion_bond"]  # exercise the documented default
    res = api.create_production(payload, BROKER)
    prod = validate_success(res, 201)
    assert_production(prod)
    assert is_valid_uuid(prod["id"]), "id must be a server-minted UUID"
    assert prod["status"] == "DRAFT"
    assert prod["coverage_posture"] == "UNBOUND"
    assert prod["version"] == 1
    assert prod["requires_completion_bond"] is False


def test_production_get_not_found_returns_404(api):
    """PRD §2.9: "Any identifier that does not resolve to an existing entity
    is `ERR_NOT_FOUND` (404)."

    Design: Corner/entities/production_get_not_found_returns_404
    """
    set_logical_clock()
    res = api.get_production(NON_EXISTENT_UUID, BROKER)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_production_list_pagination_envelope(api):
    """PRD §2.3: "The `meta` object of every list response carries four
    pagination fields: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/production_list_pagination_envelope
    """
    set_logical_clock()
    for _ in range(3):
        create_production()
    data, meta = validate_paginated(
        api.list_productions(BROKER, params={"limit": 2, "offset": 0}))
    assert meta["total_count"] == 3
    assert len(data) == 2
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["has_more"] is True


def test_production_create_missing_required_field_returns_invalid_request(api):
    """PRD §2.9: "Requests whose bodies are missing required fields or carry
    malformed types, outside the specific checks above, are rejected with
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/production_create_missing_required_field_returns_invalid_request
    """
    set_logical_clock()
    payload = create_production_payload()
    del payload["production_code"]
    res = api.create_production(payload, BROKER)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_production_invalid_enum_production_type_returns_invalid_enum(api):
    """PRD §2.9: "Enum membership for every enum-typed field (`coverage_line`,
    `claim_type`, `endorsement_type`, and the rest); an undeclared value is
    `ERR_INVALID_ENUM` (400)."

    Design: Corner/entities/production_invalid_enum_production_type_returns_invalid_enum
    """
    set_logical_clock()
    payload = create_production_payload(production_type="BAD_TYPE")
    res = api.create_production(payload, BROKER)
    validate_error(res, "ERR_INVALID_ENUM", expected_status=400)


def test_production_invalid_temporal_range_returns_temporal_error(api):
    """PRD §3.1: "the scheduled shooting window as `principal_photography_start`
    and `principal_photography_end` (the last shooting day must fall strictly
    after the first)"
    PRD §2.9: "Datetime ordering: every end must fall strictly after its start,
    and a claim's `occurrence_date` must lie inside the referenced policy's
    effective window; violations are `ERR_TEMPORAL_RANGE_INVALID` (422)."

    Design: Corner/entities/production_invalid_temporal_range_returns_temporal_error
    """
    set_logical_clock()
    payload = create_production_payload(
        principal_photography_start="2026-08-01T00:00:00Z",
        principal_photography_end="2026-06-01T00:00:00Z")
    res = api.create_production(payload, BROKER)
    validate_error(res, "ERR_TEMPORAL_RANGE_INVALID", expected_status=422)
