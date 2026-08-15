"""RBAC denial and role-model tests (PRD §2.1, §3.7, §4)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, headers_for,
    setup_reference_data, setup_complaint, intake_complaint,
    intake_portal_complaint, setup_pending_decision,
    create_template, claim_review,
    get_complaint, get_referral, get_template, get_review,
)

MANAGER = TEST_USERS["complaint_manager_headers"]
HANDLER = TEST_USERS["case_handler_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]
QA = TEST_USERS["qa_reviewer_headers"]
EXECUTIVE = TEST_USERS["executive_reviewer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_intake_specialist_cannot_triage(api):
    """PRD §2.1: "A request whose role is authenticated but not permitted for the
    target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "| POST | /complaint-office/complaints/{complaintId}/triage | INTAKE →
    TRIAGED | CaseHandler |"

    Design: Corner/rbac/intake_specialist_cannot_triage
    """
    ctx = setup_complaint("P-R1", "WEB", "C.R1", narrative="rbac")
    response = api.triage_complaint(ctx["complaint"]["id"], INTAKE)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert get_complaint(ctx["complaint"]["id"])["status"] == "INTAKE"


def test_case_handler_cannot_approve_remediation(api):
    """PRD §2.1: "A request whose role is authenticated but not permitted for the
    target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "| POST | /complaint-office/remediation-decisions/{decisionId}/approve
    | PENDING_APPROVAL → APPROVED (segregation of duties + authority cap) |
    RemediationApprover |"

    Design: Corner/rbac/case_handler_cannot_approve_remediation
    """
    ctx = setup_pending_decision(
        "P-R2", "WEB", "C.R2",
        line_items=[{"label": "fee", "amount_cents": 1000}],
        drafter_id="user_handler_r2",
    )
    response = api.approve_remediation_decision(
        ctx["decision"]["id"], headers_for("CaseHandler", "user_handler_r2b"),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_auditor_is_read_only(api):
    """PRD §2.1: "`Auditor` — read-only access to all resources, including the
    audit trail and trend snapshots."
    PRD §2.1: "A request whose role is authenticated but not permitted for the
    target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "| POST | /complaint-office/complaints | Intake a complaint;
    auto-creates a RegulatoryReferral on portal channels | IntakeSpecialist,
    CaseHandler |"

    Design: Corner/rbac/auditor_is_read_only
    """
    setup_reference_data("P-R3", "WEB", "C.R3")
    response = api.create_complaint(
        {"complainant_ref": "CU-R3", "channel_code": "WEB", "product_code": "P-R3",
         "category_code": "C.R3", "narrative": "auditor write"},
        AUDITOR,
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_executive_reviewer_cannot_close_referral(api):
    """PRD §2.1: "A request whose role is authenticated but not permitted for the
    target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "| POST | /complaint-office/referrals/{referralId}/close |
    RESPONSE_SUBMITTED → CLOSED_BY_REGULATOR | ComplaintManager |"

    Design: Corner/rbac/executive_reviewer_cannot_close_referral
    """
    complaint, referral = intake_portal_complaint(
        "P-R4", "CFPB_PORTAL", "C.R4", narrative="rbac close", portal_ref="R-R4",
    )
    validate_success(api.submit_referral_response(
        referral["id"], {"response_text": "resp"}, HANDLER,
    ))
    assert get_referral(referral["id"])["status"] == "RESPONSE_SUBMITTED"
    response = api.close_referral(referral["id"], EXECUTIVE)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert get_referral(referral["id"])["status"] == "RESPONSE_SUBMITTED"


def test_qa_reviewer_cannot_publish_template(api):
    """PRD §2.1: "A request whose role is authenticated but not permitted for the
    target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "| POST | /complaint-office/response-templates/{templateId}/publish |
    Publish a DRAFT template; supersedes the ACTIVE template of the same pair |
    ComplaintManager |"

    Design: Corner/rbac/qa_reviewer_cannot_publish_template
    """
    setup_reference_data("P-R5", "WEB", "C.R5")
    template = create_template("TPL-R5", "WEB", "C.R5", "b")
    response = api.publish_response_template(template["id"], QA)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert get_template(template["id"])["status"] == "DRAFT"


def test_complaint_manager_can_cancel_any_review_but_qa_reviewer_only_own(api):
    """PRD §3.7: "Cancellation moves `OPEN → CANCELLED` and is available to a
    `QAReviewer` — again only their own reviews, or `ERR_REVIEW_NOT_OWNED` — and
    to a `ComplaintManager`, who is not subject to the ownership check."

    Design: Corner/rbac/complaint_manager_can_cancel_any_review_but_qa_reviewer_only_own
    """
    refs = setup_reference_data("P-R6", "WEB", "C.R6")
    ca = intake_complaint("P-R6", "WEB", "C.R6", complainant_ref="CU-R6A", narrative="a")
    cb = intake_complaint("P-R6", "WEB", "C.R6", complainant_ref="CU-R6B", narrative="b")
    review_a = claim_review(ca["id"], "user_qa_r6", "2026-08-01T00:00:00Z",
                            "2026-08-05T00:00:00Z")
    review_b = claim_review(cb["id"], "user_qa_r6", "2026-08-06T00:00:00Z",
                            "2026-08-09T00:00:00Z")

    cancelled = validate_success(api.cancel_quality_review(review_a["id"], MANAGER))
    assert cancelled["status"] == "CANCELLED", (
        "ComplaintManager is not subject to the ownership check"
    )

    response = api.cancel_quality_review(
        review_b["id"], headers_for("QAReviewer", "user_qa_r6b"),
    )
    validate_error(response, ApiErrorId.ERR_REVIEW_NOT_OWNED)
    assert get_review(review_b["id"])["status"] == "OPEN"
