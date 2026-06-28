"""Cross-entity state guards (place needs OPERATING center; grade needs ACTIVE
enrollment), temporal overlap (enrollment double-book half-open; instructor buffered
double-book), and compensating invariants (void refunds wallet; cancel restores seat).

Queue A — Difficulty/cross_entity_state_dependency, Difficulty/resource_temporal_overlap,
Difficulty/compensating_invariant.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_operating_center_with_subject, setup_active_enrollment_with_worksheet,
    create_family, create_student, create_enrollment, create_and_place_enrollment,
    create_session, create_and_open_session, book_seat, adjust_wallet,
    create_and_issue_invoice, create_invoice, make_franchise_admin_headers,
    make_center_director_headers, make_instructor_headers,
)
from test_helpers import api_client as api

ADMIN = make_franchise_admin_headers()
DIRECTOR = make_center_director_headers()
INSTRUCTOR = make_instructor_headers()


# ===========================================================================
# enrollment_place_blocked_when_center_not_operating
# ===========================================================================
def test_place_rejected_when_center_suspended():
    """PRD §3.3: "Placement may proceed only when the enrollment's center is
    `OPERATING` (otherwise `ERR_CENTER_NOT_OPERATING`)"

    A PLACEMENT_PENDING enrollment whose center has been suspended cannot be placed ->
    ERR_CENTER_NOT_OPERATING.

    Design: Difficulty/cross_entity_state_dependency/enrollment_place_blocked_when_center_not_operating
    """
    center, _ag, subject, _levels = setup_operating_center_with_subject(num_levels=1)
    family = create_family(center["id"])
    student = create_student(family["id"])
    en = create_enrollment(center["id"], student["id"], subject["id"], diagnostic_raw_score=50)
    validate_success(api.suspend_center(center["id"], ADMIN))

    resp = api.place_enrollment(en["id"], {"placement_policy": "STRICT"}, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_CENTER_NOT_OPERATING.value)


def test_place_rejected_leaves_enrollment_placement_pending():
    """PRD §3.3: "Placement is the act of running the diagnostic and activating the
    enrollment, transitioning it from `PLACEMENT_PENDING` to `ACTIVE`."
    PRD §3.3: "Placement may proceed only when the enrollment's center is `OPERATING`
    (otherwise `ERR_CENTER_NOT_OPERATING`)"

    The rejected placement leaves the enrollment in PLACEMENT_PENDING.

    Design: Difficulty/cross_entity_state_dependency/enrollment_place_blocked_when_center_not_operating
    """
    center, _ag, subject, _levels = setup_operating_center_with_subject(num_levels=1)
    family = create_family(center["id"])
    student = create_student(family["id"])
    en = create_enrollment(center["id"], student["id"], subject["id"], diagnostic_raw_score=50)
    validate_success(api.suspend_center(center["id"], ADMIN))

    api.place_enrollment(en["id"], {"placement_policy": "STRICT"}, DIRECTOR)
    fresh = validate_success(api.get_enrollment(en["id"], DIRECTOR))
    assert fresh["status"] == "PLACEMENT_PENDING"


# ===========================================================================
# worksheet_grade_blocked_when_enrollment_not_active
# ===========================================================================
def test_grade_rejected_when_enrollment_paused():
    """PRD §3.4: "An instructor grades an assigned set by supplying a `score`; this is
    allowed only when the parent enrollment is `ACTIVE` (otherwise
    `ERR_ENROLLMENT_NOT_ACTIVE`)"

    Pausing the parent enrollment then grading -> ERR_ENROLLMENT_NOT_ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/worksheet_grade_blocked_when_enrollment_not_active
    """
    _c, _s, _l, _f, _st, enrollment, ws = setup_active_enrollment_with_worksheet()
    validate_success(api.pause_enrollment(enrollment["id"], DIRECTOR))

    resp = api.grade_worksheet(ws["id"], {"score": 90}, INSTRUCTOR)
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE.value)


def test_grade_rejected_leaves_worksheet_assigned():
    """PRD §3.4: "this is allowed only when the parent enrollment is `ACTIVE` (otherwise
    `ERR_ENROLLMENT_NOT_ACTIVE`)"
    PRD §3.4: "Grading records the `score`, increments `attempt_count` by one, moves the
    set from `ASSIGNED` to `GRADED`"

    The rejected grade leaves the worksheet ASSIGNED (un-graded).

    Design: Difficulty/cross_entity_state_dependency/worksheet_grade_blocked_when_enrollment_not_active
    """
    _c, _s, _l, _f, _st, enrollment, ws = setup_active_enrollment_with_worksheet()
    validate_success(api.pause_enrollment(enrollment["id"], DIRECTOR))

    api.grade_worksheet(ws["id"], {"score": 90}, INSTRUCTOR)
    fresh = validate_success(api.get_worksheet(ws["id"], DIRECTOR))
    assert fresh["status"] == "ASSIGNED"


# ===========================================================================
# enrollment_double_book_half_open_overlap_rejected_touching_allowed
# ===========================================================================
def _center_one_enrollment_three_sessions():
    """OPERATING center + one ACTIVE enrollment + three OPEN sessions: S1 09:00-10:00,
    S2 09:30-10:30 (overlaps S1), S3 10:00-11:00 (touches S1). Each on a distinct
    instructor to avoid the double-book buffer. Returns (en, s1, s2, s3)."""
    from test_helpers import setup_active_enrollment
    center, _subject, _level, _family, _student, en = setup_active_enrollment(
        clock="2026-05-01T08:00:00Z", instructor_ratio_cap=6)
    s1 = create_and_open_session(center["id"], "2026-05-01T09:00:00Z",
                                "2026-05-01T10:00:00Z", 6, instructor_user_id="instr-1")
    s2 = create_and_open_session(center["id"], "2026-05-01T09:30:00Z",
                                "2026-05-01T10:30:00Z", 6, instructor_user_id="instr-2")
    s3 = create_and_open_session(center["id"], "2026-05-01T10:00:00Z",
                                "2026-05-01T11:00:00Z", 6, instructor_user_id="instr-3")
    return en, s1, s2, s3


def test_overlapping_second_booking_rejected_with_session_overlap():
    """PRD §3.5: "A booking is also refused when the same enrollment already holds a
    `BOOKED` or `PRESENT` record at the same center on a session whose time overlaps the
    new one: intervals are half-open `[start_at, end_at)`, so two sessions that merely
    touch (one's `end_at` equal to the other's `start_at`) do not overlap, but any true
    overlap is rejected with `ERR_SESSION_OVERLAP`."

    Already booked on S1 (09:00-10:00); booking S2 (09:30-10:30) truly overlaps ->
    ERR_SESSION_OVERLAP.

    Design: Difficulty/resource_temporal_overlap/enrollment_double_book_half_open_overlap_rejected_touching_allowed
    """
    en, s1, s2, _s3 = _center_one_enrollment_three_sessions()
    book_seat(s1["id"], en["id"])
    s2_fresh = validate_success(api.get_session(s2["id"], DIRECTOR))
    resp = api.create_attendance_record(
        {"session_id": s2["id"], "enrollment_id": en["id"],
         "expected_session_version": s2_fresh["version"]}, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_SESSION_OVERLAP.value)


def test_adjacent_touching_session_booking_accepted():
    """PRD §3.5: "intervals are half-open `[start_at, end_at)`, so two sessions that
    merely touch (one's `end_at` equal to the other's `start_at`) do not overlap"

    Booked on S1 (09:00-10:00); booking S3 (10:00-11:00) which touches at 10:00 is
    accepted -> AttendanceRecord BOOKED.

    Design: Difficulty/resource_temporal_overlap/enrollment_double_book_half_open_overlap_rejected_touching_allowed
    """
    en, s1, _s2, s3 = _center_one_enrollment_three_sessions()
    book_seat(s1["id"], en["id"])
    s3_fresh = validate_success(api.get_session(s3["id"], DIRECTOR))
    ar3 = validate_success(api.create_attendance_record(
        {"session_id": s3["id"], "enrollment_id": en["id"],
         "expected_session_version": s3_fresh["version"]}, DIRECTOR), expected_status=201)
    assert ar3["status"] == "BOOKED", "touching (end==start) booking accepted"


# ===========================================================================
# instructor_double_book_buffered_interval_rejected
# ===========================================================================
def test_instructor_session_within_buffer_rejected():
    """PRD §3.5: "A new session may not be created for the same `instructor_user_id` at
    the same center when the new session's interval, expanded by a thirty-minute buffer
    on each side ... overlaps the unexpanded interval of any existing session staffed by
    that instructor whose status is `SCHEDULED`, `OPEN`, or `CLOSED`"
    PRD §3.5: "two of an instructor's sessions falling within thirty minutes of each
    other count as a conflict; such a collision is rejected with
    `ERR_INSTRUCTOR_DOUBLE_BOOKED`."

    instr-1 has a 09:00-10:00 session; a second 10:15-11:15 session starts within the
    30-min buffer after 10:00 -> ERR_INSTRUCTOR_DOUBLE_BOOKED.

    Design: Difficulty/resource_temporal_overlap/instructor_double_book_buffered_interval_rejected
    """
    from test_helpers import create_and_activate_center
    center, _ag = create_and_activate_center(clock="2026-05-01T08:00:00Z", instructor_ratio_cap=6)
    create_session(center["id"], "2026-05-01T09:00:00Z", "2026-05-01T10:00:00Z", 6,
                  instructor_user_id="instr-1")
    resp = api.create_session(
        {"center_id": center["id"], "instructor_user_id": "instr-1",
         "start_at": "2026-05-01T10:15:00Z", "end_at": "2026-05-01T11:15:00Z", "seat_cap": 6},
        DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_DOUBLE_BOOKED.value)


def test_instructor_session_outside_buffer_accepted():
    """PRD §3.5: "the new session's interval, expanded by a thirty-minute buffer on each
    side — that is, the closed window running from thirty minutes before its `start_at`
    to thirty minutes after its `end_at` — overlaps the unexpanded interval of any
    existing session staffed by that instructor"

    A second instr-1 session 10:45-11:45 begins more than 30 minutes after the first
    ends at 10:00, so the buffered window does not overlap -> session created (201).

    Design: Difficulty/resource_temporal_overlap/instructor_double_book_buffered_interval_rejected
    """
    from test_helpers import create_and_activate_center
    center, _ag = create_and_activate_center(clock="2026-05-01T08:00:00Z", instructor_ratio_cap=6)
    create_session(center["id"], "2026-05-01T09:00:00Z", "2026-05-01T10:00:00Z", 6,
                  instructor_user_id="instr-1")
    resp = api.create_session(
        {"center_id": center["id"], "instructor_user_id": "instr-1",
         "start_at": "2026-05-01T10:45:00Z", "end_at": "2026-05-01T11:45:00Z", "seat_cap": 6},
        DIRECTOR)
    created = validate_success(resp, expected_status=201)
    assert created["status"] == "SCHEDULED"


# ===========================================================================
# invoice_void_after_issue_restores_wallet_credit
# ===========================================================================
def test_void_issued_invoice_refunds_wallet_to_pre_issue_balance():
    """PRD §3.7: "If the invoice had already been issued, voiding refunds its
    `wallet_applied_cents` back to the family's `wallet_credit_cents`, restoring the
    conserved wallet balance the issue had reserved"

    Wallet 3000 is applied at issue (wallet -> 0); voiding the ISSUED invoice refunds
    exactly 3000 (wallet -> 3000).

    Design: Difficulty/compensating_invariant/invoice_void_after_issue_restores_wallet_credit
    """
    center, _ag, subject, _levels = setup_operating_center_with_subject(
        num_levels=1, monthly_tuition_cents=15000, enrollment_fee_cents=5000)
    family = create_family(center["id"])
    student = create_student(family["id"])
    create_and_place_enrollment(center["id"], student["id"], subject["id"])
    adjust_wallet(family["id"], 3000)
    invoice = create_and_issue_invoice(family["id"], center["id"], "2026-05")
    assert invoice["wallet_applied_cents"] == 3000

    voided = validate_success(api.void_invoice(invoice["id"], DIRECTOR))
    assert voided["status"] == "VOID"
    fam = validate_success(api.get_family(family["id"], DIRECTOR))
    assert fam["wallet_credit_cents"] == 3000, \
        f"voiding ISSUED invoice refunds 3000, got {fam['wallet_credit_cents']}"


def test_void_from_draft_makes_no_wallet_change():
    """PRD §3.7: "If the invoice had already been issued, voiding refunds its
    `wallet_applied_cents` back to the family's `wallet_credit_cents`, restoring the
    conserved wallet balance the issue had reserved; a void from `DRAFT` makes no wallet
    change because nothing was reserved."

    Conserved-quantity invariant, other branch: voiding a DRAFT (never-issued) invoice
    leaves the family wallet exactly where it was (3000 unchanged), since the issue step
    that reserves wallet credit never ran.

    Design: Difficulty/compensating_invariant/invoice_void_after_issue_restores_wallet_credit
    """
    center, _ag, subject, _levels = setup_operating_center_with_subject(
        num_levels=1, monthly_tuition_cents=15000, enrollment_fee_cents=5000)
    family = create_family(center["id"])
    student = create_student(family["id"])
    create_and_place_enrollment(center["id"], student["id"], subject["id"])
    adjust_wallet(family["id"], 3000)
    inv = create_invoice(family["id"], center["id"], "2026-05")  # left DRAFT

    voided = validate_success(api.void_invoice(inv["id"], DIRECTOR))
    assert voided["status"] == "VOID"
    assert voided["wallet_applied_cents"] == 0, "no wallet reserved on a DRAFT void"
    fam = validate_success(api.get_family(family["id"], DIRECTOR))
    assert fam["wallet_credit_cents"] == 3000, \
        f"DRAFT void leaves wallet unchanged at 3000, got {fam['wallet_credit_cents']}"


# ===========================================================================
# booking_then_cancel_conserves_session_seat_capacity
# ===========================================================================
def test_cancel_booking_frees_seat_restoring_count():
    """PRD §3.5: "A booking may be cancelled from `BOOKED` to `CANCELLED` by a director
    or the booking parent; cancelling recomputes the session's `booked_seat_count` to
    free the seat and increments the record's `version`."

    Booking takes booked_seat_count 0 -> 1; cancelling it returns booked_seat_count to 0.

    Design: Difficulty/compensating_invariant/booking_then_cancel_conserves_session_seat_capacity
    """
    from test_helpers import setup_active_enrollment
    center, _subject, _level, _family, _student, en = setup_active_enrollment(
        clock="2026-05-01T08:00:00Z", instructor_ratio_cap=6)
    session = create_and_open_session(center["id"], "2026-05-01T09:00:00Z",
                                      "2026-05-01T10:00:00Z", 2)
    ar = book_seat(session["id"], en["id"])
    booked = validate_success(api.get_session(session["id"], DIRECTOR))
    assert booked["booked_seat_count"] == 1

    cancelled = validate_success(api.cancel_attendance(ar["id"], DIRECTOR))
    assert cancelled["status"] == "CANCELLED"
    fresh = validate_success(api.get_session(session["id"], DIRECTOR))
    assert fresh["booked_seat_count"] == 0, \
        f"cancel frees the seat -> booked_seat_count 0, got {fresh['booked_seat_count']}"


def test_cancel_frees_capacity_so_a_new_booking_succeeds_on_full_cap_one_session():
    """PRD §3.5: "A booking is refused when it would push `booked_seat_count` above the
    session's `seat_cap`, in which case it is rejected with `ERR_RATIO_EXCEEDED`."
    PRD §3.5: "cancelling recomputes the session's `booked_seat_count` to free the seat"

    Conserved-quantity invariant via behaviour: a cap=1 session booked to capacity, then
    the booking cancelled, frees the seat so a fresh booking of a second enrollment
    succeeds (the restored capacity is genuinely usable, not merely a recomputed count).

    Design: Difficulty/compensating_invariant/booking_then_cancel_conserves_session_seat_capacity
    """
    from test_helpers import setup_active_enrollment
    center, subject, _level, family, _student, en1 = setup_active_enrollment(
        clock="2026-05-01T08:00:00Z", instructor_ratio_cap=6)
    st2 = create_student(family["id"], full_name="K2", birthdate="2017-01-01T00:00:00Z")
    en2 = create_and_place_enrollment(center["id"], st2["id"], subject["id"])
    session = create_and_open_session(center["id"], "2026-05-01T09:00:00Z",
                                      "2026-05-01T10:00:00Z", 1)
    ar1 = book_seat(session["id"], en1["id"])
    validate_success(api.cancel_attendance(ar1["id"], DIRECTOR))

    sess = validate_success(api.get_session(session["id"], DIRECTOR))
    ar2 = validate_success(api.create_attendance_record(
        {"session_id": session["id"], "enrollment_id": en2["id"],
         "expected_session_version": sess["version"]}, DIRECTOR), expected_status=201)
    assert ar2["status"] == "BOOKED", "freed seat is usable by a new booking"
    final = validate_success(api.get_session(session["id"], DIRECTOR))
    assert final["booked_seat_count"] == 1
