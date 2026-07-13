"""Guardianship referral eligibility, cross-report recording, and the
authentication / authorization gates."""
from test_helpers import validate_success, validate_error, ApiErrorId, TEST_USERS
from test_helpers import fixtures as fx

INTAKE = TEST_USERS["intake_worker_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
CASEWORKER = TEST_USERS["caseworker_headers"]


def test_refer_guardianship_capacity_not_impaired_returns_422(api):
    """PRD §3.7: "the referral requires the client's `capacity_status` to be
    `IMPAIRED`, and a referral against a client who is not impaired is rejected
    with `ERR_CAPACITY_NOT_IMPAIRED` (422)."

    Design: Corner/validations/refer_guardianship_capacity_not_impaired_returns_422
    """
    base = fx.create_screened_in_case(allegation_types=["NEGLECT"], priority="PRIORITY")
    resp = api.refer_guardianship(base["case_id"], {}, CASEWORKER)
    validate_error(resp, ApiErrorId.ERR_CAPACITY_NOT_IMPAIRED.value)


def test_auth_missing_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of
    these four known roles, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/validations/auth_missing_headers_returns_unauthenticated
    """
    resp = api.create_client(
        {"full_name": "No Auth", "date_of_birth": "1948-01-01", "address": "12 Way"},
        {},  # no X-User-ID / X-User-Role headers
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_unauthorized_intakeworker_cannot_screen_returns_403(api):
    """PRD §2.1: "If the headers are valid but the acting role is not permitted
    to perform the requested operation according to the authorization matrix in
    Section 4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "POST `/reports/{id}/screen` — Screen a report in or out —
    Supervisor".

    Design: Corner/validations/unauthorized_intakeworker_cannot_screen_returns_403
    """
    client = fx.new_client()
    report = fx.new_report(client["id"], allegation_types=["NEGLECT"], priority="ROUTINE", narrative="n")
    resp = api.screen_report(report["id"], {"decision": "SCREEN_IN"}, INTAKE)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_cross_report_sets_agency_and_timestamp(api):
    """PRD §3.7: "A `Caseworker` or a `Supervisor` cross-reports by supplying the
    `recipient_agency`; the system records it as the case's `cross_report_agency`
    and stamps `cross_reported_at` with the logical clock."

    Design: Corner/endpoints/cross_report_sets_agency
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    base = fx.create_screened_in_case(allegation_types=["FINANCIAL_EXPLOITATION"], priority="PRIORITY")
    resp = api.cross_report_case(base["case_id"], {"recipient_agency": "COUNTY_SHERIFF"}, SUPERVISOR)
    data = validate_success(resp)
    assert data["cross_report_agency"] == "COUNTY_SHERIFF"
    assert data["cross_reported_at"] == "2026-06-01T00:00:00.000Z"
