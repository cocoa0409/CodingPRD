"""Stage-check and endorsement claims: the FAILED -> retry SCHEDULED -> IN_PROGRESS
cycle, the in-order stage gate, the PASSED terminal lock, endorsement
authorization, and the revoke-already-revoked precondition.
"""
from test_helpers import (
    get_success_data, validate_error,
    ApiErrorId,
    setup_active_enrollment, setup_failed_stage_check, setup_passed_stage_check,
    create_student, create_syllabus, create_enrollment, create_instructor,
    schedule_stage_check, issue_endorsement,
    get_stage_check, get_enrollment, get_endorsement,
    make_instructor_headers,
)


def test_failed_stage_check_retry_reenters_in_progress(api):
    """PRD §3.6: "Failing likewise requires `IN_PROGRESS`, otherwise
    `ERR_STAGE_CHECK_NOT_IN_PROGRESS`; a fail moves the check to `FAILED` and leaves
    `current_stage_index` unchanged. `FAILED` is not a dead end: a fresh stage check
    may later be scheduled with its `retry_of_stage_check_id` referencing this failed
    one, which restarts the loop at `SCHEDULED`."

    Design: Difficulty/non_linear_state_machine/stage_check_cyclic_failed_retry_scheduled
    """
    ctx = setup_failed_stage_check(stage_index=1)
    assert ctx["stage_check"]["status"] == "FAILED"
    assert get_enrollment(ctx["enrollment"]["id"])["current_stage_index"] == 1

    instr_id = ctx["instructor"]["id"]
    retry = schedule_stage_check(
        ctx["enrollment"]["id"], instr_id, 1,
        retry_of_stage_check_id=ctx["stage_check"]["id"],
    )
    assert retry["retry_of_stage_check_id"] == ctx["stage_check"]["id"]
    assert retry["status"] == "SCHEDULED"

    begun = get_success_data(api.begin_stage_check(retry["id"], make_instructor_headers(instr_id)))
    assert begun["status"] == "IN_PROGRESS"


def test_failed_stage_check_leaves_index_unchanged(api):
    """PRD §3.6: "a fail moves the check to `FAILED` and leaves `current_stage_index`
    unchanged."

    Design: Difficulty/non_linear_state_machine/stage_check_cyclic_failed_retry_scheduled
    """
    ctx = setup_failed_stage_check(stage_index=1)
    assert get_stage_check(ctx["stage_check"]["id"])["status"] == "FAILED"
    assert get_enrollment(ctx["enrollment"]["id"])["current_stage_index"] == 1


def test_begin_stage_check_out_of_order_rejected(api):
    """PRD §3.6: "the check's `stage_index` must equal the enrollment's
    `current_stage_index`, ensuring stages are attempted in order, or it is rejected
    with `ERR_STAGE_OUT_OF_ORDER`."

    Design: Corner/state_machines/stage_check_begin_out_of_order_rejected
    """
    base = setup_active_enrollment(deposit_cents=60000)  # current_stage_index == 1
    sc = schedule_stage_check(base["enrollment"]["id"], base["instructor"]["id"], 2)
    validate_error(
        api.begin_stage_check(sc["id"], make_instructor_headers(base["instructor"]["id"])),
        ApiErrorId.ERR_STAGE_OUT_OF_ORDER.value,
    )


def test_passed_stage_check_cannot_be_failed(api):
    """PRD §3.6: "Failing likewise requires `IN_PROGRESS`, otherwise
    `ERR_STAGE_CHECK_NOT_IN_PROGRESS`..."
    PRD §3.6: "a pass moves it to `PASSED` and increments the enrollment's
    `current_stage_index` by one, opening the next stage."

    Design: Corner/state_machines/terminal_passed_stage_check_cannot_fail
    """
    ctx = setup_passed_stage_check(stage_index=1)
    assert ctx["stage_check"]["status"] == "PASSED"
    assert get_enrollment(ctx["enrollment"]["id"])["current_stage_index"] == 2
    validate_error(
        api.fail_stage_check(ctx["stage_check"]["id"], make_instructor_headers(ctx["instructor"]["id"])),
        ApiErrorId.ERR_STAGE_CHECK_NOT_IN_PROGRESS.value,
    )


def test_endorsement_outside_authorization_rejected(api):
    """PRD §3.6: "An instructor may only issue an endorsement whose
    `endorsement_code` is among that instructor's `authorized_endorsement_codes`; an
    attempt to sign a code outside the instructor's authorization is refused with
    `ERR_ENDORSEMENT_NOT_AUTHORIZED` (HTTP 403)."

    Design: Corner/errors/endorsement_not_authorized_code
    """
    student = create_student()
    syllabus = create_syllabus()
    instructor = create_instructor(authorized_endorsement_codes=["SOLO"])
    enrollment = create_enrollment(student["id"], syllabus["id"])
    validate_error(
        api.create_endorsement(
            {"enrollment_id": enrollment["id"], "instructor_id": instructor["id"], "endorsement_code": "COMPLEX"},
            make_instructor_headers(instructor["id"]),
        ),
        ApiErrorId.ERR_ENDORSEMENT_NOT_AUTHORIZED.value,
    )


def test_revoke_already_revoked_endorsement_rejected(api):
    """PRD §3.6: "An `Instructor` may later revoke a valid endorsement, moving its
    `status` to `REVOKED`; the endorsement must be `VALID` to revoke, otherwise
    `ERR_ENDORSEMENT_NOT_VALID`."

    Design: Corner/errors/endorsement_revoke_already_revoked
    """
    student = create_student()
    syllabus = create_syllabus()
    instructor = create_instructor(authorized_endorsement_codes=["SOLO"])
    enrollment = create_enrollment(student["id"], syllabus["id"])
    end = issue_endorsement(enrollment["id"], instructor["id"], "SOLO")
    instr_headers = make_instructor_headers(instructor["id"])
    api.revoke_endorsement(end["id"], instr_headers)
    assert get_endorsement(end["id"])["status"] == "REVOKED"
    validate_error(api.revoke_endorsement(end["id"], instr_headers), ApiErrorId.ERR_ENDORSEMENT_NOT_VALID.value)
