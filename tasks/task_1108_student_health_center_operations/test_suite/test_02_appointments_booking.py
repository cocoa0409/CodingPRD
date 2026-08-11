"""Appointment booking claims: initial state, temporal rules, half-open slot
semantics, same-day triage quota, compliance/insurance gates, ownership scoping,
no-show sweep, and validation-order priority pairs (PRD §2.1, §2.4, §2.9, §3.4)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_appointment,
    book_appointment,
    check_in,
    create_appointment_payload,
    get_student,
    make_policy,
    make_provider,
    make_student,
    make_student_headers,
    set_clock,
    setup_registration_hold_student,
    validate_error,
    validate_success,
)

BILLING = TEST_USERS["billing_officer_headers"]


def test_appointment_initial_state_booked(api, front_desk_headers):
    """PRD §3.4: "A successful booking lands in `BOOKED` with `cancel_reason`
    set to `NONE`."

    Design: Corner/state_machines/appointment_initial_state_booked
    """
    set_clock("2026-05-01T00:00:00Z")
    student = make_student("S10", "Init State")
    provider = make_provider("Dr A")
    appt = validate_success(
        api.create_appointment(
            create_appointment_payload(
                student["id"], provider["id"], "FOLLOW_UP",
                "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z",
            ),
            front_desk_headers,
        ),
        201,
    )
    assert_appointment(appt)
    assert appt["status"] == "BOOKED"
    assert appt["cancel_reason"] == "NONE"


def test_appointment_invalid_transitions(api, front_desk_headers, clinician_headers):
    """PRD §3.5: "Check-in requires the appointment to be `BOOKED` — anything
    else is rejected with `ERR_APPOINTMENT_NOT_BOOKED`".
    PRD §3.4: "only a `BOOKED` appointment may be cancelled this way, otherwise
    `ERR_APPOINTMENT_NOT_CANCELLABLE`."
    PRD §3.5: "A successful close ... cascades the linked appointment from
    `CHECKED_IN` to `COMPLETED`, its terminal state."

    Design: Corner/state_machines/appointment_invalid_transitions
    """
    set_clock("2026-05-01T00:00:00Z")
    student = make_student("S11", "Trans Test")
    provider = make_provider("Dr B")
    appt1 = book_appointment(
        student["id"], provider["id"], "FOLLOW_UP",
        "2026-05-02T09:00:00Z", "2026-05-02T09:30:00Z",
    )
    appt2 = book_appointment(
        student["id"], provider["id"], "PRIMARY_URGENT",
        "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z",
    )
    enc2 = check_in(appt2["id"])
    # Fee-covered urgent visit for an ENROLLED student closes with no invoice.
    closed = validate_success(api.close_encounter(enc2["id"], {}, clinician_headers), 200)
    assert closed["status"] == "CLOSED"
    appt2_after = validate_success(api.get_appointment(appt2["id"], front_desk_headers), 200)
    assert appt2_after["status"] == "COMPLETED"

    validate_success(api.cancel_appointment(appt1["id"], front_desk_headers), 200)

    res1 = api.check_in_appointment(appt1["id"], front_desk_headers)
    validate_error(res1, ApiErrorId.ERR_APPOINTMENT_NOT_BOOKED, expected_status=409)

    res2 = api.cancel_appointment(appt2["id"], front_desk_headers)
    validate_error(res2, ApiErrorId.ERR_APPOINTMENT_NOT_CANCELLABLE, expected_status=409)


def test_appointment_no_show_by_clock_sweep(api, front_desk_headers):
    """PRD §3.4: "And if its `scheduled_end` passes while it is still `BOOKED`,
    the clock sweep marks it `NO_SHOW`."

    Design: Corner/state_machines/appointment_no_show_by_clock_sweep
    """
    set_clock("2026-05-01T00:00:00Z")
    student = make_student("S12", "No Show")
    provider = make_provider("Dr C")
    appt = book_appointment(
        student["id"], provider["id"], "FOLLOW_UP",
        "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z",
    )
    set_clock("2026-05-03T00:00:00Z")
    after = validate_success(api.get_appointment(appt["id"], front_desk_headers), 200)
    assert after["status"] == "NO_SHOW", (
        f"expected NO_SHOW after scheduled_end passed under the sweep, got {after['status']}"
    )


class TestBookingTemporalRules:
    """Per-violation temporal errors on booking."""

    def test_booking_in_past_rejected(self, api, front_desk_headers):
        """PRD §3.4: "The appointment must lie in the future: a `scheduled_start`
        at or before the current logical time is rejected with
        `ERR_APPOINTMENT_IN_PAST`."

        Design: Corner/validations/booking_temporal_rule_matrix
        """
        set_clock("2026-05-01T00:00:00Z")
        student = make_student("S30", "Temp Rules")
        provider = make_provider("Dr M")
        res = api.create_appointment(
            create_appointment_payload(
                student["id"], provider["id"], "FOLLOW_UP",
                "2026-04-30T10:00:00Z", "2026-04-30T10:30:00Z",
            ),
            front_desk_headers,
        )
        validate_error(res, ApiErrorId.ERR_APPOINTMENT_IN_PAST, expected_status=422)

    def test_booking_inverted_range_rejected(self, api, front_desk_headers):
        """PRD §3.4: "The window must be well-formed: `scheduled_end` strictly
        after `scheduled_start`, else `ERR_INVALID_TIME_RANGE`."

        Design: Corner/validations/booking_temporal_rule_matrix
        """
        set_clock("2026-05-01T00:00:00Z")
        student = make_student("S30I", "Temp Rules Inverted")
        provider = make_provider("Dr M")
        res = api.create_appointment(
            create_appointment_payload(
                student["id"], provider["id"], "FOLLOW_UP",
                "2026-05-02T10:30:00Z", "2026-05-02T10:00:00Z",
            ),
            front_desk_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_TIME_RANGE, expected_status=422)

    def test_same_day_triage_must_be_today(self, api, front_desk_headers):
        """PRD §3.4: "A `SAME_DAY_TRIAGE` appointment must be scheduled on the
        current logical calendar date; any other date is rejected with
        `ERR_SAME_DAY_ONLY`."

        Design: Corner/validations/booking_temporal_rule_matrix
        """
        set_clock("2026-05-01T00:00:00Z")
        student = make_student("S30T", "Temp Rules Triage")
        provider = make_provider("Dr M")
        res = api.create_appointment(
            create_appointment_payload(
                student["id"], provider["id"], "SAME_DAY_TRIAGE",
                "2026-05-02T11:00:00Z", "2026-05-02T11:15:00Z",
            ),
            front_desk_headers,
        )
        validate_error(res, ApiErrorId.ERR_SAME_DAY_ONLY, expected_status=422)


def test_travel_booking_requires_verified_policy(api, front_desk_headers):
    """PRD §3.4: "A `TRAVEL_CLINIC` booking carries an additional fiscal gate,
    evaluated later in the ordering: the student must hold a `VERIFIED`
    insurance policy, and booking without one is rejected with
    `ERR_INSURANCE_NOT_VERIFIED`."

    Design: Corner/validations/travel_booking_requires_verified_policy
    """
    set_clock("2026-05-01T00:00:00Z")
    student = make_student("S31", "Traveler")
    provider = make_provider("Dr N")

    # No policy at all -> rejected.
    res1 = api.create_appointment(
        create_appointment_payload(
            student["id"], provider["id"], "TRAVEL_CLINIC",
            "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z",
        ),
        front_desk_headers,
    )
    validate_error(res1, ApiErrorId.ERR_INSURANCE_NOT_VERIFIED, expected_status=402)

    # Policy exists but is UNVERIFIED -> still rejected.
    policy = make_policy(student, policy_number="TR-1")
    assert policy["status"] == "UNVERIFIED"
    res2 = api.create_appointment(
        create_appointment_payload(
            student["id"], provider["id"], "TRAVEL_CLINIC",
            "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z",
        ),
        front_desk_headers,
    )
    validate_error(res2, ApiErrorId.ERR_INSURANCE_NOT_VERIFIED, expected_status=402)

    # After verification the gate opens.
    validate_success(api.verify_insurance_policy(policy["id"], BILLING), 200)
    appt = validate_success(
        api.create_appointment(
            create_appointment_payload(
                student["id"], provider["id"], "TRAVEL_CLINIC",
                "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z",
            ),
            front_desk_headers,
        ),
        201,
    )
    assert appt["status"] == "BOOKED"


def test_triage_quota_boundary_and_release(api, front_desk_headers):
    """PRD §3.4: "rejects the booking with `ERR_TRIAGE_QUOTA_EXHAUSTED` when the
    count has already reached four. The boundary works in the caller's favor —
    with three counted, the fourth booking succeeds; with four counted, the
    fifth is refused. `CANCELLED` and `NO_SHOW` appointments never count toward
    the quota, which is why cancelling a triage booking frees the slot for
    someone else."

    Design: Corner/validations/triage_quota_boundary_and_release
    """
    set_clock("2026-05-01T00:00:00Z")
    student = make_student("S32", "Triage Test")
    provider = make_provider("Dr O")

    triage_ids = []
    for hour_min in ("09:00", "09:15", "09:30", "09:45"):
        start = f"2026-05-01T{hour_min}:00Z"
        end_h, end_m = divmod(int(hour_min[:2]) * 60 + int(hour_min[3:]) + 15, 60)
        end = f"2026-05-01T{end_h:02d}:{end_m:02d}:00Z"
        appt = validate_success(
            api.create_appointment(
                create_appointment_payload(
                    student["id"], provider["id"], "SAME_DAY_TRIAGE", start, end
                ),
                front_desk_headers,
            ),
            201,
        )
        triage_ids.append(appt["id"])
    assert len(triage_ids) == 4, "with three counted, the fourth booking succeeds"

    # Fifth booking: count == 4 >= 4 -> refused.
    res = api.create_appointment(
        create_appointment_payload(
            student["id"], provider["id"], "SAME_DAY_TRIAGE",
            "2026-05-01T10:00:00Z", "2026-05-01T10:15:00Z",
        ),
        front_desk_headers,
    )
    validate_error(res, ApiErrorId.ERR_TRIAGE_QUOTA_EXHAUSTED, expected_status=409)

    # Cancelling one frees the quota; the retry succeeds.
    validate_success(api.cancel_appointment(triage_ids[0], front_desk_headers), 200)
    retry = validate_success(
        api.create_appointment(
            create_appointment_payload(
                student["id"], provider["id"], "SAME_DAY_TRIAGE",
                "2026-05-01T10:00:00Z", "2026-05-01T10:15:00Z",
            ),
            front_desk_headers,
        ),
        201,
    )
    assert retry["status"] == "BOOKED"


def test_student_booking_for_other_forbidden(api):
    """PRD §2.1: "a `Student` caller attempting to book or cancel an appointment
    for someone else is rejected with `ERR_FORBIDDEN`."
    PRD §3.4: "when `X-User-Role` is `Student`, the supplied `student_id` must
    equal `X-User-ID` or the booking is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/student_booking_for_other_forbidden
    """
    set_clock("2026-05-01T00:00:00Z")
    student_a = make_student("S60", "Self A")
    student_b = make_student("S61", "Other B")
    provider = make_provider("Dr V")

    # Self-booking: student_id == X-User-ID -> allowed.
    own = validate_success(
        api.create_appointment(
            create_appointment_payload(
                student_a["id"], provider["id"], "FOLLOW_UP",
                "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z",
            ),
            make_student_headers(student_a["id"]),
        ),
        201,
    )
    assert own["status"] == "BOOKED"

    # Booking for another student -> 403.
    res = api.create_appointment(
        create_appointment_payload(
            student_b["id"], provider["id"], "FOLLOW_UP",
            "2026-05-02T11:00:00Z", "2026-05-02T11:30:00Z",
        ),
        make_student_headers(student_a["id"]),
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


# ---------------------------------------------------------------------------
# Depth probes: half-open slot semantics (resource_temporal_overlap)
# ---------------------------------------------------------------------------

def _setup_slot_scenario():
    set_clock("2026-05-01T00:00:00Z")
    s1 = make_student("S900", "Slot One")
    s2 = make_student("S901", "Slot Two")
    provider = make_provider("Dr R")
    existing = book_appointment(
        s1["id"], provider["id"], "PRIMARY_URGENT",
        "2026-06-01T10:00:00Z", "2026-06-01T10:30:00Z",
    )
    return s1, s2, provider, existing


def test_overlapping_booking_rejected_with_slot_conflict(api, front_desk_headers):
    """PRD §3.4: "an existing `BOOKED` or `CHECKED_IN` appointment for the same
    provider overlapping the new window is rejected with `ERR_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/appointment_half_open_intervals_allow_adjacency
    """
    _, s2, provider, _ = _setup_slot_scenario()
    res = api.create_appointment(
        create_appointment_payload(
            s2["id"], provider["id"], "FOLLOW_UP",
            "2026-06-01T10:15:00Z", "2026-06-01T10:45:00Z",
        ),
        front_desk_headers,
    )
    validate_error(res, ApiErrorId.ERR_SLOT_CONFLICT, expected_status=409)


def test_adjacent_booking_allowed_under_half_open_semantics(api, front_desk_headers):
    """PRD §3.4: "Overlap uses **half-open** semantics — the interval includes
    its start and excludes its end — so an existing booking ending exactly at
    the new appointment's start, or starting exactly at its end, does not
    conflict."

    Design: Difficulty/resource_temporal_overlap/appointment_half_open_intervals_allow_adjacency
    """
    _, s2, provider, _ = _setup_slot_scenario()
    appt = validate_success(
        api.create_appointment(
            create_appointment_payload(
                s2["id"], provider["id"], "FOLLOW_UP",
                "2026-06-01T10:30:00Z", "2026-06-01T11:00:00Z",
            ),
            front_desk_headers,
        ),
        201,
    )
    assert appt["status"] == "BOOKED", (
        "start == existing end is not a conflict under half-open semantics"
    )


# ---------------------------------------------------------------------------
# Depth probes: compliance safety gate beats temporal slot conflict (P6 > P7)
# ---------------------------------------------------------------------------

def _setup_hold_and_occupied_slot():
    student, _, _, provider = setup_registration_hold_student(ref="S601")
    other = make_student("S602", "Other Student")
    blocker = book_appointment(
        other["id"], provider["id"], "PRIMARY_URGENT",
        "2026-06-01T10:00:00Z", "2026-06-01T10:30:00Z",
    )
    return student, provider, blocker


def test_hold_booking_into_occupied_slot_reports_compliance_hold(api, front_desk_headers):
    """PRD §2.9: "the error the caller sees is determined by a fixed evaluation
    order" — "6. **Compliance and safety gates** — elective bookings under a
    `REGISTRATION_HOLD` ..." precedes "7. **Temporal rules** — ... slot and
    on-call conflicts ...".
    PRD §3.4: "Booking a `SPORTS_PHYSICAL` or `TRAVEL_CLINIC` while the
    student's `compliance_posture` is `REGISTRATION_HOLD` is rejected with
    `ERR_COMPLIANCE_HOLD_ACTIVE`".

    Design: Difficulty/priority_pair_validation_conflict/booking_hold_safety_beats_slot_temporal
    """
    student, provider, _ = _setup_hold_and_occupied_slot()
    held = get_student(student["id"])
    assert held["compliance_posture"] == "REGISTRATION_HOLD"
    assert "IMMUNIZATION" in held["active_hold_types"]

    res = api.create_appointment(
        create_appointment_payload(
            student["id"], provider["id"], "SPORTS_PHYSICAL",
            "2026-06-01T10:15:00Z", "2026-06-01T10:45:00Z",
        ),
        front_desk_headers,
    )
    validate_error(res, ApiErrorId.ERR_COMPLIANCE_HOLD_ACTIVE, expected_status=403)


def test_hold_booking_into_free_slot_also_reports_compliance_hold(api, front_desk_headers):
    """PRD §3.4: "Booking a `SPORTS_PHYSICAL` or `TRAVEL_CLINIC` while the
    student's `compliance_posture` is `REGISTRATION_HOLD` is rejected with
    `ERR_COMPLIANCE_HOLD_ACTIVE` (a `PROVISIONAL_HOLD` does not block elective
    booking)." The safety gate fires even with no competing slot conflict.

    Design: Difficulty/priority_pair_validation_conflict/booking_hold_safety_beats_slot_temporal
    """
    student, provider, blocker = _setup_hold_and_occupied_slot()
    res = api.create_appointment(
        create_appointment_payload(
            student["id"], provider["id"], "SPORTS_PHYSICAL",
            "2026-06-01T12:00:00Z", "2026-06-01T12:30:00Z",
        ),
        front_desk_headers,
    )
    validate_error(res, ApiErrorId.ERR_COMPLIANCE_HOLD_ACTIVE, expected_status=403)

    # The failed bookings mutate nothing: the other student's booking survives.
    blocker_after = validate_success(
        api.get_appointment(blocker["id"], front_desk_headers), 200
    )
    assert blocker_after["status"] == "BOOKED"
