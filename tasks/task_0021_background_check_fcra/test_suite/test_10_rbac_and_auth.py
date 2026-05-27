"""Authentication / authorization / RBAC errors, plus OCC stale_version on
application submit.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    set_clock,
    application_in_conditional_offer,
    application_in_submitted,
    create_applicant_and_application,
    create_consent, grant_consent,
    make_applicant_headers, REC, CO, PA,
)


def test_request_without_x_user_role_returns_missing_auth(api):
    """A request that omits the X-User-Role header (or X-User-ID) on a
    non-public endpoint is rejected with ERR_MISSING_AUTH (HTTP 401).

    PRD §2.1: "Every request to a non-public endpoint must include two
    HTTP headers: `X-User-ID`, identifying the caller, and `X-User-Role`,
    naming the caller's role. A request missing either header is rejected
    with `ERR_MISSING_AUTH` (HTTP 401)."

    Design: Corner/errors/error_missing_auth_when_x_user_role_absent
    """
    set_clock("2026-06-01T10:00:00.000Z")
    # Pass headers with no X-User-ID / X-User-Role — only Content-Type.
    resp = api.list_applications({"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value)


def test_request_with_unknown_x_user_role_returns_invalid_role(api):
    """A request whose X-User-Role is not one of the five declared roles
    is rejected with ERR_INVALID_ROLE (HTTP 401).

    PRD §2.1: "A request whose `X-User-Role` does not match one of the
    declared role names below is rejected with `ERR_INVALID_ROLE` (HTTP
    401)."

    Design: Corner/errors/error_invalid_role_when_unknown_x_user_role
    """
    set_clock("2026-06-01T10:00:00.000Z")
    bogus = {
        "X-User-ID": "anyone",
        "X-User-Role": "SomethingUndeclared",
        "Content-Type": "application/json",
    }
    resp = api.list_applications(bogus)
    validate_error(resp, ApiErrorId.ERR_INVALID_ROLE.value)


def test_applicant_attempting_recruiter_endpoint_returns_unauthorized(api):
    """An Applicant attempting POST /background-check-orders (Recruiter
    exclusive) is authenticated but not permitted → ERR_UNAUTHORIZED.

    PRD §2.1: "When the role is authenticated but is not permitted to
    call the requested endpoint, the rejection is `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/errors/error_unauthorized_when_applicant_attempts_recruiter_endpoint
    """
    jur, applicant, app, consent = application_in_conditional_offer(state_code="IA")
    resp = api.create_order(
        {"application_id": app["id"], "consent_id": consent["id"],
         "expected_application_version": app["version"]},
        make_applicant_headers(applicant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_submit_with_stale_application_version_returns_stale_version(api):
    """The submit endpoint takes expected_application_version and rejects
    a mismatch with ERR_STALE_VERSION (HTTP 412).

    PRD §2.6: "Every other mutating endpoint that takes an
    `expected_*_version` field (application submit, conditional offer,
    hire, withdraw, consent grant, consent revoke, order cancel,
    verification report, verification dispute, verification resolve)
    likewise requires that field as part of the request payload and
    rejects a mismatch with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/error_stale_version_on_application_submit
    """
    # PRD §2.9 fixes priority: state-legality (slot 5) precedes OCC (slot 6),
    # so an already-SUBMITTED app would surface ERR_INVALID_STATE before OCC
    # could be evaluated. To target ERR_STALE_VERSION we must keep the app in
    # DRAFT (state-legal for submit) AND ensure the request payload is valid
    # (priority slot 7+ for §3 business rules — submit's GRANTED-consent
    # precondition would come AFTER OCC if state passes). Grant a consent so
    # the consent precondition is satisfied, but DO NOT submit; then call
    # submit with a stale version (current is 1; pass 0).
    jur, applicant, app = create_applicant_and_application(state_code="WY")
    consent = create_consent(app["id"], applicant["id"])
    grant_consent(consent["id"], consent["version"], applicant["id"])
    # App version is currently 1 (still DRAFT); pass 0 to force stale.
    resp = api.submit_application(
        app["id"],
        {"expected_application_version": app["version"] - 1},
        make_applicant_headers(applicant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_compliance_officer_can_read_audit_logs_recruiter_denied(api):
    """GET /audit-logs is exclusive to the ComplianceOfficer role; a
    Recruiter is denied with ERR_UNAUTHORIZED.

    PRD §3.8: "The log is read-only and is available only to the
    `ComplianceOfficer` role, with optional filters on `entity_type` and
    `entity_id`."
    PRD §2.1: "When the role is authenticated but is not permitted to
    call the requested endpoint, the rejection is `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/rbac_compliance_officer_can_read_audit_logs
    """
    set_clock("2026-06-01T10:00:00.000Z")
    # Recruiter forbidden.
    rec_resp = api.list_audit_logs(REC)
    validate_error(rec_resp, ApiErrorId.ERR_UNAUTHORIZED.value)
    # ComplianceOfficer permitted (response_type=array).
    co_resp = api.list_audit_logs(CO)
    body = co_resp.json() if hasattr(co_resp, "json") else co_resp
    # Use validate_success-like check: response_type=='array' and data is list.
    assert body.get("response_type") == "array", \
        f"ComplianceOfficer audit-log list must return array envelope, got {body.get('response_type')!r}"
    assert isinstance(body.get("data"), list), \
        f"audit-log data must be a list, got {type(body.get('data'))!r}"
