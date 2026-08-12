"""Authentication and role authorization (PRD §2.1, §4)."""
from test_helpers import (
    validate_success, validate_error,
    fiscal_year_payload, make_member_headers, TEST_USERS,
    create_district, create_member, set_clock, setup_year_with_deliveries,
    close_year_provisional, finalize_year, get_fiscal_year,
    list_member_certificates, create_redemption_request, submit_request,
)

SECRETARY = TEST_USERS["secretary_headers"]


def test_missing_x_user_role_returns_401(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` is not one of
    the declared role names, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_x_user_role_returns_unauthenticated
    """
    res = api.get_member(
        "00000000-0000-0000-0000-000000000000",
        {"Content-Type": "application/json"},
    )
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_member_role_cannot_create_fiscal_year(api):
    """PRD §2.1: "Beyond authentication, each endpoint admits only the roles
    listed in §4. An authenticated caller whose role is not authorized for
    the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: POST /coop/fiscal_years is authorized for CoopAccountant only.

    Design: Corner/validations/wrong_role_for_endpoint_returns_forbidden
    """
    district = create_district(code="DIST-COR-12", name="Corner 12",
                               max_delegates=2)
    member = create_member(district["id"], patron_ref="P-COR-12",
                           legal_name="NoAuth Farm")
    res = api.create_fiscal_year(
        fiscal_year_payload(),
        make_member_headers(member["id"]),
    )
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_member_cannot_decide_redemption(api):
    """PRD §2.1: "Beyond authentication, each endpoint admits only the roles
    listed in §4. An authenticated caller whose role is not authorized for
    the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: POST /coop/redemption_requests/{req_id}/decide is authorized for
    BoardSecretary only.

    Design: Corner/rbac/member_cannot_decide_redemption
    """
    ctx = setup_year_with_deliveries(
        [{"member_key": "patron", "commodity": "CORN", "gross_bushels": 100}],
    )
    member = ctx["members"]["patron"]
    fy = ctx["fiscal_year"]
    close_year_provisional(fy["id"])
    finalize_year(fy["id"])
    certs = list_member_certificates(
        member["id"], headers=make_member_headers(member["id"]),
    )
    set_clock("2031-09-01T00:00:00Z")
    request = create_redemption_request(
        member["id"], "RETIREMENT", [certs[0]["id"]], 100,
        "2031-10-01T10:00:00Z",
    )
    submitted = submit_request(request["id"], member["id"])
    assert submitted["status"] == "UNDER_REVIEW"
    res = api.decide_redemption(
        submitted["id"],
        {"decision": "APPROVE", "resolution_id": "stub"},
        make_member_headers(member["id"]),
    )
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_elevator_operator_cannot_finalize_fiscal_year(api, operator_headers):
    """PRD §2.1: "Beyond authentication, each endpoint admits only the roles
    listed in §4. An authenticated caller whose role is not authorized for
    the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: POST /coop/fiscal_years/{fy_id}/finalize_close is authorized for
    CoopAccountant only.

    Design: Corner/rbac/elevator_operator_cannot_finalize_fiscal_year
    """
    ctx = setup_year_with_deliveries(
        [{"member_key": "patron", "commodity": "CORN", "gross_bushels": 10}],
    )
    fy = ctx["fiscal_year"]
    close_year_provisional(fy["id"])
    validate_success(api.begin_audit(fy["id"], TEST_USERS["auditor_headers"]))
    current = get_fiscal_year(fy["id"])
    res = api.finalize_close(
        fy["id"],
        {"expected_fiscal_year_version": current["version"]},
        operator_headers,
    )
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)
