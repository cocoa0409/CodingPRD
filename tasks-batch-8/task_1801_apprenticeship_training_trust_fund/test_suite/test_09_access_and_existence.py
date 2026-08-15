"""Access control and resource existence: identity headers, role matrix, and
per-resource 404s (PRD §2.1, §2.10, §3.1)."""
from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
    NO_AUTH_HEADERS,
    ApiErrorId,
    create_employer_payload,
    create_fund,
    validate_error,
)


def test_request_without_identity_headers_rejected(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, declaring their
    operational capacity."
    PRD §2.1: "A request missing either header, or presenting a role the
    system does not recognize, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/roles/unauthenticated_request_rejected
    """
    resp = api.create_trust_fund({"name": "No Auth Fund"}, NO_AUTH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    assert resp.status_code == 400


def test_employer_get_not_found_returns_404(api):
    """PRD §2.10: "Fourth, existence: every resource id appearing in the path
    or the request body must resolve, validated left to right, so the first
    unresolvable id determines the error — an unknown fund yields
    `ERR_FUND_NOT_FOUND`, an unknown employer `ERR_EMPLOYER_NOT_FOUND`, an
    unknown apprentice `ERR_APPRENTICE_NOT_FOUND`, an unknown report
    `ERR_REPORT_NOT_FOUND`, an unknown class `ERR_CLASS_NOT_FOUND`, an unknown
    enrollment `ERR_ENROLLMENT_NOT_FOUND`, an unknown claim
    `ERR_CLAIM_NOT_FOUND`, an unknown allocation `ERR_ALLOCATION_NOT_FOUND`,
    and an unknown purchase `ERR_PURCHASE_NOT_FOUND` (all HTTP 404)."

    Design: Corner/entities/employer_get_not_found_returns_404
    """
    resp = api.get_employer(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_EMPLOYER_NOT_FOUND)
    assert resp.status_code == 404


def test_enrollment_get_not_found_returns_404(api):
    """PRD §2.10: "Fourth, existence: every resource id appearing in the path
    or the request body must resolve, validated left to right, so the first
    unresolvable id determines the error — an unknown fund yields
    `ERR_FUND_NOT_FOUND`, an unknown employer `ERR_EMPLOYER_NOT_FOUND`, an
    unknown apprentice `ERR_APPRENTICE_NOT_FOUND`, an unknown report
    `ERR_REPORT_NOT_FOUND`, an unknown class `ERR_CLASS_NOT_FOUND`, an unknown
    enrollment `ERR_ENROLLMENT_NOT_FOUND`, an unknown claim
    `ERR_CLAIM_NOT_FOUND`, an unknown allocation `ERR_ALLOCATION_NOT_FOUND`,
    and an unknown purchase `ERR_PURCHASE_NOT_FOUND` (all HTTP 404)."

    Design: Corner/entities/enrollment_get_not_found_returns_404
    """
    resp = api.get_enrollment(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_FOUND)
    assert resp.status_code == 404


def test_get_not_found_variants(api):
    """PRD §2.10: "Fourth, existence: every resource id appearing in the path
    or the request body must resolve, validated left to right, so the first
    unresolvable id determines the error — an unknown fund yields
    `ERR_FUND_NOT_FOUND`, an unknown employer `ERR_EMPLOYER_NOT_FOUND`, an
    unknown apprentice `ERR_APPRENTICE_NOT_FOUND`, an unknown report
    `ERR_REPORT_NOT_FOUND`, an unknown class `ERR_CLASS_NOT_FOUND`, an unknown
    enrollment `ERR_ENROLLMENT_NOT_FOUND`, an unknown claim
    `ERR_CLAIM_NOT_FOUND`, an unknown allocation `ERR_ALLOCATION_NOT_FOUND`,
    and an unknown purchase `ERR_PURCHASE_NOT_FOUND` (all HTTP 404)."

    Design: Corner/errors/error_not_found_variants
    """
    cases = [
        (api.get_trust_fund, ApiErrorId.ERR_FUND_NOT_FOUND),
        (api.get_apprentice, ApiErrorId.ERR_APPRENTICE_NOT_FOUND),
        (api.get_contribution_report, ApiErrorId.ERR_REPORT_NOT_FOUND),
        (api.get_class, ApiErrorId.ERR_CLASS_NOT_FOUND),
        (api.get_pay_claim, ApiErrorId.ERR_CLAIM_NOT_FOUND),
        (api.get_funding_allocation, ApiErrorId.ERR_ALLOCATION_NOT_FOUND),
        (api.get_equipment_purchase, ApiErrorId.ERR_PURCHASE_NOT_FOUND),
    ]
    for getter, expected_error in cases:
        resp = getter(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, expected_error)
        assert resp.status_code == 404, (
            f"{expected_error.value} must be HTTP 404"
        )


def test_employer_create_missing_rate_rejected(api):
    """PRD §3.1: "Employers are onboarded onto the fund with a payload
    carrying the `trust_fund_id` they are signatory to, their `legal_name`,
    and their `agreement_rate_cents_per_hour` — the negotiated hourly training
    contribution, expressed in cents."
    PRD §2.10: "Fifth, request shape: required fields present with correct
    types, a non-empty line set, period validity, class-window validity, and
    registration-outcome validity."

    Design: Corner/entities/required_field_missing_rejected
    """
    fund = create_fund()
    payload = create_employer_payload(fund["id"], legal_name="No Rate Inc")
    del payload["agreement_rate_cents_per_hour"]
    resp = api.create_employer(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert resp.status_code == 400
