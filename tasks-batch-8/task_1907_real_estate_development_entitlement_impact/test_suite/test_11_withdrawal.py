"""Withdrawal: origin states, the refund/cancel cascade, and terminal lockout."""
from test_helpers import (
    ApiErrorId,
    get_application,
    get_single_assessment,
    schedule_hearing,
    setup_approved_application,
    setup_submitted_application,
    setup_under_review_application,
    validate_error,
    validate_success,
)


def test_withdraw_cascades_assessment_refund_and_hearing_cancel(api):
    """PRD 3.9: "Withdrawal cascades: every assessment standing `OPEN` or
    `PARTIALLY_PAID` is refunded under the rule of §3.7, every `SCHEDULED`
    hearing is moved to `CANCELLED`, and every `PENDING` condition of approval
    is moved to `WAIVED` as moot."
    PRD 3.9: "From `SUBMITTED`, `UNDER_REVIEW`, `HEARING_SCHEDULED`, or
    `DECISION_PENDING`, the applicant may withdraw the application".

    Design: Difficulty/transitive_cascade/application_withdraw_cascades_assessment_refund_and_hearing_cancel
    """
    ctx = setup_under_review_application()
    hearing = schedule_hearing(ctx, hearing_body="CITY_COUNCIL")
    app_id = ctx["application"]["id"]
    assessment = get_single_assessment(
        app_id, ctx["reviewer_headers"], variant="PROVISIONAL"
    )
    assert assessment["status"] == "OPEN"

    withdrawn = validate_success(
        api.withdraw_application(app_id, ctx["applicant_headers"])
    )
    assert withdrawn["status"] == "WITHDRAWN", (
        f"withdrawal origin must land WITHDRAWN, got {withdrawn['status']}"
    )

    assessment_after = validate_success(
        api.get_assessment(assessment["id"], ctx["reviewer_headers"])
    )
    assert assessment_after["status"] == "REFUNDED", (
        f"cascade hop 1: provisional assessment must be REFUNDED, got "
        f"{assessment_after['status']}"
    )

    hearing_after = validate_success(
        api.get_hearing(hearing["id"], ctx["reviewer_headers"])
    )
    assert hearing_after["status"] == "CANCELLED", (
        f"cascade hop 2: scheduled hearing must be CANCELLED, got "
        f"{hearing_after['status']}"
    )


def test_withdraw_from_submitted_refunds_provisional(api):
    """PRD 3.9: "From `SUBMITTED`, `UNDER_REVIEW`, `HEARING_SCHEDULED`, or
    `DECISION_PENDING`, the applicant may withdraw the application" and
    "Withdrawal cascades: every assessment standing `OPEN` or `PARTIALLY_PAID`
    is refunded under the rule of §3.7".

    Design: Difficulty/transitive_cascade/application_withdraw_cascades_assessment_refund_and_hearing_cancel
    """
    ctx = setup_submitted_application()
    app_id = ctx["application"]["id"]
    assessment = get_single_assessment(
        app_id, ctx["applicant_headers"], variant="PROVISIONAL"
    )

    withdrawn = validate_success(
        api.withdraw_application(app_id, ctx["applicant_headers"])
    )
    assert withdrawn["status"] == "WITHDRAWN"

    assessment_after = validate_success(
        api.get_assessment(assessment["id"], ctx["applicant_headers"])
    )
    assert assessment_after["status"] == "REFUNDED", (
        f"withdrawal from SUBMITTED must refund the OPEN provisional, got "
        f"{assessment_after['status']}"
    )


def test_terminal_approved_application_rejects_withdraw(api):
    """PRD 3.9: "`APPROVED`, `DENIED`, and `WITHDRAWN` are the application's
    terminal states."
    PRD 2.9: "an entity already in a terminal state accepts no further
    transitions and reports `ERR_ALREADY_TERMINAL` (409)."

    Design: Corner/state_machines/terminal_approved_application_rejects_withdraw
    """
    ctx = setup_approved_application()
    app_id = ctx["application"]["id"]
    assert get_application(app_id, ctx["applicant_headers"])["status"] == "APPROVED"

    response = api.withdraw_application(app_id, ctx["applicant_headers"])
    validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL, expected_status=409)

    after = get_application(app_id, ctx["applicant_headers"])
    assert after["status"] == "APPROVED"
