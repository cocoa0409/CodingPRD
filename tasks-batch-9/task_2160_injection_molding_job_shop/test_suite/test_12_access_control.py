"""Authentication, role authorization and the customer-scope boundary."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_quote,
    create_customer,
    create_mold,
    create_press,
    create_priced_submitted_quote,
    create_production_report_payload,
    create_resin_lot,
    job_version,
    make_customer_rep_headers,
    make_headers_without_role,
    mold_version,
    read_job,
    read_lot,
    read_mold,
    read_quote,
    set_clock,
    setup_running_job,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["plant_admin_headers"]
SE = TEST_USERS["sales_engineer_headers"]
PE = TEST_USERS["process_engineer_headers"]
QE = TEST_USERS["quality_engineer_headers"]
TT = TEST_USERS["toolroom_tech_headers"]


def test_a_sales_engineer_may_not_post_a_shift_report(api):
    """PRD §2.1: "Once the headers are accepted, the acting role must appear in the
    authorized-role list for the endpoint being called; if it does not, the request
    is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.1: "**`ProcessEngineer`** — owns the manufacturing surface. Opens
    qualification rows and books run-at-rate trials, opens and schedules jobs,
    stages material, starts and completes jobs, unblocks them, and posts shift
    reports. A `ProcessEngineer` may never render a quality verdict."
    PRD §4: "| POST | `/production-reports` | Post a shift report against a RUNNING
    job | `ProcessEngineer` |"

    Design: Corner/rbac/sales_engineer_cannot_post_production_reports
    """
    shop = setup_running_job()
    version_before = job_version(shop["job"]["id"])

    response = api.create_production_report(
        create_production_report_payload(
            shop["job"]["id"],
            version_before,
            shots=100,
            short_shot_shots=0,
            good_parts=390,
            scrap_parts=10,
            virgin_grams=3600,
            regrind_grams=400,
            run_minutes=60,
        ),
        SE,
    )

    assert response.status_code == 403, f"Expected 403, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    _, meta = validate_paginated(
        api.list_production_reports(QE, params={"job_id": shop["job"]["id"]})
    )
    assert meta["total_count"] == 0
    assert read_job(shop["job"]["id"])["version"] == version_before


def test_a_process_engineer_may_receive_resin_but_never_disposition_it(api):
    """PRD §2.1: "Once the headers are accepted, the acting role must appear in the
    authorized-role list for the endpoint being called; if it does not, the request
    is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.1: "**`QualityEngineer`** — owns every quality verdict. Resin lot
    disposition, mold quarantine and release, PPAP filing, internal endorsement,
    run-at-rate verdicts and shift-report reversal all belong to this role."
    PRD §4: "| POST | `/resin-lots/{id}/disposition` | Release, hold or reject a
    resin lot | `QualityEngineer` |"

    Design: Corner/rbac/process_engineer_cannot_disposition_a_resin_lot
    """
    set_clock()
    lot = create_resin_lot()
    assert lot["status"] == "QUARANTINE"

    response = api.resin_lot_disposition(lot["id"], {"decision": "RELEASE"}, PE)

    assert response.status_code == 403, f"Expected 403, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    assert read_lot(lot["id"])["status"] == "QUARANTINE"


def test_a_customer_rep_may_not_decide_another_customers_quote(api):
    """PRD §2.1: "Concretely, a `CustomerRep` deciding a quote must match the
    quote's `customer_id`, a `CustomerRep` rendering a PPAP customer decision must
    match the `customer_id` of the mold the package qualifies, a `CustomerRep`
    requesting a tool transfer must match the `to_customer_id` named in the request,
    and a `CustomerRep` reading a customer record must match that record's `id`. Any
    mismatch is rejected with `ERR_CUSTOMER_SCOPE_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/customer_rep_cannot_decide_another_customers_quote
    """
    set_clock()
    acme = create_customer()
    beta = create_customer(name="Beta Devices", code="BETA")
    press = create_press()
    mold = create_mold(acme["id"])
    quote = create_priced_submitted_quote(acme["id"], mold["id"], press["id"])
    version_before = mold_version(mold["id"])

    intruder = api.quote_customer_decision(
        quote["id"],
        {"decision": "ACCEPT", "expected_mold_version": version_before},
        make_customer_rep_headers(beta["id"]),
    )
    assert intruder.status_code == 403, f"Expected 403, got {intruder.status_code}"
    validate_error(intruder, ApiErrorId.ERR_CUSTOMER_SCOPE_VIOLATION.value)
    assert read_quote(quote["id"])["status"] == "SUBMITTED"
    assert read_mold(mold["id"])["version"] == version_before

    owner = validate_success(
        api.quote_customer_decision(
            quote["id"],
            {"decision": "ACCEPT", "expected_mold_version": version_before},
            make_customer_rep_headers(acme["id"]),
        )
    )
    assert owner["status"] == "ACCEPTED"


def test_a_request_without_a_role_header_is_rejected_before_any_other_rule(api):
    """PRD §2.1: "Every request to the API must carry two headers: `X-User-ID`,
    identifying the acting principal, and `X-User-Role`, naming the role that
    principal is acting in. If either header is absent, or if `X-User-Role` does not
    name one of the six roles defined below, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401) before any other rule in the system is
    consulted."

    Design: Corner/rbac/request_missing_x_user_role_header_returns_unauthenticated
    """
    set_clock()

    response = api.create_customer(
        {"name": "Acme Controls", "code": "ACME"}, make_headers_without_role()
    )

    assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_every_resource_family_answers_with_its_own_not_found_code(api):
    """PRD §2.4: "Where an endpoint does carry path parameters, they are resolved
    strictly left to right, and the first segment that names a resource which does
    not exist determines the error: `ERR_CUSTOMER_NOT_FOUND`, `ERR_PRESS_NOT_FOUND`,
    `ERR_MOLD_NOT_FOUND`, `ERR_QUALIFICATION_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`,
    `ERR_PPAP_SUBMISSION_NOT_FOUND`, `ERR_RESIN_LOT_NOT_FOUND`, `ERR_JOB_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND`, `ERR_MAINTENANCE_ORDER_NOT_FOUND`,
    `ERR_TOOL_TRANSFER_NOT_FOUND` or `ERR_CAPACITY_COMMIT_NOT_FOUND`, each with
    HTTP 404."

    Design: Corner/errors/unknown_ids_return_resource_specific_not_found_codes
    """
    set_clock()
    cases = [
        (api.get_press("00000000-0000-4000-8000-00000000000a", PA), ApiErrorId.ERR_PRESS_NOT_FOUND),
        (api.get_quote("00000000-0000-4000-8000-00000000000b", SE), ApiErrorId.ERR_QUOTE_NOT_FOUND),
        (
            api.get_ppap_submission("00000000-0000-4000-8000-00000000000c", QE),
            ApiErrorId.ERR_PPAP_SUBMISSION_NOT_FOUND,
        ),
        (
            api.get_resin_lot("00000000-0000-4000-8000-00000000000d", QE),
            ApiErrorId.ERR_RESIN_LOT_NOT_FOUND,
        ),
        (
            api.get_production_report("00000000-0000-4000-8000-00000000000e", QE),
            ApiErrorId.ERR_REPORT_NOT_FOUND,
        ),
        (
            api.get_press_qualification("00000000-0000-4000-8000-00000000000f", PE),
            ApiErrorId.ERR_QUALIFICATION_NOT_FOUND,
        ),
        (
            api.get_maintenance_order("00000000-0000-4000-8000-000000000010", TT),
            ApiErrorId.ERR_MAINTENANCE_ORDER_NOT_FOUND,
        ),
        (
            api.get_tool_transfer("00000000-0000-4000-8000-000000000011", PA),
            ApiErrorId.ERR_TOOL_TRANSFER_NOT_FOUND,
        ),
        (
            api.get_capacity_commit("00000000-0000-4000-8000-000000000012", PA),
            ApiErrorId.ERR_CAPACITY_COMMIT_NOT_FOUND,
        ),
    ]

    for response, expected in cases:
        assert response.status_code == 404, (
            f"Expected 404 for {expected.value}, got {response.status_code}"
        )
        validate_error(response, expected.value)
