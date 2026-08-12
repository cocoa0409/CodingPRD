"""Envelope shape, authentication, authorization, and list pagination (PRD §2)."""
from test_helpers import (
    ANONYMOUS_HEADERS,
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    customer_payload,
    depot_payload,
    get_success_data,
    is_valid_uuid,
    make_customer_agent_headers,
    make_depot,
    make_customer,
    make_order,
    order_line,
    set_logical_clock,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
CLERK_1 = TEST_USERS["billing_clerk_1_headers"]


def test_success_envelope_shape(api):
    """PRD §2.2: "All successful API responses (those with 2xx status codes)
    follow this standard envelope format in their JSON body".
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    Design: Corner/endpoints/success_envelope_shape
    """
    resp = api.create_customer(
        customer_payload(
            account_name="P41", kind="BAR_RESTAURANT", tier="STANDARD",
            credit_terms="NET_30", credit_limit_cents=100000,
        ),
        ADMIN,
    )
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    body = resp.json()
    req_id = body["meta"]["api_request_id"]
    assert isinstance(req_id, str) and req_id.startswith("req_"), (
        f"api_request_id must start with 'req_', got {req_id!r}"
    )
    assert isinstance(body["meta"].get("api_request_timestamp"), str)
    assert body["response_type"] == "object"
    assert is_valid_uuid(body["data"]["id"]), "data.id must be a server-minted UUID"


def test_order_not_found_error_envelope(api):
    """PRD §2.6: "every identifier in the URL must exist, validated left to
    right (a depot identifier before any segment nested beneath it), else
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/order_not_found_error_envelope
    """
    resp = api.get_order(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_unauthenticated_missing_headers(api):
    """PRD §2.1: "A request missing either header, or carrying a role value
    outside the recognized set, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/errors/unauthenticated_missing_headers
    """
    resp = api.create_depot(
        depot_payload("NoAuth", 10), ANONYMOUS_HEADERS
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_forbidden_role_depot_create(api):
    """PRD §2.1: "an authenticated caller attempting an operation outside their
    role is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/errors/forbidden_role_depot_create
    """
    cust = make_customer(
        account_name="E44", kind="BAR_RESTAURANT", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=100000,
    )
    resp = api.create_depot(
        depot_payload("Forbidden", 10), make_customer_agent_headers(cust["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_forbidden_ownership_cross_customer(api):
    """PRD §2.1: "ownership checks on any resource that references a customer
    compare the resource's customer foreign key to `X-User-ID` — `customer_id`
    on an order, route, invoice, or payment, or the linked order's
    `customer_id` for a waitlist entry."

    Design: Corner/errors/forbidden_ownership_cross_customer
    """
    depot = make_depot(10, "Depot E45")
    set_logical_clock()
    cust_a = make_customer(
        account_name="E45 A", kind="BAR_RESTAURANT", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=100000,
    )
    cust_b = make_customer(
        account_name="E45 B", kind="BAR_RESTAURANT", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=100000,
    )
    order = make_order(
        cust_a["id"], depot["id"],
        [order_line("BLOCK", "PALLET", 1)],
        channel="WILL_CALL", event_date="2026-05-10",
        window_start="10:00", window_end="12:00",
    )
    resp = api.cancel_order(order["id"], make_customer_agent_headers(cust_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_dispatcher_cannot_issue_invoice(api):
    """PRD §2.1: "an authenticated caller attempting an operation outside their
    role is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: the invoice issue row lists BillingClerk as its only authorized role.

    Design: Corner/rbac/dispatcher_cannot_issue_invoice
    """
    from test_helpers import (
        make_active_book,
        mini_book_payload,
        picked_up_order,
        generate_invoice,
    )

    depot = make_depot(10, "Depot R50")
    set_logical_clock()
    make_active_book(mini_book_payload())
    cust = make_customer(
        account_name="R50", kind="BAR_RESTAURANT", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=200000,
    )
    picked_up_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)],
        channel="WILL_CALL", event_date="2026-05-10",
        window_start="10:00", window_end="12:00",
    )
    invoice = generate_invoice(cust["id"], "2026-05-01", "2026-06-01", CLERK_1)
    resp = api.issue_invoice(invoice["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_billing_clerk_cannot_create_cert(api):
    """PRD §2.1: "an authenticated caller attempting an operation outside their
    role is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.2: "A `SafetyOfficer` registers a `HandlerCertification` against a
    customer account".

    Design: Corner/rbac/billing_clerk_cannot_create_cert
    """
    cust = make_customer(
        account_name="R51", kind="BAR_RESTAURANT", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=100000,
    )
    resp = api.create_certification(
        cust["id"],
        {
            "handler_name": "Wrong Role",
            "certificate_number": "CERT-51",
            "max_dry_ice_lbs": 500,
            "expires_at": "2027-01-01T00:00:00Z",
        },
        CLERK_1,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_orders_list_pagination_filter(api):
    """PRD §2.3: "`limit` sets the maximum number of items returned: it
    defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the
    number of items skipped and defaults to 0."
    PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/orders_list_pagination_filter
    """
    depot = make_depot(10, "Depot P40")
    set_logical_clock()
    cust_a = make_customer(
        account_name="P40 A", kind="BAR_RESTAURANT", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=100000,
    )
    cust_b = make_customer(
        account_name="P40 B", kind="BAR_RESTAURANT", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=100000,
    )
    for date in ("2026-05-10", "2026-05-11", "2026-05-12"):
        make_order(
            cust_a["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)],
            channel="WILL_CALL", event_date=date,
            window_start="10:00", window_end="12:00",
        )
    make_order(
        cust_b["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)],
        channel="WILL_CALL", event_date="2026-05-10",
        window_start="10:00", window_end="12:00",
    )

    page1, meta1 = validate_paginated(
        api.list_orders(ADMIN, params={"customer_id": cust_a["id"], "limit": 2, "offset": 0})
    )
    assert meta1["total_count"] == 3 and meta1["has_more"] is True
    assert len(page1) == 2

    page2, meta2 = validate_paginated(
        api.list_orders(ADMIN, params={"customer_id": cust_a["id"], "limit": 2, "offset": 2})
    )
    assert meta2["total_count"] == 3 and meta2["has_more"] is False
    assert len(page2) == 1
