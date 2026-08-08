"""Contractor certification cycle, case close gate, auth/RBAC, pagination, surveillance report.

Queue B: state_machines, validations, rbac, endpoints.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    build_remediation_scenario, setup_case,
    create_child_payload, create_grant_fund_payload, create_investigation_payload,
    create_contractor_payload, TEST_USERS,
)

IC = TEST_USERS["intake_headers"]
CM = TEST_USERS["case_manager_headers"]
PA = TEST_USERS["program_admin_headers"]


# ─── Corner: state_machines / contractor_cycle_suspend_then_reinstate ──
def test_contractor_certification_cycles_suspend_reinstate(api):
    """PRD §3.7: "From `ACTIVE`, the `SUSPEND` action moves it to `SUSPENDED`, and from
    `SUSPENDED` the `REINSTATE` action moves it back to `ACTIVE` — the cyclic edge that
    lets certification be paused and resumed."

    Design: Corner/state_machines/contractor_cycle_suspend_then_reinstate
    """
    con = validate_success(api_client.create_contractor(create_contractor_payload(), PA), 201)
    validate_success(api_client.contractor_certification(
        con["id"], {"action": "ACTIVATE", "expires_at": "2027-01-01T00:00:00Z"}, PA), 200)
    suspended = validate_success(api_client.contractor_certification(
        con["id"], {"action": "SUSPEND"}, PA), 200)
    assert suspended["certification_status"] == "SUSPENDED"
    reinstated = validate_success(api_client.contractor_certification(
        con["id"], {"action": "REINSTATE"}, PA), 200)
    assert reinstated["certification_status"] == "ACTIVE"


# ─── Corner: validations / close_case_while_unresolved_returns_case_not_resolvable ─
def test_close_unresolved_case_returns_case_not_resolvable(api):
    """PRD §3.9: "Closure is allowed only from `case_status` `ENFORCEMENT`, and only
    when three conditions all hold: `medical_status` is `RESOLVED`, `open_hazard_count`
    is 0, and at least one of the case's hazard-control orders is `CLEARED` (with every
    order of the case being either `CLEARED` or `VOID`). If any of these fails, closure
    is rejected with `ERR_CASE_NOT_RESOLVABLE` (HTTP 409)."

    Design: Corner/validations/close_case_while_unresolved_returns_case_not_resolvable
    """
    ctx = build_remediation_scenario(stage="order", income_tier="LOW", num_hazards=1)
    res = api_client.close_case(ctx["case_id"], CM)
    validate_error(res, "ERR_CASE_NOT_RESOLVABLE")


# ─── Corner: validations / missing_auth_headers_returns_unauthenticated ─
def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the
    roles defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    payload = create_child_payload("00000000-0000-4000-8000-000000000000", income_tier="LOW")
    res = api_client.create_child(payload, {})
    validate_error(res, "ERR_UNAUTHENTICATED")


# ─── Corner: validations / wrong_role_on_grant_create_returns_unauthorized ─
def test_wrong_role_on_grant_create_returns_unauthorized(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted
    to invoke the requested endpoint, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/validations/wrong_role_on_grant_create_returns_unauthorized
    """
    res = api_client.create_grant_fund(create_grant_fund_payload(total_budget_cents=100000), IC)
    validate_error(res, "ERR_UNAUTHORIZED")


# ─── Corner: rbac / intake_cannot_schedule_investigation ───────────────
def test_intake_cannot_schedule_investigation(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted
    to invoke the requested endpoint, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/intake_cannot_schedule_investigation
    """
    res = api_client.create_investigation(
        create_investigation_payload("00000000-0000-4000-8000-00000000000a",
                                     "00000000-0000-4000-8000-00000000000b",
                                     "00000000-0000-4000-8000-00000000000c"), IC)
    validate_error(res, "ERR_UNAUTHORIZED")


# ─── Corner: endpoints / cases_list_pagination_total_and_has_more ──────
def test_cases_list_pagination_total_and_has_more(api):
    """PRD §2.3: "`total_count` is the number of records matching the query before
    pagination is applied, and `has_more` is true exactly when records remain beyond the
    current page."

    Design: Corner/endpoints/cases_list_pagination_total_and_has_more
    """
    setup_case(income_tier="LOW", bll=22.0)
    setup_case(income_tier="LOW", bll=25.0)
    data, meta = validate_paginated(api_client.list_cases(CM, params={"limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


# ─── Corner: endpoints / surveillance_report_returns_aggregate_shape ───
def test_surveillance_report_returns_aggregate_shape(api):
    """PRD §3.9: "It aggregates over cases and the grant ledger and returns eight counts
    and totals: `total_cases`, `open_cases`, `class_i_count`, `class_ii_count`,
    `class_iii_count` (case counts by `priority_class`), `resolved_count` (cases whose
    `medical_status` is `RESOLVED`), and `total_reserved_cents` and `total_spent_cents`
    aggregated across grant funds."

    Design: Corner/endpoints/surveillance_report_returns_aggregate_shape
    """
    setup_case(income_tier="LOW", bll=22.0)  # priority_class CLASS_II
    report = validate_success(api_client.surveillance_report(PA), 200)
    assert report["total_cases"] == 1
    assert report["class_ii_count"] == 1
    assert report["total_reserved_cents"] == 0
    assert report["total_spent_cents"] == 0
