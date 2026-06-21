"""Access control, customer ownership reads, notifications, and list pagination.

Translates queue B (Corner) rbac, errors (missing-auth), endpoints, and the
entities immutability instance.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, build_user_headers, make_customer_headers,
    create_customer, create_order, add_line, measure_line, quote, pay,
    create_workbench, setup_ready_order,
    assert_notification,
)

DESIGNER = TEST_USERS["frame_designer_headers"]
TECH = TEST_USERS["frame_production_tech_headers"]
CLERK = TEST_USERS["front_desk_clerk_headers"]


# ===========================================================================
# Corner: rbac
# ===========================================================================
def test_production_tech_cannot_apply_payment(api):
    """PRD §2.1: "A `FrontDeskClerk` owns deposits and payments, pickup, cancellation,
    and the customer-facing notifications."
    PRD §2.1: "When a request carries a recognized role but that role is not permitted
    to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/production_tech_cannot_apply_payment
    """
    cust = create_customer()
    order = create_order(cust["id"], deposit_pct=0.30)
    line = add_line(order["id"], order["version"], artwork_label="Rb",
                    nominal_width_in=8, nominal_height_in=10, molding_rate_per_ui=0.30)
    measure_line(line["id"], 8, 10)
    quote(order["id"])
    resp = api.apply_payment(order["id"], {"kind": "DEPOSIT", "amount": 25.00}, TECH)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_customer_cannot_read_other_customers_order(api):
    """PRD §2.1: "A `Customer` request that addresses an order, line, payment, or task
    belonging to a different customer is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/customer_cannot_read_other_customers_order
    """
    cust_a = create_customer(email="ownera@x.com", full_name="OwnerA")
    cust_b = create_customer(email="otherb@x.com", full_name="OtherB")
    order = create_order(cust_a["id"])
    # Customer B (entity_backed) addresses A's order.
    resp = api.get_order(order["id"], make_customer_headers(cust_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_customer_can_read_own_order(api):
    """PRD §2.1: "they may retrieve their own profile (the `X-User-ID` must equal the
    addressed customer), list and read their own framing orders (the order's
    `customer_id` must equal `X-User-ID`)".

    Design: Corner/rbac/customer_can_read_own_order
    """
    cust = create_customer(email="owner@x.com", full_name="Owner")
    order = create_order(cust["id"])
    data = validate_success(api.get_order(order["id"], make_customer_headers(cust["id"])),
                            expected_status=200)
    assert data["id"] == order["id"]
    assert data["production_status"] == "INTAKE"


def test_missing_auth_header_returns_401(api):
    """PRD §2.1: "If either header is missing or malformed, the request is rejected
    with `ERR_MISSING_AUTH_CONTEXT`."

    Design: Corner/rbac/missing_auth_header_returns_401
    """
    # Empty role -> malformed auth context, rejected before any role check.
    resp = api.list_workbenches(build_user_headers("nobody", ""))
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_CONTEXT)


# ===========================================================================
# Corner: endpoints
# ===========================================================================
def test_list_orders_filtered_by_customer_id_paginated(api):
    """PRD §2.3: "Unless a workflow states otherwise, all list endpoints return
    resources sorted by their creation timestamp (`created_at`) in ascending order.
    Every list response includes `limit`, `offset`, `total_count`, and `has_more` in
    the `meta` object of the envelope."

    Design: Corner/endpoints/list_orders_filtered_by_customer_id_paginated
    """
    cust = create_customer(email="pag@x.com", full_name="Pag")
    create_order(cust["id"])
    create_order(cust["id"])
    data, meta = validate_paginated(
        api.list_orders(DESIGNER, params={"customer_id": cust["id"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert all(o["customer_id"] == cust["id"] for o in data)


def test_deposit_receipt_notification_emitted_on_deposit(api):
    """PRD §3.9: "A `DEPOSIT_RECEIPT` notification is emitted when a deposit payment is
    applied, and a `READY` notification is emitted when the order transitions into
    `READY`."

    Design: Corner/endpoints/deposit_receipt_notification_emitted_on_deposit
    """
    cust = create_customer(email="rcpt@x.com", full_name="Rcpt")
    order = create_order(cust["id"], deposit_pct=0.30)
    line = add_line(order["id"], order["version"], artwork_label="Rc",
                    nominal_width_in=8, nominal_height_in=10, molding_rate_per_ui=0.30)
    measure_line(line["id"], 8, 10)
    quote(order["id"])
    pay(order["id"], "DEPOSIT", 25.00)
    data, meta = validate_paginated(api.list_notifications(order["id"], CLERK))
    kinds = [n["kind"] for n in data]
    assert "DEPOSIT_RECEIPT" in kinds, f"expected a DEPOSIT_RECEIPT notification, got {kinds}"


# ===========================================================================
# Corner: entities / notification_immutable_entity_has_no_version_field
# ===========================================================================
def test_notification_immutable_entity_has_no_version_field(api):
    """PRD §2.4: "A notification is an append-only record and therefore carries only
    `id` and `created_at`; it has neither an `updated_at` field nor a `version` field."
    PRD §3.9: "a `READY` notification is emitted when the order transitions into `READY`."

    Design: Corner/entities/notification_immutable_entity_has_no_version_field
    """
    cust, ready, line, bench, task = setup_ready_order(
        deposit_pct=0.30, measure_dims=(8, 10), deposit_amount=25.00)
    data, meta = validate_paginated(api.list_notifications(ready["id"], CLERK))
    ready_notes = [n for n in data if n["kind"] == "READY"]
    assert ready_notes, "expected a READY notification after mark-ready"
    note = ready_notes[0]
    assert_notification(note)
    assert "version" not in note
    assert "updated_at" not in note
