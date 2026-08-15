"""Booking cancellation and rescheduling: idempotency, cutoff gates,
window-state precedence, successor creation, OCC, and counter conservation."""
from test_helpers import (
    ApiErrorId,
    add_link,
    assert_booking,
    assert_interpreter_request,
    assert_window_counters,
    book_slot,
    get_success_data,
    guardian_headers,
    lock_window,
    read_window,
    request_for_booking,
    scenario_locked_cancel,
    set_clock,
    setup_booked_slot,
    setup_family_with_students,
    setup_window_at_stage,
    start_window,
    validate_error,
    validate_success,
)


def test_cancel_already_cancelled_booking_rejected(api):
    """PRD 3.5: "Cancellation moves a booking from `CONFIRMED` to `CANCELLED`."
    PRD 2.7: "Whether the target entity's own state permits the transition — a
    slot must be `OPEN` for booking, `BLOCKED` for unblock, an entry `OFFERED`
    for claim, a booking `CONFIRMED` (or `NO_SHOW` for staff reschedule), a
    request `ASSIGNED` for accept or decline; this tier also carries the
    dedicated state rejections `ERR_FAMILY_RESTRICTED`, `ERR_TEACHER_INACTIVE`,
    `ERR_SLOT_NOT_AVAILABLE`, `ERR_NO_ACTIVE_OFFER`, `ERR_WINDOW_GRID_LOCKED`,
    and `ERR_SLOTS_ALREADY_BOOKED` where they apply; otherwise failures yield
    `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/cancel_already_cancelled_booking_rejected
    """
    ctx = setup_booked_slot()
    first = validate_success(api.cancel_booking(ctx["booking"]["id"], {}, ctx["guardian"]))
    assert first["status"] == "CANCELLED"

    response = api.cancel_booking(ctx["booking"]["id"], {}, ctx["guardian"])
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)


def test_cancel_within_cutoff_rejected_staff_bypass(api, front_office_headers):
    """PRD 3.5: "A `FamilyGuardian` caller must own the booking's family
    (otherwise `ERR_FORBIDDEN`) and may cancel only while the logical clock is
    no later than `cancel_cutoff_hours` hours before the slot's `start_at` —
    once that cutoff instant has passed, the family attempt is rejected with
    `ERR_CANCELLATION_CUTOFF`. Staff callers bypass the cutoff entirely."

    Design: Corner/validations/cancel_within_cutoff_rejected_staff_bypass
    """
    ctx = setup_booked_slot()
    # Slot 0 starts 2026-10-05T15:00Z; the 24-hour cutoff is 2026-10-04T15:00Z.
    set_clock("2026-10-04T16:00:00Z")

    rejected = api.cancel_booking(ctx["booking"]["id"], {}, ctx["guardian"])
    validate_error(rejected, ApiErrorId.ERR_CANCELLATION_CUTOFF, 422)

    staff = validate_success(
        api.cancel_booking(ctx["booking"]["id"], {}, front_office_headers)
    )
    assert staff["status"] == "CANCELLED"


