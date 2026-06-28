"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server with an empty DB before each test).
Helpers use get_success_data() so a setup failure surfaces as a clear
"Setup step failed" rather than a confusing downstream assertion error.

Identity threading: Instructor and Student are entity_backed roles. Whenever a
fixture issues an ownership/identity-gated call it uses make_instructor_headers
or make_student_headers with the real entity id, never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    make_registrar_headers,
    make_financial_aid_officer_headers,
    make_instructor_headers,
    make_student_headers,
)
from .factories import (
    create_program_payload,
    create_student_payload,
    create_instructor_payload,
    create_station_payload,
    create_enrollment_payload,
    create_attendance_payload,
    create_clinic_ticket_payload,
    create_station_assignment_payload,
    create_disbursement_payload,
    create_exam_application_payload,
    create_withdrawal_payload,
)

REGISTRAR = make_registrar_headers()
FAO = make_financial_aid_officer_headers()


# --------------------------------------------------------------------------
# Tier 0: clock control (PRD §2.9)
# --------------------------------------------------------------------------
def set_clock(to_iso8601, headers=None):
    """Set the server logical clock. Registrar/FAO may set the clock."""
    return get_success_data(api_client.set_clock(to_iso8601, headers or REGISTRAR))


# --------------------------------------------------------------------------
# Tier 1: reference-data builders
# --------------------------------------------------------------------------
def create_program(**overrides) -> dict:
    return get_success_data(
        api_client.create_program(create_program_payload(**overrides), REGISTRAR)
    )


def create_student(**overrides) -> dict:
    return get_success_data(
        api_client.create_student(create_student_payload(**overrides), REGISTRAR)
    )


def create_instructor(**overrides) -> dict:
    return get_success_data(
        api_client.create_instructor(create_instructor_payload(**overrides), REGISTRAR)
    )


def create_station(**overrides) -> dict:
    return get_success_data(
        api_client.create_station(create_station_payload(**overrides), REGISTRAR)
    )


# --------------------------------------------------------------------------
# Tier 2: enrollment builders
# --------------------------------------------------------------------------
def create_enrollment(program=None, student=None, **overrides) -> dict:
    """Create an ACTIVE enrollment. Auto-creates program/student if not given."""
    program = program or create_program()
    student = student or create_student()
    return get_success_data(
        api_client.create_enrollment(
            create_enrollment_payload(student["id"], program["id"], **overrides),
            REGISTRAR,
        )
    )


def setup_program_student_instructor(program_overrides=None, **_):
    """Active program + PROSPECT student + active instructor. Returns the triple."""
    program = create_program(**(program_overrides or {}))
    student = create_student()
    instructor = create_instructor()
    return program, student, instructor


# --------------------------------------------------------------------------
# Tier 3: hours accrual (the workhorse for actual_hours thresholds)
# --------------------------------------------------------------------------
def create_approved_attendance(enrollment_id, instructor, hours, scheduled_hours=None,
                               session_date_iso="2026-05-01T00:00:00Z"):
    """Record + approve one attendance session, accruing `hours` of actual time.
    scheduled_hours defaults to `hours`. Returns the approved record."""
    sched = hours if scheduled_hours is None else scheduled_hours
    ins_headers = make_instructor_headers(instructor["id"])
    rec = get_success_data(
        api_client.create_attendance(
            create_attendance_payload(
                enrollment_id, instructor["id"],
                scheduled_hours=sched, hours=hours,
                session_date_iso=session_date_iso,
            ),
            ins_headers,
        )
    )
    return get_success_data(api_client.approve_attendance(rec["id"], ins_headers))


def setup_enrollment_with_hours(actual_hours, scheduled_hours_to_date,
                                program_overrides=None, instructor=None):
    """Active enrollment whose actual_hours == `actual_hours` via one approved
    attendance record, with the given scheduled_hours_to_date.
    Returns (program, student, instructor, enrollment)."""
    program = create_program(**(program_overrides or {}))
    student = create_student()
    instructor = instructor or create_instructor()
    enrollment = create_enrollment(
        program=program, student=student,
        scheduled_hours_to_date=scheduled_hours_to_date,
    )
    create_approved_attendance(enrollment["id"], instructor, actual_hours)
    enrollment = get_success_data(api_client.get_enrollment(enrollment["id"], REGISTRAR))
    return program, student, instructor, enrollment


