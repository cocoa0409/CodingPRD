"""Session scheduling: station/moderator overlap semantics, start gates,
cancellation lockdown, and the full live-window lifecycle."""
from test_helpers import (
    ApiErrorId,
    assign_moderator,
    assert_session,
    book_session,
    close_study,
    create_lab_session,
    create_moderator,
    create_remote_session,
    create_station,
    create_study,
    get_session,
    get_success_data,
    is_valid_uuid,
    make_moderator_headers,
    register_participant,
    enroll_participant,
    run_session_at_midpoint,
    set_clock,
    setup_study_with_published_nda,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
RESEARCHER = TEST_USERS["researcher_headers"]


def _setup_station_with_occupied_window():
    """Study RECRUITING; station ST1 holds an IN_LAB session 10:00-11:00."""
    study = create_study(code="OV1")
    station = create_station(station_code="ST1", location="Lab A",
                             equipment_tags=["devkit"])
    session_x = create_lab_session(study["id"], station["id"],
                                   "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z",
                                   seat_capacity=4)
    return study, station, session_x


class TestStationHalfOpenAdjacency:
    def test_touching_station_windows_do_not_conflict(self, api):
        """PRD §2.8: "Windows that merely touch — one ending at exactly the
        instant the other begins — do not conflict."

        Design: Difficulty/resource_temporal_overlap/station_half_open_adjacency
        """
        study, station, _x = _setup_station_with_occupied_window()
        data = validate_success(api.create_session(
            {"study_id": study["id"], "mode": "IN_LAB", "station_id": station["id"],
             "starts_at": "2026-08-10T11:00:00Z", "ends_at": "2026-08-10T12:00:00Z",
             "seat_capacity": 4}, RESEARCHER), expected_status=201)
        assert is_valid_uuid(data["id"]), (
            "a session starting exactly when the other ends is allowed (half-open)")
        assert_session(data)

    def test_strictly_overlapping_station_window_conflicts(self, api):
        """PRD §2.8: "A **lab station** is occupied by sessions in `SCHEDULED`
        or `IN_PROGRESS` under half-open interval semantics: a new window
        conflicts with an existing window whenever the new window's `starts_at`
        falls before the existing window's `ends_at` and the existing window's
        `starts_at` falls before the new window's `ends_at`."
        PRD §2.8: "Violations are rejected with `ERR_STATION_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/station_half_open_adjacency
        """
        study, station, _x = _setup_station_with_occupied_window()
        resp = api.create_session(
            {"study_id": study["id"], "mode": "IN_LAB", "station_id": station["id"],
             "starts_at": "2026-08-10T10:30:00Z", "ends_at": "2026-08-10T11:30:00Z",
             "seat_capacity": 4}, RESEARCHER)
        validate_error(resp, ApiErrorId.ERR_STATION_CONFLICT)


def _setup_moderator_with_session_a():
    """Moderator M assigned to REMOTE session A (2026-08-10 10:00-11:00);
    sessions B (11:10-12:00) and C (11:15-12:00) exist unassigned."""
    study = create_study(code="OV2")
    moderator = create_moderator(display_name="Mod OV2")
    sa = create_remote_session(study["id"], "2026-08-10T10:00:00Z",
                               "2026-08-10T11:00:00Z", seat_capacity=4)
    sb = create_remote_session(study["id"], "2026-08-10T11:10:00Z",
                               "2026-08-10T12:00:00Z", seat_capacity=4)
    sc = create_remote_session(study["id"], "2026-08-10T11:15:00Z",
                               "2026-08-10T12:00:00Z", seat_capacity=4)
    assign_moderator(sa["id"], moderator["id"])
    return study, moderator, sa, sb, sc


class TestModeratorTurnaroundBuffer:
    def test_ten_minute_gap_conflicts(self, api):
        """PRD §2.8: "A **moderator** is occupied by their sessions in
        `SCHEDULED` or `IN_PROGRESS` under fifteen-minute buffered semantics: a
        new window conflicts whenever its `starts_at` falls before fifteen
        minutes after the existing window's `ends_at`, and the existing
        window's `starts_at` falls before fifteen minutes after the new
        window's `ends_at`."
        PRD §2.8: "A gap of exactly fifteen minutes between windows is
        permitted; anything shorter conflicts with `ERR_MODERATOR_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/moderator_turnaround_buffer
        """
        _study, moderator, _sa, sb, _sc = _setup_moderator_with_session_a()
        resp = api.assign_moderator(sb["id"], moderator["id"], RESEARCHER)
        validate_error(resp, ApiErrorId.ERR_MODERATOR_CONFLICT)
        assert get_session(sb["id"]).get("moderator_id") is None, (
            "the rejected assignment persisted nothing")

    def test_fifteen_minute_gap_is_permitted(self, api):
        """PRD §2.8: "A gap of exactly fifteen minutes between windows is
        permitted; anything shorter conflicts with `ERR_MODERATOR_CONFLICT`."
        PRD §3.5: "success writes the payload's `moderator_id` onto the session
        and increments the session's `version`."

        Design: Difficulty/resource_temporal_overlap/moderator_turnaround_buffer
        """
        _study, moderator, _sa, _sb, sc = _setup_moderator_with_session_a()
        before = get_session(sc["id"])
        data = validate_success(api.assign_moderator(sc["id"], moderator["id"],
                                                     RESEARCHER))
        assert data["moderator_id"] == moderator["id"], (
            "the 15-minute gap (== buffer) is allowed")
        assert data["version"] == before["version"] + 1


def test_start_without_moderator_rejected(api):
    """PRD §3.5: "Only the assigned moderator may start a session, and the
    start is heavily preconditioned: the session must be `SCHEDULED`; a
    moderator must be assigned at all, else `ERR_MODERATOR_REQUIRED`"

    Design: Corner/validations/start_without_moderator_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    study = create_study(code="MR1")
    moderator = create_moderator(display_name="Mod MR")
    session = create_remote_session(study["id"], "2026-08-10T10:00:00Z",
                                    "2026-08-10T11:00:00Z", seat_capacity=4)
    close_study(study["id"])
    set_clock("2026-08-10T10:30:00Z")
    resp = api.start_session(session["id"], make_moderator_headers(moderator["id"]))
    validate_error(resp, ApiErrorId.ERR_MODERATOR_REQUIRED)


def test_start_outside_window_rejected(api):
    """PRD §3.5: "the current instant must fall within the session window, both
    `starts_at` and `ends_at` inclusive (`ERR_SESSION_NOT_IN_WINDOW`)"

    Design: Corner/validations/start_outside_window_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    study = create_study(code="OW1")
    moderator = create_moderator(display_name="Mod OW")
    session = create_remote_session(study["id"], "2026-08-10T10:00:00Z",
                                    "2026-08-10T11:00:00Z", seat_capacity=4)
    assign_moderator(session["id"], moderator["id"])
    close_study(study["id"])
    set_clock("2026-08-10T12:00:00Z")  # one hour after the window closed
    resp = api.start_session(session["id"], make_moderator_headers(moderator["id"]))
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_IN_WINDOW)


