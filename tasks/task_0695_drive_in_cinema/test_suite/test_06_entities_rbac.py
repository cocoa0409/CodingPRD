"""Entity CRUD, defaults, system/type/parent constraints, immutability, and RBAC tests.

Covers Corner queue (entities, rbac sections).
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    make_patron_headers,
    anonymous_headers,
    TEST_USERS,
    setup_venue_lot_film,
    create_venue,
    create_lot,
    create_film,
    create_season_pass,
    create_showtime,
    make_reservation,
    set_clock,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPERATOR = TEST_USERS["venue_operator_headers"]
GATE = TEST_USERS["gate_attendant_headers"]
PATRON = TEST_USERS["patron_headers"]


# =====================================================================
# Corner: entities / create_venue_returns_201_with_fields
# =====================================================================
def test_create_venue_returns_201_with_fields(api):
    """PRD §3.1: "A drive-in begins with a venue, created by a `PlatformAdmin`. A venue is
    given a display `name` and an optional `timezone` ... The venue also defines the shared
    radio airspace through its `fm_channel_pool`: an ordered, non-empty array of distinct FM
    frequency strings."
    PRD §2.4: "The `version` field is an integer that begins at its initial value and
    increments by one on every mutation of the resource."

    Design: Corner/entities/create_venue_returns_201_with_fields
    """
    res = api.create_venue(
        {"name": "Twilight Drive-In", "fm_channel_pool": ["87.9", "88.1"],
         "turnaround_buffer_minutes": 20, "no_show_grace_minutes": 10},
        ADMIN,
    )
    data = validate_success(res, expected_status=201)
    assert data["name"] == "Twilight Drive-In"
    assert data["version"] == 1
    assert data["turnaround_buffer_minutes"] == 20


# =====================================================================
# Corner: entities / get_showtime_returns_stored_entity
# =====================================================================
def test_get_showtime_returns_computed_end_utc(api):
    """PRD §3.2: "`end_utc` equals `start_utc` plus the primary film's runtime, plus the
    secondary film's runtime when (and only when) `is_double_feature` is true; for a single
    feature only the primary runtime is added."
    PRD §3.2: "A showtime also exposes the two derived occupancy counters introduced in §2.5,
    `reserved_stall_count` and `reserved_person_count`, both starting at 0."

    Design: Corner/entities/get_showtime_returns_stored_entity
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z", runtime_minutes=100)
    st = create_showtime(venue["id"], lot["id"], film["id"], "2026-07-20T02:00:00Z")
    fetched = validate_success(api.get_showtime(st["id"], make_patron_headers("p-any")))
    # start 02:00 + 100m = 03:40
    assert fetched["end_utc"].startswith("2026-07-20T03:40:00")
    assert fetched["reserved_stall_count"] == 0


