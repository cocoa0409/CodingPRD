"""Authentication, role authorization, and ownership-scoped access."""
from test_helpers import (
    ApiErrorId,
    create_development_agreement_payload,
    get_application,
    make_applicant_headers,
    register_applicant,
    render_decision_payload,
    setup_approved_application,
    setup_decision_pending_application,
    setup_submitted_application,
    validate_error,
    validate_success,
)


def test_missing_auth_header_returns_unauthenticated(api):
    """PRD 2.1: "A request missing either header, or declaring a role the
    system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (401)."
    PRD 2.9: "Authentication. `X-User-ID` and `X-User-Role` are present and the
    role is declared, else `ERR_UNAUTHENTICATED` (401)." — gate 1 runs before
    every other check.

    Design: Corner/validations/missing_auth_header_returns_unauthenticated
    """
    response = api.list_projects(headers={})
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_applicant_cannot_render_decision(api):
    """PRD 2.1: "Once authenticated, the declared role must be authorized for
    the target operation; otherwise the request fails with `ERR_FORBIDDEN`
    (403)."
    PRD 4: POST `/entitlement/applications/{appId}/decisions` is authorized for
    DecisionAuthority only.

    Design: Corner/rbac/applicant_cannot_render_decision
    """
    ctx = setup_decision_pending_application()
    app_id = ctx["application"]["id"]
    current = get_application(app_id, ctx["reviewer_headers"])

    payload = render_decision_payload(
        decided_by=ctx["applicant"]["id"],
        expected_application_version=current["version"],
        decision="APPROVE",
    )
    response = api.render_decision(app_id, payload, ctx["applicant_headers"])
    validate_error(response, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    after = get_application(app_id, ctx["reviewer_headers"])
    assert after["status"] == "DECISION_PENDING", (
        f"forbidden render must not mutate state, got {after['status']}"
    )


def test_staff_reviewer_cannot_adopt_development_agreement(api):
    """PRD 2.1: "Once authenticated, the declared role must be authorized for
    the target operation; otherwise the request fails with `ERR_FORBIDDEN`
    (403)."
    PRD 3.8: "Adoption, again by a `DecisionAuthority`, requires the parent
    application to stand `APPROVED` — else `ERR_APPLICATION_NOT_APPROVED`" —
    the adopting actor is a DecisionAuthority, not staff.

    Design: Corner/rbac/staff_reviewer_cannot_adopt_development_agreement
    """
    ctx = setup_approved_application()
    auth_headers = ctx["authority_headers"]
    payload = create_development_agreement_payload(
        agreement_number="ORD-R", registered_voters=1000
    )
    da = validate_success(
        api.create_development_agreement(ctx["application"]["id"], payload, auth_headers),
        expected_status=201,
    )
    assert da["status"] == "DRAFT"

    response = api.adopt_development_agreement(da["id"], ctx["reviewer_headers"])
    validate_error(response, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    after = validate_success(api.get_development_agreement(da["id"], auth_headers))
    assert after["status"] == "DRAFT", (
        f"forbidden adoption must leave the agreement DRAFT, got {after['status']}"
    )


def test_withdraw_by_non_owner_applicant_returns_not_owner(api):
    """PRD 3.9: "the applicant may withdraw the application — but only the
    applicant who owns the parent project: the `X-User-ID` must equal the
    project's `applicant_id`, else `ERR_NOT_PROJECT_OWNER`."

    Design: Corner/rbac/withdraw_by_non_owner_applicant_returns_not_owner
    """
    ctx = setup_submitted_application()
    app_id = ctx["application"]["id"]

    intruder = register_applicant(legal_name="NotOwnerB", contact_email="b@x.com")
    intruder_headers = make_applicant_headers(intruder["id"])

    response = api.withdraw_application(app_id, intruder_headers)
    validate_error(response, ApiErrorId.ERR_NOT_PROJECT_OWNER, expected_status=403)

    after = get_application(app_id, ctx["applicant_headers"])
    assert after["status"] == "SUBMITTED", (
        f"rejected withdrawal must leave the application SUBMITTED, got {after['status']}"
    )
