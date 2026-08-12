"""Continuing-activity reviews: overdue sweep boundary and lifecycle gating
(PRD §2.5, §3.6)."""
from test_helpers import (
    ApiErrorId,
    assert_continuing_review,
    assert_same_instant,
    complete_review_payload,
    create_customer,
    create_staff,
    first_continuing_review,
    run_sweep,
    set_clock,
    setup_filed_sar,
    validate_error,
    validate_success,
)


def test_review_marked_overdue_strictly_after_due(api):
    """PRD §2.5: "it transitions every `ContinuingReview` whose status is
    `SCHEDULED` and whose `due_at` is in the past to `OVERDUE`".
    PRD §3.6: "The daily sweep marks a `SCHEDULED` review `OVERDUE` once
    `due_at` passes."

    For a SAR filed 2026-05-05 the review is due 2026-08-03T00:00:00Z; at
    exactly that instant the due date has not passed, and one second later it
    has.

    Design: Corner/calculations/continuing_review_overdue_strict_boundary
    """
    staff = create_staff()
    filed = setup_filed_sar(staff, create_customer(staff)["id"],
                            file_clock="2026-05-05T00:00:00Z")
    review = first_continuing_review(staff, filed.sar["id"])
    assert_continuing_review(review)
    assert_same_instant(review["due_at"], "2026-08-03T00:00:00Z", "filed + 90 days")
    assert review["status"] == "SCHEDULED"

    set_clock(staff, "2026-08-03T00:00:00Z")  # exactly due_at: not yet past
    sweep = run_sweep(staff)
    assert sweep["reviews_marked_overdue"] == 0
    mid = validate_success(api.get_continuing_review(review["id"], staff.analyst), 200)
    assert mid["status"] == "SCHEDULED"

    set_clock(staff, "2026-08-03T00:00:01Z")  # one second past
    sweep = run_sweep(staff)
    assert sweep["reviews_marked_overdue"] == 1
    end = validate_success(api.get_continuing_review(review["id"], staff.analyst), 200)
    assert end["status"] == "OVERDUE"


def test_complete_review_before_start_rejected(api):
    """PRD §3.6: "A `BSAAnalyst` may start a `SCHEDULED` review, moving it to
    `IN_PROGRESS`; the same action works from `OVERDUE` as a late start."
    PRD §3.6: "Completing a review requires the reviewed SAR to still be
    `FILED` (otherwise `ERR_INVALID_STATE`) and records an `outcome` of either
    `FILE_CONTINUING_SAR` or `CLOSE_MONITORING`, plus `completed_at`."
    PRD §2.10: "then state-machine legality (`ERR_INVALID_STATE`)".

    Completion is described only for a started review; completing directly
    from SCHEDULED is not a permitted transition.

    Design: Corner/state_machines/review_complete_before_start_rejected
    """
    staff = create_staff()
    filed = setup_filed_sar(staff, create_customer(staff)["id"])
    review = first_continuing_review(staff, filed.sar["id"])
    assert review["status"] == "SCHEDULED"

    res = api.complete_continuing_review(
        review["id"], complete_review_payload("CLOSE_MONITORING"), staff.analyst)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert res.status_code == 409
    after = validate_success(api.get_continuing_review(review["id"], staff.analyst), 200)
    assert after["status"] == "SCHEDULED"
    assert after["completed_at"] is None
