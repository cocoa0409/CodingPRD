"""Response envelope, common-field defaults, and basic CRUD shape."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_buyer_commitment,
    assert_growing_room,
    assert_substrate_batch,
    assert_variety,
    create_room_payload,
    create_substrate_batch_payload,
    create_variety_payload,
    get_success_data,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

FARM = TEST_USERS["farm_manager_headers"]
COMPOST = TEST_USERS["compost_supervisor_headers"]
ANY = TEST_USERS["any_headers"]


def test_variety_create_applies_computed_defaults(api):
    """PRD §3.1: "A new variety starts with `active_committed_kg` and
    `planned_production_kg` both at 0.0; these are computed demand and supply
    signals maintained by the system."

    Design: Corner/entities/variety_create_applies_computed_defaults
    """
    resp = api.create_variety(create_variety_payload(), COMPOST)
    data = validate_success(resp, expected_status=201)
    assert_variety(data)
    assert data["version"] == 1, f"new variety version must be 1, got {data['version']}"
    assert data["active_committed_kg"] == 0.0
    assert data["planned_production_kg"] == 0.0
    assert is_valid_uuid(data["id"])
    assert data["created_at"], "server-minted created_at required"


def test_variety_create_rejects_unknown_recipe_enum(api):
    """PRD §3.1: "the `substrate_recipe` it requires (one of `PHASE_II_COMPOST`
    or `STRAW_SAWDUST`)"; PRD §2.8: "an enum value outside its declared
    constraints ... [is] rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/variety_create_invalid_enum_returns_400
    """
    payload = create_variety_payload(variety_code="XX1", substrate_recipe="GOLDEN_COMPOST")
    resp = api.create_variety(payload, COMPOST)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_variety_create_invalid_enum_persists_nothing(api):
    """PRD §2.8: "an enum value outside its declared constraints ... [is]
    rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    A rejected create must not leave a resource behind: a follow-up GET on a
    never-created variety id is a 404.

    Design: Corner/entities/variety_create_invalid_enum_returns_400
    """
    payload = create_variety_payload(variety_code="XX2", substrate_recipe="GOLDEN_COMPOST")
    resp = api.create_variety(payload, COMPOST)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    follow = api.get_variety(NON_EXISTENT_UUID, ANY)
    validate_error(follow, ApiErrorId.ERR_VARIETY_NOT_FOUND)


def test_batch_create_missing_required_tonnage_returns_400(api):
    """PRD §2.8: "Malformed requests — a missing required field ... — are
    rejected with `ERR_INVALID_REQUEST` (HTTP 400)." PRD §3.1 requires
    `tonnage` on batch creation.

    Design: Corner/entities/batch_create_missing_required_returns_400
    """
    resp = api.create_substrate_batch({"recipe": "PHASE_II_COMPOST"}, COMPOST)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_room_create_ignores_client_supplied_id_and_version(api):
    """PRD §2.4: "The `id` is a server-minted UUID with no type prefix. The
    `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with
    three fractional digits; `updated_at` is refreshed on every mutation. The
    `version` field is an integer that increments by 1 on every mutation of
    the resource."
    PRD §3.2: "A new room is `IDLE` and `CLEAR`."

    Design: Corner/entities/room_create_extra_id_field_input_ignored
    """
    supplied_id = "11111111-1111-1111-1111-111111111111"
    payload = create_room_payload(id=supplied_id, version=99)
    resp = api.create_room(payload, FARM)
    data = validate_success(resp, expected_status=201)
    assert_growing_room(data)
    assert data["id"] != supplied_id, "server must mint its own id"
    assert data["version"] == 1, f"client-supplied version must be ignored; got {data['version']}"
    assert data["occupancy_status"] == "IDLE"
    assert data["health_status"] == "CLEAR"


def test_flush_get_not_found_returns_flush_404(api):
    """PRD §2.8: "A missing resource surfaces from the family
    `ERR_VARIETY_NOT_FOUND`, ..., `ERR_FLUSH_NOT_FOUND`, ... (all HTTP 404)."

    Design: Corner/entities/flush_get_not_found_returns_404
    """
    resp = api.get_flush("22222222-2222-2222-2222-222222222222", ANY)
    validate_error(resp, ApiErrorId.ERR_FLUSH_NOT_FOUND)


def test_envelope_success_shape_on_room_create(api):
    """PRD §2.2: "All successful API responses (those with 2xx status codes)
    follow this standard envelope format in their JSON body" with
    `meta.api_request_id`, `meta.api_request_timestamp`, `response_type` of
    "object" for a single resource, and the resource in `data`.
    PRD §3.2: "A new room is `IDLE` and `CLEAR`."

    Design: Corner/endpoints/envelope_success_shape
    """
    resp = api.create_room(create_room_payload(), FARM)
    body = resp.json()
    assert resp.status_code == 201
    assert isinstance(body["meta"]["api_request_id"], str) and body["meta"]["api_request_id"]
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert body["response_type"] == "object"
    data = body["data"]
    assert data["room_code"] == "R1"
    assert data["occupancy_status"] == "IDLE"
    assert data["health_status"] == "CLEAR"
    assert data["version"] == 1


def test_envelope_error_shape_on_missing_room(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format" with `response_type` of "error" and `data`
    carrying `error_id` and `message`. PRD §2.8: a missing resource surfaces
    from the `ERR_..._NOT_FOUND` family (all HTTP 404).

    Design: Corner/endpoints/envelope_error_shape
    """
    resp = api.get_room("66666666-6666-6666-6666-666666666666", ANY)
    validate_error(resp, ApiErrorId.ERR_ROOM_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_ROOM_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()
    assert isinstance(body["meta"]["api_request_id"], str)


def test_rooms_list_pagination_defaults_and_filter(api):
    """PRD §2.3: "The `limit` defaults to 10, with a minimum of 1 and a
    maximum of 100; the `offset` defaults to 0. List responses are sorted by
    `created_at` ascending, and the `meta` block of a list response carries
    the pagination fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/rooms_list_pagination_defaults_and_filter
    """
    r1 = get_success_data(api.create_room(create_room_payload(room_code="R1"), FARM))
    r2 = get_success_data(api.create_room(create_room_payload(room_code="R2", capacity_tonnes=60.0), FARM))

    page1, meta1 = validate_paginated(api.list_rooms(ANY, params={"limit": 1}))
    assert len(page1) == 1
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True
    assert meta1["limit"] == 1 and meta1["offset"] == 0

    page2, meta2 = validate_paginated(api.list_rooms(ANY, params={"limit": 1, "offset": 1}))
    assert len(page2) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False
    assert meta2["offset"] == 1
    assert page1[0]["id"] != page2[0]["id"], "pages must not repeat a room"
    assert {page1[0]["id"], page2[0]["id"]} == {r1["id"], r2["id"]}

    default_page, default_meta = validate_paginated(api.list_rooms(ANY))
    assert default_meta["limit"] == 10
    assert default_meta["offset"] == 0
    assert default_meta["total_count"] == 2
    assert default_meta["has_more"] is False
    assert len(default_page) == 2


def test_immediate_read_after_write_consistency(api):
    """PRD §2.4: "Consistency is immediate: whenever an operation cascades
    into derived fields or related entities ... all of those effects are
    reconciled inside the same request, and the response reflects the fully
    reconciled state." PRD §3.1: "A batch is born in `MIXED` status with its
    `remaining_tonnage` initialized to its full `tonnage`, and with
    `variety_id` and `spawn_kg` both null until spawning."

    Design: Corner/consistency_model/immediate_read_after_write_consistency
    """
    created = get_success_data(api.create_substrate_batch(
        create_substrate_batch_payload(tonnage=40.0), COMPOST,
    ))
    read = get_success_data(api.get_substrate_batch(created["id"], ANY))
    assert_substrate_batch(read)
    assert read["status"] == "MIXED"
    assert read["remaining_tonnage"] == 40.0
    assert read["spent_revenue_cents"] == 0
    assert read["disposal_cost_cents"] == 0
    assert read["version"] == 1
    assert read["updated_at"] == read["created_at"], (
        "for a freshly created entity updated_at must equal created_at"
    )