def test_start_while_recruiting_returns_study_not_closed(api):
    """PRD §3.5: "the study must be in `CLOSED` or `ANALYSIS`
    (`ERR_STUDY_NOT_CLOSED`)"
    PRD §2.9: "`ERR_STUDY_NOT_CLOSED` for a session start while the study is
    outside `CLOSED` and `ANALYSIS`"

    Design: Corner/validations/start_while_recruiting_returns_study_not_closed
    """
    set_clock("2026-08-01T00:00:00Z")
    study = create_study(code="RC1")  # stays RECRUITING
    moderator = create_moderator(display_name="Mod RC")
    session = create_remote_session(study["id"], "2026-08-10T10:00:00Z",
                                    "2026-08-10T11:00:00Z", seat_capacity=4)
    assign_moderator(session["id"], moderator["id"])
    set_clock("2026-08-10T10:30:00Z")
    resp = api.start_session(session["id"], make_moderator_headers(moderator["id"]))
    validate_error(resp, ApiErrorId.ERR_STUDY_NOT_CLOSED)


def test_complete_cancelled_session_returns_invalid_state(api):
    """PRD §3.5: "Cancelling the session outright — `SCHEDULED` → `CANCELLED`,
    available to a `Researcher` or `ResearchOpsAdmin` — cancels every booking
    in `BOOKED`, `PROMOTED`, or `WAITLISTED` with no waitlist promotion and
    zeroes `seats_taken`."
    PRD §3.5: "Completing the session — `IN_PROGRESS` → `COMPLETED`, again the
    assigned moderator only"
    PRD §2.9: "The generic rejection is `ERR_INVALID_STATE`"

    Design: Corner/state_machines/complete_cancelled_session_returns_invalid_state
    """
    study = create_study(code="IV1")
    moderator = create_moderator(display_name="Mod IV1")
    session = create_remote_session(study["id"], "2026-08-10T10:00:00Z",
                                    "2026-08-10T11:00:00Z", seat_capacity=4)
    assign_moderator(session["id"], moderator["id"])
    cancelled = get_success_data(api.cancel_session(session["id"], RESEARCHER))
    assert cancelled["status"] == "CANCELLED"
    resp = api.complete_session(session["id"], make_moderator_headers(moderator["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_session(session["id"])["status"] == "CANCELLED"


def test_session_full_lifecycle_happy_path(api):
    """PRD §3.5: "Starting moves `SCHEDULED` → `IN_PROGRESS`."
    PRD §3.5: "a booking moves `BOOKED` → `ATTENDED` or `PROMOTED` → `ATTENDED`
    via the mark-attended action"
    PRD §3.5: "Completing the session — `IN_PROGRESS` → `COMPLETED`, again the
    assigned moderator only"
    PRD §3.5: "`seats_taken` always counts bookings in `BOOKED`, `PROMOTED`,
    `ATTENDED`, or `NO_SHOW`."

    Design: Corner/endpoints/session_full_lifecycle_happy_path
    """
    set_clock("2026-08-01T00:00:00Z")
    study, _nda = setup_study_with_published_nda(code="LC1")
    participant = register_participant(email="lc-p@x.com")
    enroll_participant(study["id"], participant)
    moderator = create_moderator(display_name="Mod LC")
    session = create_remote_session(study["id"], "2026-08-10T10:00:00Z",
                                    "2026-08-10T11:00:00Z", seat_capacity=5)
    assert session["status"] == "SCHEDULED"
    assign_moderator(session["id"], moderator["id"])
    booking = book_session(session["id"], participant["id"])
    assert booking["status"] == "BOOKED"
    close_study(study["id"])
    mod_headers = make_moderator_headers(moderator["id"])
    set_clock("2026-08-10T10:30:00Z")
    started = validate_success(api.start_session(session["id"], mod_headers))
    assert started["status"] == "IN_PROGRESS"
    attended = validate_success(api.mark_booking_attended(booking["id"], mod_headers))
    assert attended["status"] == "ATTENDED"
    completed = validate_success(api.complete_session(session["id"], mod_headers))
    assert completed["status"] == "COMPLETED"
    assert completed["seats_taken"] == 1, (
        "an ATTENDED booking still occupies its seat historically")
