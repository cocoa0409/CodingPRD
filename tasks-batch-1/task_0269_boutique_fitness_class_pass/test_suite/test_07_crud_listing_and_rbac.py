"""Entity creation defaults, not-found and validation negatives, computed fields,
list pagination, FK-reverse listing, and role-based access control. Translates the
corner entities / endpoints / rbac instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    setup_network, setup_member_with_membership, create_studio, create_room,
    create_instructor, create_published_session, reserve, get_session,
    set_clock, api_client, make_member_headers, build_user_headers, TEST_USERS,
)

ADMIN = TEST_USERS["network_admin_headers"]
MANAGER = TEST_USERS["studio_manager_headers"]


def test_create_studio_returns_201_with_defaults(api):
    """PRD §3.1: "A new studio opens in `OPEN` `status` with an `active_room_count` of
    zero."
    PRD §3.1: "optionally an IANA `timezone` such as `America/Los_Angeles`; when the
    timezone is omitted it defaults to `UTC`."

    Design: Corner/entities/create_studio_returns_201_with_defaults
    """
    res = api.create_studio({"name": "Downtown", "state_code": "CA"}, ADMIN)
    studio = validate_success(res, 201)
    assert studio["status"] == "OPEN"
    assert studio["active_room_count"] == 0
    assert studio["version"] == 1
    assert studio["timezone"] == "UTC"


def test_get_member_not_found_returns_404(api):
    """PRD §2.7: "rejects the request with `ERR_NOT_FOUND` the moment it reaches an
    identifier that resolves to nothing."

    Design: Corner/entities/get_member_not_found_returns_404
    """
    res = api.get_member("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_session_missing_seat_capacity_returns_422(api):
    """PRD §2.9: "then request well-formedness — required fields present, correct types,
    enum values within their declared sets, and numeric fields within their declared
    ranges (`ERR_INVALID_REQUEST`)."
    PRD §3.5: "a `seat_capacity` integer of at least 1".

    Design: Corner/entities/create_session_missing_required_field_returns_422
    """
    net = setup_network()
    res = api.create_session({
        "studio_id": net["studio"]["id"], "room_id": net["room"]["id"],
        "instructor_id": net["instructor"]["id"], "template_id": net["template"]["id"],
        "starts_at": "2026-06-20T10:00:00Z",  # seat_capacity omitted
    }, MANAGER)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_plan_invalid_enum_kind_returns_422(api):
    """PRD §3.2: "a `kind` that is one of `INTRO`, `CREDIT_PACK`, or `MEMBERSHIP`".
    PRD §2.9: "then request well-formedness — required fields present, correct types,
    enum values within their declared sets, and numeric fields within their declared
    ranges (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/create_plan_invalid_enum_kind_returns_422
    """
    res = api.create_package_plan(
        {"name": "Bad", "kind": "GOLD", "price_cents": 1000, "grant_credits": 5, "validity_days": 30}, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_session_ends_at_computed_from_duration(api):
    """PRD §3.5: "its `ends_at` computed as `starts_at` plus the template's `duration_min`
    minutes."

    Design: Corner/entities/session_ends_at_computed_from_duration
    """
    studio = create_studio()
    room = create_room(studio["id"])
    instructor = create_instructor(studio["id"])
    template = get_success_data(api.create_class_template(
        {"name": "Long", "duration_min": 75, "credit_cost": 5}, ADMIN))
    res = api.create_session({
        "studio_id": studio["id"], "room_id": room["id"], "instructor_id": instructor["id"],
        "template_id": template["id"], "starts_at": "2026-06-20T10:00:00Z", "seat_capacity": 5,
    }, MANAGER)
    session = validate_success(res, 201)
    assert session["ends_at"].startswith("2026-06-20T11:15:00"), (
        f"75-min template on a 10:00 start must end 11:15, got {session['ends_at']}")


def test_list_sessions_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter caps how many items are returned; it defaults to
    10 when omitted, may be no smaller than 1, and may be no larger than 100."
    PRD §2.3: "The `meta` object of a list response carries the pagination fields
    `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_sessions_pagination_envelope
    """
    studio = create_studio()
    room_a = create_room(studio["id"], name="Room A")
    room_b = create_room(studio["id"], name="Room B")
    instructor = create_instructor(studio["id"])
    template = get_success_data(api.create_class_template(
        {"name": "Flow", "duration_min": 60, "credit_cost": 5}, ADMIN))
    for room, start in ((room_a, "2026-06-20T10:00:00Z"), (room_b, "2026-06-20T13:00:00Z")):
        validate_success(api.create_session({
            "studio_id": studio["id"], "room_id": room["id"], "instructor_id": instructor["id"],
            "template_id": template["id"], "starts_at": start, "seat_capacity": 5}, MANAGER), 201)

    data, meta = validate_paginated(api.list_sessions(MANAGER, params={"limit": 1, "offset": 0, "studio_id": studio["id"]}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_fk_reverse_list_reservations_by_member(api):
    """PRD §4 endpoint table: "GET `/reservations` | List reservations; filter by
    `member_id` or `membership_id`".
    PRD §3.6: "The created `Reservation` records the `session_id`, the `member_id`, and
    the `membership_id`".

    Design: Corner/endpoints/fk_reverse_list_reservations_by_member
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"price_cents": 8000, "grant_credits": 20, "validity_days": 60})
    member, membership = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], active=True)
    session = create_published_session(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"], net["template"]["id"],
        starts_at="2026-06-20T10:00:00Z", seat_capacity=5)
    r1 = reserve(session["id"], member["id"], membership["id"])

    data, meta = validate_paginated(api.list_reservations(
        make_member_headers(member["id"]), params={"member_id": member["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == r1["id"]
    assert data[0]["member_id"] == member["id"]


def test_member_cannot_publish_session(api):
    """PRD §2.1: "When the headers are present and well-formed but the role is not
    permitted to perform the requested operation — or an ownership check fails — the
    request is rejected with `ERR_FORBIDDEN`."
    PRD §4 endpoint table: "POST `/sessions/{id}/publish` | Publish a scheduled session |
    StudioManager, NetworkAdmin".

    Design: Corner/rbac/member_cannot_publish_session
    """
    net = setup_network()
    member = get_success_data(api.create_member(
        {"email": "m1@x.com", "full_name": "M One", "home_studio_id": net["studio"]["id"]}, ADMIN))
    session = get_success_data(api.create_session({
        "studio_id": net["studio"]["id"], "room_id": net["room"]["id"],
        "instructor_id": net["instructor"]["id"], "template_id": net["template"]["id"],
        "starts_at": "2026-06-20T10:00:00Z", "seat_capacity": 5}, MANAGER))

    res = api.publish_session(session["id"], make_member_headers(member["id"]))
    validate_error(res, "ERR_FORBIDDEN")


def test_member_cannot_cancel_other_members_reservation(api):
    """PRD §2.1: "a `Member` may act only on memberships, reservations, and fees that
    trace back to their own `Member.id` — for example a reservation whose `member_id`
    equals the caller's `X-User-ID`".

    Design: Corner/rbac/member_cannot_cancel_other_members_reservation
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(template_overrides={"credit_cost": 5, "late_cancel_window_hours": 12},
                        plan_overrides={"price_cents": 8000, "grant_credits": 20, "validity_days": 60})
    m1, sub1 = setup_member_with_membership(net["studio"]["id"], net["plan"]["id"], email="m1@x.com", full_name="M One")
    m2 = get_success_data(api.create_member(
        {"email": "m2@x.com", "full_name": "M Two", "home_studio_id": net["studio"]["id"]}, ADMIN))
    session = create_published_session(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"], net["template"]["id"],
        starts_at="2026-06-20T10:00:00Z", seat_capacity=5)
    r1 = reserve(session["id"], m1["id"], sub1["id"])

    res = api.cancel_reservation(r1["id"], make_member_headers(m2["id"]))
    validate_error(res, "ERR_FORBIDDEN")
    after = validate_success(api.get_reservation(r1["id"], ADMIN), 200)
    assert after["booking_status"] == "BOOKED", "rejected cross-member cancel must not release the seat"


def test_missing_auth_header_returns_401(api):
    """PRD §2.1: "A request that omits either header, or that carries a role string
    outside this set, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_header_returns_401
    """
    studio = create_studio()
    res = api.get_studio(studio["id"], headers={})
    validate_error(res, "ERR_UNAUTHENTICATED")
