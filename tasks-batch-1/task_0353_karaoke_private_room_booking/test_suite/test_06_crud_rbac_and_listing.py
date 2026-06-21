"""Creation/defaults/required-fields/not-found/immutability, song & reservation
listing with filters and pagination, RBAC forbidden/unauthenticated, and the
not-queue-head playback guard.

Covers the corner entities / endpoints / rbac / errors sections.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    is_valid_uuid, NON_EXISTENT_UUID,
    setup_base, create_song, create_checked_in_reservation, create_song as _mk_song,
    queue_song, create_held_reservation, get_room_version,
    create_venue_payload, create_room_type_payload, create_reservation_payload,
    create_customer, create_venue, create_room_type, create_room, set_clock,
    make_customer_headers, make_front_desk_headers, make_venue_manager_headers,
)

FD = make_front_desk_headers()
VM = make_venue_manager_headers()


def _cust(c):
    return make_customer_headers(c["id"])


# ─── Creation / defaults / required / not-found / immutability ─────
def test_create_venue_returns_201_with_system_fields(api):
    """PRD §3.1: "A new venue is born at `version` 1."
    PRD §3.1: "the `peak_multiplier` defaults to 1.5".

    POST /venues returns 201 with a UUID id, version 1, and peak_multiplier default 1.5.

    Design: Corner/entities/create_venue_returns_201_with_system_fields
    """
    payload = {"name": "Fresh", "timezone": "UTC", "peak_start_minute": 1080,
               "peak_end_minute": 1380}
    data = validate_success(api.create_venue(payload, VM), 201)
    assert is_valid_uuid(data["id"])
    assert data["version"] == 1
    assert float(data["peak_multiplier"]) == 1.5


def test_create_room_type_defaults_applied(api):
    """PRD §3.1: "an optional `fb_minimum_cents`, the required food-and-beverage spend
    floor for any reservation on this size, which defaults to 0 and must be zero or
    greater; and an optional `active` flag, defaulting to true".

    Omitting fb_minimum_cents and active -> fb_minimum_cents 0, active true.

    Design: Corner/entities/create_room_type_defaults_applied
    """
    v = create_venue()
    payload = {"venue_id": v["id"], "name": "MEDIUM", "capacity": 6,
               "base_hourly_rate_cents": 5000}
    data = validate_success(api.create_room_type(payload, VM), 201)
    assert data["fb_minimum_cents"] == 0
    assert data["active"] is True


def test_reservation_missing_required_field_rejected(api):
    """PRD §2.8: "required fields must be present ... failing which the request is
    rejected with `ERR_INVALID_REQUEST`."
    PRD §3.3: "the half-open interval boundaries `slot_start_utc` and `slot_end_utc`".

    Omitting slot_start_utc on create -> ERR_INVALID_REQUEST.

    Design: Corner/entities/reservation_missing_required_field_rejected
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000},
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    room_v = get_room_version(room["id"])
    payload = {
        "venue_id": venue["id"], "room_id": room["id"], "customer_id": customer["id"],
        "party_size": 4, "slot_end_utc": "2026-08-01T22:00:00.000Z",
        "expected_room_version": room_v,
    }
    validate_error(api.create_reservation(payload, _cust(customer)),
                   ApiErrorId.ERR_INVALID_REQUEST.value)


def test_reservation_end_before_start_rejected(api):
    """PRD §2.8: "required fields must be present, enums must be valid, `slot_end_utc`
    must be strictly after `slot_start_utc`, and numeric fields must lie within their
    declared ranges, failing which the request is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/reservation_invalid_interval_end_before_start_rejected
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000},
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    room_v = get_room_version(room["id"])
    payload = create_reservation_payload(
        venue["id"], room["id"], customer["id"], room_v,
        "2026-08-01T22:00:00.000Z", "2026-08-01T21:00:00.000Z", party_size=4,
    )
    validate_error(api.create_reservation(payload, _cust(customer)),
                   ApiErrorId.ERR_INVALID_REQUEST.value)


def test_song_immutable_no_version_field(api):
    """PRD §2.4: "A `Song` and a `Payment` are immutable once written: each carries only
    an `id` and a `created_at`, and neither has an `updated_at` field nor a `version`
    field."

    Design: Corner/entities/song_immutable_no_version_field
    """
    v = create_venue()
    payload = {"venue_id": v["id"], "title": "T", "artist": "A",
               "duration_seconds": 200, "language": "EN"}
    data = validate_success(api.create_song(payload, FD), 201)
    assert is_valid_uuid(data["id"])
    assert "version" not in data
    assert "updated_at" not in data


def test_get_reservation_nonexistent_not_found(api):
    """PRD §2.5: "The first identifier in that chain that does not resolve to an existing
    in-scope resource causes the request to be rejected with `ERR_NOT_FOUND` before any
    later validation runs."

    Design: Corner/entities/get_reservation_nonexistent_returns_not_found
    """
    create_venue()
    validate_error(api.get_reservation(NON_EXISTENT_UUID, FD),
                   ApiErrorId.ERR_NOT_FOUND.value)


# ─── Listing / pagination ─────────────────────────────────────────
def test_list_songs_filter_by_language_paginated(api):
    """PRD §3.3 endpoint table: "List/search the song catalog, filter by venue and/or
    language".
    PRD §2.3: "Every list response includes the following fields inside the `meta`
    object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Two EN songs + one JP song; filtering language=JP returns only the JP song.

    Design: Corner/endpoints/list_songs_filter_by_language_paginated
    """
    v = create_venue()
    create_song(v["id"], title="E1", artist="A", language="EN")
    create_song(v["id"], title="E2", artist="B", language="EN")
    create_song(v["id"], title="J1", artist="C", language="JP")
    data, meta = validate_paginated(
        api.list_songs(_cust({"id": "test-customer-1"}),
                       params={"venue_id": v["id"], "language": "JP", "limit": 10, "offset": 0})
    )
    assert len(data) == 1
    assert data[0]["language"] == "JP"
    assert "total_count" in meta and "has_more" in meta


def test_list_reservations_filtered_by_room(api):
    """PRD §4 endpoint table: "List reservations, filtered by venue, room, customer,
    package, room type, or status".

    One HELD reservation on the room; GET /reservations?room_id= returns it.

    Design: Corner/endpoints/list_reservations_filtered_by_room_returns_array
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000},
        clock_utc="2026-08-16T10:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_held_reservation(venue, room, customer,
                                  "2026-08-16T20:00:00.000Z", "2026-08-16T22:00:00.000Z",
                                  party_size=4)
    data, _meta = validate_paginated(
        api.list_reservations(FD, params={"room_id": room["id"]})
    )
    assert len(data) == 1
    assert data[0]["id"] == res["id"]


