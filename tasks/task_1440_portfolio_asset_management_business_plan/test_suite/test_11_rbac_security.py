"""Authentication/authorization surface: missing user context, role-exclusive
denials, property-manager ownership, and user-level segregation of duties."""
import pytest

from test_helpers import (
    ApiErrorId,
    actuals_line_entry,
    approve_project,
    create_actuals_report_payload,
    create_business_plan_payload,
    create_disposition_decision_payload,
    create_funding_draw_payload,
    create_portfolio_payload,
    create_project,
    find_line,
    get_success_data,
    lines_plan10,
    lines_rent_m1_m2,
    make_committee_headers,
    make_property_manager_headers,
    setup_base_asset,
    setup_plan_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director"]
AM = TEST_USERS["asset_manager"]
IC = TEST_USERS["committee"]
LENDER = TEST_USERS["lender"]
ANALYST = TEST_USERS["analyst"]


def test_missing_auth_header_returns_400(api):
    """PRD §2.1: "A request missing either header, carrying a malformed value,
    or naming an undeclared role is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_header_returns_400
    """
    portfolio = get_success_data(api.create_portfolio(
        create_portfolio_payload(), DIRECTOR))
    res = api.get_portfolio(portfolio["id"], headers={})
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_plan_approve_forbidden_for_property_manager_role(api):
    """PRD §4: `POST /api/business-plans/{id}/approve` authorizes
    PortfolioDirector only.
    PRD §2.1: "A request whose role is not on the endpoint's authorized list
    is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

    Design: Corner/validations/plan_approve_forbidden_for_property_manager_role
    """
    ctx = setup_plan_scenario(fiscal_year=2027, lines=lines_plan10(),
                              approve=False)
    pm_headers = make_property_manager_headers(ctx["manager"]["id"])
    res = api.approve_business_plan(ctx["plan"]["id"], pm_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
    plan = get_success_data(api.get_business_plan(ctx["plan"]["id"], ANALYST))
    assert plan["status"] == "SUBMITTED"


def test_lender_cannot_create_plan(api):
    """PRD §4: `POST /api/business-plans` authorizes AssetManager only.
    PRD §2.1: "A request whose role is not on the endpoint's authorized list
    is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

    Design: Corner/rbac/lender_cannot_create_plan
    """
    ctx = setup_base_asset()
    res = api.create_business_plan(
        create_business_plan_payload(ctx["asset"]["id"], 2027,
                                     ctx["asset"]["version"]), LENDER)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


def test_ic_cannot_release_draw(api):
    """PRD §4: `POST /api/funding-draws/{id}/release` authorizes
    PortfolioDirector only.
    PRD §1 (Introduction): "the committee that approves a funding draw never
    releases the cash."

    Design: Corner/rbac/ic_cannot_release_draw
    """
    ctx = setup_plan_scenario(fiscal_year=2027, lines=lines_plan10())
    project = create_project(ctx["asset"]["id"], ctx["plan"]["id"],
                             1000000, 3, 4, name="X")
    approve_project(project["id"], ctx["plan"]["id"], IC)
    draw = get_success_data(api.create_funding_draw(
        create_funding_draw_payload(project["id"], 400000), AM))
    get_success_data(api.approve_funding_draw(draw["id"], IC))

    res = api.release_funding_draw(draw["id"], IC)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
    draws, _ = validate_paginated(
        api.list_capital_project_funding_draws(project["id"], ANALYST))
    assert draws[0]["status"] == "APPROVED", \
        "the committee-approved draw is never released by the committee"


def test_pm_cannot_accept_actuals(api):
    """PRD §4: `POST /api/actuals-reports/{id}/accept` authorizes AssetManager
    only.
    PRD §3.3: "Acceptance by an `AssetManager` moves the report from
    `SUBMITTED` to `ACCEPTED`".

    Design: Corner/rbac/pm_cannot_accept_actuals
    """
    ctx = setup_plan_scenario(fiscal_year=2026, lines=lines_rent_m1_m2())
    pm_headers = make_property_manager_headers(ctx["manager"]["id"])
    rent_m1 = find_line(ctx["lines"], "RENT_REVENUE", 1)
    report = get_success_data(api.create_actuals_report(
        create_actuals_report_payload(
            ctx["plan"]["id"], 1, [actuals_line_entry(rent_m1["id"], 11000000)]),
        pm_headers))
    res = api.accept_actuals_report(report["id"], pm_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


def test_disposition_ratify_self_rejected(api):
    """PRD §3.8: "The `InvestmentCommittee` then ratifies it — with
    segregation of duties enforced: the ratifier's `X-User-ID` must differ
    from `created_by_user_id` (`ERR_SELF_APPROVAL_FORBIDDEN`)".

    Design: Corner/rbac/disposition_ratify_self_rejected
    """
    ctx = setup_base_asset()
    decision = get_success_data(api.create_disposition_decision(
        create_disposition_decision_payload(ctx["asset"]["id"], "HOLD"), AM))
    get_success_data(api.submit_disposition_review(decision["id"], AM))
    # Ratifier carries the correct role but the creator's user id ("am-1").
    res = api.ratify_disposition_decision(decision["id"],
                                          make_committee_headers("am-1"))
    validate_error(res, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN)
    decisions, _ = validate_paginated(
        api.list_asset_disposition_decisions(ctx["asset"]["id"], ANALYST))
    assert decisions[0]["status"] == "COMMITTEE_REVIEW"