# --------------------------------------------------------------------------
# Tier 4: disbursement lifecycle
# --------------------------------------------------------------------------
def schedule_disbursement(enrollment_id, **overrides) -> dict:
    """Create a SCHEDULED disbursement. Returns it."""
    return get_success_data(
        api_client.create_disbursement(
            create_disbursement_payload(enrollment_id, **overrides), FAO,
        )
    )


def post_disbursement(disbursement_id, enrollment_id):
    """Read the live enrollment version, then post the disbursement (OCC-guarded).
    Returns the posted disbursement."""
    enr = get_success_data(api_client.get_enrollment(enrollment_id, FAO))
    return get_success_data(
        api_client.post_disbursement(disbursement_id, enr["version"], FAO)
    )


def setup_posted_disbursement(net_overrides=None, program_overrides=None,
                              actual_hours=405, period_hours=400, period_weeks=4,
                              gross_amount_cents=600000, origination_fee_cents=0,
                              scheduled_hours_to_date=450,
                              post_clock_iso="2026-06-01T00:00:00Z"):
    """Full chain to one POSTED disbursement on an ACTIVE enrollment.
    Advances the clock so the time gate clears. Returns
    (program, student, instructor, enrollment, disbursement)."""
    program = create_program(**(program_overrides or {}))
    student = create_student()
    instructor = create_instructor()
    enrollment = create_enrollment(
        program=program, student=student,
        scheduled_hours_to_date=scheduled_hours_to_date,
    )
    create_approved_attendance(enrollment["id"], instructor, actual_hours)
    set_clock(post_clock_iso, FAO)
    dis = schedule_disbursement(
        enrollment["id"], period_hours=period_hours, period_weeks=period_weeks,
        gross_amount_cents=gross_amount_cents, origination_fee_cents=origination_fee_cents,
    )
    post_disbursement(dis["id"], enrollment["id"])
    enrollment = get_success_data(api_client.get_enrollment(enrollment["id"], FAO))
    dis = get_success_data(api_client.get_disbursement(dis["id"], FAO))
    return program, student, instructor, enrollment, dis


def setup_scheduled_disbursement_ready_to_post(program_overrides=None,
                                               actual_hours=405, period_hours=400,
                                               period_weeks=4, gross_amount_cents=600000,
                                               origination_fee_cents=0,
                                               scheduled_hours_to_date=450,
                                               post_clock_iso="2026-06-01T00:00:00Z"):
    """An ACTIVE enrollment with a SCHEDULED (not yet posted) disbursement, clock
    advanced. Returns (program, student, instructor, enrollment, disbursement)."""
    program = create_program(**(program_overrides or {}))
    student = create_student()
    instructor = create_instructor()
    enrollment = create_enrollment(
        program=program, student=student,
        scheduled_hours_to_date=scheduled_hours_to_date,
    )
    create_approved_attendance(enrollment["id"], instructor, actual_hours)
    set_clock(post_clock_iso, FAO)
    dis = schedule_disbursement(
        enrollment["id"], period_hours=period_hours, period_weeks=period_weeks,
        gross_amount_cents=gross_amount_cents, origination_fee_cents=origination_fee_cents,
    )
    enrollment = get_success_data(api_client.get_enrollment(enrollment["id"], FAO))
    return program, student, instructor, enrollment, dis


# --------------------------------------------------------------------------
# Tier 5: clinic-floor builders
# --------------------------------------------------------------------------
def setup_clinic_phase_enrollment(program_overrides=None, actual_hours=320,
                                  scheduled_hours_to_date=320, station_type="HAIR",
                                  station_label="Styling-1",
                                  clock_iso="2026-06-01T00:00:00Z"):
    """An enrollment past the clinic phase (actual_hours >= clinic_phase_start_hour)
    plus a station, clock advanced. Returns (program, student, instructor,
    station, enrollment)."""
    program = create_program(**(program_overrides or {}))
    student = create_student()
    instructor = create_instructor()
    station = create_station(label=station_label, station_type=station_type)
    enrollment = create_enrollment(
        program=program, student=student,
        scheduled_hours_to_date=scheduled_hours_to_date,
    )
    create_approved_attendance(enrollment["id"], instructor, actual_hours)
    set_clock(clock_iso, REGISTRAR)
    enrollment = get_success_data(api_client.get_enrollment(enrollment["id"], REGISTRAR))
    return program, student, instructor, station, enrollment


def open_clinic_ticket(enrollment_id, station_id, instructor, **overrides) -> dict:
    """Open a clinic ticket (sets station OCCUPIED). Returns the OPEN ticket."""
    return get_success_data(
        api_client.create_clinic_ticket(
            create_clinic_ticket_payload(
                enrollment_id, station_id, instructor["id"], **overrides,
            ),
            make_instructor_headers(instructor["id"]),
        )
    )