# ─── RBAC / auth ──────────────────────────────────────────────────
def test_customer_cannot_create_venue_forbidden(api):
    """PRD §2.1: "creating venues, room types, rooms, and group packages, and toggling
    room maintenance are operations only a `VenueManager` may perform."
    PRD §2.1: "When the headers are well-formed but the acting role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/customer_cannot_create_venue_forbidden
    """
    payload = {"name": "Sneaky", "timezone": "UTC", "peak_start_minute": 1080,
               "peak_end_minute": 1380}
    validate_error(api.create_venue(payload, make_customer_headers("00000000-0000-4000-8000-000000000abc")),
                   ApiErrorId.ERR_FORBIDDEN.value)


def test_customer_cannot_checkin_forbidden(api):
    """PRD §2.1: "checking parties in, closing and settling sessions, playing and
    skipping queued songs, and voiding food-and-beverage lines are operations only a
    `FrontDesk` operator may perform."

    A Customer calling check-in on their own CONFIRMED reservation -> ERR_FORBIDDEN.

    Design: Corner/rbac/customer_cannot_checkin_reservation_forbidden
    """
    base = setup_base(
        venue_overrides={"grace_minutes": 15},
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000},
        clock_utc="2026-08-17T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    from test_helpers import create_confirmed_reservation
    res = create_confirmed_reservation(venue, room, customer,
                                       "2026-08-17T20:00:00.000Z", "2026-08-17T22:00:00.000Z",
                                       confirm_clock_utc=None, party_size=4)
    set_clock(venue["id"], "2026-08-17T20:00:00.000Z")
    validate_error(api.check_in_reservation(res["id"], _cust(customer)),
                   ApiErrorId.ERR_FORBIDDEN.value)


def test_customer_cannot_cancel_other_customers_reservation(api):
    """PRD §2.1: "A `Customer` may act only on reservations whose `customer_id` equals
    their own `X-User-ID` ... An attempt by a `Customer` to operate on a reservation
    they do not own is rejected with `ERR_FORBIDDEN`."

    Customer B cancelling Customer A's HELD reservation -> ERR_FORBIDDEN.

    Design: Corner/rbac/customer_cannot_cancel_other_customers_reservation_forbidden
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000},
        clock_utc="2026-08-18T10:00:00.000Z",
    )
    venue, room, cust_a = base["venue"], base["room"], base["customer"]
    cust_b = create_customer()
    res = create_held_reservation(venue, room, cust_a,
                                  "2026-08-18T20:00:00.000Z", "2026-08-18T22:00:00.000Z",
                                  party_size=4)
    validate_error(api.cancel_reservation(res["id"], _cust(cust_b)),
                   ApiErrorId.ERR_FORBIDDEN.value)


def test_missing_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` carries a value that
    is not one of these three known roles, the request is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    v = create_venue()
    validate_error(api.get_venue(v["id"], {}), ApiErrorId.ERR_UNAUTHENTICATED.value)


# ─── Queue head guard ─────────────────────────────────────────────
def test_not_queue_head_play_rejected(api):
    """PRD §3.6: "Playing an entry that is not the head is rejected with
    `ERR_NOT_QUEUE_HEAD`".

    Two PENDING entries (priority 10 head, 20 second). Playing the second ->
    ERR_NOT_QUEUE_HEAD.

    Design: Corner/errors/not_queue_head_play_rejected
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000},
        clock_utc="2026-08-21T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    s1 = create_song(venue["id"], title="S1", artist="A")
    s2 = create_song(venue["id"], title="S2", artist="B")
    res = create_checked_in_reservation(venue, room, customer,
                                        "2026-08-21T20:00:00.000Z", "2026-08-21T22:00:00.000Z",
                                        checkin_clock_utc="2026-08-21T20:00:00.000Z")
    queue_song(res, customer, s1["id"], priority=10)
    q2 = queue_song(res, customer, s2["id"], priority=20)
    validate_error(api.play_queue_entry(q2["id"], FD),
                   ApiErrorId.ERR_NOT_QUEUE_HEAD.value)