# =====================================================================
# Corner: entities / list_lots_filtered_by_venue_paginated
# =====================================================================
def test_list_lots_filtered_by_venue_paginated(api):
    """PRD §2.3: "The pagination bookkeeping fields surfaced in the `meta` object are
    `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_lots_filtered_by_venue_paginated
    """
    venue = create_venue(name="VC2")
    create_lot(venue["id"], name="LA", stall_count=5, person_capacity=50)
    create_lot(venue["id"], name="LB", stall_count=5, person_capacity=50)
    data, meta = validate_paginated(
        api.list_lots(OPERATOR, params={"venue_id": venue["id"], "limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert all(lot["venue_id"] == venue["id"] for lot in data)


# =====================================================================
# Corner: entities / create_lot_missing_stall_count_rejected
# =====================================================================
def test_create_lot_missing_stall_count_rejected(api):
    """PRD §3.1: "It records the `venue_id` it belongs to, a `name` such as "North Field", a
    `stall_count` (the total number of car stalls, at least 1, which is the upper bound on
    per-car reservations for any one showtime), and a `person_capacity`."

    Design: Corner/entities/create_lot_missing_stall_count_rejected
    """
    venue = create_venue(name="VC3")
    res = api.create_lot(
        {"venue_id": venue["id"], "name": "L", "person_capacity": 50}, OPERATOR
    )
    validate_error(res, "ERR_INVALID_REQUEST")


# =====================================================================
# Corner: entities / venue_timezone_default_applied
# =====================================================================
def test_venue_defaults_applied(api):
    """PRD §3.1: "A venue is given a display `name` and an optional `timezone` (an IANA
    timezone string in which all showtime windows are interpreted, defaulting to `UTC`)."
    PRD §3.1: "`turnaround_buffer_minutes`, the required cleanup gap between consecutive
    showtimes on the same lot, which must be zero or greater and defaults to 30; and
    `no_show_grace_minutes` ... which must be zero or greater and defaults to 15."

    Design: Corner/entities/venue_timezone_default_applied
    """
    res = api.create_venue({"name": "VC4", "fm_channel_pool": ["89.7"]}, ADMIN)
    data = validate_success(res, expected_status=201)
    assert data["timezone"] == "UTC"
    assert data["turnaround_buffer_minutes"] == 30
    assert data["no_show_grace_minutes"] == 15


# =====================================================================
# Corner: entities / reservation_id_system_minted
# =====================================================================
def test_reservation_system_minted_fields(api):
    """PRD §3.4: "a `gate_code` scan token is minted by the server (distinct from the `id`,
    and presented later at the gate). The reservation's `amount_paid_cents` starts at 0. ...
    its `occupancy_status` ... beginning at `CONFIRMED`; and its `payment_status` ...
    beginning at `UNPAID`."

    Design: Corner/entities/reservation_id_system_minted
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z")
    st = create_showtime(venue["id"], lot["id"], film["id"], "2026-07-21T02:00:00Z")
    resv = make_reservation(st, "patron-sys", occupant_count=2)
    assert resv["version"] == 1
    assert isinstance(resv["gate_code"], str) and len(resv["gate_code"]) > 0
    assert resv["gate_code"] != resv["id"]
    assert resv["occupancy_status"] == "CONFIRMED"
    assert resv["payment_status"] == "UNPAID"


# =====================================================================
# Corner: entities / showtime_invalid_rating_enum_rejected
# =====================================================================
def test_film_invalid_rating_enum_rejected(api):
    """PRD §3.1: "a `rating` that is one of `G`, `PG`, `PG13`, or `R`."

    Design: Corner/entities/showtime_invalid_rating_enum_rejected
    """
    res = api.create_film({"title": "Bad", "runtime_minutes": 90, "rating": "XYZ"}, OPERATOR)
    validate_error(res, "ERR_INVALID_REQUEST")


# =====================================================================
# Corner: entities / showtime_references_existing_lot_and_films
# =====================================================================
def test_showtime_nonexistent_lot_not_found(api):
    """PRD §2.7: "Next, existence of every resource named in the path or body is checked,
    left to right, with the first missing one yielding `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/showtime_references_existing_lot_and_films
    """
    venue = create_venue(name="VC6")
    film = create_film()
    res = api.create_showtime(
        {"venue_id": venue["id"], "lot_id": "11111111-1111-4111-8111-111111111111",
         "primary_film_id": film["id"], "is_double_feature": False,
         "start_utc": "2026-07-22T02:00:00Z", "pricing_mode": "PER_CAR",
         "base_price_cents": 2000},
        OPERATOR,
    )
    validate_error(res, "ERR_NOT_FOUND")


# =====================================================================
# Corner: entities / film_immutable_no_version_field
# =====================================================================
def test_film_has_no_version_field(api):
    """PRD §2.4: "A `Film` and a `WeatherEvent` carry only `id` and `created_at`; they have
    neither an `updated_at` field nor a `version` field, because once created they are never
    mutated."

    Design: Corner/entities/film_immutable_no_version_field
    """
    film = create_film(title="Immutable", runtime_minutes=95, rating="PG")
    fetched = validate_success(api.get_film(film["id"], make_patron_headers("p-any")))
    assert "version" not in fetched, "Film must not expose a version field"
    assert "updated_at" not in fetched, "Film must not expose an updated_at field"


# =====================================================================
# Corner: rbac / patron_cannot_schedule_showtime
# =====================================================================
def test_patron_cannot_schedule_showtime(api):
    """PRD §2.1: "When a request is well-authenticated but the acting role is not permitted to
    invoke the requested operation per the endpoint authorization table in §4, the request is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/patron_cannot_schedule_showtime
    """
    venue, lot, film = setup_venue_lot_film(clock=None)
    res = api.create_showtime(
        {"venue_id": venue["id"], "lot_id": lot["id"], "primary_film_id": film["id"],
         "is_double_feature": False, "start_utc": "2026-08-18T02:00:00Z",
         "pricing_mode": "PER_CAR", "base_price_cents": 2000},
        make_patron_headers("patron-z"),
    )
    validate_error(res, "ERR_UNAUTHORIZED")


# =====================================================================
# Corner: rbac / patron_cannot_cancel_others_reservation
# =====================================================================
def test_patron_cannot_cancel_others_reservation(api):
    """PRD §2.1: "When a `Patron` attempts to mutate a reservation, a concession order, or a
    season pass whose owning `patron_id` does not equal the caller's `X-User-ID`, the request
    is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/patron_cannot_cancel_others_reservation
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z")
    st = create_showtime(venue["id"], lot["id"], film["id"], "2026-08-19T02:00:00Z")
    resv = make_reservation(st, "patron-owner", occupant_count=2)
    res = api.cancel_reservation(resv["id"], resv["version"], make_patron_headers("patron-intruder"))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


# =====================================================================
# Corner: rbac / missing_auth_headers_rejected
# =====================================================================
def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "Every request must carry two authentication headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, declaring the capacity in which they act.
    If either header is missing, or if `X-User-Role` is not one of the recognized roles, the
    request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_rejected
    """
    venue = create_venue(name="VC34")
    res = api.get_venue(venue["id"], anonymous_headers())
    validate_error(res, "ERR_UNAUTHENTICATED")


# =====================================================================
# Corner: rbac / gate_attendant_cannot_revoke_pass
# =====================================================================
def test_gate_attendant_cannot_revoke_pass(api):
    """PRD §2.1: "When a request is well-authenticated but the acting role is not permitted to
    invoke the requested operation per the endpoint authorization table in §4, the request is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/gate_attendant_cannot_revoke_pass
    """
    create_venue(name="VC35")
    sp = create_season_pass("patron-r", "2026-08-01T00:00:00Z", "2026-08-31T23:59:59Z",
                            tier="GOLD", max_redemptions=5)
    res = api.revoke_season_pass(sp["id"], GATE)
    validate_error(res, "ERR_UNAUTHORIZED")