def test_cancel_in_locked_window_reports_state_not_cutoff(api):
    """PRD 2.7: "When several checks could reject the same request, the server
    evaluates them in a fixed order so that the surfaced error is
    deterministic:"
    PRD 2.7: "Whether the window's `status` permits the operation at all —
    booking, cancellation, rescheduling, and waitlist join need `BOOKING_OPEN`;
    publish needs `DRAFT`; opening booking needs `PUBLISHED`; locking needs
    `BOOKING_OPEN`; starting needs `LOCKED`; completing needs `IN_PROGRESS`;
    archiving needs `COMPLETED`; slot generation needs `PUBLISHED`; slot block
    and unblock need `PUBLISHED` or `BOOKING_OPEN`; attendance marking needs
    `IN_PROGRESS` or `COMPLETED`; failures yield `ERR_INVALID_WINDOW_STATE`
    (409)."
    PRD 3.5: "Cancellation moves a booking from `CONFIRMED` to `CANCELLED`. The
    window must be `BOOKING_OPEN` (otherwise `ERR_INVALID_WINDOW_STATE`)."

    Design: Difficulty/priority_pair_validation_conflict/cancel_locked_window_state_beats_cutoff_temporal
    """
    ctx = scenario_locked_cancel()
    # The clock (2026-10-04T16:00Z) is also past the family cancel cutoff, but
    # the window-state gate is evaluated first under the fixed order.
    response = api.cancel_booking(ctx["booking"]["id"], {}, ctx["guardian"])
    validate_error(response, ApiErrorId.ERR_INVALID_WINDOW_STATE, 409)

    booking = validate_success(api.get_booking(ctx["booking"]["id"], ctx["guardian"]))
    assert booking["status"] == "CONFIRMED"


def test_cancel_in_in_progress_window_rejected_for_family(api):
    """PRD 3.5: "Cancellation moves a booking from `CONFIRMED` to `CANCELLED`.
    The window must be `BOOKING_OPEN` (otherwise `ERR_INVALID_WINDOW_STATE`)."

    Design: Difficulty/priority_pair_validation_conflict/cancel_locked_window_state_beats_cutoff_temporal
    """
    ctx = setup_booked_slot()
    set_clock("2026-10-02T00:00:00Z")
    lock_window(ctx["window"]["id"])
    start_window(ctx["window"]["id"])
    set_clock("2026-10-05T15:30:00Z")

    response = api.cancel_booking(ctx["booking"]["id"], {}, ctx["guardian"])
    validate_error(response, ApiErrorId.ERR_INVALID_WINDOW_STATE, 409)
    booking = validate_success(api.get_booking(ctx["booking"]["id"], ctx["guardian"]))
    assert booking["status"] == "CONFIRMED"


def test_reschedule_creates_linked_successor(api, front_office_headers):
    """PRD 3.5: "A successful reschedule writes the old booking to
    `RESCHEDULED` with `cancel_reason` set to `RESCHEDULED` and increments the
    old booking's `version`; the old slot moves from `BOOKED` to `OPEN` and
    runs the promotion sweep. In the same operation a successor booking is
    created in `CONFIRMED` status with `version` 1 and its
    `rescheduled_from_booking_id` pointing at the old booking, while the new
    slot moves from `OPEN` to `BOOKED`. Any open interpreter request on the old
    booking moves to `CANCELLED`, and when the old booking carried a non-null
    `interpreter_language`, a fresh interpreter request in `REQUESTED` status
    is auto-created for the successor."
    PRD 3.4: "The booking list may be filtered by `window_id`, `family_id`,
    `student_id`, `teacher_id`, `slot_id`, `rescheduled_from_booking_id`, and
    `status`."

    Design: Corner/endpoints/reschedule_creates_linked_successor
    """
    ctx = setup_booked_slot(interpreter_language="es")
    teacher_id = ctx["teachers"][0]["id"]
    old_slot = ctx["slot"]
    new_slot = ctx["teacher_slots"][teacher_id][3]
    old_booking = ctx["booking"]
    old_request = request_for_booking(old_booking["id"])

    successor = validate_success(api.reschedule_booking(
        old_booking["id"],
        {"new_slot_id": new_slot["id"],
         "expected_booking_version": old_booking["version"],
         "channel": "IN_PERSON"},
        ctx["guardian"],
    ))
    assert_booking(successor)
    assert successor["id"] != old_booking["id"]
    assert successor["status"] == "CONFIRMED"
    assert successor["version"] == 1
    assert successor["rescheduled_from_booking_id"] == old_booking["id"]

    old_after = validate_success(api.get_booking(old_booking["id"], front_office_headers))
    assert old_after["status"] == "RESCHEDULED"
    assert old_after["cancel_reason"] == "RESCHEDULED"

    successors = validate_success(api.list_bookings(
        front_office_headers, params={"rescheduled_from_booking_id": old_booking["id"]}
    ))
    assert [b["id"] for b in successors] == [successor["id"]]

    slot_old = validate_success(api.get_slot(old_slot["id"], front_office_headers))
    slot_new = validate_success(api.get_slot(new_slot["id"], front_office_headers))
    assert slot_old["status"] == "OPEN"
    assert slot_new["status"] == "BOOKED"

    old_request_after = validate_success(
        api.get_interpreter_request(old_request["id"], front_office_headers)
    )
    assert old_request_after["status"] == "CANCELLED"
    new_request = request_for_booking(successor["id"])
    assert_interpreter_request(new_request)
    assert new_request["status"] == "REQUESTED"
    assert new_request["language"] == "es"


