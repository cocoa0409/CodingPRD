"""Role-based access control, segregation of duties, and the 404 catalogue."""

from test_helpers import (
    ALICE,
    CARLA,
    TEST_USERS,
    USER_IDS,
    ApiErrorId,
    make_counsel_headers,
    make_separating_employee_headers,
    read_plan,
    run_and_clear_analysis,
    setup_selected_scenario,
    submit_for_review,
    validate_error,
    validate_success,
)

LEAD = TEST_USERS["lead_headers"]
COUNSEL = TEST_USERS["counsel_headers"]
BENEFITS = TEST_USERS["benefits_headers"]
UNKNOWN_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def _plan_in_legal_review():
    scn = setup_selected_scenario(
        people=(ALICE, CARLA), select_indexes=(0,), propose_only_indexes=(1,)
    )
    run_and_clear_analysis(scn["plan"]["id"])
    submit_for_review(scn["plan"]["id"], USER_IDS["LEAD"])
    return scn


def test_the_benefits_administrator_may_not_render_the_legal_decision(api):
    """PRD 2.1: "The system recognises exactly five roles: `RestructuringLead`,
    `EmploymentCounsel`, `BenefitsAdministrator`, `SeparatingEmployee`, and
    `SystemAdmin`. A value of `X-User-Role` that is not one of those five, or
    that names a role the target operation does not admit, is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD 2.1: "`EmploymentCounsel` renders the legal decision, runs and clears
    adverse-impact analysis, generates OWBPA disclosures, determines and issues
    WARN notices, and waives rehire restrictions."

    Design: Corner/rbac/benefits_administrator_cannot_render_the_legal_decision
    """
    scn = _plan_in_legal_review()

    response = api.legal_decision(
        scn["plan"]["id"], {"decision": "APPROVE"}, BENEFITS
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)
    assert response.status_code == 403

    plan = read_plan(scn["plan"]["id"])
    assert plan["approval_status"] == "IN_LEGAL_REVIEW"
    assert plan["approved_by_user_id"] is None


def test_the_separating_employee_may_not_list_the_roster(api):
    """PRD 2.1: "A `SeparatingEmployee` is the individual receiving the release
    and may only sign or revoke it."
    PRD 2.1: "A value of `X-User-Role` that is not one of those five, or that
    names a role the target operation does not admit, is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/separating_employee_cannot_list_the_employee_roster
    """
    from test_helpers import create_site, hire

    site = create_site(name="Austin Campus", state_code="TX")
    alice = hire(site["id"], ALICE)

    response = api.list_employees(
        make_separating_employee_headers(alice["id"]),
        params={"site_id": site["id"]},
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)
    assert response.status_code == 403


def test_missing_headers_are_rejected_before_any_lookup(api):
    """PRD 2.1: "Every request to the API must carry two headers: `X-User-ID`,
    identifying the acting principal, and `X-User-Role`, declaring the capacity
    in which that principal is acting. A request that omits either header, or
    supplies either as an empty string, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401) before any other processing occurs."
    PRD 2.6: "When a request violates more than one rule, exactly one error is
    returned, and it is always the violation with the lowest priority number in
    the ladder below."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated_before_any_lookup
    """
    response = api.raw_get(
        f"/reduction-plans/{UNKNOWN_ID}", headers={"Content-Type": "application/json"}
    )
    error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert response.status_code == 401
    assert error["error_id"] != ApiErrorId.ERR_PLAN_NOT_FOUND.value


def test_the_submitting_principal_may_not_render_the_decision(api):
    """PRD 2.1: "Rendering a legal decision from an `X-User-ID` equal to the
    plan's recorded `submitted_by_user_id` is refused with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD 2.1: "The person who hands a plan to counsel and the person who renders
    the legal decision on it must be different principals, even when the same
    human being holds both roles."

    Design: Corner/rbac/the_submitting_user_cannot_render_the_legal_decision
    """
    scn = _plan_in_legal_review()

    conflicted = api.legal_decision(
        scn["plan"]["id"],
        {"decision": "APPROVE"},
        make_counsel_headers(USER_IDS["LEAD"]),
    )
    validate_error(conflicted, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert conflicted.status_code == 403

    approved = validate_success(
        api.legal_decision(
            scn["plan"]["id"],
            {"decision": "APPROVE"},
            make_counsel_headers(USER_IDS["COUNSEL"]),
        )
    )
    assert approved["approval_status"] == "APPROVED"
    assert approved["approved_by_user_id"] == USER_IDS["COUNSEL"]
    assert approved["submitted_by_user_id"] == USER_IDS["LEAD"]


def test_each_collection_answers_its_own_domain_specific_404(api):
    """PRD 2.6: "Path resource existence — identifiers in the URL are resolved
    left to right and each must exist, yielding whichever of
    `ERR_PLAN_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`,
    `ERR_SELECTION_NOT_FOUND`, `ERR_ANALYSIS_NOT_FOUND`,
    `ERR_DISCLOSURE_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`,
    `ERR_RESTRICTION_NOT_FOUND` or `ERR_WARN_RULE_NOT_FOUND` matches the missing
    segment (404). Applies to every path-parameterised endpoint."

    Design: Corner/errors/error_not_found_for_every_remaining_resource_collection
    """
    checks = [
        (api.get_site(UNKNOWN_ID, LEAD), ApiErrorId.ERR_SITE_NOT_FOUND.value),
        (
            api.get_severance_offer(UNKNOWN_ID, BENEFITS),
            ApiErrorId.ERR_OFFER_NOT_FOUND.value,
        ),
        (
            api.get_analysis(UNKNOWN_ID, COUNSEL),
            ApiErrorId.ERR_ANALYSIS_NOT_FOUND.value,
        ),
        (
            api.get_disclosure(UNKNOWN_ID, COUNSEL),
            ApiErrorId.ERR_DISCLOSURE_NOT_FOUND.value,
        ),
        (
            api.get_warn_notice(UNKNOWN_ID, COUNSEL),
            ApiErrorId.ERR_NOTICE_NOT_FOUND.value,
        ),
        (
            api.get_position_restriction(UNKNOWN_ID, COUNSEL),
            ApiErrorId.ERR_RESTRICTION_NOT_FOUND.value,
        ),
    ]
    for response, expected in checks:
        validate_error(response, expected)
        assert response.status_code == 404, f"{expected} must answer HTTP 404"
        assert response.json()["response_type"] == "error"
