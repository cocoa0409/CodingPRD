"""State-machine corner cases: invalid transitions, precondition enforcement,
terminal-state lockdown, and initial states.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    make_teacher_headers,
    make_guardian_headers,
    create_draft_trip,
    create_pending_principal_trip,
    create_approved_trip,
    create_teacher_guardian,
    create_guardian,
    create_student,
    create_slip,
    create_vehicle,
    request_booking,
    invite_chaperone,
    confirm_chaperone,
    setup_completed_trip,
    setup_in_progress_trip_no_return_headcount,
)


_PRINCIPAL = TEST_USERS["principal_headers"]
_DISTRICT = TEST_USERS["district_admin_headers"]


# ─── Invalid transitions ──────────────────────────────────────────────────────
def test_cancel_already_cancelled_trip_returns_not_cancellable(api):
    """PRD §3.10: "a cancel against a completed or cancelled trip is rejected with `ERR_TRIP_NOT_CANCELLABLE`."

    Design: Corner/state_machines/cancel_already_cancelled_trip_returns_not_cancellable
    """
    teacher_id = create_teacher_guardian()
    trip = create_draft_trip(teacher_id, grade_band="HIGH", capacity=5)
    teacher = make_teacher_headers(teacher_id)
    validate_success(api.cancel_trip(trip["id"], teacher), 200)
    validate_error(api.cancel_trip(trip["id"], teacher), "ERR_TRIP_NOT_CANCELLABLE")


def test_submit_non_draft_trip_returns_not_draft(api):
    """PRD §3.2: "Submission is allowed only from `DRAFT`; a submit from any other state is rejected with `ERR_TRIP_NOT_DRAFT`."

    Design: Corner/state_machines/submit_non_draft_trip_returns_not_draft
    """
    teacher_id, trip = create_pending_principal_trip(grade_band="HIGH", capacity=5)
    validate_error(api.submit_trip(trip["id"], make_teacher_headers(teacher_id)),
                   "ERR_TRIP_NOT_DRAFT")


def test_district_step_on_pending_principal_returns_invalid_step(api):
    """PRD §2.11/§3.2: "the body's `step` is checked against the trip's current
    pending step (`ERR_INVALID_APPROVAL_STEP`, 422) before the state precondition";
    "A well-formed but wrong-for-now step is rejected with `ERR_INVALID_APPROVAL_STEP`
    before the state precondition is examined."

    A DISTRICT approval while the trip is still PENDING_PRINCIPAL: the body's step
    (DISTRICT) does not match the current pending step (PRINCIPAL), so the step-match
    check fires first and yields ERR_INVALID_APPROVAL_STEP — the
    ERR_TRIP_NOT_AWAITING_DISTRICT state precondition is never reached for a DISTRICT
    step unless the trip is already PENDING_DISTRICT.

    Design: Corner/state_machines/district_step_on_pending_principal_returns_not_awaiting_district
    """
    teacher_id, trip = create_pending_principal_trip(grade_band="HIGH", capacity=5)
    validate_error(
        api.create_approval(trip["id"], {"step": "DISTRICT", "decision": "APPROVE"}, _DISTRICT),
        "ERR_INVALID_APPROVAL_STEP",
    )


def test_start_before_lock_returns_not_locked(api):
    """PRD §3.9: "After the roster locks, the `Teacher` starts the trip, advancing `ROSTER_LOCKED → IN_PROGRESS`; starting requires the trip to be in `ROSTER_LOCKED`, otherwise `ERR_TRIP_NOT_LOCKED`."

    Design: Corner/state_machines/start_before_lock_returns_not_locked
    """
    teacher_id, trip = create_approved_trip(grade_band="HIGH", capacity=5)
    validate_error(api.start_trip(trip["id"], make_teacher_headers(teacher_id)),
                   "ERR_TRIP_NOT_LOCKED")


# ─── Precondition enforcement ─────────────────────────────────────────────────
def test_pay_unsigned_slip_returns_slip_not_signed(api):
    """PRD §3.7: "A guardian pays their own slip by submitting `amount_cents`. Payment is limited to the slip's guardian (`ERR_NOT_SLIP_GUARDIAN`), requires the slip to be `SIGNED` (`ERR_SLIP_NOT_SIGNED`)..."

    Design: Corner/state_machines/pay_unsigned_slip_returns_slip_not_signed
    """
    teacher_id, trip = create_approved_trip(grade_band="ELEMENTARY", capacity=5, base_fee_cents=1000)
    trip_id = trip["id"]
    g = create_guardian(full_name="G10c")
    st = create_student(teacher_id, full_name="S10c", grade_level=5)
    slip = create_slip(teacher_id, trip_id, st["id"], g["id"])
    validate_error(
        api.pay_slip(trip_id, slip["id"], {"amount_cents": 1000}, make_guardian_headers(g["id"])),
        "ERR_SLIP_NOT_SIGNED",
    )


def test_sign_without_emergency_contact_returns_required(api):
    """PRD §3.3: "A sign attempt against a slip with no emergency contact on file is rejected with `ERR_EMERGENCY_CONTACT_REQUIRED`."

    The signature stays UNSIGNED.

    Design: Corner/state_machines/sign_without_emergency_contact_returns_required
    """
    teacher_id, trip = create_approved_trip(grade_band="ELEMENTARY", capacity=5)
    trip_id = trip["id"]
    g = create_guardian(full_name="G11c")
    st = create_student(teacher_id, full_name="S11c", grade_level=5)
    slip = create_slip(teacher_id, trip_id, st["id"], g["id"])
    validate_error(api.sign_slip(trip_id, slip["id"], make_guardian_headers(g["id"])),
                   "ERR_EMERGENCY_CONTACT_REQUIRED")
    slip = get_success_data(api.get_permission_slip(slip["id"], make_teacher_headers(teacher_id)))
    assert slip["signature_status"] == "UNSIGNED"


def test_clear_without_background_check_returns_missing(api):
    """PRD §3.4: "requires the chaperone to carry a `background_check_ref` (`ERR_BACKGROUND_CHECK_MISSING`)."

    Clearing a CONFIRMED chaperone that has no background_check_ref → that error;
    the chaperone stays CONFIRMED.

    Design: Corner/state_machines/clear_without_background_check_returns_missing
    """
    teacher_id, trip = create_approved_trip(grade_band="HIGH", capacity=5)
    trip_id = trip["id"]
    g = create_guardian(full_name="Gch12")
    chap = invite_chaperone(teacher_id, trip_id, g["id"], background_check_ref=None)
    confirm_chaperone(g["id"], trip_id, chap["id"])
    validate_error(api.clear_chaperone(trip_id, chap["id"], _PRINCIPAL),
                   "ERR_BACKGROUND_CHECK_MISSING")
    chap = get_success_data(api.get_chaperone(chap["id"], make_teacher_headers(teacher_id)))
    assert chap["status"] == "CONFIRMED"


def test_confirm_booking_overbook_returns_overbooked(api):
    """PRD §3.6: "requires that adding this booking's `seat_count` to the vehicle's
    current `seats_reserved` not exceed the vehicle's `seat_capacity`, otherwise
    `ERR_VEHICLE_OVERBOOKED`."

    Vehicle capacity 4; a REQUESTED 5-seat booking → ERR_VEHICLE_OVERBOOKED on
    confirm; no seats reserved.

    Design: Corner/state_machines/confirm_booking_overbook_returns_overbooked
    """
    teacher_id, trip = create_approved_trip(grade_band="HIGH", capacity=10)
    trip_id = trip["id"]
    vehicle = create_vehicle(label="Small", seat_capacity=4)
    booking = request_booking(teacher_id, trip_id, vehicle["id"], 5)
    teacher = make_teacher_headers(teacher_id)
    validate_error(api.confirm_booking(trip_id, booking["id"], teacher), "ERR_VEHICLE_OVERBOOKED")
    v = get_success_data(api.get_vehicle(vehicle["id"], teacher))
    assert v["seats_reserved"] == 0


def test_complete_without_return_headcount_returns_incomplete(api):
    """PRD §3.9: "Completion requires the trip to be in `IN_PROGRESS`, otherwise `ERR_TRIP_NOT_IN_PROGRESS`, and requires that every slip that was snapshotted `CONFIRMED` at lock has at least one `RETURN` attendance record; if any confirmed slip lacks a return headcount, completion is refused with `ERR_RETURN_HEADCOUNT_INCOMPLETE`."

    Design: Corner/state_machines/complete_without_return_headcount_returns_incomplete
    """
    bundle = setup_in_progress_trip_no_return_headcount()
    teacher_id, trip_id = bundle["teacher_id"], bundle["trip_id"]
    teacher = make_teacher_headers(teacher_id)
    validate_error(api.complete_trip(trip_id, teacher), "ERR_RETURN_HEADCOUNT_INCOMPLETE")
    trip = get_success_data(api.get_field_trip(trip_id, teacher))
    assert trip["status"] == "IN_PROGRESS"


# ─── Terminal-state lockdown ──────────────────────────────────────────────────
def test_terminal_completed_trip_cancel_locked_down(api):
    """PRD §3.9: "`COMPLETED` is terminal."
    PRD §3.10: "A trip may be cancelled from any state that is not already `COMPLETED` or `CANCELLED ... a cancel against a completed or cancelled trip is rejected with `ERR_TRIP_NOT_CANCELLABLE`."

    Design: Corner/state_machines/terminal_completed_trip_cancel_locked_down
    """
    bundle = setup_completed_trip()
    teacher_id, trip_id = bundle["teacher_id"], bundle["trip_id"]
    teacher = make_teacher_headers(teacher_id)
    trip = get_success_data(api.get_field_trip(trip_id, teacher))
    assert trip["status"] == "COMPLETED", f"setup should reach COMPLETED, got {trip['status']}"
    validate_error(api.cancel_trip(trip_id, _PRINCIPAL), "ERR_TRIP_NOT_CANCELLABLE")


# ─── Initial state ────────────────────────────────────────────────────────────
def test_initial_slip_states_on_creation(api):
    """PRD §3.3: "The slip begins with `signature_status` `UNSIGNED`, `payment_status` `UNPAID`, and `participation_status` `PENDING`."

    Design: Corner/state_machines/initial_slip_states_on_creation
    """
    teacher_id = create_teacher_guardian()
    trip = create_draft_trip(teacher_id, grade_band="ELEMENTARY", capacity=5)
    g = create_guardian(full_name="G16c")
    st = create_student(teacher_id, full_name="S16c", grade_level=5)
    slip = create_slip(teacher_id, trip["id"], st["id"], g["id"])
    assert slip["signature_status"] == "UNSIGNED"
    assert slip["payment_status"] == "UNPAID"
    assert slip["participation_status"] == "PENDING"
