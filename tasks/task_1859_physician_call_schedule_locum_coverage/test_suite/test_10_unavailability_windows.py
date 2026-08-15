"""Unavailability windows: closed-interval overlap, approval cascade, and the
no-restoration guarantee of window cancellation."""
from test_helpers import (
    ApiErrorId,
    approve_window,
    assert_unavailability_window,
    assign_staff,
    create_published_program,
    create_staff_physician,
    create_window,
    create_window_payload,
    get_program,
    get_slot_for_date,
    list_gaps,
    make_physician_headers,
    serve_assignment,
    set_clock,
    setup_published_with_assignment,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_create_window_end_before_start_returns_invalid_request(api):
    """PRD §3.2: "the request carries `physician_id`, `start_date`, and
    `end_date` as a closed date interval — an end before the start is
    `ERR_INVALID_REQUEST`".

    Design: Corner/validations/create_window_end_before_start_returns_invalid_request
    """
    physician = create_staff_physician("Dr A")
    resp = api.create_window(
        create_window_payload(
            physician["id"], start_date="2026-09-10", end_date="2026-09-05"
        ),
        make_physician_headers(physician["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


# ─── Closed-interval overlap boundary ────────────────────────────────

def _setup_approved_window_a():
    """P1 with an APPROVED window covering 2026-09-05..2026-09-10 (closed)."""
    physician = create_staff_physician("Dr Alvarez")
    window_a = create_window(
        physician["id"], start_date="2026-09-05", end_date="2026-09-10"
    )
    approve_window(window_a["id"])
    return physician


def test_unavailability_window_touching_closed_endpoint_rejected(api):
    """PRD §3.2: "First, no other APPROVED window of the same physician may
    overlap the requested closed interval — because the intervals are closed,
    windows that touch on a single date overlap, and such a request is rejected
    with `ERR_WINDOW_OVERLAP`."

    Window B 2026-09-10..2026-09-12 shares only the closed endpoint 2026-09-10
    with the approved window.

    Design: Difficulty/resource_temporal_overlap/unavailability_window_closed_interval_touching_conflict
    """
    physician = _setup_approved_window_a()
    window_b = create_window(
        physician["id"], start_date="2026-09-10", end_date="2026-09-12", kind="CME"
    )
    resp = api.approve_window(window_b["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP, 409)
    after = validate_success(api.get_window(window_b["id"], ADMIN))
    assert after["status"] == "REQUESTED"


def test_unavailability_window_first_disjoint_date_approved(api):
    """PRD §2.6: "Unavailability windows are closed date intervals: both
    `start_date` and `end_date` count as covered days, and two windows that
    touch on a single shared date overlap."

    Window C 2026-09-11..2026-09-13 starts on the first date after the approved
    closed window, so it does not overlap and is approved.

    Design: Difficulty/resource_temporal_overlap/unavailability_window_closed_interval_touching_conflict
    """
    physician = _setup_approved_window_a()
    window_c = create_window(
        physician["id"], start_date="2026-09-11", end_date="2026-09-13",
        kind="PERSONAL",
    )
    resp = api.approve_window(window_c["id"], ADMIN)
    approved = validate_success(resp, 200)
    assert_unavailability_window(approved)
    assert approved["status"] == "APPROVED"


# ─── Approval cascade ────────────────────────────────────────────────

def _setup_approval_cascade():
    """PUBLISHED 3-weekday program; P1 assigned to the 2026-09-09 slot and
    holding a REQUESTED window 2026-09-09..2026-09-10."""
    program = create_published_program(
        name="Cards Cascade", period_start="2026-09-08", period_end="2026-09-10"
    )
    physician = create_staff_physician("Dr Alvarez")
    slot = get_slot_for_date(program["id"], "2026-09-09")
    assignment = assign_staff(slot["id"], physician["id"])
    window = create_window(
        physician["id"], start_date="2026-09-09", end_date="2026-09-10"
    )
    return program, physician, slot, assignment, window


def test_unavailability_approval_cancels_assignment_and_reopens_slot(api):
    """PRD §3.2: "When approval succeeds it cascades: every SCHEDULED assignment
    of the physician whose slot date falls inside the closed window is
    CANCELLED; each cancellation reopens its slot from ASSIGNED to OPEN, opens
    a CoverageGap with `reason` ASSIGNMENT_CANCELLED, releases the assignment's
    projected pay from the reserve, and cancels any non-terminal swap
    referencing the cancelled assignment."

    Design: Difficulty/transitive_cascade/unavailability_approval_cancellation_cascade
    """
    program, _physician, slot, assignment, window = _setup_approval_cascade()
    resp = api.approve_window(window["id"], ADMIN)
    approved = validate_success(resp, 200)
    assert approved["status"] == "APPROVED"

    assignment_after = validate_success(api.get_assignment(assignment["id"], ADMIN))
    assert assignment_after["status"] == "CANCELLED"

    slot_after = validate_success(api.get_slot(slot["id"], ADMIN))
    assert slot_after["status"] == "OPEN"


def test_unavailability_approval_opens_gap_and_releases_reserve(api):
    """PRD §3.2: "each cancellation ... opens a CoverageGap with `reason`
    ASSIGNMENT_CANCELLED, releases the assignment's projected pay from the
    reserve".

    The reserve goes from 50000 (the 09-09 assignment's projection) back to 0.

    Design: Difficulty/transitive_cascade/unavailability_approval_cancellation_cascade
    """
    program, _physician, slot, _assignment, window = _setup_approval_cascade()
    assert get_program(program["id"])["payroll_reserved_cents"] == 50000
    approve_window(window["id"])

    cancel_gaps = [
        g for g in list_gaps(program["id"], slot_id=slot["id"])
        if g["reason"] == "ASSIGNMENT_CANCELLED"
    ]
    assert len(cancel_gaps) == 1
    assert cancel_gaps[0]["status"] == "OPEN"
    assert cancel_gaps[0]["resolved_by_assignment_id"] is None

    assert get_program(program["id"])["payroll_reserved_cents"] == 0


# ─── Window cancellation semantics ───────────────────────────────────

def test_window_cancel_after_approval_does_not_restore_assignments(api):
    """PRD §3.2: "Cancellation has no side effects; in particular, cancelling an
    APPROVED window does not restore the assignments its approval cancelled."

    Design: Corner/state_machines/window_cancel_after_approval_does_not_restore_assignments
    """
    program, physician, slot, assignment = setup_published_with_assignment()
    window = create_window(
        physician["id"], start_date="2026-09-08", end_date="2026-09-08", kind="CME"
    )
    assert window["status"] == "REQUESTED"
    approve_window(window["id"])

    cancelled_assignment = validate_success(api.get_assignment(assignment["id"], ADMIN))
    assert cancelled_assignment["status"] == "CANCELLED"

    resp = api.cancel_window(window["id"], make_physician_headers(physician["id"]))
    cancelled_window = validate_success(resp, 200)
    assert cancelled_window["status"] == "CANCELLED"

    assignment_after = validate_success(api.get_assignment(assignment["id"], ADMIN))
    assert assignment_after["status"] == "CANCELLED", "no automatic restoration"
    open_gaps = [
        g for g in list_gaps(program["id"], slot_id=slot["id"]) if g["status"] == "OPEN"
    ]
    assert len(open_gaps) == 1, "the gap stays OPEN after the window cancel"


def test_cancel_cancelled_window_returns_not_cancellable(api):
    """PRD §3.2: "Cancellation moves a REQUESTED or APPROVED window to CANCELLED
    — any other phase is `ERR_WINDOW_NOT_CANCELLABLE`".

    Design: Corner/errors/cancel_cancelled_window_returns_not_cancellable
    """
    physician = create_staff_physician("Dr A")
    window = create_window(
        physician["id"], start_date="2026-09-05", end_date="2026-09-06"
    )
    resp = api.cancel_window(window["id"], make_physician_headers(physician["id"]))
    validate_success(resp, 200)

    resp = api.cancel_window(window["id"], make_physician_headers(physician["id"]))
    validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_CANCELLABLE, 409)


def test_window_approve_covering_served_assignment_rejected(api):
    """PRD §3.2: "Second, no ACTIVATED or SERVED assignment of the physician may
    have its slot date inside the window — activated or served calls cannot be
    retroactively uncovered — and such a request is
    `ERR_WINDOW_COVERS_SERVED_ASSIGNMENT`."

    Design: Corner/validations/window_approve_covering_served_assignment_rejected
    """
    program = create_published_program(
        period_start="2026-09-08", period_end="2026-09-10"
    )
    physician = create_staff_physician("Dr A")
    slot = get_slot_for_date(program["id"], "2026-09-09")
    assignment = assign_staff(slot["id"], physician["id"])
    set_clock("2026-09-10T08:00:00Z")  # window ended 2026-09-10T07:00:00Z
    serve_assignment(assignment["id"])

    window = create_window(
        physician["id"], start_date="2026-09-09", end_date="2026-09-10"
    )
    resp = api.approve_window(window["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_WINDOW_COVERS_SERVED_ASSIGNMENT, 409)

    window_after = validate_success(api.get_window(window["id"], ADMIN))
    assert window_after["status"] == "REQUESTED"
    assignment_after = validate_success(api.get_assignment(assignment["id"], ADMIN))
    assert assignment_after["status"] == "SERVED"
