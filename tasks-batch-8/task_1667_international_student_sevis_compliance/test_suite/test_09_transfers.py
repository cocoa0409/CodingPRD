"""Transfer request release sweep and cancellation claims (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    assert_transfer_request,
    create_term_enrollment,
    create_transfer_request,
    get_enrollment,
    get_record,
    set_clock,
    setup_active_student,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_transfer_release_sweep_cascade_and_terminal_lockdown(api, dso_headers):
    """PRD §3.7: "when the clock date reaches the `release_date` of a
    `REQUESTED` outbound transfer, the transfer moves to `RELEASED` and the
    student's SEVIS record transitions from `ACTIVE` to `TRANSFERRED_OUT`. That
    record transition flips each of the student's `PENDING` enrollments to
    `NOT_ENROLLED`, and each flip recomputes the student's
    `compliance_posture`."
    PRD §3.7: "A transfer already released, already cancelled, or whose release
    date has been reached is rejected with `ERR_TRANSFER_NOT_CANCELLABLE`."

    Design: Corner/state_machines/transfer_release_sweep_cascade_and_terminal_lockdown
    """
    ctx = setup_active_student()
    student_id = ctx["student"]["id"]
    spring = create_term_enrollment(
        student_id, term_code="2027-SPRING",
        term_start_date="2027-01-11", term_end_date="2027-05-07",
        enrolled_credits=12,
    )
    transfer = create_transfer_request(student_id, "OUT", "ABC123", "2026-09-01")
    assert transfer["status"] == "REQUESTED"

    set_clock("2026-09-01T00:00:00Z")

    transfers, _meta = validate_paginated(
        api.list_transfer_requests(student_id, dso_headers)
    )
    assert transfers[0]["status"] == "RELEASED"
    assert get_record(student_id)["status"] == "TRANSFERRED_OUT"
    assert get_enrollment(spring["id"])["status"] == "NOT_ENROLLED"

    # RELEASED is terminal: a late cancel is rejected.
    resp = api.cancel_transfer_request(transfer["id"], dso_headers)
    validate_error(resp, ApiErrorId.ERR_TRANSFER_NOT_CANCELLABLE, 409)


def test_transfer_cancel_before_release_succeeds(api, dso_headers):
    """PRD §3.7: "A request that has not yet been released may be withdrawn:
    cancellation by a DSO requires the transfer still `REQUESTED` and the clock
    date strictly before the `release_date`, and moves it to `CANCELLED`."

    Design: Corner/state_machines/transfer_cancel_before_release_succeeds
    """
    ctx = setup_active_student()
    student_id = ctx["student"]["id"]
    transfer = create_transfer_request(student_id, "OUT", "ABC123", "2026-09-01")

    cancelled = validate_success(
        api.cancel_transfer_request(transfer["id"], dso_headers), 200,
    )
    assert_transfer_request(cancelled)
    assert cancelled["status"] == "CANCELLED"
    assert get_record(student_id)["status"] == "ACTIVE"
