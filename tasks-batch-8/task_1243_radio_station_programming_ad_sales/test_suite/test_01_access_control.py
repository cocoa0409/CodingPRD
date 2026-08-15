"""Authentication, role authorization, ownership, and segregation of duties
(PRD §2.1 identity model, §2.8 validation ordering, §3.4/§3.8 SoD rules)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_station,
    create_clock_payload,
    create_log_payload,
    create_order_payload,
    create_rate_card_entry_payload,
    create_station,
    get_success_data,
    make_billing_admin_headers,
    make_headers,
    make_sales_manager_headers,
    make_sales_rep_headers,
    make_traffic_director_headers,
    validate_error,
    validate_success,
)


def test_spots_create_missing_auth_returns_401(api):
    """PRD §2.1: "A request missing either header, or carrying a role outside
    this enumeration, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/spots_create_missing_auth_returns_401
    """
    payload = {
        "order_id": NON_EXISTENT_UUID,
        "log_id": NON_EXISTENT_UUID,
        "daypart": "MORNING_DRIVE",
        "hour": 6,
        "duration_sec": 60,
        "expected_order_version": 1,
    }
    resp = api.create_spot(payload, headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_rate_card_create_sales_rep_forbidden(api):
    """PRD §2.1: "A request whose role is authenticated but not authorized for
    the target operation is rejected with `ERR_ROLE_FORBIDDEN`."
    PRD §4: POST /rate-card-entries is authorized for "SalesManager" only.

    Design: Corner/validations/rate_card_create_sales_rep_forbidden
    """
    payload = create_rate_card_entry_payload(NON_EXISTENT_UUID)
    resp = api.create_rate_card_entry(payload, make_sales_rep_headers("rep-1"))
    validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN)


def test_existence_beats_state_on_approve(api):
    """PRD §2.8: "then existence of every path id and referenced foreign key
    validated left-to-right (`ERR_NOT_FOUND`), then the TRADE-agreement-required
    structural rule (`ERR_TRADE_AGREEMENT_REQUIRED`), then the OCC stale-version
    check (`ERR_STALE_VERSION`), then generic from-state legality
    (`ERR_INVALID_STATE`)"

    Design: Corner/validations/existence_beats_state_on_approve
    """
    resp = api.approve_order(NON_EXISTENT_UUID, make_sales_manager_headers("mgr-1"))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_order_create_billing_admin_forbidden(api, sales_manager_headers):
    """PRD §4: POST /orders is authorized for "SalesRep" only; PRD §2.1: "A
    request whose role is authenticated but not authorized for the target
    operation is rejected with `ERR_ROLE_FORBIDDEN`."

    Design: Corner/rbac/order_create_billing_admin_forbidden
    """
    station = create_station(headers=sales_manager_headers)
    payload = create_order_payload(station["id"])
    resp = api.create_order(payload, make_billing_admin_headers("ba-1"))
    validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN)


def test_affidavit_issue_program_director_forbidden(api):
    """PRD §4: POST /logs/{id}/issue-affidavit is authorized for "BillingAdmin"
    only. PRD §2.1: "A request whose role is authenticated but not authorized
    for the target operation is rejected with `ERR_ROLE_FORBIDDEN`."

    Design: Corner/rbac/affidavit_issue_program_director_forbidden
    """
    resp = api.issue_affidavit(NON_EXISTENT_UUID, make_headers("ProgramDirector", "pd-1"))
    validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN)


def test_discrepancy_waive_traffic_director_forbidden(api):
    """PRD §4: POST /discrepancies/{id}/waive is authorized for "BillingAdmin"
    only; PRD §2.1: "A request whose role is authenticated but not authorized
    for the target operation is rejected with `ERR_ROLE_FORBIDDEN`."

    Design: Corner/rbac/discrepancy_waive_traffic_director_forbidden
    """
    resp = api.waive_discrepancy(NON_EXISTENT_UUID, {}, make_traffic_director_headers("td-1"))
    validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN)


def test_order_submit_by_other_rep_returns_403(api, sales_manager_headers):
    """PRD §3.4: "Submission (`DRAFT → SUBMITTED`) is restricted to the creator
    — any other `X-User-ID` is rejected with `ERR_NOT_ORDER_OWNER`"

    Design: Corner/rbac/order_submit_by_other_rep_returns_403
    """
    station = create_station(headers=sales_manager_headers)
    payload = create_order_payload(station["id"])
    order = get_success_data(api.create_order(payload, make_sales_rep_headers("rep-1")))
    assert order["status"] == "DRAFT"

    resp = api.submit_order(order["id"], make_sales_rep_headers("rep-2"))
    validate_error(resp, ApiErrorId.ERR_NOT_ORDER_OWNER)

    after = get_success_data(api.get_order(order["id"], make_sales_rep_headers("rep-1")))
    assert after["status"] == "DRAFT", "Order stays DRAFT after a rejected submit"


def test_order_approve_same_user_returns_403(api, sales_manager_headers):
    """PRD §3.4: "Approval (`SUBMITTED → APPROVED`) requires a `SalesManager`
    whose `X-User-ID` differs from `created_by_user_id`; matching the creator
    is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/order_approve_same_user_returns_403
    """
    station = create_station(headers=sales_manager_headers)
    payload = create_order_payload(station["id"])
    order = get_success_data(api.create_order(payload, make_sales_rep_headers("dup-1")))
    get_success_data(api.submit_order(order["id"], make_sales_rep_headers("dup-1")))

    resp = api.approve_order(order["id"], make_sales_manager_headers("dup-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    after = get_success_data(api.get_order(order["id"], make_sales_rep_headers("dup-1")))
    assert after["status"] == "SUBMITTED", "Order stays SUBMITTED after a rejected approve"


def test_affidavit_issuer_equals_reconciler_returns_403(api, sales_manager_headers):
    """PRD §3.8: "Issuing the affidavit (`RECONCILED → AFFIDAVIT_ISSUED`) is
    restricted to a `BillingAdmin` whose `X-User-ID` differs from
    `reconciled_by_user_id`; a match is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/affidavit_issuer_equals_reconciler_returns_403
    """
    from test_helpers import TD

    station = create_station(headers=sales_manager_headers)
    clock = api.create_clock(
        create_clock_payload(station["id"], applies_weekdays=["MON"], slots=[]),
        make_headers("ProgramDirector", "pd-1"),
    )
    clock = get_success_data(clock)
    get_success_data(api.activate_clock(clock["id"], make_headers("ProgramDirector", "pd-1")))

    log = get_success_data(api.create_log(create_log_payload(station["id"]), TD))
    log = get_success_data(
        api.lock_log(log["id"], {"expected_log_version": log["version"]}, TD)
    )
    get_success_data(
        api.as_run_import(
            log["id"],
            {"aired_spot_ids": [], "aired_live_read_ids": [], "aired_barter_avail_ids": []},
            TD,
        )
    )
    get_success_data(api.begin_reconciliation(log["id"], TD))
    reconciled = get_success_data(
        api.reconcile_log(log["id"], make_traffic_director_headers("same-1"))
    )
    assert reconciled["posture"] == "RECONCILED"

    # Issuer identity equal to the reconciler is rejected.
    resp = api.issue_affidavit(log["id"], make_billing_admin_headers("same-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    # A different BillingAdmin identity issues successfully.
    issued = get_success_data(api.issue_affidavit(log["id"], make_billing_admin_headers("ba-9")))
    assert issued["posture"] == "AFFIDAVIT_ISSUED"
