"""Ladder-page and submission workflows: revision cycles, review preconditions,
the approve/un-approve count side effect, page-number geometry, and invalid
transitions.

Difficulty (queue A) and corner (queue B) instances appear here.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    create_page_payload,
    create_submission_payload,
    create_staff_assignment_payload,
    create_yearbook,
    create_page,
    create_active_staff_assignment,
    TEST_USERS,
)

ADVISER = TEST_USERS["adviser_headers"]
STAFF = TEST_USERS["staff_headers"]
CONTRIBUTOR = TEST_USERS["contributor_headers"]


# ─── LadderPage revision cycle (non-linear) ──────────────────────────────────

def test_ladderpage_revision_cycle_back_to_in_review(api):
    """PRD §3.4: "Requesting changes moves an `IN_REVIEW` page to `CHANGES_REQUESTED`,
    sending it back to staff for another revision pass." PRD §3.3: "When `Staff`
    submits a page for the adviser's review — advancing it from `DRAFT` to `IN_REVIEW`,
    or from `CHANGES_REQUESTED` back to `IN_REVIEW` after edits".

    Design: Difficulty/non_linear_state_machine/non_linear_ladderpage_revision_cycle
    """
    yb = create_yearbook()
    sa = create_active_staff_assignment(yb["id"])
    page = create_page(yb["id"], 1, "STUDENT_LIFE", template_code="T-2COL",
                       required_submission_count=0, assigned_staff_id=sa["id"])
    validate_success(api.submit_review_page(page["id"], STAFF), 200)
    validate_success(api.request_changes_page(page["id"], ADVISER), 200)
    res = api.submit_review_page(page["id"], STAFF)  # CHANGES_REQUESTED -> IN_REVIEW
    page_after = validate_success(res, 200)
    assert page_after["status"] == "IN_REVIEW"


def test_ladderpage_revision_cycle_reaches_in_review_after_two_passes(api):
    """PRD §3.3: "When `Staff` submits a page for the adviser's review — advancing it
    from `DRAFT` to `IN_REVIEW`, or from `CHANGES_REQUESTED` back to `IN_REVIEW` after
    edits". PRD §3.4: "Requesting changes moves an `IN_REVIEW` page to
    `CHANGES_REQUESTED`, sending it back to staff for another revision pass."

    Design: Difficulty/non_linear_state_machine/non_linear_ladderpage_revision_cycle
    """
    yb = create_yearbook()
    sa = create_active_staff_assignment(yb["id"])
    page = create_page(yb["id"], 1, "STUDENT_LIFE", template_code="T-2COL",
                       required_submission_count=0, assigned_staff_id=sa["id"])
    p1 = validate_success(api.submit_review_page(page["id"], STAFF), 200)
    assert p1["status"] == "IN_REVIEW"
    p2 = validate_success(api.request_changes_page(page["id"], ADVISER), 200)
    assert p2["status"] == "CHANGES_REQUESTED"
    p3 = validate_success(api.submit_review_page(page["id"], STAFF), 200)
    assert p3["status"] == "IN_REVIEW"


# ─── Submission reject/resubmit cycle (non-linear) ───────────────────────────

def test_submission_reject_resubmit_cycle(api):
    """PRD §3.2: "When a `Contributor` resubmits a corrected asset, the submission
    moves from `REJECTED` back to `PENDING`, optionally carrying a fresh `asset_ref`;
    this is the revision loop that lets a contributor fix and re-offer a rejected
    asset."

    Design: Difficulty/non_linear_state_machine/non_linear_submission_reject_resubmit_cycle
    """
    yb = create_yearbook()
    page = create_page(yb["id"], 1, "SPORTS", template_code="T-COLLAGE")
    sub = validate_success(
        api.create_submission(
            create_submission_payload(page["id"], kind="PHOTO", contributor_id="c-1",
                                      asset_ref="img/1.jpg"),
            CONTRIBUTOR,
        ), 201,
    )
    validate_success(api.reject_submission(sub["id"], {"review_note": "blurry"}, STAFF), 200)
    res = api.resubmit_submission(sub["id"], {"asset_ref": "img/1b.jpg"}, CONTRIBUTOR)
    sub_after = validate_success(res, 200)
    assert sub_after["status"] == "PENDING"


def test_submission_reject_moves_pending_to_rejected(api):
    """PRD §3.2: "Reviewing a pending submission, the staff member either approves it,
    moving it from `PENDING` to `APPROVED`, or rejects it, moving it from `PENDING` to
    `REJECTED`; a `review_note` may accompany either action."

    Design: Difficulty/non_linear_state_machine/non_linear_submission_reject_resubmit_cycle
    """
    yb = create_yearbook()
    page = create_page(yb["id"], 1, "SPORTS", template_code="T-COLLAGE")
    sub = validate_success(
        api.create_submission(
            create_submission_payload(page["id"], kind="PHOTO", contributor_id="c-1",
                                      asset_ref="img/1.jpg"),
            CONTRIBUTOR,
        ), 201,
    )
    res = api.reject_submission(sub["id"], {"review_note": "blurry"}, STAFF)
    sub_after = validate_success(res, 200)
    assert sub_after["status"] == "REJECTED"


# ─── Submission count side effect (approve increments, un-approve decrements) ─

def test_submission_approve_increments_then_decrements_on_reject(api):
    """PRD §3.2: "approving a submission increases this count by one and un-approving a
    previously approved submission decreases it by one, with the page's count always
    recomputed from the live set of its approved submissions."

    Design: Corner/state_machines/submission_approve_increments_then_decrements_on_reject
    """
    yb = create_yearbook()
    page = create_page(yb["id"], 1, "CLUBS")
    sub = validate_success(
        api.create_submission(
            create_submission_payload(page["id"], kind="QUOTE", contributor_id="c-1",
                                      asset_ref="Best year ever"),
            CONTRIBUTOR,
        ), 201,
    )
    validate_success(api.approve_submission(sub["id"], {}, STAFF), 200)
    after_approve = validate_success(api.get_page(page["id"], ADVISER), 200)
    assert after_approve["approved_submission_count"] == 1

    validate_success(api.reject_submission(sub["id"], {"review_note": "changed mind"}, STAFF), 200)
    after_reject = validate_success(api.get_page(page["id"], ADVISER), 200)
    assert after_reject["approved_submission_count"] == 0


# ─── Review preconditions ─────────────────────────────────────────────────────

def test_submit_review_without_assigned_staff_returns_page_unassigned(api):
    """PRD §3.3: "On the very first submission for review out of `DRAFT`, the server
    additionally requires that the page has an `assigned_staff_id` whose staff
    assignment is `ACTIVE`; a page lacking an active assigned staff member is rejected
    with `ERR_PAGE_UNASSIGNED`."

    Design: Corner/state_machines/submit_review_without_assigned_staff_returns_page_unassigned
    """
    yb = create_yearbook()
    page = create_page(yb["id"], 1, "CLUBS", required_submission_count=0)
    res = api.submit_review_page(page["id"], STAFF)
    validate_error(res, "ERR_PAGE_UNASSIGNED")


def test_submit_review_with_insufficient_submissions_returns_incomplete(api):
    """PRD §3.3: "the server first checks that the page's `approved_submission_count`
    is at least its `required_submission_count`; a page short of its required approvals
    is rejected with `ERR_SUBMISSIONS_INCOMPLETE`."

    Design: Corner/state_machines/submit_review_with_insufficient_submissions_returns_incomplete
    """
    yb = create_yearbook()
    sa = create_active_staff_assignment(yb["id"], role_title="PHOTOGRAPHER")
    page = create_page(yb["id"], 1, "CLUBS", required_submission_count=1,
                       assigned_staff_id=sa["id"])
    res = api.submit_review_page(page["id"], STAFF)
    validate_error(res, "ERR_SUBMISSIONS_INCOMPLETE")


# ─── Invalid transitions ─────────────────────────────────────────────────────

def test_approve_page_from_draft_returns_invalid_state(api):
    """PRD §3.4: "A successful approval moves the page from `IN_REVIEW` to `APPROVED`".
    PRD §2.6: "that the target resource is in a state from which the requested
    transition is defined, else `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/state_machines/approve_page_from_draft_returns_invalid_state
    """
    yb = create_yearbook()
    page = create_page(yb["id"], 1, "CLUBS")
    res = api.approve_page(page["id"], ADVISER)  # approve only defined from IN_REVIEW
    validate_error(res, "ERR_INVALID_STATE")


# ─── Page-number geometry (spread overlap / out of bounds) ───────────────────

def test_page_spread_collides_with_adjacent_slot(api):
    """PRD §3.1: "It also enforces that the occupied range does not overlap any slot
    already occupied by another page on the same yearbook; an overlap is rejected with
    `ERR_PAGE_NUMBER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/overlap_page_spread_collides_adjacent_slot
    """
    yb = create_yearbook(target_page_count=96)
    # spread_span 2 at page 7 occupies {7, 8}.
    create_page(yb["id"], 7, "SPORTS", template_code="T-SPREAD", spread_span=2)
    res = api.create_page(
        create_page_payload(yb["id"], 8, "CLUBS"), ADVISER  # collides on slot 8
    )
    validate_error(res, "ERR_PAGE_NUMBER_CONFLICT")


def test_spread_page_then_non_overlapping_single_page_accepted(api):
    """PRD §3.1: "A page's spread occupies the slots from its `page_number` through
    `page_number + spread_span - 1`." PRD §3.1: "It also enforces that the occupied
    range does not overlap any slot already occupied by another page on the same
    yearbook; an overlap is rejected with `ERR_PAGE_NUMBER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/overlap_page_spread_collides_adjacent_slot
    """
    yb = create_yearbook(target_page_count=96)
    # spread_span 2 at page 7 occupies {7, 8}; a single page at 9 does NOT overlap.
    create_page(yb["id"], 7, "SPORTS", template_code="T-SPREAD", spread_span=2)
    res = api.create_page(create_page_payload(yb["id"], 9, "CLUBS"), ADVISER)
    page = validate_success(res, 201)
    assert page["page_number"] == 9


def test_page_number_out_of_bounds_returns_error(api):
    """PRD §3.1: "if any slot in the range would exceed the `1`-through-
    `target_page_count` bounds the page is rejected with
    `ERR_PAGE_NUMBER_OUT_OF_BOUNDS`."

    Design: Corner/validations/page_number_out_of_bounds_returns_error
    """
    yb = create_yearbook(target_page_count=96)
    res = api.create_page(
        create_page_payload(yb["id"], 200, "CLUBS"), ADVISER
    )
    validate_error(res, "ERR_PAGE_NUMBER_OUT_OF_BOUNDS")
