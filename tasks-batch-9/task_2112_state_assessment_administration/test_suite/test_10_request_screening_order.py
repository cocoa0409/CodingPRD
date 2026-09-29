"""The order in which a request is screened, and the transitions that a
resource's own status forbids."""
from test_helpers import (
    ApiErrorId,
    TEST_CALENDAR,
    add_proctor,
    create_district_payload,
    create_proctor_assignment_payload,
    create_registration_payload,
    create_session,
    create_transition_payload,
    make_officer_headers,
    make_proctor_headers,
    make_school_coordinator_headers,
    move_session,
    read_registration,
    read_session,
    read_window,
    register_student,
    set_clock,
    setup_active_session_at_capacity,
    setup_program,
    setup_program_with_certified_proctor,
    setup_staffed_session,
    setup_two_windows_one_affidavit,
    sign_affidavit,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"


# ─── State check (8) outranks the seat-capacity check (23) ────────────────

def test_registration_into_an_open_room_reports_the_state_error(api):
    """PRD §3.4: "Registrations may only be added to a session whose `status` is
    `DRAFT` or `SCHEDULED`; a session that has already opened, closed, been
    cancelled, or been invalidated rejects them with
    `ERR_SESSION_NOT_ACCEPTING_REGISTRATIONS`."
    PRD §2.7: "Checks are evaluated in strictly ascending order and **the first
    check that fails determines both the `error_id` and the HTTP status**; no
    later check may mask an earlier one."
    PRD §2.7: "23. **Seat capacity after applying the request.** Failure:
    `ERR_SESSION_CAPACITY_EXCEEDED` (422)."

    Design: Difficulty/priority_pair_validation_conflict/session_state_error_outranks_seat_capacity_error
    """
    ctx = setup_active_session_at_capacity()
    assert ctx["session"]["status"] == "ACTIVE"
    assert ctx["session"]["seats_consumed"] == 1
    assert ctx["session"]["effective_seat_capacity"] == 1, (
        "the single declared seat is already taken, so the capacity gate would "
        "also fire on this request")

    response = api.create_registration(
        create_registration_payload(ctx["session"]["id"],
                                    student_state_id="S00000002", grade=10,
                                    guardian_email="g2@fam.example"),
        make_school_coordinator_headers(ctx["school"]["id"]))

    error = validate_error(
        response, ApiErrorId.ERR_SESSION_NOT_ACCEPTING_REGISTRATIONS.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_SESSION_CAPACITY_EXCEEDED.value, (
        "the earlier state check must not be masked by the seat-capacity check")


def test_the_refused_registration_leaves_the_room_exactly_as_it_was(api):
    """PRD §3.4: "After applying the request, `seats_consumed` may not exceed
    `effective_seat_capacity`; if it would, the whole request is rejected with
    `ERR_SESSION_CAPACITY_EXCEEDED` and nothing is written."
    PRD §3.4: "Registrations may only be added to a session whose `status` is
    `DRAFT` or `SCHEDULED`; a session that has already opened, closed, been
    cancelled, or been invalidated rejects them with
    `ERR_SESSION_NOT_ACCEPTING_REGISTRATIONS`."

    Design: Difficulty/priority_pair_validation_conflict/session_state_error_outranks_seat_capacity_error
    """
    ctx = setup_active_session_at_capacity()

    response = api.create_registration(
        create_registration_payload(ctx["session"]["id"],
                                    student_state_id="S00000002", grade=10,
                                    guardian_email="g2@fam.example"),
        make_school_coordinator_headers(ctx["school"]["id"]))
    validate_error(response,
                   ApiErrorId.ERR_SESSION_NOT_ACCEPTING_REGISTRATIONS.value, 409)

    untouched = read_session(ctx["session"]["id"])
    assert untouched["seats_consumed"] == 1
    assert untouched["effective_seat_capacity"] == 1
    assert untouched["status"] == "ACTIVE"

    data, meta = validate_paginated(api.list_registrations(
        make_officer_headers(), params={"session_id": ctx["session"]["id"]}))
    assert meta["total_count"] == 1, "no seat may be written by the refused request"


# ─── Affidavit presence (11) outranks proctor availability (18) ───────────

def test_assignment_without_the_window_affidavit_reports_the_affidavit_error(api):
    """PRD §3.3: "An affidavit with `status` `ACTIVE` must exist for the pairing
    of that proctor and the session's window, failing with
    `ERR_AFFIDAVIT_MISSING`."
    PRD §2.7: "11. **Affidavit presence.** Failure: `ERR_AFFIDAVIT_MISSING`
    (422)."
    PRD §2.7: "18. **Proctor availability conflict.** Failure:
    `ERR_PROCTOR_TIME_CONFLICT` (409)."
    PRD §2.7: "Checks are evaluated in strictly ascending order and **the first
    check that fails determines both the `error_id` and the HTTP status**; no
    later check may mask an earlier one."

    Design: Difficulty/priority_pair_validation_conflict/missing_affidavit_outranks_proctor_time_conflict
    """
    ctx = setup_two_windows_one_affidavit()

    response = api.assign_proctor(
        ctx["session_b"]["id"],
        create_proctor_assignment_payload(ctx["proctor"]["id"],
                                          ctx["session_b"]["version"]),
        make_school_coordinator_headers(ctx["school"]["id"]))

    error = validate_error(response, ApiErrorId.ERR_AFFIDAVIT_MISSING.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_PROCTOR_TIME_CONFLICT.value, (
        "the affidavit check is screened before the availability check")
    assert read_session(ctx["session_b"]["id"])["proctor_id"] is None


def test_the_same_assignment_reports_the_time_conflict_once_signed(api):
    """PRD §3.3: "The assignment conflicts exactly when the proposed start is at
    or before the existing end and the existing start is at or before the
    proposed end — so two sessions that merely touch, where one begins at the
    very instant the other ends, do conflict."
    PRD §3.3: "A collision is `ERR_PROCTOR_TIME_CONFLICT`."
    PRD §3.3: "An affidavit with `status` `ACTIVE` must exist for the pairing of
    that proctor and the session's window, failing with
    `ERR_AFFIDAVIT_MISSING`."

    Design: Difficulty/priority_pair_validation_conflict/missing_affidavit_outranks_proctor_time_conflict
    """
    ctx = setup_two_windows_one_affidavit()
    sign_affidavit(ctx["proctor"]["id"], ctx["window_two"]["id"])

    response = api.assign_proctor(
        ctx["session_b"]["id"],
        create_proctor_assignment_payload(ctx["proctor"]["id"],
                                          ctx["session_b"]["version"]),
        make_school_coordinator_headers(ctx["school"]["id"]))
    validate_error(response, ApiErrorId.ERR_PROCTOR_TIME_CONFLICT.value, 409)

    assert read_session(ctx["session_b"]["id"])["proctor_id"] is None
    assert read_session(ctx["session_a"]["id"])["proctor_id"] == \
        ctx["proctor"]["id"]


# ─── The first three screening layers ─────────────────────────────────────

def test_a_request_without_the_two_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request to the API, without exception, must carry two
    headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`,
    declaring the capacity in which that principal is acting. If either header
    is missing, empty, or if `X-User-Role` names something outside the
    recognized set, the request is rejected with `ERR_UNAUTHENTICATED`."
    PRD §2.7: "1. **Authentication** — both headers present and non-empty, and
    `X-User-Role` naming one of the four roles. Failure: `ERR_UNAUTHENTICATED`
    (401)."

    Design: Corner/validations/request_missing_auth_headers_returns_unauthenticated
    """
    set_clock(TEST_CALENDAR["CLOCK_SETUP"])

    response = api.create_district({"name": "Northgate District"},
                                   {"Content-Type": "application/json"})

    error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value, (
        "authentication is screened before body well-formedness")

    data, meta = validate_paginated(api.list_schools(make_officer_headers()))
    assert meta["total_count"] == 0


def test_role_authorization_is_screened_before_path_resolution(api):
    """PRD §2.7: "2. **Role authorization**, including sub-operation ownership
    on the three multiplexing endpoints described in §2.1. Failure:
    `ERR_ROLE_NOT_PERMITTED` (403)."
    PRD §2.7: "3. **Path resolution**, left to right, per §2.6. Failure: the
    matching not-found error (404)."
    PRD §2.7: "Checks are evaluated in strictly ascending order and **the first
    check that fails determines both the `error_id` and the HTTP status**; no
    later check may mask an earlier one."

    Design: Corner/validations/role_check_returns_forbidden_before_path_existence_is_evaluated
    """
    ctx = setup_program(district_code="NG-1022", school_code="IW-01",
                        max_concurrent_seats=40, open_the_window=False,
                        ship_a_lot=False)
    proctor = add_proctor(ctx["school"]["id"])

    response = api.transition_test_window(
        UNKNOWN_ID, create_transition_payload("OPEN"),
        make_proctor_headers(proctor["id"]))

    error = validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
    assert error["error_id"] != ApiErrorId.ERR_TEST_WINDOW_NOT_FOUND.value, (
        "the role check is screened before the path is resolved")


def test_advancing_the_window_before_its_clock_gate_is_refused(api):
    """PRD §3.2: "**`OPEN → MAKEUP`** closes the initial period and opens the
    make-up period. It requires that the logical clock have reached or passed
    `window_end`, failing with `ERR_TIMING_PRECONDITION_NOT_MET` otherwise, and
    that no session in the window is still `ACTIVE`."
    PRD §2.7: "19. **Logical-clock gates on transitions.** Failure:
    `ERR_TIMING_PRECONDITION_NOT_MET` (422)."

    Design: Corner/validations/window_phase_advance_before_its_clock_gate_is_rejected
    """
    ctx = setup_program(district_code="NG-1026", school_code="NT-01",
                        lot_code="LOT-X8", seal_start=4300,
                        max_concurrent_seats=40)
    set_clock("2026-09-10T08:00:00Z")

    response = api.transition_test_window(
        ctx["window"]["id"], create_transition_payload("MAKEUP"),
        make_officer_headers())
    validate_error(response, ApiErrorId.ERR_TIMING_PRECONDITION_NOT_MET.value, 422)

    assert read_window(ctx["window"]["id"])["status"] == "OPEN"


def test_a_repeated_district_code_is_refused(api):
    """PRD §3.1: "District codes are unique across the entire program; a repeat
    is rejected with `ERR_DUPLICATE_CODE`."
    PRD §2.7: "21. **Code uniqueness.** Failure: `ERR_DUPLICATE_CODE` (409)."

    Design: Corner/validations/duplicate_district_code_is_rejected
    """
    set_clock(TEST_CALENDAR["CLOCK_SETUP"])
    validate_success(api.create_district(
        create_district_payload(district_code="NG-1027"), make_officer_headers()),
        expected_status=201)

    response = api.create_district(
        create_district_payload(name="Southgate District",
                                district_code="NG-1027"),
        make_officer_headers())
    validate_error(response, ApiErrorId.ERR_DUPLICATE_CODE.value, 409)

    accepted = validate_success(api.create_district(
        create_district_payload(name="Southgate District",
                                district_code="NG-1028"),
        make_officer_headers()), expected_status=201)
    assert accepted["district_code"] == "NG-1028"


# ─── Transitions a session's own status forbids ───────────────────────────

def test_closing_a_draft_session_is_an_undeclared_edge(api):
    """PRD §3.6: "**`ACTIVE → CLOSED`** is likewise the proctor's act and
    requires that the floor be genuinely clear."
    PRD §2.7: "**The target resource's own status** permits the operation.
    Failure: `ERR_SESSION_NOT_ACCEPTING_REGISTRATIONS`,
    `ERR_LOT_NOT_AWAITING_RECONCILIATION`, `ERR_SCORE_NOT_RELEASED`, or
    `ERR_INVALID_STATE_TRANSITION`, each with HTTP 409."
    PRD §2.7: "Likewise, a session's own status gate (check 8) precedes the
    window-phase gate (check 9), so attempting a transition that the session's
    current state does not offer reports `ERR_INVALID_STATE_TRANSITION` rather
    than `ERR_WINDOW_PHASE_INVALID`, even when the window is in the wrong phase
    as well."

    Design: Corner/state_machines/closing_a_draft_session_is_an_undeclared_edge
    """
    ctx = setup_program_with_certified_proctor(
        district_code="NG-1010", school_code="VH-01", lot_code="LOT-Z6",
        seal_start=2700)
    built = setup_staffed_session(ctx, room_code="R101", seat_capacity=20,
                                  students=[], schedule=False)
    session = built["session"]

    response = api.transition_session(
        session["id"], create_transition_payload("CLOSED"),
        make_proctor_headers(ctx["proctor"]["id"]))
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

    unchanged = read_session(session["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["proctor_id"] == ctx["proctor"]["id"]
    assert unchanged["closed_at"] is None


def test_a_cancelled_session_accepts_no_further_transition(api):
    """PRD §3.6: "`CANCELLED` and `INVALIDATED` are terminal for a session."
    PRD §3.6: "Both `DRAFT → CANCELLED` and `SCHEDULED → CANCELLED` behave
    identically: the `status` becomes `CANCELLED`, every registration on the
    session whose `attendance_status` is still `PENDING` moves
    `PENDING → WITHDRAWN`, the session then recomputes `seats_consumed`,
    `separate_setting_count`, and `effective_seat_capacity` over the surviving
    roster, and the session's `version` increments."

    Design: Corner/state_machines/cancelled_session_is_locked_against_further_transitions
    """
    ctx = setup_program(district_code="NG-1011", school_code="WH-01",
                        lot_code="LOT-Z7", seal_start=2800)
    session = create_session(ctx["window"]["id"], ctx["school"]["id"],
                             room_code="R101", seat_capacity=20)
    registration = register_student(session["id"], ctx["school"]["id"],
                                    student_state_id="S00000001")
    move_session(session["id"], "CANCELLED", school_id=ctx["school"]["id"])

    response = api.transition_session(
        session["id"], create_transition_payload("SCHEDULED"),
        make_school_coordinator_headers(ctx["school"]["id"]))
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

    locked = read_session(session["id"])
    assert locked["status"] == "CANCELLED"
    assert locked["seats_consumed"] == 0
    assert read_registration(registration["id"])["attendance_status"] == "WITHDRAWN"


def test_reverting_an_open_window_cancels_its_sessions_and_withdraws_seats(api):
    """PRD §3.2: "**`OPEN → PLANNED`** is the escape hatch for an administrative
    mistake, and it is destructive. It is permitted only while no session in the
    window has reached `ACTIVE`, `CLOSED`, or `INVALIDATED` — once a single room
    has opened, the mistake can no longer be quietly unwound."
    PRD §3.2: "When it is permitted, the revert propagates in three hops: every
    session in the window sitting in `DRAFT` or `SCHEDULED` moves to
    `CANCELLED`; every registration on those newly cancelled sessions whose
    `attendance_status` is still `PENDING` moves to `WITHDRAWN`; and each
    affected session then recomputes its `seats_consumed`, its
    `separate_setting_count`, and its `effective_seat_capacity` against the
    reduced roster."

    Design: Corner/state_machines/window_revert_from_open_to_planned_cancels_draft_sessions_and_withdraws_seats
    """
    ctx = setup_program(district_code="NG-1013", school_code="ZH-01",
                        lot_code="LOT-Y1", seal_start=3100)
    session = create_session(ctx["window"]["id"], ctx["school"]["id"],
                             room_code="R101", seat_capacity=20)
    first = register_student(session["id"], ctx["school"]["id"],
                             student_state_id="S00000001")
    second = register_student(session["id"], ctx["school"]["id"],
                              student_state_id="S00000002",
                              guardian_email="g2@fam.example")

    reverted = validate_success(api.transition_test_window(
        ctx["window"]["id"],
        create_transition_payload("PLANNED",
                                  reason="Calendar published in error."),
        make_officer_headers()))
    assert reverted["status"] == "PLANNED"

    cancelled = read_session(session["id"])
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["seats_consumed"] == 0
    assert read_registration(first["id"])["attendance_status"] == "WITHDRAWN"
    assert read_registration(second["id"])["attendance_status"] == "WITHDRAWN"
