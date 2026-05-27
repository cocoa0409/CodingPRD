"""RBAC role denials, missing-authentication, and the body-FK not-found
error. PRD §2.1 sets the role gating; PRD §4 lists the per-endpoint role
authorizations.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_applicant_headers,
    set_clock,
    setup_application_in_awaiting_examination, setup_application_in_allowed,
    create_applicant,
    get_application,
    create_pay_issue_fee_payload, create_fee_payment_payload,
)


# =============================================================================
# Corner / rbac / applicant_cannot_docket_application
# =============================================================================

def test_applicant_cannot_docket_application(api):
    """Applicant role cannot POST /applications/{id}/docket — that endpoint
    is exclusive to USPTOExaminer. Returns ERR_FORBIDDEN (403).

    PRD §2.1: "A request whose role lacks permission for the endpoint per
    §4 is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/applicant_cannot_docket_application
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application = setup_application_in_awaiting_examination(
        entity_size="LARGE", application_type="UTILITY",
    )
    # Use a fresh application in FILED with filing fee paid (preconditions
    # for docket) — but as Applicant role (forbidden).
    from test_helpers import setup_applicant_and_application, pay_filing_fee
    applicant2, app2 = setup_applicant_and_application(
        entity_size="LARGE", application_type="UTILITY",
    )
    pay_filing_fee(applicant2, app2)

    res = api.docket_application(app2["id"], make_applicant_headers(applicant2["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# =============================================================================
# Corner / rbac / examiner_cannot_pay_issue_fee
# =============================================================================

def test_examiner_cannot_pay_issue_fee(api, examiner_headers):
    """USPTOExaminer cannot POST /applications/{id}/pay-issue-fee — that
    endpoint is exclusive to Applicant. Returns ERR_FORBIDDEN (403).

    PRD §2.1: "A request whose role lacks permission for the endpoint per
    §4 is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/examiner_cannot_pay_issue_fee
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application = setup_application_in_allowed(
        entity_size="LARGE", application_type="UTILITY",
    )
    version_now = get_application(application["id"], applicant)["version"]

    res = api.pay_issue_fee(
        application["id"],
        create_pay_issue_fee_payload(
            amount_cents=120000,  # LARGE UTILITY issue
            expected_application_version=version_now,
        ),
        examiner_headers,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# =============================================================================
# Corner / rbac / missing_x_user_role_returns_unauthenticated
# =============================================================================

def test_missing_x_user_role_header_returns_unauthenticated(api):
    """A request missing the X-User-Role header is rejected with
    ERR_UNAUTHENTICATED (401).

    PRD §2.1: "Every request must carry two headers: `X-User-ID`,
    identifying the calling principal, and `X-User-Role`, naming one of
    three roles — `Applicant`, `USPTOExaminer`, or `USPTOAdmin`. A request
    missing either header, carrying an unknown role string, or naming an
    `X-User-ID` that does not resolve to an existing applicant when the
    role is `Applicant`, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_x_user_role_returns_unauthenticated
    """
    # Empty headers — no X-User-Role.
    res = api.list_applications({}, params={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)


# =============================================================================
# Corner / errors / error_application_not_found_for_fee_payment
# =============================================================================

def test_fee_payment_with_nonexistent_application_id_returns_not_found(api):
    """POST /fee-payments with a body-referenced application_id that does
    not exist returns ERR_APPLICATION_NOT_FOUND (404).

    PRD §2.5: "The same `ERR_APPLICATION_NOT_FOUND` is raised when a
    request body references a foreign key — `applicant_id`, `application_id`,
    `office_action_id`, `parent_application_id`, or `maintenance_fee_id` —
    that does not resolve to an existing row."

    Design: Corner/errors/error_application_not_found_for_fee_payment
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant = create_applicant(legal_name="NF Co", entity_size="LARGE")
    res = api.create_fee_payment(
        create_fee_payment_payload(
            application_id="00000000-0000-0000-0000-000000000000",
            payment_category="FILING",
            amount_cents=32000,
        ),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_APPLICATION_NOT_FOUND.value)
