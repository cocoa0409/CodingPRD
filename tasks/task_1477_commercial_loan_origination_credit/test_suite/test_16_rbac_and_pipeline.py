"""Authentication, role gating, validation-pipeline ordering, and segregation of
duties (PRD sections 2.1, 2.8, 2.9, 4).
"""
from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS, api_client, borrower_payload,
    build_user_headers, create_borrower, deal_spreading, finalize_statement,
    get_application, loan_application_payload, make_credit_analyst_headers,
    setup_officers, spread_statement, statement_payload, validate_error,
    validate_paginated, validate_success,
)


def test_missing_auth_headers_returns_400():
    """PRD section 2.1: "A request missing either header, or carrying a role value
    outside this set, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/validations/missing_auth_headers_returns_400
    """
    o = setup_officers(["rm"])

    no_headers = api_client.create_borrower(
        borrower_payload(legal_name="No Headers LLC"), headers={})
    validate_error(no_headers, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    bad_role = api_client.create_borrower(
        borrower_payload(legal_name="Bad Role LLC"),
        headers=build_user_headers("x", "SuperUser"))
    validate_error(bad_role, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    rows, meta = validate_paginated(api_client.list_borrowers(o["rm"]["headers"]))
    assert rows == [], "neither rejected request persisted a borrower"


def test_role_check_precedes_body_validation():
    """PRD section 2.8: "Every request is evaluated against a fixed pipeline of
    checks in strict priority order; the first failing check determines the error
    response" — role permission (stage 2) precedes body schema (stage 4).

    Design: Corner/validations/role_check_precedes_body_validation
    """
    o = setup_officers(["an"])
    # CreditAnalyst creating a borrower AND a body missing legal_name.
    resp = api_client.create_borrower(
        {"naics_code": "332710", "relationship_since": "2018-01-01"}, o["an"]["headers"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)
    assert resp.json()["data"]["error_id"] != "ERR_VALIDATION"


def test_existence_check_precedes_state_check():
    """PRD section 2.8: path existence (stage 3) precedes transition legality
    (stage 6); PRD section 2.10: "the request is rejected with `ERR_NOT_FOUND`
    (HTTP 404) at the first identifier that does not correspond to an existing
    resource."

    Design: Corner/validations/existence_check_precedes_state_check
    """
    o = setup_officers(["rm"])
    resp = api_client.submit_application(NON_EXISTENT_UUID, o["rm"]["headers"])
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)
    assert resp.json()["data"]["error_id"] != "ERR_INVALID_STATE"


def test_officer_registry_denied_for_relationship_manager():
    """PRD section 4: registering a bank officer is restricted to `BankAdmin`.
    PRD section 2.1: "An authenticated caller who attempts an operation their role
    is not permitted to perform is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/officer_registry_denied_for_relationship_manager
    """
    o = setup_officers(["rm"])
    resp = api_client.create_bank_officer({"full_name": "Mallory RM"}, o["rm"]["headers"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_borrower_create_denied_for_credit_analyst():
    """PRD section 4: creating a borrower is restricted to `RelationshipManager`.
    PRD section 2.1: "An authenticated caller who attempts an operation their role
    is not permitted to perform is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/borrower_create_denied_for_credit_analyst
    """
    o = setup_officers(["an"])
    resp = api_client.create_borrower(
        borrower_payload(legal_name="Analyst Owned LLC"), o["an"]["headers"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    rows, meta = validate_paginated(api_client.list_borrowers(o["an"]["headers"]))
    assert rows == []


def test_statement_create_denied_for_relationship_manager():
    """PRD section 4: attaching a financial statement is restricted to
    `CreditAnalyst`. PRD section 2.1: "An authenticated caller who attempts an
    operation their role is not permitted to perform is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/statement_create_denied_for_relationship_manager
    """
    o = setup_officers(["rm", "an"])
    bor = create_borrower(o)
    app = validate_success(api_client.create_loan_application(
        loan_application_payload(bor["id"]), o["rm"]["headers"]), 201)

    resp = api_client.create_financial_statement(
        statement_payload(app["id"]), o["rm"]["headers"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    rows, meta = validate_paginated(api_client.list_financial_statements(
        o["an"]["headers"], params={"loan_application_id": app["id"]}))
    assert rows == [], "the application still has zero statements"


def test_appraiser_registry_denied_for_credit_analyst():
    """PRD section 4: registering an appraiser is restricted to `AppraisalManager`.
    PRD section 2.1: "An authenticated caller who attempts an operation their role
    is not permitted to perform is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/appraiser_registry_denied_for_credit_analyst
    """
    o = setup_officers(["an"])
    resp = api_client.create_appraiser(
        {"name": "Analyst Appraisals", "license_number": "LIC-X"}, o["an"]["headers"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_clock_set_denied_for_relationship_manager():
    """PRD section 4: advancing the logical clock is restricted to `BankAdmin`.
    PRD section 2.6: "A `BankAdmin` may advance the logical clock to a supplied
    instant `to_iso8601`; this is an admin-only test-driving capability".

    Design: Corner/rbac/clock_set_denied_for_relationship_manager
    """
    o = setup_officers(["rm"])
    resp = api_client.set_clock({"to_iso8601": "2026-08-10T14:30:00Z"}, o["rm"]["headers"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_shared_get_endpoints_allowed_for_all_roles():
    """PRD section 4: "Every `GET` endpoint is open to any authenticated role".
    PRD section 2.1: "When `X-User-Role` is `BankAdmin`, `X-User-ID` is an opaque
    operator identifier not tied to any persisted entity".

    Design: Corner/rbac/shared_get_endpoints_allowed_for_all_roles
    """
    o = setup_officers(["rm", "m1", "apm"])
    bor = create_borrower(o)
    app = validate_success(api_client.create_loan_application(
        loan_application_payload(bor["id"]), o["rm"]["headers"]), 201)

    r1 = api_client.get_borrower(bor["id"], o["m1"]["headers"])
    assert validate_success(r1, 200)["id"] == bor["id"]

    r2 = api_client.get_loan_application(app["id"], TEST_USERS["bank_admin_headers"])
    assert validate_success(r2, 200)["id"] == app["id"]

    r3 = api_client.list_borrower_applications(bor["id"], o["apm"]["headers"])
    rows, meta = validate_paginated(r3)
    assert meta["total_count"] == 1


def test_sod_finalize_spreads_by_originator_rejected():
    """PRD section 2.9: "The officer who finalizes an application's spreads must not
    be the application's `originating_officer_id`; a violation is rejected with
    `ERR_SOD_SPREAD_FINALIZE_BY_ORIGINATOR`."

    Design: Corner/rbac/sod_finalize_spreads_by_originator_rejected
    """
    ctx = deal_spreading()
    o = ctx["o"]
    spread_statement(o, ctx["statement"]["id"])
    finalize_statement(o, ctx["statement"]["id"])

    # The originator (rm) calls finalize-spreads wearing a CreditAnalyst hat.
    resp = api_client.finalize_spreads(
        ctx["application"]["id"], make_credit_analyst_headers(o["rm"]["id"]))
    validate_error(resp, ApiErrorId.ERR_SOD_SPREAD_FINALIZE_BY_ORIGINATOR, 403)

    app = get_application(o, ctx["application"]["id"])
    assert app["status"] == "SPREADING"
    assert app["dscr_standard"] is None, "no computation ran"
