"""State-machine preconditions, transitions, side effects, and terminal locks.

Corner-design queue B: section `state_machines`.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    make_instructor_headers, make_guardian_headers,
    set_clock, create_student, create_granted_consent,
    setup_classroom_scheduling_context,
    setup_submitted_certificate, setup_licensed_student,
    schedule_lesson,
)

ADMIN = TEST_USERS["admin_headers"]


def test_complete_lesson_before_end_returns_invalid_state(api):
    """PRD §3.7: "Completion moves the lesson from `SCHEDULED` to `COMPLETED`
    and is legal only from `SCHEDULED` and only once the current clock has
    reached or passed the lesson's `end_at`; an early attempt is an
    invalid-state rejection."

    Design: Corner/state_machines/complete_lesson_before_end_returns_invalid_state
    """
    set_clock("2026-06-10T08:00:00.000Z")
    ctx = setup_classroom_scheduling_context(package_overrides={
        "included_classroom_hours": 30, "included_online_hours": 0,
        "included_road_hours": 0, "enrollment_fee_cents": 0,
        "bundle_discount_cents": 0, "price_cents": 60000,
    })
    lesson = schedule_lesson(
        ctx["student"]["id"], ctx["enrollment"]["id"], "CLASSROOM",
        "2026-06-10T09:00:00.000Z", "2026-06-10T10:00:00.000Z",
        instructor_id=ctx["instructor"]["id"],
    )
    set_clock("2026-06-10T08:30:00.000Z")  # before end_at
    resp = api.complete_lesson(
        lesson["id"], make_instructor_headers(ctx["instructor"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_lesson(lesson["id"], ADMIN))
    assert after["status"] == "SCHEDULED"


def test_grant_already_granted_consent_returns_invalid_state(api):
    """PRD §3.2: "The named guardian grants it, moving it from `PENDING` to
    `GRANTED`; this transition is legal only while the consent sits at
    `PENDING`, and an attempt from any other state is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/grant_already_granted_consent_returns_invalid_state
    """
    set_clock("2026-06-01T00:00:00.000Z")
    stu = create_student(full_name="Gee Gee", email="geegee@x.com",
                        date_of_birth="2010-01-01")
    consent = create_granted_consent(stu["id"], guardian_name="Greg G",
                                    guardian_email="greg@x.com")
    resp = api.grant_consent(consent["id"], make_guardian_headers(consent["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_guardian_consent(consent["id"], ADMIN))
    assert after["status"] == "GRANTED"


def test_dmv_callback_accepted_bubbles_student_to_licensed(api):
    """PRD §3.10: "an `ACCEPTED` outcome moves the certificate from `SUBMITTED`
    to `ACCEPTED` and bubbles the student from `CERTIFIED` to `LICENSED`."

    Design: Corner/state_machines/dmv_callback_accepted_bubbles_student_to_licensed
    """
    ctx = setup_submitted_certificate()
    resp = api.dmv_callback(ctx["certificate"]["id"], {"outcome": "ACCEPTED"}, ADMIN)
    cert = validate_success(resp)
    assert cert["status"] == "ACCEPTED"
    student = validate_success(api.get_student(ctx["student"]["id"], ADMIN))
    assert student["status"] == "LICENSED"


def test_record_permit_on_licensed_student_returns_invalid_state(api):
    """PRD §3.3: "Recording a learner permit is a `SchoolAdmin` action that
    supplies a non-empty `permit_number` and advances the student from
    `ENROLLED` to `PERMITTED`. It is legal only while the student is at
    `ENROLLED`; from any other milestone it is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/terminal_licensed_student_record_permit_rejected
    """
    ctx = setup_licensed_student()
    assert ctx["student"]["status"] == "LICENSED"
    resp = api.record_permit(ctx["student"]["id"], {"permit_number": "P-AGAIN"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_student(ctx["student"]["id"], ADMIN))
    assert after["status"] == "LICENSED"

# NOTE: Corner/state_machines/cancel_lesson_inside_cutoff_window_rejected is
# SKIPPED. The PRD (§3.9) never states a numeric value for the cancellation
# cutoff lead time, so whether a clock 30 minutes before start_at falls inside
# the window is not uniquely derivable from PRD prose — a faithful PRD-only
# implementer could pick a cutoff under 30 minutes and legitimately allow the
# cancel. The asserted outcome is therefore not pinned (Core rule, unique
# derivability fails).
