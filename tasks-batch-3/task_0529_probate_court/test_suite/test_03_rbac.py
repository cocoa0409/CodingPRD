"""Role-based access control and segregation of duties (Corner queue: rbac section)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_estate, create_petition,
    create_open_estate_with_nominated_pr, create_independent_estate_with_appointed_pr,
    nominate_representative, list_asset,
    make_judge_headers, build_user_headers,
    ApiErrorId, TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]
JUDGE = TEST_USERS["judge_headers"]
REP = TEST_USERS["representative_headers"]


def test_clerk_cannot_grant_petition_returns_unauthorized(api):
    """PRD §2.1: "When a caller is authenticated but their role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)." PRD §4 lists `POST /petitions/{id}/grant` as authorized for
    ProbateJudge only.

    Design: Corner/rbac/clerk_cannot_grant_petition_returns_unauthorized
    """
    est = create_estate(gross_estate_value_cents=300_000)
    pet = create_petition(est["id"])
    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    resp = api.grant_petition(pet["id"], {"expected_estate_version": v}, CLERK)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_judge_cannot_appraise_asset_returns_unauthorized(api):
    """PRD §2.1: "When a caller is authenticated but their role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)." PRD §4 lists `POST /assets/{id}/appraise` as authorized for
    PersonalRepresentative only.

    Design: Corner/rbac/judge_cannot_appraise_asset_returns_unauthorized
    """
    est, pet, rep = create_independent_estate_with_appointed_pr()
    asset = list_asset(est["id"], "CASH", 100_000, "X")
    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    resp = api.appraise_asset(
        asset["id"], {"appraised_value_cents": 100_000, "expected_estate_version": v}, JUDGE)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_judge_appoints_self_as_pr_returns_segregation_of_duties(api):
    """PRD §2.1: "On appointment, if the acting judge's `X-User-ID` is equal to the
    representative's `representative_user_id`, the request is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). This check is specific to the appointment
    operation."

    Design: Corner/rbac/judge_appoints_self_as_pr_returns_segregation_of_duties
    """
    est, pet, rep = create_open_estate_with_nominated_pr(
        gross=300_000, representative_user_id="judge-self")
    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    resp = api.appoint_representative(
        rep["id"], {"expected_estate_version": v}, make_judge_headers("judge-self"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    rep_after = get_success_data(api.get_representative(rep["id"], CLERK))
    assert rep_after["status"] == "NOMINATED"


def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "Every request to the API must be authenticated by two mandatory
    HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`,
    which declares the operational capacity in which they act. If either header is
    absent, or if `X-User-Role` names a role the system does not recognize, the
    request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    resp = api.create_estate({
        "decedent_name": "NoAuth", "date_of_death": "2026-04-01T00:00:00Z",
        "county_code": "LA", "estate_type": "INTESTATE",
        "gross_estate_value_cents": 300_000,
    }, {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
