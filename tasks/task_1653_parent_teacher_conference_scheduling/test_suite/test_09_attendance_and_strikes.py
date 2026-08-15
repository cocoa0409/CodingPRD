"""Attendance marking, strike accounting, family restriction, the ops
auto-no-show sweep, and the window attendance report."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_link,
    add_teacher,
    assert_attendance_record,
    assert_booking,
    assert_family,
    book_slot,
    create_booking_payload,
    create_waitlist_entry_payload,
    generate_slots,
    get_success_data,
    guardian_headers,
    list_window_slots,
    open_booking,
    publish_window,
    run_ops,
    scenario_strike_boundary,
    set_clock,
    setup_booked_slot,
    setup_family_with_students,
    setup_in_progress_booking,
    setup_window_at_stage,
    create_window,
    lock_window,
    start_window,
    validate_error,
    validate_success,
)


def test_double_attendance_mark_rejected(api, front_office_headers):
    """PRD 3.8: "`ATTENDED` and `LATE` both move the booking from `CONFIRMED`
    to `COMPLETED` and recompute the family's risk scores. `EXCUSED` moves the
    booking from `CONFIRMED` to `EXCUSED` and recomputes the weighted risk
    score — an excused absence weighs 0.25 — but records no strike. `NO_SHOW`
    moves the booking from `CONFIRMED` to `NO_SHOW` and fires the full strike
    cascade below."
    PRD 2.7: "Whether the target entity's own state permits the transition — a
    slot must be `OPEN` for booking, `BLOCKED` for unblock, an entry `OFFERED`
    for claim, a booking `CONFIRMED` (or `NO_SHOW` for staff reschedule), a
    request `ASSIGNED` for accept or decline; this tier also carries the
    dedicated state rejections `ERR_FAMILY_RESTRICTED`, `ERR_TEACHER_INACTIVE`,
    `ERR_SLOT_NOT_AVAILABLE`, `ERR_NO_ACTIVE_OFFER`, `ERR_WINDOW_GRID_LOCKED`,
    and `ERR_SLOTS_ALREADY_BOOKED` where they apply; otherwise failures yield
    `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/double_attendance_mark_rejected
    """
    ctx = setup_in_progress_booking()
    booking_id = ctx["booking"]["id"]

    marked = validate_success(
        api.mark_attendance(booking_id, {"outcome": "ATTENDED"}, front_office_headers))
    assert marked["status"] == "COMPLETED"

    rejected = api.mark_attendance(booking_id, {"outcome": "NO_SHOW"}, front_office_headers)
    validate_error(rejected, ApiErrorId.ERR_INVALID_STATE, 409)

    records = validate_success(
        api.list_attendance_records(front_office_headers, params={"booking_id": booking_id}))
    assert len(records) == 1
    assert records[0]["outcome"] == "ATTENDED"


def test_attendance_record_has_no_version_field(api, front_office_headers):
    """PRD 2.5: "Two resources deviate from this convention. A
    **StudentTeacherLink** and an **AttendanceRecord** carry only `id` and
    `created_at`; both `updated_at` and `version` are absent from them."
    PRD 3.8: "The mark supplies an `outcome` and an optional `note`, and
    produces an **AttendanceRecord** holding the `booking_id`, the `outcome`,
    the `marked_by_role`, and the `marked_by_user_id` — the caller's
    `X-User-ID`, or the literal string "system" when the ops checkpoint marks
    automatically."

    Design: Corner/entities/attendance_record_has_no_version_field
    """
    ctx = setup_in_progress_booking()
    booking_id = ctx["booking"]["id"]
    validate_success(
        api.mark_attendance(booking_id, {"outcome": "ATTENDED"}, front_office_headers))

    records = validate_success(
        api.list_attendance_records(front_office_headers, params={"booking_id": booking_id}))
    assert len(records) == 1
    record = records[0]
    assert_attendance_record(record)
    assert record["outcome"] == "ATTENDED"
    assert record["marked_by_role"] == "FrontOfficeStaff"
    assert record["marked_by_user_id"] == "test-staff-1"


def test_strike_one_below_threshold_keeps_family_active(api, front_office_headers):
    """PRD 3.8: "After each `NO_SHOW` record — manual or automatic — the strike
    count is recomputed, and when the family is `ACTIVE` and the recomputed
    count has reached the `no_show_strike_threshold` of the window whose
    booking was marked, the family moves from `ACTIVE` to `RESTRICTED`. The
    boundary is exact: a count equal to the threshold restricts, while one
    short of it does not."

    Design: Difficulty/boundary_precision_check/strike_threshold_exact_value_restricts
    """
    ctx = scenario_strike_boundary(threshold=2)
    family_id = ctx["party"]["family"]["id"]

    get_success_data(api.mark_attendance(ctx["b1"]["id"], {"outcome": "NO_SHOW"},
                                         front_office_headers))
    family = validate_success(api.get_family(family_id, front_office_headers))
    assert_family(family)
    assert family["no_show_strike_count"] == 1
    assert family["status"] == "ACTIVE"


def test_strike_at_exact_threshold_restricts_family(api, front_office_headers):
    """PRD 3.8: "After each `NO_SHOW` record — manual or automatic — the strike
    count is recomputed, and when the family is `ACTIVE` and the recomputed
    count has reached the `no_show_strike_threshold` of the window whose
    booking was marked, the family moves from `ACTIVE` to `RESTRICTED`. The
    boundary is exact: a count equal to the threshold restricts, while one
    short of it does not."

    Design: Difficulty/boundary_precision_check/strike_threshold_exact_value_restricts
    """
    ctx = scenario_strike_boundary(threshold=2)
    family_id = ctx["party"]["family"]["id"]

    get_success_data(api.mark_attendance(ctx["b1"]["id"], {"outcome": "NO_SHOW"},
                                         front_office_headers))
    set_clock("2026-10-05T15:50:00Z")
    get_success_data(api.mark_attendance(ctx["b2"]["id"], {"outcome": "NO_SHOW"},
                                         front_office_headers))

    family = validate_success(api.get_family(family_id, front_office_headers))
    assert family["no_show_strike_count"] == 2
    assert family["status"] == "RESTRICTED"


def test_clear_strikes_resets_count_but_not_risk(api, front_office_headers):
    """PRD 3.8: "It moves the family from `RESTRICTED` to `ACTIVE`, adds the
    current `no_show_strike_count` into `strikes_cleared_total` — so the strike
    count recomputes to zero — and increments the family's `version`. The two
    risk scores are deliberately untouched by the clear: they ignore clears and
    keep their historical memory."
    PRD 3.8: "The strict variant, stored as `attendance_risk_strict`, is simply
    the lifetime count of the family's `NO_SHOW` records across every booking
    in every window, weighted at 1.0 each — it ignores strike clears entirely."

    Design: Corner/calculations/clear_strikes_resets_count_but_not_risk
    """
    ctx = setup_booked_slot(window_overrides={"no_show_strike_threshold": 1})
    set_clock("2026-10-02T00:00:00Z")
    lock_window(ctx["window"]["id"])
    start_window(ctx["window"]["id"])
    set_clock("2026-10-05T15:30:00Z")
    get_success_data(api.mark_attendance(ctx["booking"]["id"], {"outcome": "NO_SHOW"},
                                         front_office_headers))
    family_id = ctx["family"]["id"]
    restricted = validate_success(api.get_family(family_id, front_office_headers))
    assert restricted["status"] == "RESTRICTED"
    assert restricted["no_show_strike_count"] == 1

    cleared = validate_success(api.clear_strikes(family_id, front_office_headers))
    assert cleared["status"] == "ACTIVE"
    assert cleared["no_show_strike_count"] == 0

    family = validate_success(api.get_family(family_id, front_office_headers))
    assert family["strikes_cleared_total"] == 1
    # The risk scores keep their historical memory across the clear.
    assert family["attendance_risk_strict"] == pytest.approx(1.00, abs=0.01)
    assert family["attendance_risk_score"] == pytest.approx(1.00, abs=0.01)


def test_restricted_family_blocked_but_staff_bypass(api, front_office_headers,
                                                    school_admin_headers):
    """PRD 3.4: "A guardian caller's family must be `ACTIVE` — a `RESTRICTED`
    family loses self-service booking and waitlist join, and the attempt is
    rejected with `ERR_FAMILY_RESTRICTED`; staff booking on behalf bypass this
    restriction."
    PRD 3.6: "The window must be `BOOKING_OPEN`; a guardian caller joins only
    for their own family and only while that family is `ACTIVE` (otherwise
    `ERR_FAMILY_RESTRICTED`, which staff callers bypass); the student must be
    `ENROLLED` and linked to the teacher per the same rules as booking."

    Design: Corner/validations/restricted_family_blocked_but_staff_bypass
    """
    # Window 1 (strike threshold 1): one NO_SHOW restricts the family.
    ctx = setup_booked_slot(window_overrides={"no_show_strike_threshold": 1})
    family = ctx["family"]
    student = ctx["student"]
    set_clock("2026-10-02T00:00:00Z")
    lock_window(ctx["window"]["id"])
    start_window(ctx["window"]["id"])
    set_clock("2026-10-05T15:30:00Z")
    get_success_data(api.mark_attendance(ctx["booking"]["id"], {"outcome": "NO_SHOW"},
                                         front_office_headers))
    assert validate_success(api.get_family(family["id"], front_office_headers))["status"] == "RESTRICTED"

    # Window 2 opens later; the student is linked to its teacher.
    window2 = create_window(
        name="W2", term_label="2026-SPRING",
        day_windows=[{
            "date": "2026-11-09",
            "start_at": "2026-11-09T15:00:00Z",
            "end_at": "2026-11-09T19:00:00Z",
        }],
        booking_open_at="2026-10-06T00:00:00Z",
        booking_close_at="2026-11-01T00:00:00Z",
        no_show_strike_threshold=3,
    )
    teacher9 = add_teacher(full_name="T9")
    published2 = publish_window(window2["id"])
    generate_slots(window2["id"], published2["version"])
    set_clock("2026-10-06T00:00:00Z")
    open_booking(window2["id"])
    add_link(student["id"], teacher9["id"], is_homeroom=True)
    slot2 = list_window_slots(window2["id"])[0]
    guardian = guardian_headers(family)

    self_book = api.create_booking(
        create_booking_payload(slot2["id"], student["id"], "IN_PERSON"), guardian
    )
    validate_error(self_book, ApiErrorId.ERR_FAMILY_RESTRICTED, 409)

    self_join = api.create_waitlist_entry(
        create_waitlist_entry_payload(window2["id"], student["id"], teacher9["id"], "EITHER"),
        guardian,
    )
    validate_error(self_join, ApiErrorId.ERR_FAMILY_RESTRICTED, 409)

    staff_booking = validate_success(api.create_booking(
        create_booking_payload(slot2["id"], student["id"], "IN_PERSON"), front_office_headers
    ), 201)
    assert_booking(staff_booking)
    assert staff_booking["status"] == "CONFIRMED"


def test_run_ops_auto_no_show_boundary(api, front_office_headers, school_admin_headers):
    """PRD 3.8: "Second, automatic no-show: while the window is `IN_PROGRESS`
    or `COMPLETED`, every `CONFIRMED` booking whose slot end plus the window's
    `auto_no_show_grace_hours` lies at or before the logical clock is marked
    `NO_SHOW` exactly as if marked by hand, with the attendance record's
    `marked_by_role` and `marked_by_user_id` recorded as "system", and the full
    strike cascade — risk recomputation, the `NO_SHOW_FOLLOW_UP` outreach task,
    and possible family restriction — fires for each."
    PRD 3.9: "Two kinds are created by the system — a `NO_SHOW_FOLLOW_UP` task
    whenever a booking is marked `NO_SHOW`, and a `LANGUAGE_ACCESS` task
    whenever an interpreter request goes `UNFILLED` at lock"

    Design: Corner/complexity_layers/run_ops_auto_no_show_boundary
    """
    ctx = setup_in_progress_booking()
    window_id = ctx["window"]["id"]
    booking_id = ctx["booking"]["id"]
    # Slot 0 ends 2026-10-05T15:20Z; with grace 24h the sweep fires at exactly
    # 2026-10-06T15:20Z ("at or before" the clock).
    set_clock("2026-10-06T15:19:00Z")
    first_run = run_ops(window_id)
    assert first_run["ops_run_index"] == 1
    still_confirmed = validate_success(api.get_booking(booking_id, front_office_headers))
    assert still_confirmed["status"] == "CONFIRMED"

    set_clock("2026-10-06T15:20:00Z")
    second_run = run_ops(window_id)
    assert second_run["ops_run_index"] == 2
    marked = validate_success(api.get_booking(booking_id, front_office_headers))
    assert marked["status"] == "NO_SHOW"

    family = validate_success(api.get_family(ctx["family"]["id"], front_office_headers))
    assert family["no_show_strike_count"] == 1

    records = validate_success(
        api.list_attendance_records(front_office_headers, params={"booking_id": booking_id}))
    assert len(records) == 1
    assert records[0]["outcome"] == "NO_SHOW"
    assert records[0]["marked_by_role"] == "system"
    assert records[0]["marked_by_user_id"] == "system"

    tasks = validate_success(api.list_outreach_tasks(
        front_office_headers, params={"family_id": ctx["family"]["id"]}))
    assert len(tasks) == 1
    assert tasks[0]["kind"] == "NO_SHOW_FOLLOW_UP"
    assert tasks[0]["status"] == "OPEN"


def test_attendance_report_rates_and_counts(api, front_office_headers):
    """PRD 3.9: "It echoes the `window_id` and reports per-status booking
    counts — `bookings_confirmed`, `bookings_completed`, `bookings_no_show`,
    `bookings_excused`, `bookings_cancelled`, and `bookings_rescheduled` —
    together with two rates: `attendance_rate_pct` is one hundred times the
    number of `COMPLETED` bookings divided by the sum of `COMPLETED` and
    `NO_SHOW` bookings, rounded half-up to two decimal places, and
    `no_show_rate_pct` substitutes the `NO_SHOW` count in the numerator under
    the same denominator and rounding; when no booking has reached `COMPLETED`
    or `NO_SHOW`, both rates report 0.00. The report closes with
    `open_outreach_tasks`, the count of the window's tasks still in `OPEN` or
    `CONTACTED` status."

    Design: Corner/calculations/attendance_report_rates_and_counts
    """
    ctx = setup_window_at_stage(
        "BOOKING_OPEN", window_overrides={"no_show_strike_threshold": 5}
    )
    teacher_id = ctx["teachers"][0]["id"]
    slots = ctx["teacher_slots"][teacher_id]
    party = setup_family_with_students(ctx, 6, grade_levels=[1, 2, 3, 4, 5, 6])
    bookings = [
        book_slot(slots[i]["id"], party["students"][i]["id"], party["guardian"])
        for i in range(6)
    ]
    # The sixth booking is cancelled before the lock.
    get_success_data(api.cancel_booking(bookings[5]["id"], {}, party["guardian"]))

    set_clock("2026-10-02T00:00:00Z")
    lock_window(ctx["window"]["id"])
    start_window(ctx["window"]["id"])
    set_clock("2026-10-05T16:40:00Z")
    for i, outcome in ((0, "ATTENDED"), (1, "ATTENDED"), (2, "ATTENDED"), (3, "NO_SHOW")):
        get_success_data(api.mark_attendance(bookings[i]["id"], {"outcome": outcome},
                                             front_office_headers))
    set_clock("2026-10-05T17:20:00Z")
    get_success_data(api.mark_attendance(bookings[4]["id"], {"outcome": "EXCUSED"},
                                         front_office_headers))

    report = validate_success(api.get_attendance_report(ctx["window"]["id"],
                                                        front_office_headers))
    assert report["window_id"] == ctx["window"]["id"]
    assert report["bookings_completed"] == 3
    assert report["bookings_no_show"] == 1
    assert report["bookings_excused"] == 1
    assert report["bookings_cancelled"] == 1
    # Denominator is COMPLETED + NO_SHOW == 4; EXCUSED and CANCELLED sit outside.
    assert report["attendance_rate_pct"] == pytest.approx(75.00, abs=0.01)
    assert report["no_show_rate_pct"] == pytest.approx(25.00, abs=0.01)
    assert report["open_outreach_tasks"] == 1
