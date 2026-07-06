"""Room cleanup-buffer conflicts, customer session overlap, registration window."""
from test_helpers import (
    validate_error, ApiErrorId,
    set_clock, create_customer, create_room, create_workshop, create_session,
    setup_open_workshop_with_session, register_customer, make_customer_headers,
)
from test_helpers import TEST_USERS
from test_helpers import factories as f


def test_room_conflict_within_cleanup_buffer(api):
    """PRD §3.6: "two sessions in the same room must be separated by at least the
    room's cleanup_buffer_min, treating the interval as closed and adding the
    buffer; a violation is rejected with ERR_ROOM_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/room_conflict_with_cleanup_buffer
    """
    room = create_room(cleanup_buffer_min=30)
    workshop = create_workshop()
    create_session(workshop["id"], room["id"], "2026-08-05T10:00:00Z", "2026-08-05T12:00:00Z", capacity=10)
    resp = api.create_session(
        workshop["id"],
        f.create_session_payload(room["id"], "2026-08-05T12:15:00Z", "2026-08-05T13:00:00Z", 10, instructor_code="I2"),
        TEST_USERS["store_manager_headers"],
    )
    # 15-min gap < 30-min buffer -> conflict.
    validate_error(resp, ApiErrorId.ERR_ROOM_CONFLICT)


def test_room_gap_beyond_buffer_allowed(api):
    """PRD §3.6: "two sessions in the same room must be separated by at least the
    room's cleanup_buffer_min, treating the interval as closed and adding the
    buffer; a violation is rejected with ERR_ROOM_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/room_conflict_with_cleanup_buffer
    """
    from test_helpers import validate_success
    room = create_room(cleanup_buffer_min=30)
    workshop = create_workshop()
    create_session(workshop["id"], room["id"], "2026-08-05T10:00:00Z", "2026-08-05T12:00:00Z", capacity=10)
    resp = api.create_session(
        workshop["id"],
        f.create_session_payload(room["id"], "2026-08-05T12:40:00Z", "2026-08-05T13:30:00Z", 10, instructor_code="I3"),
        TEST_USERS["store_manager_headers"],
    )
    # 40-min gap >= 30-min buffer -> allowed.
    validate_success(resp, expected_status=201)


def test_customer_session_overlap_rejected(api):
    """PRD §3.6: "A customer's REGISTERED sessions may not overlap in time; overlap
    is judged on the half-open interval from starts_at to ends_at, so back-to-back
    sessions that merely touch at an endpoint are allowed, while a true overlap is
    rejected with ERR_CUSTOMER_SESSION_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/customer_session_overlap_half_open
    """
    set_clock("2026-05-01T00:00:00Z")
    customer = create_customer()
    room_a = create_room(name="RA")
    room_b = create_room(name="RB")
    workshop = create_workshop()
    s1 = create_session(workshop["id"], room_a["id"], "2026-08-06T10:00:00Z", "2026-08-06T12:00:00Z", capacity=10)
    s2 = create_session(workshop["id"], room_b["id"], "2026-08-06T11:00:00Z", "2026-08-06T13:00:00Z", capacity=10)
    from test_helpers import get_success_data
    get_success_data(api.open_workshop(workshop["id"], TEST_USERS["store_manager_headers"]))
    register_customer(workshop["id"], s1["id"], customer["id"])
    resp = api.register_workshop(
        workshop["id"], f.register_payload(s2["id"], customer["id"]),
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_SESSION_OVERLAP)


def test_back_to_back_sessions_allowed(api):
    """PRD §3.6: "back-to-back sessions that merely touch at an endpoint are
    allowed, while a true overlap is rejected with ERR_CUSTOMER_SESSION_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/customer_session_overlap_half_open
    """
    from test_helpers import validate_success, get_success_data
    set_clock("2026-05-01T00:00:00Z")
    customer = create_customer()
    room_a = create_room(name="RA2")
    room_b = create_room(name="RB2")
    workshop = create_workshop()
    s1 = create_session(workshop["id"], room_a["id"], "2026-08-07T10:00:00Z", "2026-08-07T12:00:00Z", capacity=10)
    s2 = create_session(workshop["id"], room_b["id"], "2026-08-07T12:00:00Z", "2026-08-07T14:00:00Z", capacity=10)
    get_success_data(api.open_workshop(workshop["id"], TEST_USERS["store_manager_headers"]))
    register_customer(workshop["id"], s1["id"], customer["id"])
    resp = api.register_workshop(
        workshop["id"], f.register_payload(s2["id"], customer["id"]),
        make_customer_headers(customer["id"]),
    )
    # touch at 12:00 endpoint under half-open intervals -> allowed.
    validate_success(resp, expected_status=201)


def test_registration_closed_after_session_start(api):
    """PRD §3.6: "the workshop must be OPEN and the clock instant must be strictly
    before the session's starts_at, otherwise ERR_REGISTRATION_CLOSED."

    Design: Corner/validations/registration_closed_after_session_start
    """
    set_clock("2026-05-01T00:00:00Z")
    customer = create_customer()
    workshop, session, _ = setup_open_workshop_with_session(
        "2026-08-10T10:00:00Z", "2026-08-10T12:00:00Z", capacity=10
    )
    set_clock("2026-08-10T11:00:00Z")  # past start
    resp = api.register_workshop(
        workshop["id"], f.register_payload(session["id"], customer["id"]),
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_CLOSED)
