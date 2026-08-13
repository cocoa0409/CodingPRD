"""Venue setup, response envelope, listing pagination, and read-after-write."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    is_valid_uuid, is_iso8601_timestamp,
    ApiErrorId, NON_EXISTENT_UUID,
    create_track_payload, create_coach_payload, create_track_day_payload,
    make_track, make_track_day,
    TEST_USERS,
)

OPS = TEST_USERS["trackops_headers"]


def test_track_creation_returns_201_with_defaults(api):
    """PRD §4: "Endpoints that create a new resource return 201 with the
    created resource in the envelope". PRD §2.4: "Every persisted resource
    carries an `id` — a server-minted UUID with no type prefix — and a
    `created_at` timestamp in ISO 8601 UTC with three fractional digits,
    fixed at creation."

    Design: Corner/entities/track_creation_returns_201_with_defaults
    """
    resp = api.create_track(create_track_payload(name="DefaultTest"), OPS)
    data = validate_success(resp, 201)
    assert is_valid_uuid(data["id"]), "Track.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data["created_at"])
    assert data["version"] == 1, "newly created resource starts at version 1"
    assert data["name"] == "DefaultTest"


def test_track_missing_required_field_returns_invalid_request(api):
    """PRD §2.9: "Request shape — required body fields present, types valid,
    enum values valid, ids well-formed, on every mutating endpoint:
    `ERR_INVALID_REQUEST` (400)." PRD §3.1: "A `TrackOps` operator registers a
    track with its `name` and four operating parameters: `noise_limit_db`,
    the maximum permitted decibel level at the property line".

    Design: Corner/entities/track_missing_required_field_returns_invalid_request
    """
    payload = create_track_payload(name="X")
    del payload["noise_limit_db"]
    resp = api.create_track(payload, OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_coach_default_active_true(api):
    """PRD §3.1: "Coaches are registered against a home track with a
    `full_name`, a `cert_level` of `BASIC`, `INTERMEDIATE`, or `RACE`, and an
    optional `active` flag that defaults to true; only active coaches are
    assignable."

    Design: Corner/entities/coach_default_active_true
    """
    track = make_track(name="D1")
    resp = api.create_coach(
        track["id"], create_coach_payload(full_name="DefaultActive",
                                          cert_level="BASIC"), OPS)
    data = validate_success(resp, 201)
    assert data["active"] is True, "omitted active flag must default to true"


def test_coach_invalid_enum_cert_level_returns_invalid_request(api):
    """PRD §3.1: "Coaches are registered against a home track with a
    `full_name`, a `cert_level` of `BASIC`, `INTERMEDIATE`, or `RACE`".
    PRD §2.9: "Request shape — required body fields present, types valid,
    enum values valid, ids well-formed, on every mutating endpoint:
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/coach_invalid_enum_cert_level_returns_invalid_request
    """
    track = make_track(name="E1")
    resp = api.create_coach(
        track["id"], create_coach_payload(full_name="BadCert",
                                          cert_level="SUPER"), OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_track_get_not_found_returns_404(api):
    """PRD §2.5: "Path identifiers are validated strictly left to right: each
    identifier must exist and must belong to the parent established by the
    identifiers to its left, and any failure is `ERR_NOT_FOUND` (404), never
    a business-rule error."

    Design: Corner/entities/track_get_not_found_returns_404
    """
    resp = api.get_track(NON_EXISTENT_UUID, OPS)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_trackday_list_pagination_defaults(api):
    """PRD §2.3: "The `limit` defaults to 10, with a minimum of 1 and a
    maximum of 100; the `offset` defaults to 0. List responses carry `limit`,
    `offset`, `total_count`, and `has_more` in the `meta` object."

    Design: Corner/entities/trackday_list_pagination_defaults
    """
    track = make_track(name="L1")
    make_track_day(track["id"], "2026-09-12")
    make_track_day(track["id"], "2026-09-13")
    resp = api.list_track_days(track["id"], OPS)
    data, meta = validate_paginated(resp)
    assert meta["limit"] == 10, "default limit is 10"
    assert meta["offset"] == 0, "default offset is 0"
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(data) == 2


def test_response_envelope_shape_for_success(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`." and "The `response_type` is
    either "object" for a single resource or "array" for a list of resources."

    Design: Corner/endpoints/response_envelope_shape_for_success
    """
    track = make_track(name="E4")
    resp = api.get_track(track["id"], OPS)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    assert body["response_type"] == "object"
    assert body["data"]["id"] == track["id"]
    assert body["data"]["name"] == "E4"


def test_immediate_consistency_read_your_writes(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field." PRD §3.1: "A `TrackOps` operator registers a track with its `name`
    and four operating parameters: `noise_limit_db`, the maximum permitted
    decibel level at the property line".

    Design: Corner/consistency_model/immediate_consistency_read_your_writes
    """
    created = validate_success(api.create_track(
        create_track_payload(name="Y1", noise_limit_db=91), OPS), 201)
    assert created["name"] == "Y1"
    assert created["noise_limit_db"] == 91
    fetched = validate_success(api.get_track(created["id"], OPS))
    assert fetched["name"] == "Y1"
    assert fetched["noise_limit_db"] == 91