def test_occ_stale_reschedule_rejected(api):
    """PRD 2.6: "Rescheduling a booking requires `expected_booking_version`
    equal to the booking's current `version`. A prior reschedule already
    produces a successor booking and advances the old booking's version, so a
    client holding an older read is acting on a superseded record; the mismatch
    is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/occ_stale_reschedule_rejected
    """
    ctx = setup_booked_slot()
    teacher_id = ctx["teachers"][0]["id"]
    slots = ctx["teacher_slots"][teacher_id]
    old_booking = ctx["booking"]

    successor = validate_success(api.reschedule_booking(
        old_booking["id"],
        {"new_slot_id": slots[3]["id"],
         "expected_booking_version": old_booking["version"]},
        ctx["guardian"],
    ))
    assert successor["status"] == "CONFIRMED"

    # The originally observed version is stale after the first reschedule.
    rejected = api.reschedule_booking(
        old_booking["id"],
        {"new_slot_id": slots[4]["id"],
         "expected_booking_version": old_booking["version"]},
        ctx["guardian"],
    )
    validate_error(rejected, ApiErrorId.ERR_STALE_VERSION, 412)

    survivor = validate_success(api.get_booking(successor["id"], ctx["guardian"]))
    assert survivor["status"] == "CONFIRMED"
    slot4 = validate_success(api.get_slot(slots[4]["id"], ctx["guardian"]))
    assert slot4["status"] == "OPEN"


def test_inactive_teacher_blocks_reschedule_in_progress_window(api, front_office_headers,
                                                               school_admin_headers):
    """PRD 3.5: "A `FamilyGuardian` reschedules only while the window is
    `BOOKING_OPEN` and only while the logical clock is no later than
    `cancel_cutoff_hours` hours before the old slot's start (otherwise
    `ERR_CANCELLATION_CUTOFF`); staff may reschedule while the window is
    `BOOKING_OPEN` and may also reschedule while it is `IN_PROGRESS`."
    PRD 3.5: "The new slot must be `OPEN`, must belong to the same window, and
    must pass the full booking validation battery from §3.4 — link, duplicate,
    caps, family gap, and channel rules all re-run against the new slot."
    PRD 3.4: "The window must be `BOOKING_OPEN` (otherwise
    `ERR_INVALID_WINDOW_STATE`). The slot must be `OPEN` (otherwise
    `ERR_SLOT_NOT_AVAILABLE`), the teacher `ACTIVE` (otherwise
    `ERR_TEACHER_INACTIVE`), and the student `ENROLLED` (otherwise
    `ERR_STUDENT_NOT_BOOKABLE`)."
    PRD 3.3: "Every slot of that teacher in a window still in `PUBLISHED` or
    `BOOKING_OPEN` whose status is `OPEN` or `BLOCKED` moves to `RETIRED`."

    Design: Corner/validations/inactive_teacher_blocks_reschedule_in_progress_window
    """
    ctx = setup_window_at_stage("BOOKING_OPEN", teacher_specs=[{}, {}])
    t1, t2 = ctx["teachers"]
    party = setup_family_with_students(ctx, 1, teacher_id=t1["id"],
                                       link_overrides={"is_homeroom": True})
    add_link(party["students"][0]["id"], t2["id"], is_homeroom=True)
    slot_t1 = ctx["teacher_slots"][t1["id"]][0]
    slot_t2 = ctx["teacher_slots"][t2["id"]][4]
    booking = book_slot(slot_t1["id"], party["students"][0]["id"], party["guardian"])

    set_clock("2026-10-02T00:00:00Z")
    lock_window(ctx["window"]["id"])
    start_window(ctx["window"]["id"])
    set_clock("2026-10-05T15:30:00Z")
    # The deactivation cascade spares this IN_PROGRESS window's slots.
    get_success_data(api.patch_teacher(t2["id"], {"status": "INACTIVE"}, school_admin_headers))

    rejected = api.reschedule_booking(
        booking["id"],
        {"new_slot_id": slot_t2["id"],
         "expected_booking_version": booking["version"],
         "channel": "IN_PERSON"},
        front_office_headers,
    )
    validate_error(rejected, ApiErrorId.ERR_TEACHER_INACTIVE, 409)

    slot_after = validate_success(api.get_slot(slot_t2["id"], school_admin_headers))
    assert slot_after["status"] == "OPEN"


