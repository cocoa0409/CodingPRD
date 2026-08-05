"""Approval quorum, issuance preconditions, validation-priority ordering, and SoD.

Difficulty: cross_entity_state_dependency, priority_pair_validation_conflict.
Corner: approve_by_reviewer_identity_rejected_sod.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID,
    create_inspection_payload, fixtures,
)
from test_helpers.test_users import TEST_USERS, make_clerk_headers

CLERK = TEST_USERS["clerk_headers"]


def test_approve_with_two_of_three_reviews_rejected(api):
    """PRD §3.6: "`approved_review_count` must equal `total_review_count`, meaning every
    agency review is `APPROVED` or `APPROVED_WITH_CONDITIONS` (else
    `ERR_REVIEWS_NOT_ALL_APPROVED`)".

    Design: Difficulty/cross_entity_state_dependency/approve_requires_all_reviews_approved
    """
    ctx = fixtures.create_under_review_application(api)
    app_id = ctx["application"]["id"]
    reviews = ctx["reviews"]
    fixtures.decide_review(api, reviews[0]["id"], app_id, "APPROVE")
    fixtures.decide_review(api, reviews[1]["id"], app_id, "APPROVE")
    fixtures.clear_document_gates(api, ctx)
    resp = api.approve_application(app_id, make_clerk_headers("clerk-1"))
    validate_error(resp, ApiErrorId.ERR_REVIEWS_NOT_ALL_APPROVED)
    assert fixtures.get_application(api, app_id)["status"] == "UNDER_REVIEW"


def test_approve_with_full_quorum_succeeds(api):
    """PRD §3.6: "When every signoff is in, a `PermitClerk` approves the application,
    moving it from `UNDER_REVIEW` to `APPROVED`."
    PRD §3.6: "`approved_review_count` must equal `total_review_count`, meaning every
    agency review is `APPROVED` or `APPROVED_WITH_CONDITIONS` (else
    `ERR_REVIEWS_NOT_ALL_APPROVED`)".

    Design: Difficulty/cross_entity_state_dependency/approve_requires_all_reviews_approved
    """
    ctx = fixtures.drive_to_ready_for_approval(api)
    resp = api.approve_application(ctx["application"]["id"], make_clerk_headers("clerk-1"))
    data = validate_success(resp)
    assert data["status"] == "APPROVED"


def test_issue_with_scheduled_inspection_rejected(api):
    """PRD §3.6: "Issuance requires the application to be `APPROVED` (else
    `ERR_APPLICATION_NOT_APPROVED`), at least one inspection for the application to have
    result `PASSED` (else `ERR_INSPECTION_NOT_PASSED`), and `balance_due_cents` to be
    exactly zero (else `ERR_OUTSTANDING_BALANCE`)."

    Balance is paid to zero; the inspection is still SCHEDULED (not PASSED).

    Design: Difficulty/cross_entity_state_dependency/issue_requires_inspection_passed
    """
    ctx = fixtures.drive_to_approved_with_inspection(api)
    app_id = ctx["application"]["id"]
    balance = fixtures.get_application(api, app_id)["balance_due_cents"]
    fixtures.pay_balance(api, app_id, balance)
    resp = api.issue_permit(app_id, CLERK)
    validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_PASSED)
    assert fixtures.get_application(api, app_id)["status"] == "APPROVED"


def test_issue_after_passed_inspection_succeeds(api):
    """PRD §3.6: "On issuance the system assigns a `permit_number`, sets `deposit_status`
    to `HELD`, and marks the application `PERMIT_ISSUED`."

    Design: Difficulty/cross_entity_state_dependency/issue_requires_inspection_passed
    """
    ctx = fixtures.drive_to_permit_issued(api)
    app = ctx["application"]
    assert app["status"] == "PERMIT_ISSUED"
    assert app["deposit_status"] == "HELD"
    assert app["permit_number"] is not None


def test_schedule_inspection_missing_inspector_beats_draft_state(api):
    """PRD §2.9: "3. Existence — all path and body-referenced resources exist (path
    before body), else the appropriate not-found error." and "4. State — the target or
    parent resource is in the correct state for the operation".
    PRD §2.5: "If any referenced resource does not exist, the request is rejected with
    the not-found error specific to that resource — ... `ERR_INSPECTOR_NOT_FOUND`".

    A DRAFT application (state would fail) plus a non-existent inspector: existence wins.

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_schedule_inspection
    """
    app = fixtures.create_application(api)  # DRAFT
    payload = create_inspection_payload(app["id"], NON_EXISTENT_UUID)
    resp = api.create_inspection(payload, CLERK)
    validate_error(resp, ApiErrorId.ERR_INSPECTOR_NOT_FOUND)


def test_schedule_inspection_missing_inspector_reports_not_found(api):
    """PRD §2.5: "If any referenced resource does not exist, the request is rejected with
    the not-found error specific to that resource — ... `ERR_INSPECTOR_NOT_FOUND`, ...
    with the first missing identifier in evaluation order determining which error surfaces."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_schedule_inspection
    """
    ctx = fixtures.drive_to_approved(api)  # a valid APPROVED application
    payload = create_inspection_payload(ctx["application"]["id"], NON_EXISTENT_UUID)
    resp = api.create_inspection(payload, CLERK)
    validate_error(resp, ApiErrorId.ERR_INSPECTOR_NOT_FOUND)


def test_issue_referential_check_beats_fiscal_check(api):
    """PRD §2.9: "6. Business referential integrity — required linked resources are
    present and in their required states (all reviews approved, all servers verified,
    insurance accepted, security approved, inspection passed, required documents present)."
    and "10. Fiscal rules — balance fully paid before issuance, deny requires a rejected
    review, positive payment amount, unresolved violations block close."

    APPROVED, inspection still SCHEDULED, balance unpaid: the referential inspection-passed
    check surfaces before the fiscal outstanding-balance check.

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_issue
    """
    ctx = fixtures.drive_to_approved_with_inspection(api)  # balance unpaid, inspection SCHEDULED
    resp = api.issue_permit(ctx["application"]["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_PASSED)


def test_issue_referential_failure_leaves_application_approved(api):
    """PRD §3.6: "Finally, a `PermitClerk` issues the permit, moving the application from
    `APPROVED` to `PERMIT_ISSUED`. Issuance requires the application to be `APPROVED`
    (else `ERR_APPLICATION_NOT_APPROVED`), at least one inspection for the application to
    have result `PASSED` (else `ERR_INSPECTION_NOT_PASSED`)".

    A rejected issuance performs no transition.

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_issue
    """
    ctx = fixtures.drive_to_approved_with_inspection(api)
    app_id = ctx["application"]["id"]
    validate_error(api.issue_permit(app_id, CLERK), ApiErrorId.ERR_INSPECTION_NOT_PASSED)
    assert fixtures.get_application(api, app_id)["status"] == "APPROVED"


def test_approve_by_reviewer_identity_violates_segregation_of_duties(api):
    """PRD §3.6: "the approving clerk's `X-User-ID` must not equal the `recorded_by` of
    any `AgencyReview` on this application (else `ERR_SEGREGATION_OF_DUTIES`), so that the
    person who signed as an agency cannot also be the person who approves the permit."

    Design: Corner/rbac/approve_by_reviewer_identity_rejected_sod
    """
    ctx = fixtures.drive_to_ready_for_approval(api, reviewer_user_id="rev-1")
    app_id = ctx["application"]["id"]
    resp = api.approve_application(app_id, make_clerk_headers("rev-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert fixtures.get_application(api, app_id)["status"] == "UNDER_REVIEW"
