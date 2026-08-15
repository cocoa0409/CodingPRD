"""Appointment book claims: booking gates (enrollment, advisor active, duration,
overlap), the half-open interval rule, the check-in window and its priority
against the state guard, and the scheduled-minutes conservation invariant."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_appointment,
    book_appointment,
    create_advisor,
    create_appointment_payload,
    create_student,
    get_advisor,
    set_logical_clock,
    setup_student_advisor_appointment,
    validate_error,
    validate_success,
)


# ─── Difficulty: cross_entity_state_dependency / appointment_requires_student_enrolled

def test_booking_rejected_when_student_on_leave(api, director_headers, front_desk_headers):
    """PRD §3.4: "The student must be `ENROLLED` (`ERR_STUDENT_NOT_ENROLLED`) and the host advisor must be `ACTIVE` (`ERR_ADVISOR_NOT_ACTIVE`) — cross-entity checks that §2.10 evaluates last."

    Design: Difficulty/cross_entity_state_dependency/appointment_requires_student_enrolled
    """
    student = create_student(full_name="X1", email="x1@x.edu")
    api.update_student(student["id"], {"care_status": "ON_LEAVE"}, director_headers)
    advisor = create_advisor(full_name="Advisor X", email="x@x.edu")
    res = api.create_appointment(
        create_appointment_payload(
            student["id"], advisor["id"],
            scheduled_start_at="2026-08-01T10:00:00Z",
            scheduled_end_at="2026-08-01T10:30:00Z",
        ),
        front_desk_headers,
    )
    validate_error(res, ApiErrorId.ERR_STUDENT_NOT_ENROLLED)


def test_booking_rejected_when_student_inactive(api, director_headers, front_desk_headers):
    """PRD §3.4: "The student must be `ENROLLED` (`ERR_STUDENT_NOT_ENROLLED`) and the host advisor must be `ACTIVE` (`ERR_ADVISOR_NOT_ACTIVE`) — cross-entity checks that §2.10 evaluates last."
    PRD §2.10 step 10: "Appointment booking requires the student be `ENROLLED` and the advisor be `ACTIVE`; releasing a plan-gated hold requires an approved plan (`ERR_PLAN_NOT_APPROVED`)."

    Design: Difficulty/cross_entity_state_dependency/appointment_requires_student_enrolled
    """
    student = create_student(full_name="X1b", email="x1b@x.edu")
    api.update_student(student["id"], {"care_status": "INACTIVE"}, director_headers)
    advisor = create_advisor(full_name="Advisor Xb", email="xb@x.edu")
    res = api.create_appointment(
        create_appointment_payload(student["id"], advisor["id"]),
        front_desk_headers,
    )
    validate_error(res, ApiErrorId.ERR_STUDENT_NOT_ENROLLED)


# ─── Difficulty: resource_temporal_overlap / appointment_half_open_adjacency ──

def test_adjacent_slots_accepted_under_half_open_semantics(api, director_headers):
    """PRD §3.4: "The requested interval must not intersect any existing `SCHEDULED` or `CHECKED_IN` appointment of the same advisor; because intervals are half-open, back-to-back slots that merely touch at an endpoint are allowed."
    PRD §3.1: "`scheduled_minutes` totals the `duration_minutes` of the advisor's appointments that are in `SCHEDULED` or `CHECKED_IN` — exactly those two statuses count; `COMPLETED`, `CANCELLED`, and `NO_SHOW` slots are excluded."

    Design: Difficulty/resource_temporal_overlap/appointment_half_open_adjacency
    """
    student, advisor, first = setup_student_advisor_appointment(
        "2026-08-01T10:00:00Z", "2026-08-01T10:30:00Z"
    )
    # [09:30, 10:00) merely touches [10:00, 10:30) at the endpoint -> allowed.
    adjacent = book_appointment(
        student["id"], advisor["id"],
        "2026-08-01T09:30:00Z", "2026-08-01T10:00:00Z",
    )
    assert_appointment(adjacent)
    assert adjacent["status"] == "SCHEDULED"
    assert adjacent["duration_minutes"] == 30
    assert get_advisor(advisor["id"])["scheduled_minutes"] == 60, (
        "two accepted 30-minute bookings; the touching adjacency counts fully"
    )


def test_intersecting_slot_rejected_with_overlap(api, front_desk_headers):
    """PRD §3.4: "A colliding request is rejected with `ERR_APPOINTMENT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/appointment_half_open_adjacency
    """
    student, advisor, _ = setup_student_advisor_appointment(
        "2026-08-01T10:00:00Z", "2026-08-01T10:30:00Z"
    )
    book_appointment(
        student["id"], advisor["id"],
        "2026-08-01T09:30:00Z", "2026-08-01T10:00:00Z",
    )
    # [09:45, 10:15) intersects both existing slots -> collision.
    res = api.create_appointment(
        create_appointment_payload(
            student["id"], advisor["id"],
            scheduled_start_at="2026-08-01T09:45:00Z",
            scheduled_end_at="2026-08-01T10:15:00Z",
        ),
        front_desk_headers,
    )
    validate_error(res, ApiErrorId.ERR_APPOINTMENT_OVERLAP)


# ─── Difficulty: compensating_invariant / book_cancel_conserve_scheduled_minutes

def test_booking_debits_scheduled_minutes(api, director_headers):
    """PRD §3.4: "A successful booking starts in `SCHEDULED`, and the host advisor's `scheduled_minutes` recomputes immediately."
    PRD §3.1: "A freshly created advisor starts with `status` set to `ACTIVE` and all three load measures at zero."

    Design: Difficulty/compensating_invariant/book_cancel_conserve_scheduled_minutes
    """
    advisor = create_advisor(full_name="Advisor I2", email="i2@x.edu")
    student = create_student(full_name="I2", email="i2s@x.edu")
    assert get_advisor(advisor["id"])["scheduled_minutes"] == 0
    book_appointment(
        student["id"], advisor["id"],
        "2026-08-01T14:00:00Z", "2026-08-01T14:30:00Z",
    )
    assert get_advisor(advisor["id"])["scheduled_minutes"] == 30, (
        "the forward action debits the minutes pool by the slot's duration"
    )


def test_cancel_restores_scheduled_minutes(api, front_desk_headers, director_headers):
    """PRD §3.4: "Cancellation — by `FrontDeskStaff`, an `Advisor`, or the director — is permitted only from `SCHEDULED` and moves the appointment to `CANCELLED`, removing the slot from `scheduled_minutes`."

    Design: Difficulty/compensating_invariant/book_cancel_conserve_scheduled_minutes
    """
    advisor = create_advisor(full_name="Advisor I2", email="i2@x.edu")
    student = create_student(full_name="I2", email="i2s@x.edu")
    appt = book_appointment(
        student["id"], advisor["id"],
        "2026-08-01T14:00:00Z", "2026-08-01T14:30:00Z",
    )
    assert get_advisor(advisor["id"])["scheduled_minutes"] == 30
    cancelled = validate_success(
        api.cancel_appointment(appt["id"], front_desk_headers), 200
    )
    assert cancelled["status"] == "CANCELLED"
    assert get_advisor(advisor["id"])["scheduled_minutes"] == 0, (
        "the compensating cancel restores the conserved sum exactly to zero"
    )


# ─── Difficulty: priority_pair_validation_conflict / checkin_cancelled_outside_window

def test_checkin_cancelled_outside_window_reports_state_error(api, front_desk_headers, director_headers):
    """PRD §2.10 step 9: "Check-in must fall inside its window, else `ERR_OUTSIDE_CHECK_IN_WINDOW` (HTTP 409); an appointment that is not `SCHEDULED` reports `ERR_APPOINTMENT_INVALID_STATE` at step 6 even when the caller is also outside the window."
    PRD §2.10: "A failure at any step stops evaluation and produces that step's error, so when several problems coexist, the earliest step's error is the one reported:"

    Design: Difficulty/priority_pair_validation_conflict/checkin_cancelled_outside_window_state_beats_temporal
    """
    student, advisor, appt = setup_student_advisor_appointment(
        "2026-08-01T10:00:00Z", "2026-08-01T10:30:00Z"
    )
    validate_success(api.cancel_appointment(appt["id"], front_desk_headers), 200)
    # Logical clock far outside the [09:50, 10:10] check-in window.
    set_logical_clock("2026-08-02T00:00:00Z")
    res = api.check_in_appointment(appt["id"], front_desk_headers)
    validate_error(res, ApiErrorId.ERR_APPOINTMENT_INVALID_STATE)


def test_rejected_checkin_leaves_appointment_untouched(api, front_desk_headers, director_headers):
    """PRD §3.4: "The appointment must be `SCHEDULED` (any other status yields `ERR_APPOINTMENT_INVALID_STATE`), and the current logical time must fall inside the window running from ten minutes before the scheduled start to ten minutes after it, with both boundaries inclusive; outside that window the check-in is rejected with `ERR_OUTSIDE_CHECK_IN_WINDOW`."
    PRD §3.4: "A successful check-in moves the appointment `SCHEDULED → CHECKED_IN` and stamps `checked_in_at` with the current logical time."

    Design: Difficulty/priority_pair_validation_conflict/checkin_cancelled_outside_window_state_beats_temporal
    """
    student, advisor, appt = setup_student_advisor_appointment(
        "2026-08-01T10:00:00Z", "2026-08-01T10:30:00Z"
    )
    validate_success(api.cancel_appointment(appt["id"], front_desk_headers), 200)
    set_logical_clock("2026-08-02T00:00:00Z")
    validate_error(
        api.check_in_appointment(appt["id"], front_desk_headers),
        ApiErrorId.ERR_APPOINTMENT_INVALID_STATE,
    )
    after = validate_success(api.get_appointment(appt["id"], director_headers), 200)
    assert after["status"] == "CANCELLED", "a rejected check-in fires no transition"
    assert after["checked_in_at"] is None, "a rejected check-in stamps nothing"


# ─── Corner: state_machines / appointment_checkin_complete_satisfies_requirement

def test_appointment_checkin_complete_satisfies_requirement(api, front_desk_headers, director_headers):
    """PRD §3.4: "Completion moves the appointment to `COMPLETED`, removes the slot from `scheduled_minutes`, and, when the appointment's `term_code` equals the student's `current_term_code`, recomputes the student's `advising_requirement_status` and `registration_clearance`: a completed current-term session is what satisfies the advising requirement defined in §3.8."
    PRD §3.8: "`advising_requirement_status` is `NOT_REQUIRED` when `advising_required_flag` is false; otherwise it is `SATISFIED` when a `COMPLETED` appointment exists for the student in the student's `current_term_code`, and `REQUIRED` when none does."

    Design: Corner/state_machines/appointment_checkin_complete_satisfies_requirement
    """
    student, advisor, appt = setup_student_advisor_appointment(
        "2026-08-01T10:00:00Z", "2026-08-01T10:30:00Z", flag=True, term_code="FA26"
    )
    set_logical_clock("2026-08-01T09:55:00Z")  # inside [09:50, 10:10] inclusive
    checked_in = validate_success(
        api.check_in_appointment(appt["id"], front_desk_headers), 200
    )
    assert checked_in["status"] == "CHECKED_IN"
    completed = validate_success(
        api.complete_appointment(appt["id"], director_headers), 200
    )
    assert completed["status"] == "COMPLETED"
    student_after = validate_success(
        api.get_student(student["id"], director_headers), 200
    )
    assert student_after["advising_requirement_status"] == "SATISFIED"
    assert student_after["registration_clearance"] == "CLEARED"


# ─── Corner: state_machines / appointment_complete_from_scheduled_rejected ────

def test_appointment_complete_from_scheduled_rejected(api, director_headers):
    """PRD §3.4: "Completion is permitted only from `CHECKED_IN` and only by the appointment's own advisor — for this operation, ownership means `X-User-ID` equals the appointment's `advisor_id` — or by the director."
    PRD §3.4: "Attempting either transition from the wrong source state yields `ERR_APPOINTMENT_INVALID_STATE`."

    Design: Corner/state_machines/appointment_complete_from_scheduled_rejected
    """
    _student, _advisor, appt = setup_student_advisor_appointment()
    res = api.complete_appointment(appt["id"], director_headers)
    validate_error(res, ApiErrorId.ERR_APPOINTMENT_INVALID_STATE)


# ─── Corner: errors / appointment_advisor_not_found_trigger ──────────────────

def test_appointment_advisor_not_found_trigger(api, front_desk_headers):
    """PRD §2.10 step 4: "Path identifiers are validated left to right, then body-referenced identifiers such as `student_id`, `advisor_id`, and `referral_id`. The first miss produces the matching 404: `ERR_STUDENT_NOT_FOUND`, `ERR_ADVISOR_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_INTERVENTION_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, or `ERR_PLAN_NOT_FOUND`."

    Design: Corner/errors/appointment_advisor_not_found_trigger
    """
    student = create_student(full_name="R1", email="r1e@x.edu")
    res = api.create_appointment(
        create_appointment_payload(student["id"], NON_EXISTENT_UUID),
        front_desk_headers,
    )
    validate_error(res, ApiErrorId.ERR_ADVISOR_NOT_FOUND)


# ─── Corner: errors / invalid_duration_rejected ──────────────────────────────

def test_invalid_duration_rejected(api, front_desk_headers):
    """PRD §3.4: "The end must be strictly after the start and the duration must be at least 15 and at most 60 minutes, else the booking fails with `ERR_INVALID_APPOINTMENT_DURATION`; the stored `duration_minutes` is the whole-minute difference between the two boundaries."

    Design: Corner/errors/invalid_duration_rejected
    """
    student = create_student(full_name="R3", email="r3e@x.edu")
    advisor = create_advisor(full_name="Advisor R3", email="r3a@x.edu")
    res = api.create_appointment(
        create_appointment_payload(
            student["id"], advisor["id"],
            scheduled_start_at="2026-08-01T10:00:00Z",
            scheduled_end_at="2026-08-01T10:10:00Z",  # 10 minutes < 15
        ),
        front_desk_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_APPOINTMENT_DURATION)


# ─── Corner: errors / appointment_with_inactive_advisor_rejected ─────────────

def test_appointment_with_inactive_advisor_rejected(api, director_headers, front_desk_headers):
    """PRD §3.1: "Marking an advisor `INACTIVE` blocks any new assignment or appointment that would reference this advisor with `ERR_ADVISOR_NOT_ACTIVE`."

    Design: Corner/errors/appointment_with_inactive_advisor_rejected
    """
    advisor = create_advisor(full_name="Advisor R8", email="r8a@x.edu")
    student = create_student(full_name="R8", email="r8e@x.edu")
    patched = validate_success(
        api.update_advisor(advisor["id"], {"status": "INACTIVE"}, director_headers), 200
    )
    assert patched["status"] == "INACTIVE"
    res = api.create_appointment(
        create_appointment_payload(student["id"], advisor["id"]),
        front_desk_headers,
    )
    validate_error(res, ApiErrorId.ERR_ADVISOR_NOT_ACTIVE)
