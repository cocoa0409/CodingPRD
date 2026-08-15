"""Meeting well-formedness and the buffered room / unbuffered instructor
overlap geometries."""
from test_helpers import (
    PC,
    ApiErrorId,
    add_meeting,
    create_class_meeting_payload,
    create_class_session,
    create_instructor,
    create_program,
    create_room,
    create_season,
    is_valid_uuid,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _api


def test_meeting_time_inverted_rejected(api):
    """PRD §3.2: "Each session meets through one or more **ClassMeetings**,
    created with the `session_id`, the assigned `room_id`, and a
    `starts_at`/`ends_at` pair with `ends_at` strictly later than
    `starts_at`."
    PRD §2.8: "Request well-formedness — required fields present, types
    correct, enum members valid, and numeric ranges honored: `capacity`
    greater than zero, `min_enrollment` at least one and no greater than
    `capacity`, amounts greater than zero, `approved_pct` one of 25, 50, 75,
    or 100, `revenue_share_bp` between 0 and 10000 inclusive, `ends_at` later
    than `starts_at`, `max_age` at least `min_age`, the season window ordering
    (`resident_opens_at` no later than `general_opens_at`, in turn no later
    than `registration_closes_at`), and `end_date` later than `start_date`.
    Violations are `ERR_INVALID_REQUEST`."

    Design: Corner/validations/meeting_time_inverted_rejected
    """
    season = create_season()
    program = create_program(season["id"], name="Crafts", category="Arts")
    room = create_room(name="Craft Room")
    instructor = create_instructor()
    session = create_class_session(program["id"], instructor["id"], title="SD")

    resp = _api.create_class_meeting(
        create_class_meeting_payload(session["id"], room["id"],
                                     starts_at="2026-09-20T19:00:00Z",
                                     ends_at="2026-09-20T18:00:00Z"),
        PC,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def _two_sessions_one_room() -> dict:
    """DRAFT season; room R1; sessions S1 (instructor I1) and S2 (I2); S1 has
    a meeting 2026-09-20 10:00-11:00 in R1."""
    season = create_season()
    program = create_program(season["id"], name="Fitness", category="Fitness")
    room = create_room(name="Gym")
    instructor_1 = create_instructor(full_name="Fit A", email="fa@x.com")
    instructor_2 = create_instructor(full_name="Fit B", email="fb@x.com")
    s1 = create_class_session(program["id"], instructor_1["id"], title="S1")
    s2 = create_class_session(program["id"], instructor_2["id"], title="S2")
    add_meeting(s1["id"], room["id"], "2026-09-20T10:00:00Z", "2026-09-20T11:00:00Z")
    return {"s2": s2, "room": room}


def test_room_conflict_inside_turnover_buffer(api):
    """PRD §2.9: "For rooms, a meeting's occupancy runs from its `starts_at`
    until fifteen minutes after its `ends_at` — a fixed turnover buffer — so a
    new meeting that begins at exactly the instant another meeting's buffered
    occupancy ends is adjacent, not conflicting."
    PRD §3.2: "Meeting creation is season-gated like session creation, and
    then runs four scheduling checks in a fixed order: first the room must be
    large enough — the room's `capacity` at least the session's `capacity`,
    with equality allowed — else `ERR_ROOM_CAPACITY_INSUFFICIENT`; second the
    room must be `ACTIVE`, else `ERR_ROOM_UNAVAILABLE`; third the buffered
    room-overlap check of §2.9 runs against every other meeting in the same
    room whose session is non-terminal, rejecting collisions with
    `ERR_ROOM_CONFLICT`; fourth the unbuffered instructor-overlap check runs
    against meetings of other non-terminal sessions assigned to the same
    instructor, rejecting collisions with `ERR_INSTRUCTOR_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/room_buffer_overlap_semantics
    """
    scenario = _two_sessions_one_room()
    # 11:14 is inside the 10:00-11:00 meeting's buffered occupancy
    # ([10:00, 11:15) with the 15-minute turnover).
    resp = _api.create_class_meeting(
        create_class_meeting_payload(scenario["s2"]["id"], scenario["room"]["id"],
                                     starts_at="2026-09-20T11:14:00Z",
                                     ends_at="2026-09-20T12:00:00Z"),
        PC,
    )
    validate_error(resp, ApiErrorId.ERR_ROOM_CONFLICT, 409)


def test_room_adjacency_at_buffer_end_allowed(api):
    """PRD §2.9: "Room and instructor scheduling both reason about half-open
    time intervals: an interval includes its start instant and excludes its
    end instant. Two intervals conflict exactly when each starts strictly
    before the other ends. For rooms, a meeting's occupancy runs from its
    `starts_at` until fifteen minutes after its `ends_at` — a fixed turnover
    buffer — so a new meeting that begins at exactly the instant another
    meeting's buffered occupancy ends is adjacent, not conflicting."

    Design: Difficulty/resource_temporal_overlap/room_buffer_overlap_semantics
    """
    scenario = _two_sessions_one_room()
    # 11:15 == prior ends_at + buffer exactly: half-open boundary, no conflict.
    created = validate_success(
        _api.create_class_meeting(
            create_class_meeting_payload(scenario["s2"]["id"], scenario["room"]["id"],
                                         starts_at="2026-09-20T11:15:00Z",
                                         ends_at="2026-09-20T12:00:00Z"),
            PC,
        ),
        201,
    )
    assert is_valid_uuid(created["id"])


def _three_sessions_one_instructor() -> dict:
    """DRAFT season; instructor IX teaches SA/SB/SC; rooms R1/R2/R3; SA has a
    meeting 2026-09-20 10:00-11:00 in R1."""
    season = create_season()
    program = create_program(season["id"], name="Tutoring", category="Education")
    rooms = [create_room(name=f"Room {i}") for i in (1, 2, 3)]
    instructor = create_instructor(full_name="Tutor X", email="tx@x.com")
    sa = create_class_session(program["id"], instructor["id"], title="SA")
    sb = create_class_session(program["id"], instructor["id"], title="SB")
    sc = create_class_session(program["id"], instructor["id"], title="SC")
    add_meeting(sa["id"], rooms[0]["id"], "2026-09-20T10:00:00Z", "2026-09-20T11:00:00Z")
    return {"sb": sb, "sc": sc, "rooms": rooms}


def test_instructor_back_to_back_allowed(api):
    """PRD §2.9: "For instructors there is no buffer at all: a meeting
    occupies exactly its own span, so a new meeting starting at exactly the
    instant the instructor's other meeting ends is likewise allowed."

    Design: Difficulty/resource_temporal_overlap/instructor_unbuffered_back_to_back
    """
    scenario = _three_sessions_one_instructor()
    # 11:00 == the other meeting's ends_at exactly: half-open, no conflict.
    created = validate_success(
        _api.create_class_meeting(
            create_class_meeting_payload(scenario["sb"]["id"],
                                         scenario["rooms"][1]["id"],
                                         starts_at="2026-09-20T11:00:00Z",
                                         ends_at="2026-09-20T12:00:00Z"),
            PC,
        ),
        201,
    )
    assert is_valid_uuid(created["id"])


def test_instructor_one_minute_overlap_rejected(api):
    """PRD §2.9: "Two intervals conflict exactly when each starts strictly
    before the other ends."
    PRD §3.2: "fourth the unbuffered instructor-overlap check runs against
    meetings of other non-terminal sessions assigned to the same instructor,
    rejecting collisions with `ERR_INSTRUCTOR_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/instructor_unbuffered_back_to_back
    """
    scenario = _three_sessions_one_instructor()
    # 10:59 overlaps the 10:00-11:00 meeting by one minute.
    resp = _api.create_class_meeting(
        create_class_meeting_payload(scenario["sc"]["id"],
                                     scenario["rooms"][2]["id"],
                                     starts_at="2026-09-20T10:59:00Z",
                                     ends_at="2026-09-20T12:00:00Z"),
        PC,
    )
    validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_DOUBLE_BOOKED, 409)
