"""Envelope shape, resource creation/defaults, not-found, pagination."""
from test_helpers import (
    FO,
    LM,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_jurisdiction,
    assert_production,
    create_jurisdiction_payload,
    create_owner_payload,
    create_production_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_success_envelope_shape_on_object_response(api):
    """PRD §2.2: "All successful API responses (those with 2xx status codes)
    follow this standard envelope format in their JSON body:"
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/success_envelope_shape_on_object_response
    """
    create_resp = api.create_production(create_production_payload(), LM)
    body = validate_success(create_resp, 201)
    raw = create_resp.json()
    assert "meta" in raw and "response_type" in raw and "data" in raw
    request_id = raw["meta"]["api_request_id"]
    assert isinstance(request_id, str) and request_id.startswith("req_"), (
        f"api_request_id must start with req_, got {request_id!r}"
    )
    assert is_iso8601_timestamp(raw["meta"]["api_request_timestamp"])
    assert raw["response_type"] == "object"

    get_resp = api.get_production(body["id"], LM)
    get_raw = get_resp.json()
    assert get_raw["response_type"] == "object"
    assert get_raw["data"]["id"] == body["id"]


def test_error_envelope_shape_on_failure(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this standard
    envelope format:"
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/endpoints/error_envelope_shape_on_failure
    """
    resp = api.get_location(NON_EXISTENT_UUID, LM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    raw = resp.json()
    assert raw["response_type"] == "error"
    assert raw["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(raw["data"]["message"], str) and raw["data"]["message"], (
        "error message must be a non-empty human-readable string"
    )


def test_production_create_applies_initial_state_and_version(api):
    """PRD §3.2: "With a production created — a `LocationManager` opens it with a
    `title`, the `production_company` legal entity name, the `cast_size` (total
    cast and crew headcount on the largest shoot day, which drives both the
    large-cast fee tier and monitor staffing), and the
    `umbrella_liability_limit_cents` the production carries, starting in `PREP`
    with `version` 1"
    PRD §2.4: "`id` (string): a unique, server-minted identifier for the resource,
    formatted as a UUID with no type prefix."
    PRD §2.4: "`created_at` (string): an ISO 8601 timestamp in UTC with three
    fractional digits (e.g., `2026-08-01T10:30:00.123Z`) indicating when the
    resource was first created."

    Design: Corner/entities/production_create_applies_initial_state_and_version
    """
    resp = api.create_production(create_production_payload(), LM)
    data = validate_success(resp, 201)
    assert_production(data)
    assert data["status"] == "PREP"
    assert data["version"] == 1
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])


def test_jurisdiction_create_missing_required_field_returns_invalid_request(api):
    """PRD §3.1: "a `FilmOffice` operator configures each **Jurisdiction** in
    which filming may occur" with "the full regulatory parameter set:
    `lead_time_business_days` (the minimum number of business days that must lie
    between permit submission and the earliest shoot day)"
    PRD §2.7: "finally payload well-formedness — required fields present and
    well-typed, enum values valid, dates parseable — as `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/jurisdiction_create_missing_required_field_returns_invalid_request
    """
    payload = create_jurisdiction_payload()
    del payload["lead_time_business_days"]
    resp = api.create_jurisdiction(payload, FO)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    _, meta = validate_paginated(api.list_jurisdictions(FO))
    assert meta["total_count"] == 0, "No jurisdiction may be persisted after a 400"


def test_jurisdiction_create_omitting_holidays_defaults_empty(api):
    """PRD §3.1: "an optional `holidays` array of ISO `YYYY-MM-DD` dates that
    defaults to an empty list and is excluded from business-day counting"
    PRD §3.1: "A jurisdiction is created `ACTIVE`"

    Design: Corner/entities/jurisdiction_create_omitting_holidays_defaults_empty
    """
    payload = create_jurisdiction_payload()
    del payload["holidays"]
    resp = api.create_jurisdiction(payload, FO)
    data = validate_success(resp, 201)
    assert_jurisdiction(data)
    assert data["holidays"] == []
    assert data["status"] == "ACTIVE"


def test_location_get_unknown_id_returns_not_found(api):
    """PRD §2.7: "the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the
    first identifier — parent `{id}` or child `{rid}` — that does not exist or
    does not belong to the enclosing production's scope"

    Design: Corner/entities/location_get_unknown_id_returns_not_found
    """
    resp = api.get_location(NON_EXISTENT_UUID, LM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_owners_list_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to
    return."
    PRD §2.3: "Paginated and non-paginated list-based responses include the
    following fields in the `meta` object of the response envelope: `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/owners_list_pagination_envelope
    """
    for i in range(3):
        payload = create_owner_payload(
            legal_name=f"Owner {i}", contact_email=f"owner-page-{i}@x.com",
            default_day_rate_cents=150_000 + i * 10_000,
        )
        validate_success(api.create_owner(payload, LM), 201)

    page1, meta1 = validate_paginated(api.list_owners(LM, params={"limit": 2, "offset": 0}))
    assert len(page1) == 2, f"Expected 2 rows at limit=2, got {len(page1)}"
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2 and meta1["offset"] == 0

    page2, meta2 = validate_paginated(api.list_owners(LM, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1, f"Expected the final row at offset=2, got {len(page2)}"
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
