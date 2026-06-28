"""Entity creation, defaults, required-field, type-constraint, not-found, listing,
computed-field, and system-field tests.

Corner queue: entities.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    assert_artist,
    create_artist_payload,
    create_event,
    add_face,
    make_client_headers,
    make_coordinator_headers,
    NON_EXISTENT_UUID,
)

COORD = make_coordinator_headers()


def test_create_artist_returns_201_with_defaults(api):
    """PRD §3.1: "A newly registered artist begins life with `status` `ACTIVE`."
    PRD §3.1: "An optional `can_assist` flag declares whether the artist may be booked as an
    assistant on another artist's window; when omitted it defaults to `false`."
    PRD §3.1: "A read-only `portfolio_published` flag, initially `false`, becomes `true` once
    at least one of the artist's portfolio items has been published."
    PRD §2.4: "The `version` field is an integer that starts at its initial value and
    increments by one on every mutation of the resource".

    Design: Corner/entities/create_artist_returns_201_with_defaults
    """
    payload = create_artist_payload(
        display_name="A", skill_tier="SENIOR", hair_rate_per_face_cents=10000,
        makeup_rate_per_face_cents=12000, travel_rate_per_km_cents=500, max_faces_per_hour=3,
    )
    data = validate_success(api.create_artist(payload, COORD), 201)
    assert_artist(data)
    assert data["status"] == "ACTIVE"
    assert data["can_assist"] is False
    assert data["portfolio_published"] is False
    assert data["version"] == 1, f"Expected version 1, got {data['version']}"


def test_create_artist_missing_skill_tier_rejected(api):
    """PRD §3.1: "A `Coordinator` registers an artist by supplying a `display_name`, a
    `skill_tier` (one of `LEAD`, `SENIOR`, or `JUNIOR`), and the artist's economic profile".
    PRD §2.9: "Malformed request bodies — a missing required field, a value outside a declared
    enum, or an integer below its declared minimum — surface as `ERR_INVALID_REQUEST` (HTTP
    400)."

    Design: Corner/entities/create_artist_missing_skill_tier_returns_invalid_request
    """
    payload = {
        "display_name": "A", "hair_rate_per_face_cents": 10000,
        "makeup_rate_per_face_cents": 12000, "travel_rate_per_km_cents": 500, "max_faces_per_hour": 3,
    }
    validate_error(api.create_artist(payload, COORD), ApiErrorId.ERR_INVALID_REQUEST)


def test_create_artist_bad_skill_tier_enum_rejected(api):
    """PRD §2.9: "Malformed request bodies — a missing required field, a value outside a
    declared enum, or an integer below its declared minimum — surface as `ERR_INVALID_REQUEST`
    (HTTP 400)."
    PRD §3.1: "a `skill_tier` (one of `LEAD`, `SENIOR`, or `JUNIOR`)".

    Design: Corner/entities/create_artist_bad_skill_tier_enum_returns_invalid_request
    """
    payload = create_artist_payload(skill_tier="PRINCIPAL", display_name="A")
    validate_error(api.create_artist(payload, COORD), ApiErrorId.ERR_INVALID_REQUEST)


def test_get_artist_nonexistent_returns_not_found(api):
    """PRD §2.5: "For any request that references resources by path or body identifier, the
    system validates existence left-to-right in the order the identifiers appear, rejecting
    with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing
    resource."

    Design: Corner/entities/get_artist_nonexistent_returns_not_found
    """
    validate_error(api.get_artist(NON_EXISTENT_UUID, COORD), ApiErrorId.ERR_NOT_FOUND)


def test_list_artists_paginated_envelope(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_artists_paginated_envelope
    """
    validate_success(api.create_artist(create_artist_payload(skill_tier="LEAD"), COORD), 201)
    resp = api.list_artists(COORD, params={"limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"Expected total_count 1, got {meta['total_count']}"
    assert meta["has_more"] is False


def test_event_party_size_recomputed_on_face_removal(api):
    """PRD §3.2: "Removing a face transitions it to `REMOVED` and again recomputes
    `party_size`. Throughout, `party_size` is the count of faces on the event in `PENDING` or
    `CONFIRMED` status — removed and serviced faces do not count toward it."

    Design: Corner/entities/event_party_size_computed_from_faces
    """
    event = create_event(client_id="client-7", venue_distance_km=5)
    add_face(event["id"], "client-7", "BRIDE", "BOTH", is_bride=True)
    f2 = add_face(event["id"], "client-7", "BM1", "HAIR")
    # Two PENDING faces -> party_size 2; remove one -> party_size 1.
    validate_success(api.remove_face(f2["id"], make_client_headers("client-7")), 200)
    event_after = validate_success(api.get_event(event["id"], COORD), 200)
    assert event_after["party_size"] == 1, (
        f"Expected party_size 1 after removal, got {event_after['party_size']}"
    )


def test_artist_status_forced_active_ignoring_input(api):
    """PRD §3.1: "A newly registered artist begins life with `status` `ACTIVE`."

    Design: Corner/entities/artist_system_fields_ignored_on_input
    """
    payload = create_artist_payload(
        display_name="A", skill_tier="JUNIOR", hair_rate_per_face_cents=5000,
        makeup_rate_per_face_cents=6000, travel_rate_per_km_cents=200, max_faces_per_hour=5,
    )
    data = validate_success(api.create_artist(payload, COORD), 201)
    assert data["status"] == "ACTIVE"
