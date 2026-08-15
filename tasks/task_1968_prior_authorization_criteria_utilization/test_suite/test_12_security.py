"""Identity headers and role-based access control (PRD §2.1, §2.7, §4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    basic_um_environment,
    create_prior_auth_request_payload,
    denied_determination,
    file_appeal,
    pended_request,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["um_admin_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]
REVIEWER = TEST_USERS["clinical_reviewer_headers"]


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
    PRD §2.7: "When several checks could reject the same call, they are evaluated in a fixed priority order so the surfaced error is deterministic. First, presence of the identity headers (§2.1)."

    Design: Corner/validations/missing_user_context_header_rejected
    """
    resp = api.create_provider({"npi": "2000000016", "name": "Anon"}, None)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_clinical_reviewer_cannot_intake(api):
    """PRD §2.1: "Once identity is established, the role is checked against the endpoint's permission set; a caller whose role is not permitted is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §4: POST /um/prior-auth-requests is authorized for IntakeSpecialist only ("Intake a prior-auth request; pins the governing guideline version and runs auto-adjudication synchronously | IntakeSpecialist").

    Design: Corner/rbac/clinical_reviewer_cannot_intake
    """
    provider, cs, _gv = basic_um_environment()
    payload = create_prior_auth_request_payload(
        provider_id=provider["id"], criteria_set_id=cs["id"],
    )
    resp = api.create_prior_auth_request(payload, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_intake_specialist_cannot_reviewer_decide(api):
    """PRD §2.1: "Once identity is established, the role is checked against the endpoint's permission set; a caller whose role is not permitted is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §2.7: "Second, role permission for the endpoint."
    PRD §4: POST /um/prior-auth-requests/{id}/reviewer-decision is authorized for ClinicalReviewer only ("Clinical reviewer tier decision: APPROVE / DENY (creates a determination) or ESCALATE to the medical director | ClinicalReviewer").

    Design: Corner/rbac/intake_specialist_cannot_reviewer_decide
    """
    provider, cs, _gv = basic_um_environment()
    req = pended_request(provider["id"], cs["id"])
    resp = api.reviewer_decision(
        req["id"],
        {"decision": "APPROVE", "reason_code": "MEDICAL_NECESSITY_MET"},
        INTAKE,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    reread = validate_success(api.get_prior_auth_request(req["id"], ADMIN))
    assert reread["status"] == "PENDED_REVIEW", (
        "role check fired before any state mutation"
    )


def test_um_admin_cannot_decide_appeal(api):
    """PRD §2.1: "Once identity is established, the role is checked against the endpoint's permission set; a caller whose role is not permitted is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §4: POST /um/appeals/{id}/decide is authorized for AppealsReviewer only ("Decide an appeal UPHELD or OVERTURNED (overturn cascades to determination, request, provider stats, and the audit log) | AppealsReviewer").

    Design: Corner/rbac/um_admin_cannot_decide_appeal
    """
    provider, cs, _gv = basic_um_environment()
    _req, det = denied_determination(
        provider["id"], cs["id"], deny_reason_code="INSUFFICIENT_INFO",
    )
    appeal = file_appeal(det["id"], appeal_reason="Appeal")
    resp = api.decide_appeal(appeal["id"], {"outcome": "UPHELD"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
