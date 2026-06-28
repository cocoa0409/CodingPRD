"""Instructor-license safety gates, validation precedence, attendance-shape
validation, and placement reporting.

Covers the state-before-safety precedence on clinic sign-off, the expired-license
block on attendance approval, the hours-exceed-scheduled rejection, the
approve-from-voided invalid-state, the empty-population placement report, and the
placement-report computed-read shape.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_program, create_student, create_instructor, create_enrollment,
    create_station, create_approved_attendance, setup_clinic_phase_enrollment,
    open_clinic_ticket, set_clock,
    create_attendance_payload,
    make_registrar_headers, make_instructor_headers,
)

REGISTRAR = make_registrar_headers()


# ==========================================================================
# priority_pair_validation_conflict / state_before_safety_on_clinic_signoff (queue A)
# ==========================================================================
def test_signoff_already_signed_off_returns_invalid_state_not_license(api):
    """PRD §3.3: "An `Instructor` signs off an `OPEN` clinic ticket once the
    service is complete, moving it to `SIGNED_OFF`. ... A pay or void requested
    against a ticket not in the required originating state is rejected with
    `ERR_INVALID_STATE`."
    PRD §2.10: "Only after a request is structurally sound does the server apply
    the domain-specific constraints: ... the state-machine precondition that the
    target resource is in a state from which the requested transition is defined
    (`ERR_INVALID_STATE`)."

    A second sign-off on an already SIGNED_OFF ticket — even with an
    expired-license instructor — fails the state check first.

    Design: Difficulty/priority_pair_validation_conflict/state_before_safety_on_clinic_signoff
    """
    # Instructor license expires 2026-05-15; sign off while still valid (clock
    # 2026-05-10), then advance past expiry and retry.
    program = create_program()
    student = create_student()
    instructor = create_instructor(license_expires_on="2026-05-15T00:00:00Z")
    # Build clinic-phase enrollment manually so we control the instructor + clock.
    station = create_station(label="Styling-8", station_type="HAIR")
    enrollment = create_enrollment(
        program=program, student=student, scheduled_hours_to_date=320,
    )
    create_approved_attendance(enrollment["id"], instructor, 320, scheduled_hours=320)
    set_clock("2026-05-10T00:00:00Z", REGISTRAR)
    ins_headers = make_instructor_headers(instructor["id"])
    ticket = open_clinic_ticket(
        enrollment["id"], station["id"], instructor,
        start_iso="2026-05-10T10:00:00Z", end_iso="2026-05-10T11:00:00Z",
        line_items=[{"service_code": "CUT", "salon_price_cents": 4000}],
        clinic_discount_pct=0.50,
    )
    get_success_data(api.sign_off_clinic_ticket(ticket["id"], ins_headers))
    set_clock("2026-06-01T00:00:00Z", REGISTRAR)  # now past license expiry
    validate_error(
        api.sign_off_clinic_ticket(ticket["id"], ins_headers),
        ApiErrorId.ERR_INVALID_STATE.value,
    )


def test_signoff_already_signed_off_ticket_stays_signed_off(api):
    """PRD §3.3: "A pay or void requested against a ticket not in the required
    originating state is rejected with `ERR_INVALID_STATE`."

    The blocked second sign-off leaves the ticket in SIGNED_OFF (no further
    transition).

    Design: Difficulty/priority_pair_validation_conflict/state_before_safety_on_clinic_signoff
    """
    program = create_program()
    student = create_student()
    instructor = create_instructor(license_expires_on="2026-05-15T00:00:00Z")
    station = create_station(label="Styling-8b", station_type="HAIR")
    enrollment = create_enrollment(
        program=program, student=student, scheduled_hours_to_date=320,
    )
    create_approved_attendance(enrollment["id"], instructor, 320, scheduled_hours=320)
    set_clock("2026-05-10T00:00:00Z", REGISTRAR)
    ins_headers = make_instructor_headers(instructor["id"])
    ticket = open_clinic_ticket(
        enrollment["id"], station["id"], instructor,
        start_iso="2026-05-10T10:00:00Z", end_iso="2026-05-10T11:00:00Z",
        line_items=[{"service_code": "CUT", "salon_price_cents": 4000}],
        clinic_discount_pct=0.50,
    )
    get_success_data(api.sign_off_clinic_ticket(ticket["id"], ins_headers))
    set_clock("2026-06-01T00:00:00Z", REGISTRAR)
    validate_error(
        api.sign_off_clinic_ticket(ticket["id"], ins_headers),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    still = validate_success(api.get_clinic_ticket(ticket["id"], REGISTRAR))
    assert still["status"] == "SIGNED_OFF"


# ==========================================================================
# validations / instructor_license_expired_blocks_attendance_approve  (queue B)
# ==========================================================================
def test_attendance_approve_expired_license_rejected(api):
    """PRD §3.3: "Approval is only permitted when the recording instructor is
    currently on staff (their `active` flag is true) and the instructor's
    `license_expires_on` is strictly later than the current logical-clock time; an
    inactive or expired-license instructor is rejected with
    `ERR_INSTRUCTOR_LICENSE_INVALID`."

    License expires 2026-05-15; clock advanced to 2026-06-01 before approval.

    Design: Corner/validations/instructor_license_expired_blocks_attendance_approve
    """
    program = create_program()
    student = create_student()
    instructor = create_instructor(license_expires_on="2026-05-15T00:00:00Z")
    enrollment = create_enrollment(
        program=program, student=student, scheduled_hours_to_date=100,
    )
    ins_headers = make_instructor_headers(instructor["id"])
    rec = validate_success(
        api.create_attendance(
            create_attendance_payload(
                enrollment["id"], instructor["id"], scheduled_hours=50, hours=50,
            ),
            ins_headers,
        ),
        201,
    )
    set_clock("2026-06-01T00:00:00Z", REGISTRAR)
    validate_error(
        api.approve_attendance(rec["id"], ins_headers),
        ApiErrorId.ERR_INSTRUCTOR_LICENSE_INVALID.value,
    )


# ==========================================================================
# validations / attendance_hours_exceed_scheduled_rejected  (queue B)
# ==========================================================================
def test_attendance_hours_exceed_scheduled_rejected(api):
    """PRD §3.3: "The recorded `hours` may not exceed the session's
    `scheduled_hours`; a record whose `hours` is greater than its
    `scheduled_hours` is rejected with `ERR_HOURS_EXCEED_SCHEDULED`."

    hours 60 > scheduled_hours 50.

    Design: Corner/validations/attendance_hours_exceed_scheduled_rejected
    """
    program = create_program()
    student = create_student()
    instructor = create_instructor()
    enrollment = create_enrollment(
        program=program, student=student, scheduled_hours_to_date=100,
    )
    resp = api.create_attendance(
        create_attendance_payload(
            enrollment["id"], instructor["id"], scheduled_hours=50, hours=60,
        ),
        make_instructor_headers(instructor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_HOURS_EXCEED_SCHEDULED.value)


# ==========================================================================
# state_machines / approve_attendance_from_voided_returns_invalid_state (queue B)
# ==========================================================================
def test_approve_voided_attendance_invalid_state(api):
    """PRD §3.3: "An `Instructor` approves a `PENDING` attendance record, moving it
    to `APPROVED`." A void requested on a PENDING record moves it to VOIDED; a
    subsequent approve is an undefined transition.
    PRD §2.10: "the state-machine precondition that the target resource is in a
    state from which the requested transition is defined (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/approve_attendance_from_voided_returns_invalid_state
    """
    program = create_program()
    student = create_student()
    instructor = create_instructor()
    enrollment = create_enrollment(
        program=program, student=student, scheduled_hours_to_date=100,
    )
    ins_headers = make_instructor_headers(instructor["id"])
    rec = validate_success(
        api.create_attendance(
            create_attendance_payload(
                enrollment["id"], instructor["id"], scheduled_hours=50, hours=50,
            ),
            ins_headers,
        ),
        201,
    )
    get_success_data(api.void_attendance(rec["id"], REGISTRAR))
    validate_error(
        api.approve_attendance(rec["id"], ins_headers),
        ApiErrorId.ERR_INVALID_STATE.value,
    )


# ==========================================================================
# boundary_precision_check / placement_report_zero_eligible_empty_set  (queue A)
# ==========================================================================
def test_placement_report_zero_graduates_zero_rate(api):
    """PRD §3.8: "If that denominator is zero or below, the `placement_rate_pct` is
    reported as 0 (there is no division by zero)."

    A program with no graduates reports total_graduates 0 and placement_rate_pct 0.

    Design: Difficulty/boundary_precision_check/placement_report_zero_eligible_empty_set
    """
    program = create_program(
        name="Esthetics 600", total_clock_hours=600, tuition_cents=500000,
        kit_fee_cents=80000, lab_fee_cents=20000, clinic_phase_start_hour=150,
    )
    data = validate_success(api.get_placement_report(program["id"], REGISTRAR))
    assert data["total_graduates"] == 0
    assert data["placement_rate_pct"] == 0


def test_placement_report_zero_placed_count_empty_population(api):
    """PRD §3.8: "Across the program's `GRADUATED` enrollments, count the
    `total_graduates`; count the `excluded_count` of those whose
    `placement_status` is `EXCLUDED`; and count the `placed_count` of those whose
    `placement_status` is `PLACED`."

    With no graduates, placed_count is 0.

    Design: Difficulty/boundary_precision_check/placement_report_zero_eligible_empty_set
    """
    program = create_program(
        name="Esthetics 600", total_clock_hours=600, tuition_cents=500000,
        kit_fee_cents=80000, lab_fee_cents=20000, clinic_phase_start_hour=150,
    )
    data = validate_success(api.get_placement_report(program["id"], REGISTRAR))
    assert data["placed_count"] == 0


# ==========================================================================
# endpoints / placement_report_computed_read  (queue B)
# ==========================================================================
def test_placement_report_returns_program_id_and_rate(api):
    """PRD §3.8: "The report returns the `program_id` together with
    `total_graduates`, `excluded_count`, `placed_count`, and
    `placement_rate_pct`." With an empty graduate population the rate is 0.

    Design: Corner/endpoints/placement_report_computed_read
    """
    program = create_program()
    data = validate_success(api.get_placement_report(program["id"], REGISTRAR))
    assert data["program_id"] == program["id"]
    assert data["placement_rate_pct"] == 0
