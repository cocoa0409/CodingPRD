"""Role-based access control and validation ordering: forbidden-role rejections,
the shared-read allowance, the auth gate, and existence-before-state precedence.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    create_curtailment_payload, TEST_USERS, build_user_headers,
    create_unit, create_floored_loan, setup_finance_submitted_deal,
)

SM = TEST_USERS["sales_manager_headers"]
SA = TEST_USERS["service_advisor_headers"]
FM = TEST_USERS["finance_manager_headers"]
DP = TEST_USERS["dealer_principal_headers"]


def test_service_advisor_cannot_create_unit(api):
    """PRD 2.1: "When the headers are well formed but the named role is not
    permitted to perform the requested operation under the access matrix in Section
    4, the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

    Design: Corner/rbac/service_advisor_cannot_create_unit
    """
    res = api.create_unit(
        {"vin": "1HD1KB4197YT00250", "category": "ATV", "model_year": 2024,
         "msrp_cents": 900_000, "dealer_cost_cents": 700_000}, SA)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_sales_manager_cannot_approve_finance(api):
    """PRD 2.1: "A FinanceManager owns the finance submission, approval, and decline
    steps of a deal."
    PRD 2.1: "When the headers are well formed but the named role is not permitted
    to perform the requested operation under the access matrix in Section 4, the
    request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

    Design: Corner/rbac/sales_manager_cannot_approve_finance
    """
    cust, unit, deal = setup_finance_submitted_deal(
        unit_overrides={"category": "MOTORCYCLE"})
    res = api.approve_deal(deal["id"], SM)
    validate_error(res, "ERR_FORBIDDEN_ROLE")
    deal_after = validate_success(api.get_deal(deal["id"], FM), 200)
    assert deal_after["status"] == "FINANCE_SUBMITTED"


def test_service_advisor_cannot_post_curtailment(api):
    """PRD 2.1: "A DealerPrincipal owns floor-plan financing and warranty
    adjudication."
    PRD 2.1: "When the headers are well formed but the named role is not permitted
    to perform the requested operation under the access matrix in Section 4, the
    request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

    Design: Corner/rbac/service_advisor_cannot_post_curtailment
    """
    unit, loan = create_floored_loan(dealer_cost_cents=1_000_000,
                                     clock="2026-01-01T00:00:00.000Z")
    res = api.create_curtailment(
        create_curtailment_payload(loan["id"], 100_000, loan["version"],
                                   reason="VOLUNTARY"), SA)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_shared_read_allowed_for_finance_manager(api):
    """PRD 2.1: "Authorization is decided solely by whether X-User-Role is permitted
    for the requested operation."
    PRD 4: "GET /units | List units (filter by status, vin, floor_plan_loan_id,
    held_by_deal_id) | SalesManager, ServiceAdvisor, FinanceManager, PartsClerk,
    DealerPrincipal."

    Design: Corner/rbac/shared_read_allowed_for_finance_manager
    """
    create_unit(category="ATV")
    data, meta = validate_paginated(api.list_units(FM))
    assert isinstance(data, list)


def test_missing_user_context_returns_401(api):
    """PRD 2.1: "If either header is missing, or if X-User-Role is not one of the
    recognized roles, the request is rejected with ERR_MISSING_OR_INVALID_USER_CONTEXT
    (HTTP 401)."

    Design: Corner/validations/missing_user_context_returns_401
    """
    bad_headers = build_user_headers("someone", "NoSuchRole")
    res = api.create_unit(
        {"vin": "1HD1KB4197YT00240", "category": "ATV", "model_year": 2024,
         "msrp_cents": 900_000, "dealer_cost_cents": 700_000}, bad_headers)
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT")


def test_existence_checked_before_state_on_quote(api):
    """PRD 2.8: "then existence of every referenced resource as described in Section
    2.7. Only after those pass does the platform check that the request body is well
    formed."
    PRD 2.7: "The first identifier that does not resolve to an existing resource
    produces that resource's specific not-found error — ... ERR_DEAL_NOT_FOUND ... —
    each at HTTP 404, and no further validation runs."

    Design: Corner/validations/existence_checked_before_state_on_quote
    """
    res = api.quote_deal("00000000-0000-4000-8000-000000000999", SM)
    validate_error(res, "ERR_DEAL_NOT_FOUND")
