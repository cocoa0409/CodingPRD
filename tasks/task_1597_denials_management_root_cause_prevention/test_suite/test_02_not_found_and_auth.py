"""Authentication, authorization, and reference-resolution gates (PRD §2.8)."""
from test_helpers import (
    ApiErrorId,
    make_denial,
    setup_catalog,
    validate_error,
    validate_success,
)

UNKNOWN_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.8: "**Authentication.** `X-User-ID` and `X-User-Role` must be present and the
    role must be one of the five declared roles, else `ERR_UNAUTHENTICATED` (401). Applies
    to every endpoint."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    resp = api.list_denial_cases(headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_missing_auth_on_unknown_denial_returns_unauthenticated(api):
    """PRD §2.8: "When a request violates several rules at once, the server evaluates the
    following gates in the order listed and returns the error from the first gate that
    fails — a lower-numbered gate always wins over a later one."
    PRD §2.8: "**Authentication.** `X-User-ID` and `X-User-Role` must be present and the
    role must be one of the five declared roles, else `ERR_UNAUTHENTICATED` (401). Applies
    to every endpoint."

    Design: Corner/validations/missing_auth_on_unknown_denial_returns_unauthenticated
    """
    resp = api.get_denial_case(UNKNOWN_ID, headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_denial_get_unknown_id_returns_not_found(api, manager_headers):
    """PRD §2.8: "An unresolvable payer, denial, or appeal reference yields
    `ERR_PAYER_NOT_FOUND`, `ERR_DENIAL_NOT_FOUND`, or `ERR_APPEAL_NOT_FOUND` respectively;
    any other unresolvable reference (appeal policy, remittance code, attachment, root-cause
    task, write-off request, scorecard, prevention program, or event) yields
    `ERR_NOT_FOUND`. All four are 404."

    Design: Corner/entities/denial_get_unknown_id_returns_not_found
    """
    resp = api.get_denial_case(UNKNOWN_ID, manager_headers)
    validate_error(resp, ApiErrorId.ERR_DENIAL_NOT_FOUND, expected_status=404)


def test_resource_not_found_variants(api, manager_headers):
    """PRD §2.8: "An unresolvable payer, denial, or appeal reference yields
    `ERR_PAYER_NOT_FOUND`, `ERR_DENIAL_NOT_FOUND`, or `ERR_APPEAL_NOT_FOUND` respectively;
    any other unresolvable reference (appeal policy, remittance code, attachment, root-cause
    task, write-off request, scorecard, prevention program, or event) yields
    `ERR_NOT_FOUND`. All four are 404."

    Design: Corner/errors/resource_not_found_variants
    """
    validate_error(api.get_payer(UNKNOWN_ID, manager_headers),
                   ApiErrorId.ERR_PAYER_NOT_FOUND, expected_status=404)
    validate_error(api.get_appeal(UNKNOWN_ID, manager_headers),
                   ApiErrorId.ERR_APPEAL_NOT_FOUND, expected_status=404)
    validate_error(api.get_root_cause_task(UNKNOWN_ID, manager_headers),
                   ApiErrorId.ERR_NOT_FOUND, expected_status=404)
    validate_error(api.get_write_off_request(UNKNOWN_ID, manager_headers),
                   ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_auditor_shared_read_access(api, auditor_headers):
    """PRD §2.1: "All five roles share read access to every retrieval and list endpoint in
    the API."

    Design: Corner/rbac/auditor_shared_read_access
    """
    catalog = setup_catalog(levels=())
    denial = make_denial(catalog["payer"]["id"], catalog["code"]["id"],
                         claim_number="CLM-2504")
    resp = api.get_denial_case(denial["id"], auditor_headers)
    data = validate_success(resp)
    assert data["status"] == "RECEIVED"