def test_book_moves_slot_and_confirmed_counters(api, school_admin_headers):
    """PRD 2.8: "These counters are recomputed by every operation that can
    change them — slot generation, blocking and unblocking, booking creation,
    cancellation, rescheduling, waitlist promotion, claims, declines,
    withdrawals, the window lock, and the deactivation, restriction, and
    withdrawal cascades — so a read of the window always reflects the current
    state of its children."
    PRD 3.4: "A successful create moves the slot from `OPEN` to `BOOKED`,
    stores the booking in `CONFIRMED` status with `version` 1, and — when
    `interpreter_language` was supplied — automatically creates an interpreter
    request in `REQUESTED` status for the booking."

    Design: Difficulty/compensating_invariant/slot_booked_confirmed_pair_conservation
    """
    ctx = setup_window_at_stage("BOOKING_OPEN")
    teacher_id = ctx["teachers"][0]["id"]
    party = setup_family_with_students(ctx, 1)
    slot = ctx["teacher_slots"][teacher_id][0]

    before = read_window(ctx["window"]["id"])
    assert_window_counters(before, total=8, open_=8, booked=0, confirmed=0)

    booking = book_slot(slot["id"], party["students"][0]["id"], party["guardian"])
    assert booking["status"] == "CONFIRMED"

    after = read_window(ctx["window"]["id"])
    assert_window_counters(after, total=8, open_=7, booked=1, confirmed=1)
    assert after["slots_booked_count"] == after["bookings_confirmed_count"]


def test_cancel_restores_slot_and_confirmed_counters(api, school_admin_headers):
    """PRD 3.5: "Cancellation frees the slot from `BOOKED` back to `OPEN`, and
    since the window is `BOOKING_OPEN` the promotion selector runs on it
    immediately."
    PRD 2.8: "These counters are recomputed by every operation that can change
    them — slot generation, blocking and unblocking, booking creation,
    cancellation, rescheduling, waitlist promotion, claims, declines,
    withdrawals, the window lock, and the deactivation, restriction, and
    withdrawal cascades — so a read of the window always reflects the current
    state of its children."

    Design: Difficulty/compensating_invariant/slot_booked_confirmed_pair_conservation
    """
    ctx = setup_booked_slot()
    cancelled = validate_success(
        api.cancel_booking(ctx["booking"]["id"], {}, ctx["guardian"])
    )
    assert cancelled["status"] == "CANCELLED"

    after = read_window(ctx["window"]["id"])
    assert_window_counters(after, total=8, open_=8, booked=0, confirmed=0)
    assert after["slots_booked_count"] == after["bookings_confirmed_count"]
