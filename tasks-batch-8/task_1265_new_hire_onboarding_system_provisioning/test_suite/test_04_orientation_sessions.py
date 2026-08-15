"""Orientation session booking, capacity, overlap, attendance, and cancellation."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    ApiErrorId,
    setup_basic_case,
    setup_case_in_provisioning,
    setup_day_one_ready,
    setup_case_with_booked_session,
    create_orientation_session_payload,
    get_summary,
    make_new_hire_headers,
)

HR = TEST_USERS["hr_admin_headers"]


def test_session_room_overlap_half_open_adjacency(api):
    """PRD §3.6: "Rooms are scarce: a new session conflicts with any non-cancelled
    session in the same `room` whose time interval overlaps it, where each session
    occupies its room from `starts_at` up to but not including `ends_at` — so a
    session beginning exactly when another ends, or ending exactly when another
    begins, does not conflict. A conflicting creation is rejected with
    `ERR_SESSION_ROOM_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/session_room_overlap_half_open_adjacency
    """
    # s1: R1 09:00-12:00
    r1 = api.create_orientation_session(create_orientation_session_payload(
        room="R1",
        starts_at="2026-05-04T09:00:00Z",
        ends_at="2026-05-04T12:00:00Z",
    ), HR)
    validate_success(r1, expected_status=201)

    # s2: R1 12:00-15:00 — starts exactly at s1.ends_at; legal under half-open.
    r2 = api.create_orientation_session(create_orientation_session_payload(
        room="R1",
        starts_at="2026-05-04T12:00:00Z",
        ends_at="2026-05-04T15:00:00Z",
    ), HR)
    validate_success(r2, expected_status=201)

    # s3: R1 11:00-13:00 — strict interior overlap with s1; rejected.
    r3 = api.create_orientation_session(create_orientation_session_payload(
        room="R1",
        starts_at="2026-05-04T11:00:00Z",
        ends_at="2026-05-04T13:00:00Z",
    ), HR)
    validate_error(r3, ApiErrorId.ERR_SESSION_ROOM_OVERLAP)

    # Same window in a different room is legal (overlap is per-room).
    r4 = api.create_orientation_session(create_orientation_session_payload(
        room="R2",
        starts_at="2026-05-04T11:00:00Z",
        ends_at="2026-05-04T13:00:00Z",
    ), HR)
    validate_success(r4, expected_status=201)


def test_session_room_overlap_is_per_room(api):
    """PRD §3.6: "a new session conflicts with any non-cancelled session in the
    same `room` whose time interval overlaps it"

    Identical overlapping window in a different room succeeds.

    Design: Difficulty/resource_temporal_overlap/session_room_overlap_half_open_adjacency
    """
    get_success_data(api.create_orientation_session(create_orientation_session_payload(
        room="R1",
        starts_at="2026-05-04T09:00:00Z",
        ends_at="2026-05-04T12:00:00Z",
    ), HR), )
    r = api.create_orientation_session(create_orientation_session_payload(
        room="R2",
        starts_at="2026-05-04T09:00:00Z",
        ends_at="2026-05-04T12:00:00Z",
    ), HR)
    validate_success(r, expected_status=201)


def test_session_capacity_zero_seat_boundary(api):
    """PRD §3.6: "to have room (a session whose `booked_count` has reached
    `capacity` draws `ERR_SESSION_FULL`)"
    PRD §3.6: "A session begins `SCHEDULED` and becomes `FULL` automatically when
    its `booked_count` reaches `capacity`"

    Design: Difficulty/boundary_precision_check/session_capacity_zero_seat_boundary
    """
    ctx = setup_case_with_booked_session(room="RC6", capacity=1)
    session = ctx["session"]
    assert session["booked_count"] == 1
    assert session["status"] == "FULL"

    # Booking case_a into the FULL session is rejected; booked_count unchanged.
    resp = api.book_orientation(ctx["case_a"]["id"], {"session_id": session["id"]}, HR)
    validate_error(resp, ApiErrorId.ERR_SESSION_FULL)

    s_after = get_success_data(api.list_orientation_sessions(HR, params={"room": "RC6"}))[0]
    assert s_after["booked_count"] == 1
    assert s_after["status"] == "FULL"


def test_session_full_auto_flip_on_booking(api):
    """PRD §3.6: "A session begins `SCHEDULED` and becomes `FULL` automatically
    when its `booked_count` reaches `capacity`"

    The booking that hits capacity flips the session from SCHEDULED to FULL.

    Design: Difficulty/boundary_precision_check/session_capacity_zero_seat_boundary
    """
    ctx = setup_case_in_provisioning()
    session = get_success_data(api.create_orientation_session(create_orientation_session_payload(
        room="RC-auto", capacity=1,
    ), HR))
    assert session["status"] == "SCHEDULED"
    assert session["booked_count"] == 0

    get_success_data(api.book_orientation(ctx["case"]["id"], {"session_id": session["id"]}, HR))
    s = get_success_data(api.list_orientation_sessions(HR, params={"room": "RC-auto"}))[0]
    assert s["booked_count"] == 1
    assert s["status"] == "FULL"


def test_orientation_seat_count_conserved_under_book_cancel(api):
    """PRD §3.6: "a cancellation that drops the count back below `capacity`
    returns it from `FULL` to `SCHEDULED`."
    PRD §3.6: "Cancelling a booking ... decrements the session's `booked_count`
    (returning a `FULL` session to `SCHEDULED`)"

    Design: Difficulty/compensating_invariant/orientation_seat_count_conserved_under_book_cancel
    """
    ctx = setup_case_in_provisioning()
    case_id = ctx["case"]["id"]
    session = get_success_data(api.create_orientation_session(create_orientation_session_payload(
        room="R9", capacity=1,
        starts_at="2026-05-04T13:00:00Z", ends_at="2026-05-04T15:00:00Z",
    ), HR))
    assert session["booked_count"] == 0

    get_success_data(api.book_orientation(case_id, {"session_id": session["id"]}, HR))
    s = get_success_data(api.list_orientation_sessions(HR, params={"room": "R9"}))[0]
    assert s["booked_count"] == 1
    assert s["status"] == "FULL"

    get_success_data(api.cancel_orientation_booking(case_id, HR))
    s = get_success_data(api.list_orientation_sessions(HR, params={"room": "R9"}))[0]
    assert s["booked_count"] == 0
    assert s["status"] == "SCHEDULED"


def test_booked_count_invariant_matches_case_references(api):
    """PRD §3.6: "each session's `booked_count` reports how many cases currently
    reference it through `orientation_session_id` with an `orientation_rsvp` of
    `BOOKED` or `ATTENDED`."

    Invariant holds at every step of the book-then-cancel pair.

    Design: Difficulty/compensating_invariant/orientation_seat_count_conserved_under_book_cancel
    """
    ctx = setup_case_in_provisioning()
    case_id = ctx["case"]["id"]
    session = get_success_data(api.create_orientation_session(create_orientation_session_payload(
        room="R9b", capacity=5,
    ), HR))
    get_success_data(api.book_orientation(case_id, {"session_id": session["id"]}, HR))
    s1 = get_success_data(api.list_orientation_sessions(HR, params={"room": "R9b"}))[0]
    assert s1["booked_count"] == 1

    get_success_data(api.cancel_orientation_booking(case_id, HR))
    s2 = get_success_data(api.list_orientation_sessions(HR, params={"room": "R9b"}))[0]
    assert s2["booked_count"] == 0


def test_day_one_ready_reverts_when_booking_cancelled(api):
    """PRD §3.7: "The case's day-one gate is re-evaluated on every
    provisioning-order mutation and every orientation booking or cancellation:
    the case advances from `PROVISIONING` to `DAY_ONE_READY` when its order is
    `FULFILLED` **and** its `orientation_rsvp` is `BOOKED`, and it falls back
    from `DAY_ONE_READY` to `PROVISIONING` whenever the rsvp ceases to be
    `BOOKED`."

    Design: Corner/state_machines/day_one_ready_reverts_when_booking_cancelled
    """
    ctx = setup_day_one_ready()
    case_id = ctx["case"]["id"]
    assert ctx["case"]["phase"] == "DAY_ONE_READY"

    resp = api.cancel_orientation_booking(case_id, HR)
    data = validate_success(resp)
    assert data["phase"] == "PROVISIONING"
    assert data["orientation_rsvp"] == "NONE"


def test_booking_phase_state_beats_session_full_constraint(api):
    """PRD §2.6: "6. **State gates.** The target entity must be in a state that
    permits the operation ... 9. **Constraint satisfaction.** The dual-role ban,
    the orientation room-overlap rule, the check-in thirty-minute buffer,
    session capacity, the ban on waiving required tasks, the probation extension
    budget, and the optimistic-concurrency version match are enforced here."
    PRD §2.6: "when several problems are present at once, the stage that runs
    first determines which error the caller sees."

    Case A in PRE_BOARDING booking a FULL session: state beats constraint.

    Design: Difficulty/priority_pair_validation_conflict/booking_phase_state_beats_session_full_constraint
    """
    ctx = setup_case_with_booked_session(room="RC5", capacity=1)
    # case_a is still PRE_BOARDING (required tasks untouched in setup_case_with_booked_session? No — we cleared).
    # Build a fresh PRE_BOARDING case to exercise the phase gate.
    from test_helpers import create_new_hire, create_case
    nh_x = create_new_hire()
    case_x = create_case(ctx["manager"], ctx["buddy"], nh_x, ctx["profile"])
    resp = api.book_orientation(case_x["id"], {"session_id": ctx["session"]["id"]}, HR)
    validate_error(resp, ApiErrorId.ERR_INVALID_CASE_PHASE)


def test_booking_into_full_session_when_phase_allows_yields_session_full(api):
    """PRD §3.6: "a session whose `booked_count` has reached `capacity` draws
    `ERR_SESSION_FULL`"

    When the phase gate passes (PROVISIONING) but the session is FULL,
    ERR_SESSION_FULL is the surviving error.

    Design: Difficulty/priority_pair_validation_conflict/booking_phase_state_beats_session_full_constraint
    """
    ctx = setup_case_with_booked_session(room="RC5b", capacity=1)
    # case_a was cleared through to PROVISIONING in setup_case_with_booked_session.
    resp = api.book_orientation(ctx["case_a"]["id"], {"session_id": ctx["session"]["id"]}, HR)
    validate_error(resp, ApiErrorId.ERR_SESSION_FULL)


def test_cancel_without_booking_and_double_booking_rejected(api):
    """PRD §3.6: "Cancelling a booking requires the case's `orientation_rsvp` to
    be `BOOKED` (otherwise `ERR_NO_BOOKING_TO_CANCEL`)."
    PRD §3.6: "the case must not already hold a booking: an `orientation_rsvp`
    of anything other than `NONE` or `SESSION_CANCELLED` draws
    `ERR_ALREADY_BOOKED`."

    Design: Corner/state_machines/cancel_without_booking_and_double_booking_rejected
    """
    ctx = setup_case_in_provisioning()
    case_id = ctx["case"]["id"]
    session = get_success_data(api.create_orientation_session(create_orientation_session_payload(
        room="R16", starts_at="2026-05-04T13:00:00Z", ends_at="2026-05-04T15:00:00Z", capacity=5,
    ), HR))

    # Cancel with rsvp NONE -> ERR_NO_BOOKING_TO_CANCEL.
    resp = api.cancel_orientation_booking(case_id, HR)
    validate_error(resp, ApiErrorId.ERR_NO_BOOKING_TO_CANCEL)

    # Book once, then attempt a second booking -> ERR_ALREADY_BOOKED.
    get_success_data(api.book_orientation(case_id, {"session_id": session["id"]}, HR))
    resp2 = api.book_orientation(case_id, {"session_id": session["id"]}, HR)
    validate_error(resp2, ApiErrorId.ERR_ALREADY_BOOKED)


def test_book_cancelled_session_rejected(api):
    """PRD §3.6: "requires the session to be bookable (a `CANCELLED` or
    `CONDUCTED` session draws `ERR_SESSION_NOT_BOOKABLE`)"

    Design: Corner/state_machines/book_cancelled_session_rejected
    """
    ctx = setup_case_in_provisioning()
    case_id = ctx["case"]["id"]
    session = get_success_data(api.create_orientation_session(create_orientation_session_payload(
        room="R17", starts_at="2026-05-04T13:00:00Z", ends_at="2026-05-04T15:00:00Z", capacity=5,
    ), HR))
    get_success_data(api.cancel_orientation_session(session["id"], HR))
    resp = api.book_orientation(case_id, {"session_id": session["id"]}, HR)
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_BOOKABLE)


def test_attendance_marks_rsvp_attended(api):
    """PRD §3.6: "an `HRAdmin` records attendance by supplying the `case_id` and
    an `attended` flag: a true value marks the case `ATTENDED`, a false value
    marks it `NO_SHOW`"
    PRD §3.6: "each session's `booked_count` reports how many cases currently
    reference it through `orientation_session_id` with an `orientation_rsvp` of
    `BOOKED` or `ATTENDED`."

    Design: Corner/endpoints/attendance_marks_rsvp_attended
    """
    ctx = setup_day_one_ready()
    case_id = ctx["case"]["id"]
    session = ctx["session"]
    resp = api.mark_attendance(session["id"], {"case_id": case_id, "attended": True}, HR)
    data = validate_success(resp)
    assert data["orientation_rsvp"] == "ATTENDED"
    # ATTENDED still counts toward occupancy.
    s = get_success_data(api.list_orientation_sessions(HR, params={"room": session["room"]}))[0]
    assert s["booked_count"] == 1


def test_orientation_no_show_applies_health_penalty(api):
    """PRD §3.6: "when the logical clock reaches a session's `ends_at`, the
    session — whether `SCHEDULED` or `FULL` — becomes `CONDUCTED`, and every
    case still merely `BOOKED` on it (never marked as having attended) is swept
    to `NO_SHOW`, recomputing each affected case's health with the 30-point
    no-show penalty."

    Design: Corner/state_machines/orientation_no_show_applies_health_penalty
    """
    ctx = setup_day_one_ready()
    case_id = ctx["case"]["id"]
    session = ctx["session"]
    # Move past session end (12:00 -> 13:00) without marking attendance.
    get_success_data(api.set_current_utc({"to_iso8601": "2026-05-04T13:00:00Z"}, HR))
    case = get_success_data(api.get_onboarding_case(case_id, HR))
    assert case["orientation_rsvp"] == "NO_SHOW"
    s = get_success_data(api.list_orientation_sessions(HR, params={"room": session["room"]}))[0]
    assert s["status"] == "CONDUCTED"
    summary = get_summary(case_id)
    assert summary["health_score"] == 70


def test_newhire_books_own_orientation(api):
    """PRD §3.6: "Booking a case into a session — allowed for an `HRAdmin`, or
    for the `NewHire` who owns the case (`ERR_NOT_RESOURCE_OWNER` otherwise)"

    Design: Corner/rbac/newhire_books_own_orientation
    """
    ctx = setup_case_in_provisioning()
    case_id = ctx["case"]["id"]
    session = get_success_data(api.create_orientation_session(create_orientation_session_payload(
        room="R1-own",
    ), HR))
    nh = make_new_hire_headers(ctx["new_hire"]["id"])
    resp = api.book_orientation(case_id, {"session_id": session["id"]}, nh)
    data = validate_success(resp)
    assert data["orientation_rsvp"] == "BOOKED"
