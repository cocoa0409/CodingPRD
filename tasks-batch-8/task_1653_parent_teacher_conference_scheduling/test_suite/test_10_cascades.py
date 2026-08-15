"""Cross-entity cascades: no-show restriction, teacher deactivation, student
withdrawal, and the window lock sweep."""
from test_helpers import (
    ApiErrorId,
    add_family,
    add_link,
    add_student,
    assert_booking,
    assert_interpreter_request,
    assert_outreach_task,
    assert_time_slot,
    assert_waitlist_entry,
    book_slot,
    create_waitlist_entry_payload,
    get_success_data,
    guardian_headers,
    lock_window,
    read_window,
    request_for_booking,
    scenario_no_show_cascade,
    scenario_teacher_deactivation,
    set_clock,
    setup_family_with_students,
    setup_window_at_stage,
    validate_error,
    validate_success,
)


def test_no_show_restriction_flips_family_at_threshold(api, front_office_headers):
    """PRD 3.8: "After each `NO_SHOW` record — manual or automatic — the strike
    count is recomputed, and when the family is `ACTIVE` and the recomputed
    count has reached the `no_show_strike_threshold` of the window whose
    booking was marked, the family moves from `ACTIVE` to `RESTRICTED`. The
    boundary is exact: a count equal to the threshold restricts, while one
    short of it does not."
    PRD 3.8: "`NO_SHOW` moves the booking from `CONFIRMED` to `NO_SHOW` and
    fires the full strike cascade below."

    Design: Difficulty/transitive_cascade/no_show_restriction_cascade_depth5
    """
    ctx = scenario_no_show_cascade(threshold=2)
    family_id = ctx["party"]["family"]["id"]

    marked = validate_success(api.mark_attendance(ctx["b2"]["id"], {"outcome": "NO_SHOW"},
                                                  front_office_headers))
    assert_booking(marked)
    assert marked["status"] == "NO_SHOW"

    family = validate_success(api.get_family(family_id, front_office_headers))
    assert family["no_show_strike_count"] == 2
    assert family["status"] == "RESTRICTED"


def test_no_show_restriction_cascades_to_future_booking(api, front_office_headers,
                                                        school_admin_headers):
    """PRD 3.8: "Restriction cascades immediately. Every `CONFIRMED` booking of
    the family in any window whose slot starts after the logical clock is
    cancelled with `cancel_reason` set to `FAMILY_RESTRICTED`, and each freed
    slot moves from `BOOKED` to `OPEN`, with the promotion sweep run per slot
    when the window is `BOOKING_OPEN` and the slot simply opening otherwise.
    Interpreter requests in `REQUESTED` or `ASSIGNED` status on those bookings
    move to `CANCELLED`, with `ASSIGNED` ones returning their `assigned_minutes`
    to the interpreter's `committed_minutes`."
    PRD 3.9: "Two kinds are created by the system — a `NO_SHOW_FOLLOW_UP` task
    whenever a booking is marked `NO_SHOW`, and a `LANGUAGE_ACCESS` task
    whenever an interpreter request goes `UNFILLED` at lock"

    Design: Difficulty/transitive_cascade/no_show_restriction_cascade_depth5
    """
    ctx = scenario_no_show_cascade(threshold=2)
    family_id = ctx["party"]["family"]["id"]

    get_success_data(api.mark_attendance(ctx["b2"]["id"], {"outcome": "NO_SHOW"},
                                         front_office_headers))

    # b3's slot starts 15:50, after the 15:46 clock: it is a future booking.
    b3 = validate_success(api.get_booking(ctx["b3"]["id"], front_office_headers))
    assert b3["status"] == "CANCELLED"
    assert b3["cancel_reason"] == "FAMILY_RESTRICTED"

    request3 = validate_success(
        api.get_interpreter_request(ctx["request3"]["id"], front_office_headers))
    assert_interpreter_request(request3)
    assert request3["status"] == "CANCELLED"

    # The window is IN_PROGRESS, so the freed slot simply opens (no promotion).
    slot = validate_success(api.get_slot(ctx["slots"][2]["id"], school_admin_headers))
    assert_time_slot(slot)
    assert slot["status"] == "OPEN"

    tasks = validate_success(api.list_outreach_tasks(
        front_office_headers, params={"family_id": family_id}))
    assert len(tasks) == 2
    for task in tasks:
        assert_outreach_task(task)
        assert task["kind"] == "NO_SHOW_FOLLOW_UP"
        assert task["status"] == "OPEN"


