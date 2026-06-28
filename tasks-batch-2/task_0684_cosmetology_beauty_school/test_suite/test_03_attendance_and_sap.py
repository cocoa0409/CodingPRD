"""Attendance accrual, void compensation, SAP pace evaluation, and the
ACTIVE<->SAP_WARNING fork.

Covers the SAP_WARNING branch (count bump only), the exact-67.00 passing
boundary, the void-conserves-actual-hours invariant, SAP recovery, the
enrollment version bump on approval, and the PATCH pace recompute.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_program, create_student, create_instructor, create_enrollment,
    create_approved_attendance, setup_enrollment_with_hours,
    create_attendance_payload,
    make_registrar_headers, make_instructor_headers,
)

REGISTRAR = make_registrar_headers()


# ==========================================================================
# non_linear_state_machine / enrollment_branching_fork_sap_vs_withdrawn (queue A)
# ==========================================================================
def test_evaluate_sap_forks_active_to_sap_warning(api):
    """PRD §3.2: "From `ACTIVE`, if pace is strictly below 67.00, the enrollment
    transitions to `SAP_WARNING`, its `sap_warning_count` is incremented by one,
    and its `version` is bumped."

    pace 600/900 = 66.67% < 67.00 forks ACTIVE -> SAP_WARNING.

    Design: Difficulty/non_linear_state_machine/enrollment_branching_fork_sap_vs_withdrawn
    """
    program, student, instructor, enrollment = setup_enrollment_with_hours(
        actual_hours=600, scheduled_hours_to_date=900,
    )
    data = validate_success(api.evaluate_sap(enrollment["id"], REGISTRAR))
    assert data["status"] == "SAP_WARNING"
    assert data["sap_warning_count"] == 1


def test_evaluate_sap_warning_branch_recomputes_pace(api):
    """PRD §3.2: "Pace is the student's `actual_hours` divided by
    `scheduled_hours_to_date`, multiplied by 100 and rounded half up to two
    decimal places."

    600/900*100 = 66.67, the value reported on the SAP_WARNING fork.

    Design: Difficulty/non_linear_state_machine/enrollment_branching_fork_sap_vs_withdrawn
    """
    program, student, instructor, enrollment = setup_enrollment_with_hours(
        actual_hours=600, scheduled_hours_to_date=900,
    )
    data = validate_success(api.evaluate_sap(enrollment["id"], REGISTRAR))
    assert data["pace_pct"] == 66.67, f"pace should be 66.67, got {data['pace_pct']}"
    assert data["sap_warning_count"] == 1


# ==========================================================================
# compensating_invariant / attendance_void_conserves_actual_hours  (queue A)
# ==========================================================================
def test_void_approved_attendance_conserves_actual_hours(api):
    """PRD §3.3: "Voiding an `APPROVED` record moves it to `VOIDED` and recomputes
    the enrollment's `actual_hours` downward by exactly that record's
    contribution — because the recompute is performed from scratch over the
    remaining approved records, the void leaves no residue."

    With a 200h and a 50h record both approved (actual 250), voiding the 50h
    record returns actual_hours to exactly 200.00.

    Design: Difficulty/compensating_invariant/attendance_void_conserves_actual_hours
    """
    program = create_program()
    student = create_student()
    instructor = create_instructor()
    enrollment = create_enrollment(
        program=program, student=student, scheduled_hours_to_date=300,
    )
    create_approved_attendance(enrollment["id"], instructor, 200,
                               session_date_iso="2026-05-01T00:00:00Z")
    rec2 = create_approved_attendance(enrollment["id"], instructor, 50,
                                      session_date_iso="2026-05-02T00:00:00Z")
    voided = validate_success(api.void_attendance(rec2["id"], REGISTRAR))
    assert voided["status"] == "VOIDED"
    enr = validate_success(api.get_enrollment(enrollment["id"], REGISTRAR))
    assert enr["actual_hours"] == 200.00, (
        f"actual_hours should return to 200.00, got {enr['actual_hours']}"
    )


def test_void_pending_attendance_no_hours_change(api):
    """PRD §3.3: "Voiding a record that is still `PENDING` also moves it to
    `VOIDED`, but since a pending record never contributed any hours, no
    enrollment recompute occurs."

    A never-approved record's void leaves the prior actual_hours total (200.00)
    unchanged — the conserved quantity.

    Design: Difficulty/compensating_invariant/attendance_void_conserves_actual_hours
    """
    program = create_program()
    student = create_student()
    instructor = create_instructor()
    enrollment = create_enrollment(
        program=program, student=student, scheduled_hours_to_date=300,
    )
    create_approved_attendance(enrollment["id"], instructor, 200)
    ins_headers = make_instructor_headers(instructor["id"])
    pending = validate_success(
        api.create_attendance(
            create_attendance_payload(
                enrollment["id"], instructor["id"], scheduled_hours=50, hours=50,
                session_date_iso="2026-05-03T00:00:00Z",
            ),
            ins_headers,
        ),
        201,
    )
    validate_success(api.void_attendance(pending["id"], REGISTRAR))
    enr = validate_success(api.get_enrollment(enrollment["id"], REGISTRAR))
    assert enr["actual_hours"] == 200.00, (
        f"voiding a PENDING record must not change actual_hours, got {enr['actual_hours']}"
    )


# ==========================================================================
# state_machines / sap_recovery_warning_to_active  (queue B)
# ==========================================================================
def test_sap_recovery_warning_to_active(api):
    """PRD §3.2: "From `SAP_WARNING`, if pace has recovered to at least 67.00, the
    enrollment returns to `ACTIVE` and its `version` is bumped."

    After 600/900 (warning), raising actual to 720 gives 80.00% which recovers to
    ACTIVE.

    Design: Corner/state_machines/sap_recovery_warning_to_active
    """
    program = create_program()
    student = create_student()
    instructor = create_instructor()
    enrollment = create_enrollment(
        program=program, student=student, scheduled_hours_to_date=900,
    )
    create_approved_attendance(enrollment["id"], instructor, 600,
                               session_date_iso="2026-05-01T00:00:00Z")
    warned = validate_success(api.evaluate_sap(enrollment["id"], REGISTRAR))
    assert warned["status"] == "SAP_WARNING"
    create_approved_attendance(enrollment["id"], instructor, 120,
                               scheduled_hours=120,
                               session_date_iso="2026-05-02T00:00:00Z")
    recovered = validate_success(api.evaluate_sap(enrollment["id"], REGISTRAR))
    assert recovered["status"] == "ACTIVE"
    assert recovered["pace_pct"] == 80.00, f"pace should be 80.00, got {recovered['pace_pct']}"


# ==========================================================================
# cross_cutting_complexity_layers / version_increments_on_attendance_approve (queue B)
# ==========================================================================
def test_enrollment_version_increments_on_attendance_approve(api):
    """PRD §2.4: "an integer `version` that begins at its initial value on creation
    and increments by one on every mutation of that resource."
    PRD §3.3: "On approval the enrollment's `actual_hours` is recomputed ... and
    the enrollment's `version` is bumped."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_attendance_approve
    """
    program = create_program()
    student = create_student()
    instructor = create_instructor()
    enrollment = create_enrollment(
        program=program, student=student, scheduled_hours_to_date=100,
    )
    v0 = enrollment["version"]
    create_approved_attendance(enrollment["id"], instructor, 50, scheduled_hours=50)
    enr = validate_success(api.get_enrollment(enrollment["id"], REGISTRAR))
    assert enr["version"] == v0 + 1, (
        f"version should increment from {v0} to {v0 + 1}, got {enr['version']}"
    )
    assert enr["actual_hours"] == 50.00


# ==========================================================================
# endpoints / patch_enrollment_updates_scheduled_hours  (queue B)
# ==========================================================================
def test_patch_enrollment_updates_scheduled_hours_and_pace(api):
    """PRD §3.2: "As the term progresses the Registrar updates
    `scheduled_hours_to_date` to reflect the curriculum calendar, and each such
    update recomputes the enrollment's pace."

    With actual_hours 0 and scheduled 900, pace recomputes to 0.00.

    Design: Corner/endpoints/patch_enrollment_updates_scheduled_hours
    """
    program = create_program()
    student = create_student()
    enrollment = create_enrollment(
        program=program, student=student, scheduled_hours_to_date=0,
    )
    data = validate_success(
        api.patch_enrollment(enrollment["id"], {"scheduled_hours_to_date": 900}, REGISTRAR)
    )
    assert data["scheduled_hours_to_date"] == 900
    assert data["pace_pct"] == 0.00, f"pace should be 0.00 with no hours, got {data['pace_pct']}"
