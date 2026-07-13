"""Role-based access control, ownership, segregation of duties, and list endpoints.

Translates the queue-B rbac and endpoints corner instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
    make_tenant_headers, make_landlord_headers, make_caseworker_headers,
    create_program_payload, create_tenant_payload, create_landlord_payload,
    create_unit_payload, create_application_payload, disbursement_payload,
    build_application, build_approved_application,
)

ADMIN = TEST_USERS["program_admin_headers"]
CW = TEST_USERS["caseworker_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_tenant_cannot_approve_application(api):
    """PRD §2.1: "When a well-authenticated principal invokes an operation their role is
    not permitted to perform, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/tenant_cannot_approve_application_returns_unauthorized
    """
    ctx = build_application(
        api, income_limits={"2": 566667}, income_sources=(),
        do_tenant_section=False, add_ledger=False, do_landlord_section=False,
        submit=False, review=False,
        arrears_start_month=None, arrears_end_month=None,
        prospective_start_date="2026-03-01", prospective_end_date="2026-03-31",
        requested_prospective_months=1,
    )
    resp = api.approve_application(ctx["aid"], {"decision_reason": "x"}, make_tenant_headers(ctx["tid"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)


def test_non_owner_tenant_cannot_submit(api):
    """PRD §2.1: "When an `entity_backed` actor (a `Tenant` or `Landlord`) is
    authenticated and authorized for the endpoint but is not the owner of the target
    resource, the request is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

    Design: Corner/rbac/non_owner_tenant_cannot_submit_returns_forbidden_ownership
    """
    pid = get_success_data(api.create_program(create_program_payload(
        monthly_income_limit_by_size={"2": 566667}), ADMIN))["id"]
    tid1 = get_success_data(api.create_tenant(create_tenant_payload(email="t1@x.com")))["id"]
    tid2 = get_success_data(api.create_tenant(create_tenant_payload(email="t2@x.com")))["id"]
    lid = get_success_data(api.create_landlord(create_landlord_payload()))["id"]
    lh = make_landlord_headers(lid)
    uid = get_success_data(api.create_unit(create_unit_payload(lid), lh))["id"]
    th1 = make_tenant_headers(tid1)
    aid = get_success_data(api.create_application(create_application_payload(
        pid, tid1, lid, uid, requested_prospective_months=1,
        arrears_start_month=None, arrears_end_month=None,
        prospective_start_date="2026-03-01", prospective_end_date="2026-03-31"), th1))["id"]
    get_success_data(api.add_income_source(aid, {"source_type": "WAGES", "monthly_amount_cents": 400000}, th1))
    get_success_data(api.complete_tenant_section(aid, {"hardship_type": "JOB_LOSS", "hardship_attested": True}, th1))
    get_success_data(api.create_ledger(aid, {"lines": []}, lh))
    get_success_data(api.complete_landlord_section(aid, {"ledger_confirmed": True}, lh))

    # A different tenant (T2) attempts to submit T1's application.
    resp = api.submit_application(aid, make_tenant_headers(tid2))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP.value, expected_status=403)


def test_same_caseworker_cannot_approve_and_disburse(api):
    """PRD §3.7: "Creation is fenced by a strict separation of duties: the creating
    principal's `X-User-ID` must differ from the application's `approved_by_cw_id`, so
    the caseworker who approved an award may never issue its payment; a violation is
    rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/same_caseworker_approve_and_disburse_returns_segregation_of_duties
    """
    ctx = build_approved_application(api, approver_id="cw-same")
    resp = api.create_disbursement(
        ctx["aid"], disbursement_payload(1000000, 5, "COMBINED", ctx["version"]),
        make_caseworker_headers("cw-same"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=403)


def test_missing_auth_headers_rejected_as_unauthenticated(api):
    """PRD §2.1: "When either header is missing, or `X-User-Role` is not one of the roles
    below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    pid = get_success_data(api.create_program(create_program_payload(
        monthly_income_limit_by_size={"2": 566667}), ADMIN))["id"]
    tid = get_success_data(api.create_tenant(create_tenant_payload(household_size=2)))["id"]
    lid = get_success_data(api.create_landlord(create_landlord_payload()))["id"]
    uid = get_success_data(api.create_unit(create_unit_payload(lid), make_landlord_headers(lid)))["id"]
    aid = get_success_data(api.create_application(create_application_payload(
        pid, tid, lid, uid, requested_prospective_months=1,
        arrears_start_month=None, arrears_end_month=None,
        prospective_start_date="2026-03-01", prospective_end_date="2026-03-31"),
        make_tenant_headers(tid)))["id"]

    resp = api.review_application(aid, ANON)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


def test_units_filtered_by_landlord_returns_the_unit(api):
    """PRD §3.3: "Units may be listed, optionally filtered by `landlord_id`, as the
    reverse lookup from landlord to units."

    Design: Corner/endpoints/units_filtered_by_landlord_returns_child_list
    """
    lid = get_success_data(api.create_landlord(create_landlord_payload()))["id"]
    lh = make_landlord_headers(lid)
    uid = get_success_data(api.create_unit(create_unit_payload(lid, address="37 I2 St"), lh))["id"]

    resp = api.list_units(ADMIN, params={"landlord_id": lid})
    data, meta = validate_paginated(resp)
    assert any(u["id"] == uid for u in data), "created unit must appear in the filtered list"


def test_applications_list_returns_pagination_envelope(api):
    """PRD §2.3: "Paginated list responses include the following fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/applications_list_pagination_envelope
    """
    pid = get_success_data(api.create_program(create_program_payload(
        monthly_income_limit_by_size={"2": 566667}), ADMIN))["id"]
    tid = get_success_data(api.create_tenant(create_tenant_payload(household_size=2)))["id"]
    lid = get_success_data(api.create_landlord(create_landlord_payload()))["id"]
    lh = make_landlord_headers(lid)
    uid = get_success_data(api.create_unit(create_unit_payload(lid), lh))["id"]
    th = make_tenant_headers(tid)
    for start, end in (("2026-03-01", "2026-03-31"), ("2026-04-01", "2026-04-30")):
        get_success_data(api.create_application(create_application_payload(
            pid, tid, lid, uid, requested_prospective_months=1,
            arrears_start_month=None, arrears_end_month=None,
            prospective_start_date=start, prospective_end_date=end), th))

    resp = api.list_applications(CW, params={"tenant_id": tid, "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
