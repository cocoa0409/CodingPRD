"""Operator identity, role authorisation and resource ownership."""

from test_helpers import (
    ApiErrorId,
    allocate_payload,
    create_branch,
    create_customer_payload,
    create_quote_payload,
    create_truck,
    get_success_data,
    list_quotes,
    make_branch_ops_headers,
    make_credit_manager_headers,
    make_driver_headers,
    make_platform_admin_headers,
    make_sales_rep_headers,
    read_order,
    read_reel,
    read_run,
    schedule_run,
    setup_converted_order,
    setup_staged_order_by_cut,
    validate_error,
)

ADMIN = make_platform_admin_headers()
REP_1 = make_sales_rep_headers("rep-1")


def test_request_without_role_header_is_unauthenticated(api):
    """PRD §2.1: "Every request to the API must carry two headers:
    `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming
    the role that operator is acting under. If either header is absent, or if
    `X-User-Role` is not exactly one of the six role names below, the request
    is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.7: "Authentication. `X-User-Role` and `X-User-ID` are present and
    `X-User-Role` is one of the six declared roles — otherwise
    `ERR_UNAUTHENTICATED` (401). Applies to every endpoint."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    branch = create_branch()

    response = api.raw_get(
        f"/branches/{branch['id']}", headers={"Content-Type": "application/json"}
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_sales_rep_may_not_run_the_allocator(api):
    """PRD §2.1: "If the headers are well-formed but the named role is not
    authorised for the endpoint being called (see the endpoint table in
    Section 4), the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.1: "`SalesRep` is the quoting desk. It builds, issues, reprices and
    converts quotes, and touches neither inventory nor delivery."
    PRD §3.6: "The order must be in `PENDING_ALLOCATION` or
    `PARTIALLY_ALLOCATED`, otherwise `ERR_ORDER_NOT_ALLOCATABLE`; the customer
    must not be on credit hold, otherwise `ERR_CUSTOMER_CREDIT_HOLD`; and the
    operator's `X-User-ID` must equal the order's `branch_id`, otherwise
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/sales_rep_cannot_run_the_allocator
    """
    scn = setup_converted_order(
        [{"put_up": "CUT", "requested_length_ft": 300}],
        reels=[{"nominal_length_ft": 1000}],
    )

    response = api.allocate_sales_order(
        scn["order"]["id"],
        allocate_payload(scn["order"]["version"]),
        REP_1,
    )

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    assert read_order(scn["order"]["id"])["fulfillment_status"] == "PENDING_ALLOCATION"
    assert read_reel(scn["reels"][0]["id"])["allocated_length_ft"] == 0


def test_branch_ops_may_not_allocate_another_branchs_order(api):
    """PRD §2.1: "Concretely, a `BranchOps` caller may only allocate or
    release a sales order whose `branch_id` equals `X-User-ID`, may only cut,
    pick or return a reel whose `branch_id` equals `X-User-ID`, and may only
    schedule a delivery run for an order at its own branch. A mismatch is
    rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/branch_ops_cannot_allocate_an_order_of_another_branch
    """
    scn = setup_converted_order(
        [{"put_up": "CUT", "requested_length_ft": 300}],
        reels=[{"nominal_length_ft": 1000}],
    )
    other_branch = create_branch(name="Dallas DC")

    response = api.allocate_sales_order(
        scn["order"]["id"],
        allocate_payload(scn["order"]["version"]),
        make_branch_ops_headers(other_branch["id"]),
    )

    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    assert read_order(scn["order"]["id"])["fulfillment_status"] == "PENDING_ALLOCATION"
    assert read_reel(scn["reels"][0]["id"])["allocated_length_ft"] == 0


def test_driver_may_not_dispatch_another_trucks_run(api):
    """PRD §2.1: "`Driver` is the delivery driver. When `X-User-Role` is
    `Driver`, `X-User-ID` is the `id` of the acting `Truck`; ownership checks
    on any resource that references a `Truck` compare the resource's
    `truck_id` to `X-User-ID`. A driver may dispatch and complete only those
    runs assigned to that truck, and any other run yields
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/driver_cannot_dispatch_another_trucks_run
    """
    scn = setup_staged_order_by_cut(
        [{"put_up": "CUT", "requested_length_ft": 300}],
        reels=[{"nominal_length_ft": 1000}],
        truck_overrides={"truck_code": "T-1"},
    )
    second_truck = create_truck(scn["branch"]["id"], truck_code="T-2")
    run = schedule_run(
        scn["order"]["id"], scn["truck"]["id"], scn["branch"]["id"],
        "2026-08-03T08:00:00Z", "2026-08-03T10:00:00Z",
    )

    response = api.dispatch_delivery_run(
        run["id"], make_driver_headers(second_truck["id"])
    )

    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    refreshed = read_run(run["id"])
    assert refreshed["status"] == "SCHEDULED"
    assert refreshed["dispatched_at"] is None


def test_credit_manager_may_not_open_a_quote(api):
    """PRD §2.1: "If the headers are well-formed but the named role is not
    authorised for the endpoint being called (see the endpoint table in
    Section 4), the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.1: "`CreditManager` is the credit control desk. It opens customer
    accounts and posts adjustments to limits and balances; it never quotes,
    allocates or delivers."
    PRD §3.3: "A `SalesRep` opens a quote against a `customer_id` and a
    `branch_id`."

    Design: Corner/rbac/credit_manager_cannot_open_a_quote
    """
    credit_desk = make_credit_manager_headers("cm-1")
    branch = create_branch()
    customer = get_success_data(
        api.create_customer(create_customer_payload(), credit_desk)
    )

    response = api.create_quote(
        create_quote_payload(customer["id"], branch["id"]), credit_desk
    )

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    assert list_quotes(customer_id=customer["id"]) == []
