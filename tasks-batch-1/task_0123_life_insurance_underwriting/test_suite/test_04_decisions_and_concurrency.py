"""Underwriting decisions: validation precedence (state before segregation), the
offer-expiry gate, and optimistic-concurrency on approve.

Covers difficulty rule priority_pair_validation_conflict (the EXAM_PENDING approve
instance) plus the corner offer-expiry and OCC-stale-application instances.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_application_in_exam_pending, setup_application_under_review,
    setup_application_approved,
    create_product, create_underwriter, create_draft_application, submit_application,
    attach_completed_exam, add_mib_check, set_clock,
    make_underwriter_headers,
    EXAM_PREFERRED,
)


def test_invalid_state_beats_segregation_on_approve_from_exam_pending(api):
    """PRD §2.11: "then whether the requested transition is even defined from the
    resource's current state (`ERR_INVALID_STATE`). Domain rules follow this preamble."
    PRD §2.11: "For the decisions rendered out of review, segregation of duties is enforced
    (`ERR_SEGREGATION_OF_DUTIES`) and then the uninsurable-risk gate (`ERR_UNINSURABLE_RISK`)."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_segregation_on_approve_from_exam_pending
    """
    # u1 orders the exam (pinning ordering underwriter) leaving status EXAM_PENDING; u1
    # then attempts approve. State precondition (UNDER_REVIEW) fails AND segregation fails;
    # the state check at priority 7 dominates -> ERR_INVALID_STATE.
    ctx = setup_application_in_exam_pending()
    app_id = ctx["application"]["id"]
    u1_h = make_underwriter_headers(ctx["u1"]["id"])
    exam_pending = validate_success(api.get_application(app_id, u1_h))
    resp = api.approve_application(
        app_id, {"expected_application_version": exam_pending["version"]}, u1_h
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    unchanged = validate_success(api.get_application(app_id, u1_h))
    assert unchanged["status"] == "EXAM_PENDING", unchanged


def test_offer_expired_on_issue_after_expiry(api):
    """PRD §3.6: "An attempt to issue after the offer instant has passed is rejected with
    `ERR_OFFER_EXPIRED`."
    PRD §3.5: "it sets `offer_expires_at` to thirty days after the current clock instant."

    Design: Corner/errors/error_offer_expired_on_issue_after_expiry
    """
    # Approve at clock 2026-06-01 -> offer_expires 2026-07-01; advance clock to 2026-08-01.
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_application_approved(exam_overrides=dict(EXAM_PREFERRED))
    app_id = ctx["application"]["id"]
    u2_h = make_underwriter_headers(ctx["u2"]["id"])
    set_clock("2026-08-01T00:00:00Z")
    resp = api.issue_application(
        app_id, {"expected_application_version": ctx["offer_version"]}, u2_h
    )
    validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED.value)


def test_approve_with_stale_application_version_rejected(api):
    """PRD §2.9: "Approving an application requires the request to carry
    `expected_application_version`, which must equal the application's current `version`;
    if another underwriter has, for example, re-ordered a paramed exam and thereby moved the
    case back to evidence-gathering and refreshed its risk assessment, the application's
    version will have advanced and the approval is rejected with
    `ERR_STALE_APPLICATION_VERSION` at HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_application_version_on_approve
    """
    ctx = setup_application_under_review(exam_overrides=dict(EXAM_PREFERRED))
    app_id = ctx["application"]["id"]
    u1_h = make_underwriter_headers(ctx["u1"]["id"])
    u2_h = make_underwriter_headers(ctx["u2"]["id"])
    stale_version = ctx["review_version"]

    # Revision loop advances the version: re-order exam, complete it, begin review again.
    # The setup exam dated 2026-05-01 (exam_validity_days 180) spans
    # [2026-05-01, 2026-10-28); the second exam dated 2026-11-01 starts after that
    # exclusive end so the windows do not overlap.
    validate_success(api.order_exam(app_id, u1_h))
    e2 = validate_success(api.create_paramed_exam(
        app_id, {"height_inches": 70, "weight_pounds": 160, "systolic_bp": 120,
                 "exam_date": "2026-11-01"}, u1_h), expected_status=201)
    validate_success(api.complete_paramed_exam(e2["id"], u1_h))
    fresh = validate_success(api.begin_review(app_id, u2_h))
    assert fresh["version"] != stale_version

    # Approving with the stale version is rejected; state (UNDER_REVIEW) is valid.
    resp = api.approve_application(
        app_id, {"expected_application_version": stale_version}, u2_h
    )
    validate_error(resp, ApiErrorId.ERR_STALE_APPLICATION_VERSION.value)
    unchanged = validate_success(api.get_application(app_id, u2_h))
    assert unchanged["status"] == "UNDER_REVIEW", unchanged
