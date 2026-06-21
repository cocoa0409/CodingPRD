"""Resource creation defaults, computed fields, seat-map materialization,
not-found handling, listing/pagination, and FK-filtered reads.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    get_success_data,
    make_distributor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    create_auditorium_payload,
    create_distributor_payload,
    create_film_payload,
)

MANAGER = TEST_USERS["manager_headers"]
AGENT = TEST_USERS["agent_headers"]


# ===========================================================================
# Corner/entities/*
# ===========================================================================

def test_create_auditorium_returns_201_with_defaults(api):
    """PRD §3.1: "An auditorium is created with a display name and a seat_count
    that must be at least 1; the count defines the size of the seat map that every
    screening in the room will materialize. An auditorium also accepts an optional
    turnaround_minutes buffer, which must be zero or greater and defaults to 20
    minutes when omitted."

    Design: Corner/entities/create_auditorium_returns_201_with_fields
    """
    resp = api.create_auditorium({"name": "Hall 1", "seat_count": 4}, MANAGER)
    data = validate_success(resp, 201)
    assert data["name"] == "Hall 1"
    assert data["seat_count"] == 4
    assert data["status"] == "ACTIVE"
    assert data["turnaround_minutes"] == 20  # default
    assert data["version"] == 1  # PRD §2.4: version starts at 1


def test_get_auditorium_not_found(api):
    """PRD §2.7: "the system validates the path identifiers from left to right and
    rejects the request with ERR_NOT_FOUND (HTTP 404) at the first identifier that
    does not correspond to an existing resource."

    Design: Corner/entities/get_auditorium_not_found
    """
    resp = api.get_auditorium(NON_EXISTENT_UUID, MANAGER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_film_missing_required_field_rejected(api):
    """PRD §2.8: "A request that omits a required field, supplies a value of the
    wrong type, or uses an out-of-set enum value is rejected with ERR_INVALID_REQUEST."

    Design: Corner/entities/create_film_missing_required_field_rejected
    """
    distributor = fx.make_distributor()
    payload = {
        "title": "F",
        "distributor_id": distributor["id"],
        "release_date": "2026-06-01T00:00:00.000Z",
        "split_schedule": [{"week_index": 0, "distributor_pct": 0.70}],
    }  # runtime_minutes omitted
    resp = api.create_film(payload, MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_distributor_default_minimum_guarantee_zero(api):
    """PRD §3.1: "It is created with a name and an optional minimum_guarantee_cents
    floor ... which must be zero or greater and defaults to 0."

    Design: Corner/entities/distributor_default_minimum_guarantee_zero
    """
    resp = api.create_distributor({"name": "Acme Films"}, MANAGER)
    data = validate_success(resp, 201)
    assert data["minimum_guarantee_cents"] == 0


def test_showtime_ends_at_computed_from_runtime_and_pad(api):
    """PRD §3.2: "The system computes the screening's ends_at as the start instant
    plus the film's runtime_minutes plus a fixed trailer-and-cleaning pad of 15
    minutes; this end instant defines the half-open occupancy interval used for
    overlap math."

    Design: Corner/entities/showtime_computed_ends_at_from_runtime_and_pad
    """
    base = fx.setup_base(seat_count=4, runtime_minutes=90)
    showtime = fx.schedule_showtime(
        base["auditorium"]["id"], base["film"]["id"], starts_at="2026-06-10T20:00:00.000Z"
    )
    # 20:00 + 90 + 15 = 21:45.
    assert showtime["ends_at"] == "2026-06-10T21:45:00.000Z"


def test_showtime_creation_materializes_seat_map(api):
    """PRD §3.2: "As the showtime is created, the system materializes the seat map:
    it creates one Seat row per physical seat, exactly as many as the auditorium's
    seat count."
    PRD §3.2: "Every freshly created seat begins with an occupancy of FREE."

    Design: Corner/entities/showtime_creation_materializes_seat_map
    """
    base = fx.setup_base(seat_count=4)
    showtime = fx.schedule_showtime(base["auditorium"]["id"], base["film"]["id"])
    resp = api.get_showtime_seats(showtime["id"], MANAGER, params={"limit": 100})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 4
    assert all(s["occupancy"] == "FREE" for s in data)


def test_list_combos_pagination_envelope(api):
    """PRD §2.3: "Paginated and non-paginated list-based responses include the
    following fields in the meta object of the response envelope: limit, offset,
    total_count, and has_more."

    Design: Corner/entities/list_combos_pagination_envelope
    """
    fx.make_combo(name="C1", price_cents=1000)
    fx.make_combo(name="C2", price_cents=1200)
    resp = api.list_combos(AGENT)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


# ===========================================================================
# Corner/endpoints/* — FK-filtered reads
# ===========================================================================

def test_list_orders_filtered_by_member(api):
    """PRD §3.10: "List endpoints accept the usual limit and offset pagination
    parameters and a variety of filters that narrow results without exposing other
    principals' data"

    Design: Corner/endpoints/list_orders_filtered_by_member
    """
    ctx = fx.setup_on_sale_showtime(base_price_cents=1000)
    member = fx.make_member()
    fx.create_held_order(ctx["showtime"], member, ctx["seat_ids"][:1])

    resp = api.list_orders(AGENT, params={"member_id": member["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert all(o["member_id"] == member["id"] for o in data)


def test_list_tickets_filtered_by_showtime(api):
    """PRD §3.10: "a variety of filters that narrow results without exposing other
    principals' data ... tickets and settlements by showtime_id"

    Design: Corner/endpoints/list_tickets_filtered_by_showtime
    """
    ctx = fx.setup_on_sale_showtime(base_price_cents=1000)
    member = fx.make_member()
    fx.create_held_order(ctx["showtime"], member, ctx["seat_ids"][:1])

    resp = api.list_tickets(MANAGER, params={"showtime_id": ctx["showtime"]["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert all(t["showtime_id"] == ctx["showtime"]["id"] for t in data)


def test_list_settlements_filtered_by_distributor(api):
    """PRD §3.10: "a variety of filters that narrow results without exposing other
    principals' data ... films, showtimes, and settlements by distributor_id"

    Design: Corner/endpoints/list_settlements_filtered_by_distributor
    """
    ctx = fx.setup_closed_box_office_showtime(
        base_price_cents=1000, num_seats=1,
        starts_at="2026-06-05T13:00:00.000Z", close_at="2026-06-05T15:00:00.000Z",
    )
    dist_id = ctx["distributor"]["id"]
    resp = api.list_settlements(make_distributor_headers(dist_id), params={"distributor_id": dist_id})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert data[0]["distributor_id"] == dist_id
    assert data[0]["film_id"] == ctx["film"]["id"]
