"""Validation-rule tests: one test per error trigger named in the PRD
(§2.1, §2.6, §3.1–§3.9)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, headers_for,
    assert_instant_equals,
    setup_reference_data, setup_complaint, intake_complaint,
    intake_portal_complaint, setup_resolved_complaint,
    setup_complaint_in_response_qa, setup_pending_decision,
    create_category, retire_category, create_rca, create_decision,
    create_template, publish_template,
    create_and_complete_rca, draft_response,
    drive_to_investigating, claim_review, complete_review, set_clock,
    get_complaint, get_rca, get_decision, get_review, get_template,
)

MANAGER = TEST_USERS["complaint_manager_headers"]
HANDLER = TEST_USERS["case_handler_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]
EXECUTIVE = TEST_USERS["executive_reviewer_headers"]


def test_error_category_retired_on_intake(api):
    """PRD §3.1: "retired categories remain on historical records but cannot be
    assigned to new complaints — intake and recode attempts against a retired
    category are rejected with `ERR_CATEGORY_RETIRED`."

    Design: Corner/validations/error_category_retired_on_intake
    """
    setup_reference_data("P-V1", "WEB", "C.RET")
    cats, _ = validate_paginated(api.list_taxonomy_categories(MANAGER))
    cat_id = next(c["id"] for c in cats if c["category_code"] == "C.RET")
    retire_category(cat_id)

    response = api.create_complaint(
        {"complainant_ref": "CU-V1", "channel_code": "WEB", "product_code": "P-V1",
         "category_code": "C.RET", "narrative": "retired cat"},
        INTAKE,
    )
    validate_error(response, ApiErrorId.ERR_CATEGORY_RETIRED)


def test_error_rca_deadline_passed_after_30_days(api):
    """PRD §3.4: "Completing the RCA is a `CaseHandler` action guarded by three
    checks: the RCA must be in `DRAFT` (otherwise `ERR_INVALID_STATE_TRANSITION`);
    the `verdict` must be one of the three declared values (otherwise
    `ERR_INVALID_REQUEST`); and the logical clock must not be past the
    complaint's `received_at` plus thirty calendar days — the boundary is
    inclusive, so completion exactly at the deadline succeeds, and anything later
    is `ERR_RCA_DEADLINE_PASSED`."

    Design: Corner/validations/error_rca_deadline_passed_after_30_days
    """
    ctx = setup_complaint("P-V2", "WEB", "C.V2", narrative="deadline")
    cid = ctx["complaint"]["id"]
    rca = create_rca(cid, "SUBSTANTIATED", "P-V2")
    set_clock("2026-09-01T00:00:00Z")  # 31 days after the 2026-08-01 receipt
    response = api.complete_rca(rca["id"], HANDLER)
    validate_error(response, ApiErrorId.ERR_RCA_DEADLINE_PASSED)
    assert get_rca(rca["id"])["status"] == "DRAFT", (
        "a rejected completion must leave the RCA in DRAFT"
    )


def test_rca_complete_exactly_at_deadline_succeeds(api):
    """PRD §3.4: "Completing the RCA is a `CaseHandler` action guarded by three
    checks: the RCA must be in `DRAFT` (otherwise `ERR_INVALID_STATE_TRANSITION`);
    the `verdict` must be one of the three declared values (otherwise
    `ERR_INVALID_REQUEST`); and the logical clock must not be past the
    complaint's `received_at` plus thirty calendar days — the boundary is
    inclusive, so completion exactly at the deadline succeeds, and anything later
    is `ERR_RCA_DEADLINE_PASSED`."

    Design: Corner/validations/rca_complete_exactly_at_deadline_succeeds
    """
    ctx = setup_complaint("P-V2B", "WEB", "C.V2B", narrative="deadline edge")
    cid = ctx["complaint"]["id"]
    rca = create_rca(cid, "SUBSTANTIATED", "P-V2B")
    set_clock("2026-08-31T00:00:00Z")  # exactly received_at + 30 calendar days
    completed = validate_success(api.complete_rca(rca["id"], HANDLER))
    assert completed["status"] == "COMPLETED"
    assert_instant_equals(completed["completed_at"], "2026-08-31T00:00:00Z",
                          "completed_at")


def test_error_retention_expired_on_reopen(api):
    """PRD §3.5: "Reopening is available to `CaseHandler` and `ComplaintManager`
    while the record is still within its retention window: the logical clock must
    be strictly before `retention_purge_at`, or the attempt is refused with
    `ERR_RETENTION_EXPIRED`."

    Design: Corner/validations/error_retention_expired_on_reopen
    """
    ctx = setup_resolved_complaint(
        "P-V3", "WEB", "C.V3", verdict="NOT_SUBSTANTIATED",
        owner_id="user_intake_v3", reviewer_id="user_qa_v3",
        window_end_at="2026-08-02T00:00:00Z", resolve_clock="2026-08-02T00:00:00Z",
    )
    cid = ctx["complaint"]["id"]
    # resolved_at 2026-08-02 -> retention_purge_at 2031-08-02; reopen exactly at
    # the purge instant is not "strictly before" and must be refused.
    set_clock("2031-08-02T00:00:00Z")
    response = api.reopen_complaint(cid, HANDLER)
    validate_error(response, ApiErrorId.ERR_RETENTION_EXPIRED)
    assert get_complaint(cid)["status"] == "RESOLVED"


def test_error_restitution_over_authority_without_manager_flag(api):
    """PRD §3.6: "Approval carries a further authority cap: when
    `restitution_amount_cents` exceeds 2500000 cents, the acting approver must
    also present the request header `X-Manager-Authority` with the value true, or
    the approval is refused with `ERR_RESTITUTION_OVER_AUTHORITY`."

    Design: Corner/validations/error_restitution_over_authority_without_manager_flag
    """
    ctx = setup_pending_decision(
        "P-V4", "WEB", "C.V4",
        line_items=[{"label": "big", "amount_cents": 2500001}],
        drafter_id="user_handler_v4",
    )
    did = ctx["decision"]["id"]
    assert ctx["decision"]["restitution_amount_cents"] == 2500001
    response = api.approve_remediation_decision(
        did, headers_for("RemediationApprover", "user_approver_v4"),
    )
    validate_error(response, ApiErrorId.ERR_RESTITUTION_OVER_AUTHORITY)
    assert get_decision(did)["status"] == "PENDING_APPROVAL"


def test_error_sod_self_approval_blocks_drafter(api):
    """PRD §3.6: "Approval and rejection belong to a `RemediationApprover`, and
    segregation of duties is enforced on both: the acting `X-User-ID` must differ
    from the decision's `drafted_by_user_id`, or the request is
    `ERR_SOD_SELF_APPROVAL`."

    Design: Corner/validations/error_sod_self_approval_blocks_drafter
    """
    ctx = setup_pending_decision(
        "P-V5", "WEB", "C.V5",
        line_items=[{"label": "fee", "amount_cents": 7000}],
        drafter_id="user_dualrole",
    )
    did = ctx["decision"]["id"]
    assert ctx["decision"]["drafted_by_user_id"] == "user_dualrole"
    response = api.approve_remediation_decision(
        did, headers_for("RemediationApprover", "user_dualrole"),
    )
    validate_error(response, ApiErrorId.ERR_SOD_SELF_APPROVAL)
    assert get_decision(did)["status"] == "PENDING_APPROVAL"


def test_error_review_not_owned_on_complete(api):
    """PRD §3.7: "Completing a review is restricted to the owning reviewer: the
    acting `X-User-ID` must equal the review's `reviewer_user_id` (otherwise
    `ERR_REVIEW_NOT_OWNED`), the review must be `OPEN` (otherwise
    `ERR_INVALID_STATE_TRANSITION`), the supplied `outcome` must be `PASS` or
    `FAIL` (otherwise `ERR_INVALID_REQUEST`), and segregation of duties bars the
    reviewer from completing a review on a complaint whose `owner_user_id` equals
    their own identifier (`ERR_SOD_SELF_REVIEW`)."

    Design: Corner/validations/error_review_not_owned_on_complete
    """
    ctx = setup_complaint("P-V6", "WEB", "C.V6", narrative="ownership")
    cid = ctx["complaint"]["id"]
    review = claim_review(cid, "user_qa_v6a", "2026-08-01T00:00:00Z",
                          "2026-08-05T00:00:00Z")
    response = api.complete_quality_review(
        review["id"], {"outcome": "PASS"}, headers_for("QAReviewer", "user_qa_v6b"),
    )
    validate_error(response, ApiErrorId.ERR_REVIEW_NOT_OWNED)
    assert get_review(review["id"])["status"] == "OPEN"


def test_withdraw_fails_while_referral_open(api):
    """PRD §3.5: "Withdrawal is blocked with `ERR_REFERRAL_OPEN` while any
    referral of the complaint is `OPEN` or `REOPENED_BY_REGULATOR`."

    Design: Corner/validations/withdraw_fails_while_referral_open
    """
    complaint, referral = intake_portal_complaint(
        "P-V7", "CFPB_PORTAL", "C.V7", narrative="withdraw blocked",
        portal_ref="R-V7",
    )
    assert referral["status"] == "OPEN"
    response = api.withdraw_complaint(complaint["id"], HANDLER)
    validate_error(response, ApiErrorId.ERR_REFERRAL_OPEN)
    assert get_complaint(complaint["id"])["status"] == "INTAKE"


def test_error_template_in_use_blocks_retire(api):
    """PRD §3.9: "Retiring an `ACTIVE` template directly is blocked with
    `ERR_TEMPLATE_IN_USE` while any complaint in `RESPONSE_DRAFTED` or
    `RESPONSE_QA` references it via `response_template_key`; otherwise it moves
    to the terminal `RETIRED` with a version bump."

    Design: Corner/validations/error_template_in_use_blocks_retire
    """
    ctx = setup_complaint("P-V8", "WEB", "C.V8", narrative="uses template")
    template = create_template("TPL-BUSY", "WEB", "C.V8", "busy body")
    publish_template(template["id"])

    cid = ctx["complaint"]["id"]
    drive_to_investigating(cid)
    create_and_complete_rca(cid, "SUBSTANTIATED", "P-V8")
    drafted = draft_response(cid, "with template", response_template_key="TPL-BUSY")
    assert drafted["status"] == "RESPONSE_DRAFTED"

    response = api.retire_response_template(template["id"], MANAGER)
    validate_error(response, ApiErrorId.ERR_TEMPLATE_IN_USE)
    assert get_template(template["id"])["status"] == "ACTIVE"


def test_error_complaint_not_remediable_from_intake(api):
    """PRD §3.6: "Submitting a `DRAFT` decision moves it `DRAFT →
    PENDING_APPROVAL` and bumps its `version`, under two guards: a `RESTITUTION`
    or `CORRECTION_AND_RESTITUTION` decision must carry non-empty `line_items`
    and a `restitution_amount_cents` greater than 0 (otherwise
    `ERR_INVALID_REQUEST`), and the parent complaint must sit in `INVESTIGATING`,
    `RESPONSE_DRAFTED`, `RESPONSE_QA`, `RESOLVED`, or `REOPENED` — a complaint
    still in `INTAKE` or `TRIAGED`, or already `WITHDRAWN`, makes the submit
    `ERR_COMPLAINT_NOT_REMEDIABLE`."

    Design: Corner/validations/error_complaint_not_remediable_from_intake
    """
    ctx = setup_complaint("P-V9", "WEB", "C.V9", narrative="early remediation")
    cid = ctx["complaint"]["id"]
    decision = create_decision(cid, "RESTITUTION",
                               [{"label": "fee", "amount_cents": 3000}])
    response = api.submit_remediation_decision(decision["id"], HANDLER)
    validate_error(response, ApiErrorId.ERR_COMPLAINT_NOT_REMEDIABLE)
    assert get_decision(decision["id"])["status"] == "DRAFT"


def test_error_unauthenticated_missing_headers(api):
    """PRD §2.1: "A request missing either header, or presenting a role string
    outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/error_unauthenticated_missing_headers
    """
    response = api.list_products({"Content-Type": "application/json"})
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)


def test_error_template_mismatch_channel_or_category(api):
    """PRD §3.5: "The draft persists `response_text` and may name a
    `response_template_key`; when a template is named it must be `ACTIVE`
    (otherwise `ERR_TEMPLATE_NOT_ACTIVE`) and its `channel_code` and
    `category_code` must both equal the complaint's own values at draft time
    (otherwise `ERR_TEMPLATE_MISMATCH`)."

    Design: Corner/errors/error_template_mismatch_channel_or_category
    """
    ctx = setup_complaint("P-E6", "WEB", "C.E6A", narrative="mismatch")
    create_category("C.E6B")
    template = create_template("TPL-E6", "WEB", "C.E6B", "wrong category")
    publish_template(template["id"])

    cid = ctx["complaint"]["id"]
    drive_to_investigating(cid)
    create_and_complete_rca(cid, "SUBSTANTIATED", "P-E6")

    response = api.draft_response(
        cid, {"response_text": "with wrong template",
              "response_template_key": "TPL-E6"}, HANDLER,
    )
    validate_error(response, ApiErrorId.ERR_TEMPLATE_MISMATCH)
    assert get_complaint(cid)["status"] == "INVESTIGATING"


def test_error_escalation_open_blocks_resolve(api):
    """PRD §3.5: "Resolution is a `CaseHandler` action moving `RESPONSE_QA →
    RESOLVED`, guarded by two further checks evaluated after the state check: a
    `QualityReview` with `status` `COMPLETED` and `outcome` `PASS` must exist for
    the complaint (otherwise `ERR_QA_PASS_REQUIRED`), and no `EscalationCase` of
    the complaint may sit in `RAISED` or `ACKNOWLEDGED` (otherwise
    `ERR_ESCALATION_OPEN`)."

    Design: Corner/errors/error_escalation_open_blocks_resolve
    """
    ctx = setup_complaint_in_response_qa(
        "P-E7", "WEB", "C.E7", owner_id="user_intake_e7",
        narrative="escalation blocks resolve",
    )
    cid = ctx["complaint"]["id"]
    review = claim_review(cid, "user_qa_e7", "2026-08-01T00:00:00Z",
                          "2026-08-03T00:00:00Z")
    complete_review(review["id"], "PASS", "user_qa_e7")
    escalation = validate_success(
        api.create_escalation(cid, {"escalation_tier": "EXECUTIVE",
                                    "reason": "Media attention"}, MANAGER),
        expected_status=201,
    )
    validate_success(api.acknowledge_escalation(escalation["id"], EXECUTIVE))

    response = api.resolve_complaint(cid, HANDLER)
    validate_error(response, ApiErrorId.ERR_ESCALATION_OPEN)
    assert get_complaint(cid)["status"] == "RESPONSE_QA"


def test_draft_response_without_rca_single_failure(api):
    """PRD §3.5: "Drafting without a completed RCA is refused with
    `ERR_RCA_REQUIRED`."

    Design: Corner/errors/draft_response_without_rca_single_failure
    """
    ctx = setup_complaint("P-E8", "WEB", "C.E8", narrative="no rca")
    cid = ctx["complaint"]["id"]
    drive_to_investigating(cid)
    response = api.draft_response(cid, {"response_text": "premature"}, HANDLER)
    validate_error(response, ApiErrorId.ERR_RCA_REQUIRED)
    assert get_complaint(cid)["status"] == "INVESTIGATING"
