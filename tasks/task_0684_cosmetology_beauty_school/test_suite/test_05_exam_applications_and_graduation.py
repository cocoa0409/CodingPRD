"""State-board exam readiness scoring, the revision cycle, approval gate,
result recording, and the graduation fiscal gate.

Covers the three-factor readiness score with per-term rounding, the
SUBMITTED -> RETURNED_FOR_REVISION -> SUBMITTED cycle, the state-before-fiscal
precedence on record-result, the not-ready approval block, the FAILED revert,
and the outstanding-balance graduation block.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_program, create_student, create_instructor, create_enrollment,
    create_approved_attendance, create_exam_application,
    setup_submitted_exam_application, setup_scheduled_exam_application,
    make_registrar_headers, make_student_headers,
)

REGISTRAR = make_registrar_headers()


# ==========================================================================
# combinatorial_formula / exam_readiness_three_factor_gated_score  (queue A)
# ==========================================================================
def test_exam_readiness_three_factor_score(api):
    """PRD §3.7: "form three weighted terms, each rounded half up to two decimal
    places on its own: the first is 0.40 times the capped hours factor; the second
    is 0.35 times the `mock_exam_avg`; the third is 0.25 times the
    `competency_signoff_pct`. The `readiness_score` is the sum of those three
    already-rounded terms — each term is rounded before summing, not after."

    hours 1350/1500=90 capped at 90: 0.40*90=36.00 + 0.35*85=29.75 + 0.25*100=25.00
    = 90.75.

    Design: Difficulty/combinatorial_formula/exam_readiness_three_factor_gated_score
    """
    program, student, instructor, enrollment, app = setup_submitted_exam_application(
        actual_hours=1350, total_clock_hours=1500,
        mock_exam_avg=85, competency_signoff_pct=100, scheduled_hours_to_date=1400,
    )
    assert app["readiness_score"] == 90.75, (
        f"readiness_score should be 90.75, got {app['readiness_score']}"
    )


def test_exam_submit_sets_submitted_status(api):
    """PRD §3.7: "The student submits the application, moving it from `DRAFT` to
    `SUBMITTED` ... Either submission requires the owning enrollment to be in
    `ACTIVE` or `SAP_WARNING` status, and recomputes the application's
    `readiness_score` and bumps the application's `version`."

    Design: Difficulty/combinatorial_formula/exam_readiness_three_factor_gated_score
    """
    program, student, instructor, enrollment, app = setup_submitted_exam_application(
        actual_hours=1350, total_clock_hours=1500,
        mock_exam_avg=85, competency_signoff_pct=100, scheduled_hours_to_date=1400,
    )
    assert app["status"] == "SUBMITTED"


# ==========================================================================
# non_linear_state_machine / exam_application_revision_cycle  (queue A)
# ==========================================================================
def test_exam_revision_cycle_resubmit_returns_to_submitted(api):
    """PRD §3.7: "the same submit action also moves an application from
    `RETURNED_FOR_REVISION` back to `SUBMITTED`, forming a revision cycle."

    DRAFT -> SUBMITTED -> RETURNED_FOR_REVISION -> SUBMITTED.

    Design: Difficulty/non_linear_state_machine/exam_application_revision_cycle
    """
    program, student, instructor, enrollment, app = setup_submitted_exam_application(
        actual_hours=1350, total_clock_hours=1500,
        mock_exam_avg=50, competency_signoff_pct=100, scheduled_hours_to_date=1400,
    )
    get_success_data(api.return_exam_application(app["id"], REGISTRAR))
    resubmitted = validate_success(
        api.submit_exam_application(app["id"], make_student_headers(student["id"]))
    )
    assert resubmitted["status"] == "SUBMITTED"


def test_exam_revision_cycle_recomputes_readiness_on_resubmit(api):
    """PRD §3.7: "Either submission ... recomputes the application's
    `readiness_score`."

    hours 1350/1500=90 capped: 0.40*90=36.00 + 0.35*50=17.50 + 0.25*100=25.00 =
    78.50, recomputed again on the second submit.

    Design: Difficulty/non_linear_state_machine/exam_application_revision_cycle
    """
    program, student, instructor, enrollment, app = setup_submitted_exam_application(
        actual_hours=1350, total_clock_hours=1500,
        mock_exam_avg=50, competency_signoff_pct=100, scheduled_hours_to_date=1400,
    )
    get_success_data(api.return_exam_application(app["id"], REGISTRAR))
    resubmitted = validate_success(
        api.submit_exam_application(app["id"], make_student_headers(student["id"]))
    )
    assert resubmitted["readiness_score"] == 78.50, (
        f"recomputed readiness should be 78.50, got {resubmitted['readiness_score']}"
    )


# ==========================================================================
# priority_pair_validation_conflict / state_before_fiscal_on_record_result (queue A)
# ==========================================================================
def test_record_result_on_draft_returns_invalid_state_not_balance(api):
    """PRD §3.7: "Recording a result against an application not in `SCHEDULED`
    status is rejected with `ERR_INVALID_STATE`."
    PRD §2.10: "the state-machine precondition that the target resource is in a
    state from which the requested transition is defined (`ERR_INVALID_STATE`),
    resource-ownership checks ..., and finally the optimistic-concurrency version
    check."

    A DRAFT application whose enrollment also has an outstanding balance fails the
    state check first, so ERR_INVALID_STATE (not ERR_OUTSTANDING_BALANCE).

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_record_result
    """
    program = create_program()
    student = create_student()
    enrollment = create_enrollment(
        program=program, student=student, scheduled_hours_to_date=100,
    )
    app = create_exam_application(
        enrollment["id"], student, mock_exam_avg=90, competency_signoff_pct=100,
    )
    validate_error(
        api.record_exam_result(app["id"], "PASSED", REGISTRAR),
        ApiErrorId.ERR_INVALID_STATE.value,
    )


def test_record_result_on_draft_leaves_application_draft(api):
    """PRD §3.7: "Recording a result against an application not in `SCHEDULED`
    status is rejected with `ERR_INVALID_STATE`."

    The rejected record-result must leave the application unchanged in DRAFT.

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_record_result
    """
    program = create_program()
    student = create_student()
    enrollment = create_enrollment(
        program=program, student=student, scheduled_hours_to_date=100,
    )
    app = create_exam_application(
        enrollment["id"], student, mock_exam_avg=90, competency_signoff_pct=100,
    )
    validate_error(
        api.record_exam_result(app["id"], "PASSED", REGISTRAR),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    still = validate_success(api.get_exam_application(app["id"], REGISTRAR))
    assert still["status"] == "DRAFT"


# ==========================================================================
# state_machines / exam_approve_not_ready_returns_error  (queue B)
# ==========================================================================
def test_exam_approve_not_ready_rejected(api):
    """PRD §3.7: "approval is gated: it requires the `readiness_score` to be at
    least 80 ... If any of those readiness conditions is unmet, approval is
    rejected with `ERR_EXAM_NOT_READY`."

    readiness 78.50 < 80 blocks approval; enrollment stays ACTIVE.

    Design: Corner/state_machines/exam_approve_not_ready_returns_error
    """
    program, student, instructor, enrollment, app = setup_submitted_exam_application(
        actual_hours=1350, total_clock_hours=1500,
        mock_exam_avg=50, competency_signoff_pct=100, scheduled_hours_to_date=1400,
    )
    validate_error(
        api.approve_exam_application(app["id"], REGISTRAR),
        ApiErrorId.ERR_EXAM_NOT_READY.value,
    )
    enr = validate_success(api.get_enrollment(enrollment["id"], REGISTRAR))
    assert enr["status"] == "ACTIVE"


# ==========================================================================
# state_machines / exam_result_failed_reverts_enrollment_to_active  (queue B)
# ==========================================================================
def test_exam_result_failed_reverts_enrollment_to_active(api):
    """PRD §3.7: "Recording `FAILED` instead reverts the owning enrollment from
    `EXAM_PENDING` back to `ACTIVE` so a retake may be pursued, bumping the
    enrollment's `version`."

    Design: Corner/state_machines/exam_result_failed_reverts_enrollment_to_active
    """
    program, student, instructor, enrollment, app = setup_scheduled_exam_application(
        actual_hours=1350, total_clock_hours=1500,
        mock_exam_avg=85, competency_signoff_pct=100, scheduled_hours_to_date=1400,
    )
    result = validate_success(api.record_exam_result(app["id"], "FAILED", REGISTRAR))
    assert result["status"] == "FAILED"
    enr = validate_success(api.get_enrollment(enrollment["id"], REGISTRAR))
    assert enr["status"] == "ACTIVE"


# ==========================================================================
# state_machines / graduate_blocked_by_outstanding_balance  (queue B)
# ==========================================================================
def test_graduate_blocked_by_outstanding_balance(api):
    """PRD §3.7: "An outstanding balance — a `ledger_balance_cents` greater than 0
    — blocks graduation and the result recording is rejected with
    `ERR_OUTSTANDING_BALANCE`."

    Full hours (1500) but ledger_balance 1400000 > 0; enrollment stays EXAM_PENDING.

    Design: Corner/state_machines/graduate_blocked_by_outstanding_balance
    """
    program, student, instructor, enrollment, app = setup_scheduled_exam_application(
        actual_hours=1500, total_clock_hours=1500,
        mock_exam_avg=85, competency_signoff_pct=100, scheduled_hours_to_date=1500,
    )
    validate_error(
        api.record_exam_result(app["id"], "PASSED", REGISTRAR),
        ApiErrorId.ERR_OUTSTANDING_BALANCE.value,
    )
    enr = validate_success(api.get_enrollment(enrollment["id"], REGISTRAR))
    assert enr["status"] == "EXAM_PENDING"