def open_station_assignment(station_id, enrollment_id, instructor, **overrides) -> dict:
    """Reserve a station over a window. Returns the RESERVED assignment."""
    return get_success_data(
        api_client.create_station_assignment(
            create_station_assignment_payload(
                station_id, enrollment_id, instructor["id"], **overrides,
            ),
            make_instructor_headers(instructor["id"]),
        )
    )


# --------------------------------------------------------------------------
# Tier 6: exam-application lifecycle
# --------------------------------------------------------------------------
def create_exam_application(enrollment_id, student, **overrides) -> dict:
    """Create a DRAFT exam application owned by `student`. Returns it."""
    return get_success_data(
        api_client.create_exam_application(
            create_exam_application_payload(enrollment_id, **overrides),
            make_student_headers(student["id"]),
        )
    )


def setup_submitted_exam_application(actual_hours=1350, total_clock_hours=1500,
                                     mock_exam_avg=85, competency_signoff_pct=100,
                                     scheduled_hours_to_date=1400):
    """An enrollment with `actual_hours` accrued plus a SUBMITTED exam application.
    Returns (program, student, instructor, enrollment, application)."""
    program = create_program(total_clock_hours=total_clock_hours)
    student = create_student()
    instructor = create_instructor()
    enrollment = create_enrollment(
        program=program, student=student,
        scheduled_hours_to_date=scheduled_hours_to_date,
    )
    create_approved_attendance(enrollment["id"], instructor, actual_hours)
    app = create_exam_application(
        enrollment["id"], student,
        mock_exam_avg=mock_exam_avg, competency_signoff_pct=competency_signoff_pct,
    )
    app = get_success_data(
        api_client.submit_exam_application(app["id"], make_student_headers(student["id"]))
    )
    return program, student, instructor, enrollment, app


def setup_scheduled_exam_application(actual_hours=1350, total_clock_hours=1500,
                                     mock_exam_avg=85, competency_signoff_pct=100,
                                     scheduled_hours_to_date=1400):
    """An exam application driven all the way to SCHEDULED for an EXAM_PENDING
    enrollment (submit -> approve -> schedule). Returns
    (program, student, instructor, enrollment, application)."""
    program, student, instructor, enrollment, app = setup_submitted_exam_application(
        actual_hours=actual_hours, total_clock_hours=total_clock_hours,
        mock_exam_avg=mock_exam_avg, competency_signoff_pct=competency_signoff_pct,
        scheduled_hours_to_date=scheduled_hours_to_date,
    )
    get_success_data(api_client.approve_exam_application(app["id"], REGISTRAR))
    app = get_success_data(api_client.schedule_exam_application(app["id"], REGISTRAR))
    enrollment = get_success_data(api_client.get_enrollment(enrollment["id"], REGISTRAR))
    return program, student, instructor, enrollment, app


# --------------------------------------------------------------------------
# Tier 7: withdrawal lifecycle
# --------------------------------------------------------------------------
def create_withdrawal(enrollment_id, **overrides) -> dict:
    """Create a CALCULATED withdrawal. Returns it."""
    return get_success_data(
        api_client.create_withdrawal(
            create_withdrawal_payload(enrollment_id, **overrides), FAO,
        )
    )


def setup_calculated_withdrawal_with_posted_disbursement(
        program_overrides=None, actual_hours=405, scheduled_hours_to_date=450,
        gross_amount_cents=600000, origination_fee_cents=0,
        last_date_of_attendance_iso="2026-05-01T00:00:00Z",
        post_clock_iso="2026-06-01T00:00:00Z"):
    """Full chain to a CALCULATED withdrawal on an enrollment that already has one
    POSTED disbursement. Returns (program, student, instructor, enrollment,
    disbursement, withdrawal)."""
    program, student, instructor, enrollment, dis = setup_posted_disbursement(
        program_overrides=program_overrides, actual_hours=actual_hours,
        scheduled_hours_to_date=scheduled_hours_to_date,
        gross_amount_cents=gross_amount_cents, origination_fee_cents=origination_fee_cents,
        post_clock_iso=post_clock_iso,
    )
    wd = create_withdrawal(
        enrollment["id"], last_date_of_attendance_iso=last_date_of_attendance_iso,
    )
    enrollment = get_success_data(api_client.get_enrollment(enrollment["id"], FAO))
    return program, student, instructor, enrollment, dis, wd