def test_teacher_deactivation_cancels_bookings_and_retires_slots(api, school_admin_headers):
    """PRD 3.3: "Every slot of that teacher in a window still in `PUBLISHED` or
    `BOOKING_OPEN` whose status is `OPEN` or `BLOCKED` moves to `RETIRED`.
    Every `CONFIRMED` booking on that teacher's slots in those windows is
    cancelled with `cancel_reason` set to `TEACHER_INACTIVE`, and the freed
    slots move to `RETIRED` rather than reopening — those seats are gone for
    good."
    PRD 2.8: "These counters are recomputed by every operation that can change
    them — slot generation, blocking and unblocking, booking creation,
    cancellation, rescheduling, waitlist promotion, claims, declines,
    withdrawals, the window lock, and the deactivation, restriction, and
    withdrawal cascades — so a read of the window always reflects the current
    state of its children."

    Design: Difficulty/transitive_cascade/teacher_deactivation_cascade_depth4
    """
    ctx = scenario_teacher_deactivation()
    get_success_data(api.patch_teacher(ctx["teacher"]["id"], {"status": "INACTIVE"},
                                       school_admin_headers))

    booking_c = validate_success(api.get_booking(ctx["booking_c"]["id"], school_admin_headers))
    assert booking_c["status"] == "CANCELLED"
    assert booking_c["cancel_reason"] == "TEACHER_INACTIVE"

    booking_d = validate_success(api.get_booking(ctx["booking_d"]["id"], school_admin_headers))
    assert booking_d["status"] == "CANCELLED"

    # The booked slot retires with its booking and never reopens.
    slot0 = validate_success(api.get_slot(ctx["booking_c"]["slot_id"], school_admin_headers))
    assert slot0["status"] == "RETIRED"

    window = read_window(ctx["window"]["id"])
    assert window["slots_total_count"] == 0
    assert window["slots_booked_count"] == 0


def test_teacher_deactivation_releases_minutes_and_withdraws_entries(api, school_admin_headers,
                                                                     front_office_headers):
    """PRD 3.3: "Interpreter requests in `REQUESTED` or `ASSIGNED` status on
    the cancelled bookings move to `CANCELLED`, and each cancellation of an
    `ASSIGNED` request subtracts its `assigned_minutes` from the interpreter's
    `committed_minutes`. Waitlist entries in `WAITING` or `OFFERED` status for
    that teacher move to `WITHDRAWN`, and an entry that was holding a slot
    releases it — the `HELD` slot moves to `RETIRED`, not back to `OPEN`."

    Design: Difficulty/transitive_cascade/teacher_deactivation_cascade_depth4
    """
    ctx = scenario_teacher_deactivation()
    get_success_data(api.patch_teacher(ctx["teacher"]["id"], {"status": "INACTIVE"},
                                       school_admin_headers))

    request = validate_success(
        api.get_interpreter_request(ctx["request_c"]["id"], front_office_headers))
    assert request["status"] == "CANCELLED"

    interpreter = validate_success(
        api.get_interpreter(ctx["interpreter"]["id"], front_office_headers))
    assert interpreter["committed_minutes"] == 0

    entry = validate_success(api.get_waitlist_entry(ctx["entry_e"]["id"], front_office_headers))
    assert_waitlist_entry(entry)
    assert entry["status"] == "WITHDRAWN"


def test_student_withdraw_cascade(api, front_office_headers, school_admin_headers):
    """PRD 3.3: "Withdrawing a student moves them from `ENROLLED` to
    `WITHDRAWN` — a terminal state — and cascades: every `CONFIRMED` booking of
    the student whose slot starts after the logical clock is cancelled with
    `cancel_reason` set to `STUDENT_WITHDRAWN`, each freed slot moves from
    `BOOKED` to `OPEN`, running the waitlist promotion sweep when the window is
    `BOOKING_OPEN` and simply opening otherwise; interpreter requests in
    `REQUESTED` or `ASSIGNED` status on those bookings move to `CANCELLED` with
    the usual committed-minutes decrement for `ASSIGNED` ones; and the
    student's waitlist entries in `WAITING` or `OFFERED` status move to
    `WITHDRAWN`, with an offered entry releasing its `HELD` slot back to `OPEN`
    and re-running promotion."

    Design: Corner/state_machines/student_withdraw_cascade
    """
    ctx = setup_window_at_stage("BOOKING_OPEN", teacher_specs=[{}, {}])
    t1, t2 = ctx["teachers"]
    family = add_family(preferred_language="es")
    st1 = add_student(family["id"], full_name="S1", grade_level=3)
    st2 = add_student(family["id"], full_name="S2", grade_level=4)
    # st1 is homeroom-linked to T1 (booking); st2 to T2 (waitlist entry).
    add_link(st1["id"], t1["id"], is_homeroom=True)
    add_link(st2["id"], t2["id"], is_homeroom=True)
    guardian = guardian_headers(family)

    slot_t1 = ctx["teacher_slots"][t1["id"]][0]
    booking = book_slot(slot_t1["id"], st1["id"], guardian, interpreter_language="es")
    request = request_for_booking(booking["id"])
    entry = get_success_data(api.create_waitlist_entry(
        create_waitlist_entry_payload(ctx["window"]["id"], st2["id"], t2["id"], "EITHER"),
        guardian,
    ))

    withdrawn1 = validate_success(api.withdraw_student(st1["id"], front_office_headers))
    withdrawn2 = validate_success(api.withdraw_student(st2["id"], front_office_headers))
    assert withdrawn1["enrollment_status"] == "WITHDRAWN"
    assert withdrawn2["enrollment_status"] == "WITHDRAWN"

    booking_after = validate_success(api.get_booking(booking["id"], front_office_headers))
    assert booking_after["status"] == "CANCELLED"
    assert booking_after["cancel_reason"] == "STUDENT_WITHDRAWN"

    slot_after = validate_success(api.get_slot(slot_t1["id"], school_admin_headers))
    assert slot_after["status"] == "OPEN"

    request_after = validate_success(
        api.get_interpreter_request(request["id"], front_office_headers))
    assert request_after["status"] == "CANCELLED"

    entry_after = validate_success(api.get_waitlist_entry(entry["id"], front_office_headers))
    assert entry_after["status"] == "WITHDRAWN"


