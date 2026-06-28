"""State-machine corners: precondition enforcement, suspend cascade, invalid
transitions, and terminal-state lockdown.

Queue B — Corner/state_machines.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    set_clock, create_center, create_agreement, create_and_activate_center,
    setup_operating_center_with_subject, setup_active_enrollment,
    setup_active_enrollment_with_worksheet,
    create_family, create_student, create_and_place_enrollment, create_enrollment,
    create_and_open_session, book_seat, create_invoice,
    make_franchise_admin_headers, make_center_director_headers, make_instructor_headers,
)
from test_helpers import api_client as api

ADMIN = make_franchise_admin_headers()
DIRECTOR = make_center_director_headers()
INSTRUCTOR = make_instructor_headers()


def test_center_activate_without_active_agreement_rejected():
    """PRD §3.1: "the center may enter `OPERATING` only when a franchise agreement naming
    that center exists and is in `ACTIVE` status — otherwise the activation is rejected
    with `ERR_AGREEMENT_NOT_ACTIVE`"

    Design: Corner/state_machines/center_activate_without_active_agreement_rejected
    """
    set_clock("2026-05-01T00:00:00Z")
    center = create_center(name="CA0")
    create_agreement(center["id"])  # left PENDING (not activated)
    resp = api.activate_center(center["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value)
    fresh = validate_success(api.get_center(center["id"], ADMIN))
    assert fresh["status"] == "PROVISIONING"


def test_center_suspend_cascade_cancels_sessions_and_attendance():
    """PRD §2.5: "When a `Center` moves from `OPERATING` to `SUSPENDED`, every `Session`
    at that center whose status is `SCHEDULED` or `OPEN` is driven to `CANCELLED` (a
    first-level cascade). For each session so cancelled, every `AttendanceRecord` on it
    whose status is `BOOKED` or `PRESENT` is in turn driven to `CANCELLED`, and that
    session's `booked_seat_count` is recomputed accordingly (a second-level cascade)."

    Design: Corner/state_machines/center_suspend_cascade_cancels_sessions_and_attendance
    """
    center, _subject, _level, _family, _student, en = setup_active_enrollment(
        clock="2026-05-01T08:00:00Z", instructor_ratio_cap=6)
    session = create_and_open_session(center["id"], "2026-05-01T09:00:00Z",
                                      "2026-05-01T10:00:00Z", 6)
    ar = book_seat(session["id"], en["id"])

    suspended = validate_success(api.suspend_center(center["id"], ADMIN))
    assert suspended["status"] == "SUSPENDED"
    sess = validate_success(api.get_session(session["id"], DIRECTOR))
    assert sess["status"] == "CANCELLED"
    assert sess["booked_seat_count"] == 0
    record = validate_success(api.get_attendance_record(ar["id"], DIRECTOR))
    assert record["status"] == "CANCELLED"


def test_invoice_pay_from_draft_invalid_state():
    """PRD §3.7: "Paying an issued invoice moves it from `ISSUED` to `PAID`."
    PRD §2.8: "a resource that is not in a valid originating state for the requested
    transition fails with `ERR_INVALID_STATE` (409)."

    Paying a DRAFT (un-issued) invoice -> ERR_INVALID_STATE; stays DRAFT.

    Design: Corner/state_machines/invoice_pay_from_draft_invalid_state
    """
    center, _ag, subject, _levels = setup_operating_center_with_subject(
        num_levels=1, monthly_tuition_cents=15000, enrollment_fee_cents=5000)
    family = create_family(center["id"])
    student = create_student(family["id"])
    create_and_place_enrollment(center["id"], student["id"], subject["id"])
    inv = create_invoice(family["id"], center["id"], "2026-05")

    resp = api.pay_invoice(inv["id"], {"amount_cents": 20000}, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    fresh = validate_success(api.get_invoice(inv["id"], DIRECTOR))
    assert fresh["status"] == "DRAFT"


def test_worksheet_reassign_from_assigned_invalid_state():
    """PRD §3.4: "A set that reaches `RETRY` can be reassigned by an instructor ... which
    returns it from `RETRY` to `ASSIGNED`"
    PRD §2.8: "a resource that is not in a valid originating state for the requested
    transition fails with `ERR_INVALID_STATE` (409)."

    Reassigning a freshly ASSIGNED (never-graded) worksheet -> ERR_INVALID_STATE.

    Design: Corner/state_machines/worksheet_reassign_from_assigned_invalid_state
    """
    *_rest, ws = setup_active_enrollment_with_worksheet()
    resp = api.reassign_worksheet(ws["id"], INSTRUCTOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    fresh = validate_success(api.get_worksheet(ws["id"], DIRECTOR))
    assert fresh["status"] == "ASSIGNED"


def test_agreement_terminate_blocked_when_center_operating():
    """PRD §3.1: "An agreement may be wound down from `ACTIVE` to `TERMINATED`, but only
    when the center it backs is not currently `OPERATING`; terminating the agreement of an
    operating center is rejected with `ERR_CENTER_OPERATING`"

    Design: Corner/state_machines/agreement_terminate_blocked_when_center_operating
    """
    _center, agreement = create_and_activate_center(clock="2026-05-01T00:00:00Z")
    resp = api.terminate_agreement(agreement["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_CENTER_OPERATING.value)
    fresh = validate_success(api.get_agreement(agreement["id"], ADMIN))
    assert fresh["status"] == "ACTIVE"


def test_session_close_before_start_rejected():
    """PRD §3.5: "A director closes a session from `OPEN` to `CLOSED`, permitted only
    once the logical clock has reached or passed the session's `start_at` (otherwise
    `ERR_SESSION_NOT_STARTED`)"

    Clock at 08:00, session starts 09:00 -> close rejected; stays OPEN.

    Design: Corner/state_machines/session_close_before_start_rejected
    """
    center, _ag = create_and_activate_center(clock="2026-05-01T08:00:00Z", instructor_ratio_cap=6)
    session = create_and_open_session(center["id"], "2026-05-01T09:00:00Z",
                                      "2026-05-01T10:00:00Z", 6)
    resp = api.close_session(session["id"], DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_STARTED.value)
    fresh = validate_success(api.get_session(session["id"], DIRECTOR))
    assert fresh["status"] == "OPEN"


def test_checkin_when_session_not_open_rejected():
    """PRD §3.5: "Checking in moves a record from `BOOKED` to `PRESENT` and sets
    `marked_at` to the current clock, permitted only while the parent session is `OPEN`
    (otherwise `ERR_SESSION_NOT_OPEN`)"

    A BOOKED record on a still-SCHEDULED session cannot check in -> ERR_SESSION_NOT_OPEN.

    Design: Corner/state_machines/checkin_when_session_not_open_rejected
    """
    center, _subject, _level, _family, _student, en = setup_active_enrollment(
        clock="2026-05-01T08:00:00Z", instructor_ratio_cap=6)
    # SCHEDULED (not opened) session; booking is allowed on SCHEDULED.
    from test_helpers import create_session
    session = create_session(center["id"], "2026-05-01T09:00:00Z",
                            "2026-05-01T10:00:00Z", 6)
    ar = book_seat(session["id"], en["id"])
    resp = api.check_in_attendance(ar["id"], INSTRUCTOR)
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_OPEN.value)
    fresh = validate_success(api.get_attendance_record(ar["id"], DIRECTOR))
    assert fresh["status"] == "BOOKED"


def test_enrollment_withdraw_terminal_then_pause_invalid_state():
    """PRD §3.3: "or withdraw an enrollment from `ACTIVE`, `PAUSED`, or
    `PLACEMENT_PENDING` to the terminal `WITHDRAWN`."
    PRD §2.8: "a resource that is not in a valid originating state for the requested
    transition fails with `ERR_INVALID_STATE` (409)."

    Pausing a WITHDRAWN (terminal) enrollment -> ERR_INVALID_STATE.

    Design: Corner/state_machines/enrollment_withdraw_terminal_then_pause_invalid_state
    """
    center, _subject, _level, _family, _student, en = setup_active_enrollment()
    validate_success(api.withdraw_enrollment(en["id"], DIRECTOR))
    resp = api.pause_enrollment(en["id"], DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    fresh = validate_success(api.get_enrollment(en["id"], DIRECTOR))
    assert fresh["status"] == "WITHDRAWN"
