"""Session scheduling: instructor travel-buffer conflicts, room cleaning-buffer
conflicts (and their half-open boundary "ok" cases), the seat-capacity-vs-room
invariant, and the closed-studio dependency check. Translates difficulty-design
resource_temporal_overlap plus the relevant corner instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_network, create_studio, create_room, create_instructor, create_template,
    set_clock, api_client, TEST_USERS,
)

ADMIN = TEST_USERS["network_admin_headers"]
MANAGER = TEST_USERS["studio_manager_headers"]


def _session_payload(studio_id, room_id, instructor_id, template_id, starts_at, seat_capacity=5):
    return {"studio_id": studio_id, "room_id": room_id, "instructor_id": instructor_id,
            "template_id": template_id, "starts_at": starts_at, "seat_capacity": seat_capacity}


def test_instructor_cross_studio_under_travel_buffer_conflicts(api):
    """PRD §3.5: "Two sessions of the same instructor at *different* studios additionally
    require a travel buffer of 30 minutes: they conflict when the gap between them is less
    than 30 minutes, where the gap is the later session's `starts_at` minus the earlier
    session's `ends_at` in minutes, floored at zero. Any such same-studio overlap or
    cross-studio under-buffer is rejected with `ERR_INSTRUCTOR_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/instructor_cross_studio_travel_buffer
    """
    studio_x = create_studio(name="Studio X", state_code="CA")
    studio_y = create_studio(name="Studio Y", state_code="CA")
    room_x = create_room(studio_x["id"], name="X Room")
    room_y = create_room(studio_y["id"], name="Y Room")
    instructor = create_instructor(studio_x["id"], full_name="Ina")
    template = create_template(name="Flow60", duration_min=60, credit_cost=5)

    validate_success(api.create_session(_session_payload(
        studio_x["id"], room_x["id"], instructor["id"], template["id"], "2026-06-20T10:00:00Z"), MANAGER), 201)
    # Same instructor at studio Y starting 11:20: ends 11:00 -> gap 20 < 30.
    res = api.create_session(_session_payload(
        studio_y["id"], room_y["id"], instructor["id"], template["id"], "2026-06-20T11:20:00Z"), MANAGER)
    validate_error(res, "ERR_INSTRUCTOR_CONFLICT")


def test_instructor_same_studio_strict_overlap_conflicts(api):
    """PRD §3.5: "Two sessions of the same instructor at the *same* studio conflict when
    their intervals strictly overlap ... Any such same-studio overlap or cross-studio
    under-buffer is rejected with `ERR_INSTRUCTOR_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/instructor_cross_studio_travel_buffer
    """
    studio_x = create_studio(name="Studio X", state_code="CA")
    room1 = create_room(studio_x["id"], name="R1")
    room2 = create_room(studio_x["id"], name="R2")
    instructor = create_instructor(studio_x["id"], full_name="Ina")
    template = create_template(name="Flow60", duration_min=60, credit_cost=5)

    validate_success(api.create_session(_session_payload(
        studio_x["id"], room1["id"], instructor["id"], template["id"], "2026-06-20T10:00:00Z"), MANAGER), 201)
    # Same instructor, same studio, 10:30-11:30 strictly overlaps the 10:00-11:00 session.
    res = api.create_session(_session_payload(
        studio_x["id"], room2["id"], instructor["id"], template["id"], "2026-06-20T10:30:00Z"), MANAGER)
    validate_error(res, "ERR_INSTRUCTOR_CONFLICT")


def test_room_cleaning_buffer_padded_overlap_conflicts(api):
    """PRD §3.5: "The **room conflict** rule appends a 15-minute cleaning buffer to each
    session: a session's effective interval runs from its `starts_at` to its `ends_at`
    plus 15 minutes. Two non-`CANCELLED` sessions in the same room conflict when each
    one's `starts_at` falls before the other's cleaning-padded end ... An overlap here is
    rejected with `ERR_ROOM_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/room_cleaning_buffer_padded_overlap
    """
    studio_x = create_studio(name="Studio X", state_code="CA")
    room_r = create_room(studio_x["id"], name="R")
    inst_a = create_instructor(studio_x["id"], full_name="Ina")
    inst_b = create_instructor(studio_x["id"], full_name="Ino")
    template = create_template(name="Flow60", duration_min=60, credit_cost=5)

    validate_success(api.create_session(_session_payload(
        studio_x["id"], room_r["id"], inst_a["id"], template["id"], "2026-06-20T10:00:00Z"), MANAGER), 201)
    # Same room, starts 11:10 < padded end 11:15 -> conflict.
    res = api.create_session(_session_payload(
        studio_x["id"], room_r["id"], inst_b["id"], template["id"], "2026-06-20T11:10:00Z"), MANAGER)
    validate_error(res, "ERR_ROOM_CONFLICT")


def test_room_raw_interval_overlap_conflicts(api):
    """PRD §3.5: "Two non-`CANCELLED` sessions in the same room conflict when each one's
    `starts_at` falls before the other's cleaning-padded end ... An overlap here is
    rejected with `ERR_ROOM_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/room_cleaning_buffer_padded_overlap
    """
    studio_x = create_studio(name="Studio X", state_code="CA")
    room_r = create_room(studio_x["id"], name="R")
    inst_a = create_instructor(studio_x["id"], full_name="Ina")
    inst_b = create_instructor(studio_x["id"], full_name="Ino")
    template = create_template(name="Flow60", duration_min=60, credit_cost=5)

    validate_success(api.create_session(_session_payload(
        studio_x["id"], room_r["id"], inst_a["id"], template["id"], "2026-06-20T10:00:00Z"), MANAGER), 201)
    # Same room, 10:30 start falls before the first session's padded end 11:15 -> overlap.
    res = api.create_session(_session_payload(
        studio_x["id"], room_r["id"], inst_b["id"], template["id"], "2026-06-20T10:30:00Z"), MANAGER)
    validate_error(res, "ERR_ROOM_CONFLICT")


def test_instructor_same_studio_touching_intervals_ok(api):
    """PRD §3.5: "Two sessions of the same instructor at the *same* studio conflict when
    their intervals strictly overlap — sessions that merely touch at a single instant do
    not conflict."

    Design: Corner/calculations/instructor_same_studio_touching_intervals_ok
    """
    studio_x = create_studio(name="Studio X", state_code="CA")
    room1 = create_room(studio_x["id"], name="R1")
    room2 = create_room(studio_x["id"], name="R2")
    inst_a = create_instructor(studio_x["id"], full_name="Ina")
    template = create_template(name="Flow60", duration_min=60, credit_cost=5)

    validate_success(api.create_session(_session_payload(
        studio_x["id"], room1["id"], inst_a["id"], template["id"], "2026-06-20T10:00:00Z"), MANAGER), 201)
    # Second session 11:00-12:00, same studio, touching at 11:00 -> no conflict.
    res = api.create_session(_session_payload(
        studio_x["id"], room2["id"], inst_a["id"], template["id"], "2026-06-20T11:00:00Z"), MANAGER)
    validate_success(res, 201)


def test_room_adjacent_at_cleaning_pad_edge_ok(api):
    """PRD §3.5: "the windows being half-open, so a session may start exactly when the
    prior padded interval ends without conflicting."

    Design: Corner/calculations/room_adjacent_at_cleaning_pad_edge_ok
    """
    studio_x = create_studio(name="Studio X", state_code="CA")
    room_r = create_room(studio_x["id"], name="R")
    inst_a = create_instructor(studio_x["id"], full_name="Ina")
    inst_b = create_instructor(studio_x["id"], full_name="Ino")
    template = create_template(name="Flow60", duration_min=60, credit_cost=5)

    validate_success(api.create_session(_session_payload(
        studio_x["id"], room_r["id"], inst_a["id"], template["id"], "2026-06-20T10:00:00Z"), MANAGER), 201)
    # Second session in same room starting exactly at the padded edge 11:15.
    res = api.create_session(_session_payload(
        studio_x["id"], room_r["id"], inst_b["id"], template["id"], "2026-06-20T11:15:00Z"), MANAGER)
    validate_success(res, 201)


def test_seat_capacity_exceeds_room_rejected(api):
    """PRD §3.5: "The seat capacity is then constrained so that a session's
    `seat_capacity` may never exceed the hosting room's `physical_capacity`; a violation
    is rejected with `ERR_CAPACITY_EXCEEDS_ROOM`."

    Design: Corner/validations/error_capacity_exceeds_room_on_create
    """
    net = setup_network()  # room physical_capacity 10
    res = api.create_session(_session_payload(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"], net["template"]["id"],
        "2026-06-20T10:00:00Z", seat_capacity=11), MANAGER)
    validate_error(res, "ERR_CAPACITY_EXCEEDS_ROOM")


def test_session_create_against_closed_studio_rejected(api):
    """PRD §3.5: "Before a session may be created, published, or edited, the operational
    state of its dependencies is checked first, ahead of any temporal-overlap or capacity
    check: the hosting studio must be `OPEN`, the room must be `ACTIVE`, and the
    instructor must be `ACTIVE`. A violation of any of these is rejected with
    `ERR_STUDIO_CLOSED`."

    Design: Corner/validations/error_studio_closed_on_session_create
    """
    net = setup_network()
    validate_success(api.close_studio(net["studio"]["id"], ADMIN), 200)
    res = api.create_session(_session_payload(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"], net["template"]["id"],
        "2026-06-20T10:00:00Z", seat_capacity=5), MANAGER)
    validate_error(res, "ERR_STUDIO_CLOSED")