def test_lock_expires_waitlist_and_unfills_requests(api, school_admin_headers,
                                                    front_office_headers):
    """PRD 3.8: "The lock is a housekeeping sweep: interpreter requests still
    `REQUESTED` move to `UNFILLED` with the language-access outreach described
    in §3.7; waitlist entries still `WAITING` or `OFFERED` move to `EXPIRED`,
    with offered entries releasing their `HELD` slots back to `OPEN` and no
    further promotion after lock; the window's counters are recomputed; and the
    window's `version` increments."
    PRD 3.7: "If the window locks while a request is still `REQUESTED`, the
    request moves to `UNFILLED`, and the system opens an outreach task of kind
    `LANGUAGE_ACCESS` for the family so the front office can follow up."

    Design: Corner/state_machines/lock_expires_waitlist_and_unfills_requests
    """
    ctx = setup_window_at_stage("BOOKING_OPEN")
    teacher_id = ctx["teachers"][0]["id"]
    slots = ctx["teacher_slots"][teacher_id]

    first = setup_family_with_students(
        ctx, 2, family_overrides={"preferred_language": "es"}, grade_levels=[3, 4]
    )
    booking_with_request = book_slot(slots[0]["id"], first["students"][0]["id"],
                                     first["guardian"], interpreter_language="es")
    booking_plain = book_slot(slots[1]["id"], first["students"][1]["id"], first["guardian"])
    request = request_for_booking(booking_with_request["id"])

    second = setup_family_with_students(ctx, 1, grade_levels=[4])
    entry_offered = get_success_data(api.create_waitlist_entry(
        create_waitlist_entry_payload(ctx["window"]["id"], second["students"][0]["id"],
                                      teacher_id, "EITHER"),
        second["guardian"],
    ))
    third = setup_family_with_students(ctx, 1, grade_levels=[5])
    entry_waiting = get_success_data(api.create_waitlist_entry(
        create_waitlist_entry_payload(ctx["window"]["id"], third["students"][0]["id"],
                                      teacher_id, "EITHER"),
        third["guardian"],
    ))

    # Freeing slot 1 promotes the earlier-created entry onto it.
    get_success_data(api.cancel_booking(booking_plain["id"], {}, first["guardian"]))
    offered = validate_success(api.get_waitlist_entry(entry_offered["id"], front_office_headers))
    assert offered["status"] == "OFFERED"
    assert offered["offered_slot_id"] == slots[1]["id"]

    set_clock("2026-10-02T00:00:00Z")
    lock_window(ctx["window"]["id"])

    offered_after = validate_success(
        api.get_waitlist_entry(entry_offered["id"], front_office_headers))
    assert offered_after["status"] == "EXPIRED"
    waiting_after = validate_success(
        api.get_waitlist_entry(entry_waiting["id"], front_office_headers))
    assert waiting_after["status"] == "EXPIRED"

    slot_after = validate_success(api.get_slot(slots[1]["id"], school_admin_headers))
    assert slot_after["status"] == "OPEN"

    request_after = validate_success(
        api.get_interpreter_request(request["id"], front_office_headers))
    assert request_after["status"] == "UNFILLED"

    tasks = validate_success(api.list_outreach_tasks(
        front_office_headers,
        params={"family_id": first["family"]["id"], "kind": "LANGUAGE_ACCESS"},
    ))
    assert len(tasks) == 1
    assert tasks[0]["status"] == "OPEN"
