"""Cyclic state-machine and cross-entity state-gate tests
(PRD §3.5, §3.8)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, headers_for,
    assert_instant_equals, assert_event_order,
    setup_complaint, intake_portal_complaint, setup_resolved_complaint,
    setup_complaint_in_response_qa, create_and_complete_rca,
    drive_to_investigating, draft_response, submit_for_qa,
    claim_review, complete_review, resolve_complaint,
    set_clock, get_complaint, get_product, get_referral, get_review,
    list_complaint_events, list_complaint_referrals,
)

MANAGER = TEST_USERS["complaint_manager_headers"]
HANDLER = TEST_USERS["case_handler_headers"]


def test_complaint_resolved_reopened_cycle_restores_work_state(api):
    """PRD §3.5: "A successful reopen moves `RESOLVED → REOPENED`, clears both
    `resolved_at` and `retention_purge_at` to null, increments the product's
    `open_complaint_count` by 1, recomputes `posture`, appends `REOPENED`, and
    bumps `version`."
    PRD §3.3: "Starting the investigation moves `TRIAGED → INVESTIGATING`; the
    same action also serves reopened complaints, so `REOPENED → INVESTIGATING` is
    legal under the identical precondition (the complaint's `status` must be
    either `TRIAGED` or `REOPENED`, otherwise `ERR_INVALID_STATE_TRANSITION`)."
    PRD §2.10: "The trail is exposed read-only, ordered by `event_at` ascending
    with `created_at` ascending as the tiebreak."

    Design: Difficulty/non_linear_state_machine/complaint_resolved_reopened_cycle_restores_work_state
    """
    ctx = setup_resolved_complaint(
        "SAVE-PLUS", "WEB", "SVC.STATEMENT",
        owner_id="user_intake_2", reviewer_id="user_qa_2",
        narrative="Statement error", window_end_at="2026-08-09T00:00:00Z",
        resolve_clock="2026-08-10T00:00:00Z",
    )
    pid = ctx["product"]["id"]
    cid = ctx["complaint"]["id"]
    assert get_product(pid)["open_complaint_count"] == 0

    reopened = validate_success(api.reopen_complaint(cid, HANDLER))
    assert reopened["status"] == "REOPENED"
    investigating = validate_success(api.start_investigation(cid, HANDLER))
    assert investigating["status"] == "INVESTIGATING"

    complaint = get_complaint(cid)
    assert complaint.get("resolved_at") is None, "reopen must clear resolved_at"
    assert complaint.get("retention_purge_at") is None, (
        "reopen must clear retention_purge_at"
    )
    assert get_product(pid)["open_complaint_count"] == 1

    events = list_complaint_events(cid)
    assert_event_order(events, ["QA_PASSED", "STATUS_CHANGED", "REOPENED"])


def test_complaint_cycle_may_repeat_within_retention(api):
    """PRD §3.5: "The loop `RESOLVED → REOPENED → INVESTIGATING → … → RESOLVED`
    may repeat any number of times within retention."
    PRD §3.5: "A successful reopen moves `RESOLVED → REOPENED`, clears both
    `resolved_at` and `retention_purge_at` to null, increments the product's
    `open_complaint_count` by 1, recomputes `posture`, appends `REOPENED`, and
    bumps `version`."

    Design: Difficulty/non_linear_state_machine/complaint_resolved_reopened_cycle_restores_work_state
    """
    ctx = setup_resolved_complaint(
        "SAVE-CYC", "WEB", "SVC.CYCLE",
        owner_id="user_intake_cyc", reviewer_id="user_qa_cyc",
        narrative="cycle twice", window_end_at="2026-08-09T00:00:00Z",
        resolve_clock="2026-08-10T00:00:00Z",
    )
    pid = ctx["product"]["id"]
    cid = ctx["complaint"]["id"]

    # Second pass through the loop: REOPENED -> INVESTIGATING -> ... -> RESOLVED.
    validate_success(api.reopen_complaint(cid, HANDLER))
    validate_success(api.start_investigation(cid, HANDLER))
    # The earlier COMPLETED RCA still satisfies the drafting gate.
    draft_response(cid, "v2 response")
    submit_for_qa(cid)
    review = claim_review(cid, "user_qa_cyc", "2026-08-10T00:00:00Z",
                          "2026-08-12T00:00:00Z")
    complete_review(review["id"], "PASS", "user_qa_cyc")
    resolved = resolve_complaint(cid)

    assert resolved["status"] == "RESOLVED"
    assert resolved.get("resolved_at") is not None, (
        "the second resolution stamps resolved_at afresh"
    )
    assert resolved.get("retention_purge_at") is not None
    assert get_product(pid)["open_complaint_count"] == 0


def test_referral_regulator_reopen_cycle_recomputes_timeliness_same_deadline(api):
    """PRD §3.8: "The cycle `RESPONSE_SUBMITTED → REOPENED_BY_REGULATOR →
    RESPONSE_SUBMITTED` may repeat; crucially, resubmission after a regulator
    reopen re-derives `timeliness` against the **same** original
    `response_due_at` — a regulator reopen never extends the deadline."
    PRD §3.8: "Submission stamps `submitted_at` from the logical clock, moves the
    referral to `RESPONSE_SUBMITTED`, derives `timeliness` as `ON_TIME` when
    `submitted_at` is at or before `response_due_at` and `LATE` otherwise,
    recomputes the parent complaint's `timeliness_score`, appends
    `REFERRAL_RESPONDED` on the complaint, and bumps the referral's `version`."

    Design: Difficulty/non_linear_state_machine/referral_regulator_reopen_cycle_recomputes_timeliness_same_deadline
    """
    complaint, referral = intake_portal_complaint(
        "HELM-FIX", "CFPB_PORTAL", "LOAN.PMI", narrative="PMI cancellation refusal",
        portal_ref="CFPB-2026-777",
    )
    rid = referral["id"]
    set_clock("2026-08-05T00:00:00Z")
    first = validate_success(api.submit_referral_response(
        rid, {"response_text": "Initial response."}, HANDLER,
    ))
    assert first["timeliness"] == "ON_TIME"

    set_clock("2026-08-06T00:00:00Z")
    validate_success(api.regulator_reopen_referral(rid, MANAGER))

    set_clock("2026-08-20T00:00:00Z")  # past the original 2026-08-16 deadline
    second = validate_success(api.submit_referral_response(
        rid, {"response_text": "Supplemental response after reopen."}, HANDLER,
    ))
    assert second["status"] == "RESPONSE_SUBMITTED"
    assert second["timeliness"] == "LATE", (
        "resubmission past the unchanged original deadline must be LATE"
    )
    assert_instant_equals(second["response_due_at"], "2026-08-16T00:00:00Z",
                          "response_due_at")
    assert_instant_equals(second["submitted_at"], "2026-08-20T00:00:00Z",
                          "submitted_at")


def test_referral_resubmission_before_same_deadline_stays_on_time(api):
    """PRD §3.8: "The cycle `RESPONSE_SUBMITTED → REOPENED_BY_REGULATOR →
    RESPONSE_SUBMITTED` may repeat; crucially, resubmission after a regulator
    reopen re-derives `timeliness` against the **same** original
    `response_due_at` — a regulator reopen never extends the deadline."
    PRD §3.8: "Submission stamps `submitted_at` from the logical clock, moves the
    referral to `RESPONSE_SUBMITTED`, derives `timeliness` as `ON_TIME` when
    `submitted_at` is at or before `response_due_at` and `LATE` otherwise,
    recomputes the parent complaint's `timeliness_score`, appends
    `REFERRAL_RESPONDED` on the complaint, and bumps the referral's `version`."

    Design: Difficulty/non_linear_state_machine/referral_regulator_reopen_cycle_recomputes_timeliness_same_deadline
    """
    complaint, referral = intake_portal_complaint(
        "HELM-ADJ", "CFPB_PORTAL", "LOAN.ESCROW", narrative="Escrow analysis",
        portal_ref="CFPB-2026-778",
    )
    rid = referral["id"]
    set_clock("2026-08-05T00:00:00Z")
    first = validate_success(api.submit_referral_response(
        rid, {"response_text": "Initial response."}, HANDLER,
    ))
    assert first["timeliness"] == "ON_TIME"

    set_clock("2026-08-06T00:00:00Z")
    validate_success(api.regulator_reopen_referral(rid, MANAGER))

    set_clock("2026-08-10T00:00:00Z")  # still at or before the 2026-08-16 deadline
    second = validate_success(api.submit_referral_response(
        rid, {"response_text": "Supplemental response."}, HANDLER,
    ))
    assert second["timeliness"] == "ON_TIME"
    assert_instant_equals(second["response_due_at"], "2026-08-16T00:00:00Z",
                          "response_due_at")
    assert_instant_equals(second["submitted_at"], "2026-08-10T00:00:00Z",
                          "submitted_at")


def test_complaint_resolve_gated_by_qualityreview_outcome(api):
    """PRD §3.5: "Resolution is a `CaseHandler` action moving `RESPONSE_QA →
    RESOLVED`, guarded by two further checks evaluated after the state check: a
    `QualityReview` with `status` `COMPLETED` and `outcome` `PASS` must exist for
    the complaint (otherwise `ERR_QA_PASS_REQUIRED`), and no `EscalationCase` of
    the complaint may sit in `RAISED` or `ACKNOWLEDGED` (otherwise
    `ERR_ESCALATION_OPEN`)."
    PRD §3.5: "Completing a review with `PASS` leaves the complaint in
    `RESPONSE_QA` — a pass alone never resolves anything — while the dedicated
    qa-fail action moves the complaint `RESPONSE_QA → INVESTIGATING`, completes
    the acting reviewer's `OPEN` review with outcome `FAIL` in the same call,
    appends `QA_FAILED`, and bumps the complaint's `version`."

    Design: Difficulty/cross_entity_state_dependency/complaint_resolve_gated_by_qualityreview_outcome
    """
    ctx = setup_complaint_in_response_qa(
        "XS-CARD", "PHONE", "FEES.FOREIGN", owner_id="user_intake_6",
        narrative="FX fee dispute",
    )
    cid = ctx["complaint"]["id"]
    review_fail = claim_review(cid, "user_qa_6", "2026-08-01T00:00:00Z",
                               "2026-08-07T00:00:00Z")
    # qa_fail completes the acting reviewer's OPEN review with FAIL and bounces
    # the complaint back to INVESTIGATING.
    validate_success(api.qa_fail(cid, headers_for("QAReviewer", "user_qa_6")))

    # Second cycle: re-draft, re-submit, and claim a fresh review that stays OPEN.
    draft_response(cid, "v2 response")
    submit_for_qa(cid)
    review_open = claim_review(cid, "user_qa_6", "2026-08-08T00:00:00Z",
                               "2026-08-14T00:00:00Z")

    response = api.resolve_complaint(cid, HANDLER)
    validate_error(response, ApiErrorId.ERR_QA_PASS_REQUIRED)
    assert get_complaint(cid)["status"] == "RESPONSE_QA"
    assert get_review(review_fail["id"])["outcome"] == "FAIL"
    assert get_review(review_open["id"])["status"] == "OPEN"


def test_complaint_resolve_succeeds_once_pass_exists_after_earlier_fail(api):
    """PRD §3.5: "Resolution is a `CaseHandler` action moving `RESPONSE_QA →
    RESOLVED`, guarded by two further checks evaluated after the state check: a
    `QualityReview` with `status` `COMPLETED` and `outcome` `PASS` must exist for
    the complaint (otherwise `ERR_QA_PASS_REQUIRED`), and no `EscalationCase` of
    the complaint may sit in `RAISED` or `ACKNOWLEDGED` (otherwise
    `ERR_ESCALATION_OPEN`)."

    Design: Difficulty/cross_entity_state_dependency/complaint_resolve_gated_by_qualityreview_outcome
    """
    ctx = setup_complaint_in_response_qa(
        "XS-DEBIT", "PHONE", "FEES.ATM", owner_id="user_intake_xd",
        narrative="ATM fee dispute",
    )
    cid = ctx["complaint"]["id"]
    review_fail = claim_review(cid, "user_qa_xd", "2026-08-01T00:00:00Z",
                               "2026-08-07T00:00:00Z")
    validate_success(api.qa_fail(cid, headers_for("QAReviewer", "user_qa_xd")))

    # Recover: re-draft, re-submit, and earn a COMPLETED PASS review.
    draft_response(cid, "v2 response")
    submit_for_qa(cid)
    review_pass = claim_review(cid, "user_qa_xd", "2026-08-08T00:00:00Z",
                               "2026-08-14T00:00:00Z")
    complete_review(review_pass["id"], "PASS", "user_qa_xd")

    resolved = validate_success(api.resolve_complaint(cid, HANDLER))
    assert resolved["status"] == "RESOLVED"
    assert resolved.get("resolved_at") is not None


def test_complaint_withdraw_gated_by_referral_state(api):
    """PRD §3.5: "Withdrawal is blocked with `ERR_REFERRAL_OPEN` while any
    referral of the complaint is `OPEN` or `REOPENED_BY_REGULATOR`."
    PRD §3.8: "From `RESPONSE_SUBMITTED` a `ComplaintManager` may close the
    referral, moving it to the terminal `CLOSED_BY_REGULATOR`, or register a
    regulator reopen, moving it `RESPONSE_SUBMITTED → REOPENED_BY_REGULATOR`."
    PRD §3.5: "Its terminal side effects mirror resolution: `resolved_at` stamps
    the clock, `retention_purge_at` is set to five years after `resolved_at`
    under the same leap-year rule, the product's open count decrements and
    `posture` recomputes, `WITHDRAWN` is appended, and `version` bumps."

    Design: Difficulty/cross_entity_state_dependency/complaint_withdraw_gated_by_referral_state
    """
    complaint, referral = intake_portal_complaint(
        "GW-CHK", "CFPB_PORTAL", "SVC.ACCT_ACCESS", narrative="Account lockout",
        portal_ref="CFPB-GW-1",
    )
    cid = complaint["id"]
    rid = referral["id"]

    blocked = api.withdraw_complaint(cid, HANDLER)
    validate_error(blocked, ApiErrorId.ERR_REFERRAL_OPEN)
    assert get_complaint(cid)["status"] == "INTAKE"

    validate_success(api.submit_referral_response(
        rid, {"response_text": "Response filed."}, HANDLER,
    ))
    validate_success(api.close_referral(rid, MANAGER))

    withdrawn = validate_success(api.withdraw_complaint(cid, HANDLER))
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn.get("retention_purge_at") is not None
    assert get_referral(rid)["status"] == "CLOSED_BY_REGULATOR", (
        "withdraw must not disturb the closed referral"
    )


def test_complaint_withdraw_blocked_while_referral_reopened_by_regulator(api):
    """PRD §3.5: "Withdrawal is blocked with `ERR_REFERRAL_OPEN` while any
    referral of the complaint is `OPEN` or `REOPENED_BY_REGULATOR`."

    Design: Difficulty/cross_entity_state_dependency/complaint_withdraw_gated_by_referral_state
    """
    complaint, referral = intake_portal_complaint(
        "GW-SAVE", "CFPB_PORTAL", "SVC.STATEMENT", narrative="Statement dispute",
        portal_ref="CFPB-GW-2",
    )
    cid = complaint["id"]
    rid = referral["id"]
    validate_success(api.submit_referral_response(
        rid, {"response_text": "Response filed."}, HANDLER,
    ))
    reopened = validate_success(api.regulator_reopen_referral(rid, MANAGER))
    assert reopened["status"] == "REOPENED_BY_REGULATOR"

    response = api.withdraw_complaint(cid, HANDLER)
    validate_error(response, ApiErrorId.ERR_REFERRAL_OPEN)
    assert get_complaint(cid)["status"] == "INTAKE"
