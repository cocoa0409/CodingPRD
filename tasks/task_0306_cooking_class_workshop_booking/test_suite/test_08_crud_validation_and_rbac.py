"""CRUD, input validation, create-time business checks, and RBAC.

Queue B: entities (creation, not-found, required/default/system fields, enum,
listing), validations (time window, skill insufficient, private partial buyout),
endpoints (get/list booking), errors and rbac (auth/role/ownership).
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    create_instructor,
    create_member,
    create_published_template,
    create_session,
    create_open_session,
    create_booking,
    add_ingredient_line,
    make_instructor_headers,
    make_member_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["studio_admin_headers"]


# ─── Entities ───────────────────────────────────────────────────────
def test_create_template_returns_201_with_fields(api):
    """PRD §3.1: "A StudioAdmin creates a ClassTemplate with a title, a skill_level
    from the same four-rung ladder, a per-seat base_price_cents (zero or more) ...
    A template's status starts at DRAFT".

    POST /culinary/templates returns 201 with status DRAFT and the echoed fields.

    Design: Corner/entities/create_template_returns_201_with_all_fields
    """
    res = api.create_template(
        {"title": "Basics", "skill_level": "BEGINNER", "base_price_cents": 5000,
         "default_capacity": 4, "station_fixed_cost_cents": 1200,
         "prep_minutes": 30, "cleanup_minutes": 15},
        ADMIN,
    )
    tmpl = validate_success(res, 201)
    assert tmpl["status"] == "DRAFT"
    assert tmpl["base_price_cents"] == 5000


def test_get_nonexistent_session_returns_not_found(api):
    """PRD §2.8: "the request is rejected with ERR_NOT_FOUND against the first
    identifier in the path that does not resolve to an existing resource".

    GET /culinary/sessions/{id} with a non-existent UUID returns ERR_NOT_FOUND (404).

    Design: Corner/entities/get_session_not_found_returns_404
    """
    res = api.get_session("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_member_missing_required_field_rejected(api):
    """PRD §2.9: "then structural validity of the request body - all required
    fields present, correctly typed, and drawn from the allowed enum values
    (ERR_INVALID_REQUEST)."
    PRD §3.2: "A Member is registered ... with a full_name, a unique email".

    POST /culinary/members omitting full_name returns ERR_INVALID_REQUEST.

    Design: Corner/entities/create_member_missing_required_field_returns_invalid_request
    """
    res = api.create_member({"email": "nofull@x.com"}, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_member_dietary_flags_defaults_to_empty_array(api):
    """PRD §3.2: "an optional dietary_flags array ... when omitted, dietary_flags
    defaults to an empty array. The system seeds three accounting fields at
    registration: wallet_credit_cents starts at 0 ... reliability_score starts at
    100; and booking_status starts at GOOD_STANDING".

    A member created without dietary_flags has [] flags, wallet 0, reliability 100,
    GOOD_STANDING.

    Design: Corner/entities/member_dietary_flags_defaults_to_empty_array
    """
    res = api.create_member({"full_name": "Defaulter", "email": "def@x.com"}, ADMIN)
    member = validate_success(res, 201)
    assert member["dietary_flags"] == []
    assert member["wallet_credit_cents"] == 0
    assert member["reliability_score"] == 100
    assert member["booking_status"] == "GOOD_STANDING"


def test_session_system_fields_stamped_not_taken_from_input(api):
    """PRD §3.4: "A freshly created session has confirmed_seats of 0 and
    prep_cost_per_seat_cents of 0; its status lifecycle is SCHEDULED, OPEN, FULL,
    LOCKED, COMPLETED, CANCELLED."
    PRD §2.4: "The version field is an integer that begins at creation".

    A new session has confirmed_seats 0, status SCHEDULED, version 1 — the system
    stamps these regardless of any client-sent values.

    Design: Corner/entities/session_system_fields_generated_input_ignored
    """
    instr = create_instructor()
    tmpl = create_published_template(
        skill_level="BEGINNER", base_price_cents=5000, default_capacity=4,
        station_fixed_cost_cents=1000,
    )
    res = api.create_session(
        {"template_id": tmpl["id"], "instructor_id": instr["id"], "station_id": "ST-SYS",
         "event_type": "GROUP", "start_at": "2026-11-01T14:00:00Z",
         "end_at": "2026-11-01T16:00:00Z", "planned_seats": 4},
        ADMIN,
    )
    session = validate_success(res, 201)
    assert session["confirmed_seats"] == 0
    assert session["status"] == "SCHEDULED"
    assert session["version"] == 1


def test_create_template_invalid_skill_level_enum_rejected(api):
    """PRD §2.9: "all required fields present, correctly typed, and drawn from the
    allowed enum values (ERR_INVALID_REQUEST)."
    PRD §3.1: "a skill_level from the same four-rung ladder".

    A template with skill_level outside the enum returns ERR_INVALID_REQUEST.

    Design: Corner/entities/create_template_invalid_skill_level_enum_rejected
    """
    res = api.create_template(
        {"title": "Bad", "skill_level": "WIZARD", "base_price_cents": 5000,
         "default_capacity": 4, "station_fixed_cost_cents": 1000,
         "prep_minutes": 0, "cleanup_minutes": 0},
        ADMIN,
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_list_sessions_pagination_envelope(api):
    """PRD §2.3: "Each list response carries the pagination bookkeeping in the meta
    object of the envelope: limit, offset, total_count (the total number of
    matching rows before pagination), and has_more (a boolean that is true when
    rows remain beyond the current page)."

    With two sessions and limit 1, the list returns one item, total_count >= 2,
    has_more true.

    Design: Corner/entities/list_sessions_pagination_envelope
    """
    instr = create_instructor()
    tmpl = create_published_template(
        skill_level="BEGINNER", base_price_cents=5000, default_capacity=4,
        station_fixed_cost_cents=1000,
    )
    create_session(
        tmpl["id"], instr["id"], station_id="ST-PAG1",
        start_at="2026-11-02T14:00:00Z", end_at="2026-11-02T16:00:00Z", planned_seats=4,
    )
    create_session(
        tmpl["id"], instr["id"], station_id="ST-PAG2",
        start_at="2026-11-03T14:00:00Z", end_at="2026-11-03T16:00:00Z", planned_seats=4,
    )
    data, meta = validate_paginated(api.list_sessions(ADMIN, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] >= 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ─── Create-time validations ────────────────────────────────────────
def test_session_end_not_after_start_rejected(api):
    """PRD §3.4: "and end_at must be strictly later than start_at, or the create
    is rejected with ERR_INVALID_TIME_WINDOW."

    A session with end_at == start_at is rejected ERR_INVALID_TIME_WINDOW.

    Design: Corner/validations/session_end_not_after_start_rejected
    """
    instr = create_instructor()
    tmpl = create_published_template(
        skill_level="BEGINNER", base_price_cents=5000, default_capacity=4,
        station_fixed_cost_cents=1000,
    )
    res = api.create_session(
        {"template_id": tmpl["id"], "instructor_id": instr["id"], "station_id": "ST-TW",
         "event_type": "GROUP", "start_at": "2026-11-15T14:00:00Z",
         "end_at": "2026-11-15T14:00:00Z", "planned_seats": 4},
        ADMIN,
    )
    validate_error(res, "ERR_INVALID_TIME_WINDOW", expected_status=422)


def test_instructor_skill_insufficient_on_session_create(api):
    """PRD §3.4: "At create time two checks apply: the assigned instructor's
    max_skill_level must be at or above the template's skill_level on the skill
    ladder, or the create is rejected with ERR_INSTRUCTOR_SKILL_INSUFFICIENT".

    A BEGINNER-max instructor on a PROFESSIONAL template is rejected
    ERR_INSTRUCTOR_SKILL_INSUFFICIENT.

    Design: Corner/validations/instructor_skill_insufficient_on_session_create
    """
    instr = create_instructor(max_skill_level="BEGINNER")
    tmpl = create_published_template(
        title="ProClass", skill_level="PROFESSIONAL", base_price_cents=9000,
        default_capacity=4, station_fixed_cost_cents=1000,
    )
    res = api.create_session(
        {"template_id": tmpl["id"], "instructor_id": instr["id"], "station_id": "ST-SK",
         "event_type": "GROUP", "start_at": "2026-11-16T14:00:00Z",
         "end_at": "2026-11-16T16:00:00Z", "planned_seats": 4},
        ADMIN,
    )
    validate_error(res, "ERR_INSTRUCTOR_SKILL_INSUFFICIENT", expected_status=422)


def test_private_booking_partial_seats_rejected(api):
    """PRD §3.5: "for a PRIVATE session the seats_requested must equal the
    session's planned_seats (a whole-studio buyout), failing which the create is
    rejected with ERR_PRIVATE_REQUIRES_FULL_BUYOUT".

    A PRIVATE planned_seats=4 session booked with seats_requested=2 is rejected
    ERR_PRIVATE_REQUIRES_FULL_BUYOUT.

    Design: Corner/validations/private_booking_partial_seats_rejected
    """
    _instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "BEGINNER", "base_price_cents": 5000, "default_capacity": 4,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={
            "event_type": "PRIVATE", "planned_seats": 4,
            "private_event_fee_cents": 30000, "station_id": "ST-PB",
        },
        ingredient_overrides={"name": "p", "qty_per_seat": 1, "unit_cost_cents": 1},
    )
    member = create_member()
    res = api.create_booking(
        {"session_id": session["id"], "member_id": member["id"], "seats_requested": 2},
        make_member_headers(member["id"]),
    )
    validate_error(res, "ERR_PRIVATE_REQUIRES_FULL_BUYOUT", expected_status=422)


# ─── Endpoints (reads) ──────────────────────────────────────────────
def test_get_booking_returns_stored_data(api):
    """PRD §3.5: "Creating a Booking supplies the session_id being booked, the
    member_id who will own it, and a seats_requested count ... The new booking
    starts with lifecycle_status of PENDING and payment_status of UNPAID".

    GET /culinary/bookings/{id} returns the stored booking with its charge_cents
    and lifecycle_status PENDING (BEGINNER 1 seat -> charge 5000).

    Design: Corner/endpoints/get_booking_returns_stored_data
    """
    _instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "BEGINNER", "base_price_cents": 5000, "default_capacity": 2,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={"planned_seats": 2, "station_id": "ST-GB"},
        ingredient_overrides={"name": "z", "qty_per_seat": 1, "unit_cost_cents": 1},
    )
    member = create_member()
    booking = create_booking(session["id"], member["id"], 1)
    fetched = validate_success(api.get_booking(booking["id"], make_member_headers(member["id"])), 200)
    assert fetched["charge_cents"] == 5000
    assert fetched["lifecycle_status"] == "PENDING"


def test_list_bookings_filtered_by_member(api):
    """PRD §4: "GET /culinary/bookings - List bookings (by session_id, member_id,
    lifecycle_status)".
    PRD §2.3: "total_count (the total number of matching rows before pagination)".

    GET /culinary/bookings?member_id=X returns only that member's bookings.

    Design: Corner/endpoints/list_bookings_filtered_by_member
    """
    _instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "BEGINNER", "base_price_cents": 5000, "default_capacity": 4,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={"planned_seats": 4, "station_id": "ST-LBF"},
        ingredient_overrides={"name": "z", "qty_per_seat": 1, "unit_cost_cents": 1},
    )
    mem1 = create_member()
    mem2 = create_member()
    create_booking(session["id"], mem1["id"], 1)
    create_booking(session["id"], mem2["id"], 1)
    data, meta = validate_paginated(api.list_bookings(ADMIN, params={"member_id": mem1["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["member_id"] == mem1["id"]


# ─── RBAC ───────────────────────────────────────────────────────────
def test_member_cannot_open_session_forbidden_role(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to invoke the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE."
    PRD §3.4: "Opening a session is an Instructor action on its own session".

    A Member calling the Instructor-exclusive open endpoint gets
    ERR_FORBIDDEN_ROLE (403).

    Design: Corner/rbac/member_cannot_open_session_forbidden
    """
    instr = create_instructor()
    tmpl = create_published_template(
        skill_level="BEGINNER", base_price_cents=5000, default_capacity=4,
        station_fixed_cost_cents=1000,
    )
    session = create_session(
        tmpl["id"], instr["id"], station_id="ST-RB",
        start_at="2026-11-25T14:00:00Z", end_at="2026-11-25T16:00:00Z", planned_seats=4,
    )
    add_ingredient_line(session["id"], instr["id"], name="z", qty_per_seat=1, unit_cost_cents=1)
    member = create_member()
    res = api.open_session(session["id"], make_member_headers(member["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_member_cannot_confirm_other_members_booking(api):
    """PRD §2.1: "When the role is permitted in general but the specific resource
    being mutated is not owned by the acting principal, the request is rejected
    with ERR_NOT_RESOURCE_OWNER."
    PRD §2.1: "ownership checks compare the relevant member-foreign-key field - a
    booking's member_id ... to X-User-ID."

    Member B confirming Member A's booking gets ERR_NOT_RESOURCE_OWNER (403); the
    booking stays PENDING.

    Design: Corner/rbac/member_cannot_confirm_other_members_booking
    """
    from test_helpers import get_session_version
    _instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "BEGINNER", "base_price_cents": 5000, "default_capacity": 4,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={"planned_seats": 4, "station_id": "ST-OWN"},
        ingredient_overrides={"name": "z", "qty_per_seat": 1, "unit_cost_cents": 1},
    )
    mem_a = create_member()
    mem_b = create_member()
    bk_a = create_booking(session["id"], mem_a["id"], 1)
    sv = get_session_version(session["id"])
    res = api.confirm_booking(bk_a["id"], sv, make_member_headers(mem_b["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)
    after = validate_success(api.get_booking(bk_a["id"], make_member_headers(mem_a["id"])), 200)
    assert after["lifecycle_status"] == "PENDING"


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value,
    is rejected with ERR_UNAUTHENTICATED."

    A request with no auth headers returns ERR_UNAUTHENTICATED (401).

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    res = api.get_session("00000000-0000-4000-8000-0000000000bb", {})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)
