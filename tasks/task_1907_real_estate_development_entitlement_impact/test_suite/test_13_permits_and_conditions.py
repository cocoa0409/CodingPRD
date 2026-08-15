"""Conditions of approval side effects and the permit/deferral fiscal gate."""
from test_helpers import (
    ApiErrorId,
    add_condition,
    assert_condition,
    assert_same_instant,
    issue_permit_now,
    request_permit,
    set_clock,
    setup_approved_application,
    setup_approved_with_fees_paid,
    validate_error,
    validate_success,
)


def test_condition_satisfied_side_effect_stamps_satisfied_at(api):
    """PRD 3.9: "The applicant satisfies it — permitted only while the parent
    application stands `APPROVED` — which stamps `satisfied_at` with the
    current instant and moves the condition to `SATISFIED`."
    PRD 2.8: statutory instants are "evaluated against a server-side logical
    clock, never against wall-clock time".

    Design: Corner/state_machines/condition_satisfied_side_effect_stamps_satisfied_at
    """
    ctx = setup_approved_application()
    condition = add_condition(ctx)
    assert_condition(condition)
    assert condition["status"] == "PENDING"

    set_clock("2026-08-10T00:00:00Z")
    satisfied = validate_success(
        api.satisfy_condition(condition["id"], ctx["applicant_headers"])
    )
    assert satisfied["status"] == "SATISFIED", (
        f"satisfy must move the condition to SATISFIED, got {satisfied['status']}"
    )
    assert_same_instant(
        satisfied["satisfied_at"], "2026-08-10T00:00:00Z", "satisfied_at"
    )


def test_error_defer_after_permit_issued(api):
    """PRD 3.7: "if any permit sequence row for the application already stands
    `ISSUED`, the request is refused with `ERR_PERMIT_ALREADY_ISSUED` (so a
    premature permit surfaces that error rather than being masked by a variant
    complaint)".

    Design: Corner/errors/error_defer_after_permit_issued
    """
    ctx = setup_approved_with_fees_paid()
    assert ctx["final_assessment"]["status"] == "PAID"

    grading = request_permit(ctx, "GRADING")
    assert grading["status"] == "REQUESTED", (
        f"with every issuance precondition green the request is REQUESTED, "
        f"got {grading['status']}"
    )
    issued = issue_permit_now(ctx, grading["id"])
    assert issued["status"] == "ISSUED"

    response = api.defer_assessment(
        ctx["final_assessment"]["id"], ctx["applicant_headers"]
    )
    validate_error(response, ApiErrorId.ERR_PERMIT_ALREADY_ISSUED)

    after = validate_success(
        api.get_assessment(ctx["final_assessment"]["id"], ctx["reviewer_headers"])
    )
    assert after["status"] == "PAID", (
        f"refused deferral must leave the assessment PAID, got {after['status']}"
    )
