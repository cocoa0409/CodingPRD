"""Provisioning, intake, listing, and access-control corner claims.

Queue B corner instances covering resource creation envelopes, required-field /
enum / referential validation, defaults, computed inventory fields, the auth
header gate, pagination, and RBAC.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_customer_headers,
    create_customer, create_device, create_ticket,
)

SA = TEST_USERS["service_advisor_headers"]
SM = TEST_USERS["store_manager_headers"]


def test_create_customer_returns_201_object_and_zero_credit(api):
    """PRD §4: "Operations that create a new stand-alone resource return `201 Created`".
    PRD §3.1: "the new customer's `store_credit_balance_cents` starts at 0."
    PRD §2.4: "`version`, an integer that begins at 1 and increments by one on every mutation".

    Design: Corner/endpoints/create_customer_returns_201_and_envelope
    """
    resp = api.create_customer({"full_name": "Al", "email": "al@x.com", "phone": "555"}, SA)
    data = validate_success(resp, 201)
    assert resp.json()["response_type"] == "object"
    assert data["store_credit_balance_cents"] == 0
    assert data["version"] == 1


def test_list_repair_tickets_pagination_shape(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned".
    PRD §2.3: "Every list response reports `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/list_repair_tickets_pagination_shape
    """
    cust = create_customer()
    dev1 = create_device(cust["id"], market_value_cents=1000)
    create_ticket(dev1["id"], cust["id"], spend_cap_cents=1000)
    dev2 = create_device(cust["id"], market_value_cents=1000)
    create_ticket(dev2["id"], cust["id"], intake_channel="MAIL_IN", spend_cap_cents=1000)

    resp = api.list_repair_tickets(SM, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_create_device_missing_market_value_returns_validation(api):
    """PRD §2.11: "the request body is checked for well-formedness — required fields
    present, enum values in range, quantities at least 1, and an interval whose end
    is after its start — surfacing `ERR_VALIDATION`, `ERR_INVALID_QUANTITY`, or
    `ERR_INVALID_INTERVAL`."

    Design: Corner/entities/create_device_missing_required_market_value_returns_validation
    """
    cust = create_customer()
    resp = api.create_device(
        {"customer_id": cust["id"], "category": "PHONE", "brand": "A",
         "model": "m", "serial_number": "s"}, SA)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 422)


def test_create_device_invalid_category_enum_returns_validation(api):
    """PRD §3.1: "the device `category` — one of `PHONE`, `LAPTOP`, `TABLET`, or `WEARABLE`".
    PRD §2.11: "the request body is checked for well-formedness — required fields
    present, enum values in range, quantities at least 1, and an interval whose end
    is after its start — surfacing `ERR_VALIDATION`".

    Design: Corner/entities/create_device_invalid_enum_category_returns_validation
    """
    cust = create_customer()
    resp = api.create_device(
        {"customer_id": cust["id"], "category": "SPACESHIP", "brand": "A",
         "model": "m", "serial_number": "s", "market_value_cents": 1000}, SA)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_device_nonexistent_customer_returns_not_found(api):
    """PRD §2.9: "a referenced customer that does not exist yields `ERR_CUSTOMER_NOT_FOUND`".

    Design: Corner/entities/create_device_nonexistent_customer_returns_not_found
    """
    resp = api.create_device(
        {"customer_id": "00000000-0000-0000-0000-000000000000", "category": "PHONE",
         "brand": "A", "model": "m", "serial_number": "s", "market_value_cents": 1000}, SA)
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value, 404)


def test_get_repair_ticket_not_found_returns_404(api):
    """PRD §2.9: "A request for an estimate under a non-existent ticket fails with
    `ERR_TICKET_NOT_FOUND` before the estimate is ever looked up".

    Design: Corner/entities/get_repair_ticket_not_found_returns_404
    """
    resp = api.get_repair_ticket("00000000-0000-0000-0000-000000000000", SM)
    validate_error(resp, ApiErrorId.ERR_TICKET_NOT_FOUND.value, 404)


def test_create_ticket_defaults_warranty_and_callback_false(api):
    """PRD §3.2: "an optional `is_under_warranty` flag (defaulting to false, which
    when true waives the diagnostic fee)".
    PRD §3.2: "A freshly opened ticket enters `INTAKE` with `is_callback` set to false."

    Design: Corner/entities/create_ticket_default_is_under_warranty_false
    """
    cust = create_customer()
    dev = create_device(cust["id"], market_value_cents=1000)
    resp = api.create_repair_ticket(
        {"device_id": dev["id"], "customer_id": cust["id"], "intake_channel": "WALK_IN",
         "reported_issue": "x", "spend_cap_cents": 1000}, SA)
    data = validate_success(resp, 201)
    assert data["is_under_warranty"] is False
    assert data["is_callback"] is False
    assert data["status"] == "INTAKE"


def test_part_available_qty_computed_on_create(api):
    """PRD §3.1: "a new part begins with `reserved_qty` of 0 and `available_qty`
    equal to its `on_hand_qty`."

    Design: Corner/entities/part_available_qty_computed_on_create
    """
    resp = api.create_part(
        {"sku": "P1", "name": "Screen", "unit_price_cents": 6000, "on_hand_qty": 5}, SM)
    data = validate_success(resp, 201)
    assert data["available_qty"] == 5
    assert data["reserved_qty"] == 0


def test_create_customer_missing_auth_header_returns_missing_user_context(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the
    four recognized roles, the request is rejected with `ERR_MISSING_USER_CONTEXT`."

    Design: Corner/validations/create_customer_missing_auth_header_returns_missing_user_context
    """
    resp = api.create_customer({"full_name": "Nh", "email": "nh@x.com", "phone": "5"}, {})
    validate_error(resp, ApiErrorId.ERR_MISSING_USER_CONTEXT.value, 400)


def test_customer_cannot_create_repair_ticket_unauthorized(api):
    """PRD §2.1: "`ServiceAdvisor` is the front desk: this role exclusively registers
    customers and devices, opens and cancels tickets, files warranty callbacks,
    submits and cancels trade-ins, and files and routes protection-plan claims."
    PRD §2.1: "When a role is present and valid but is not permitted to perform the
    requested operation — or when a `Customer` attempts to act on a resource it does
    not own — the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/customer_cannot_create_repair_ticket_unauthorized
    """
    cust = create_customer()
    dev = create_device(cust["id"], market_value_cents=1000)
    resp = api.create_repair_ticket(
        {"device_id": dev["id"], "customer_id": cust["id"], "intake_channel": "WALK_IN",
         "reported_issue": "x", "spend_cap_cents": 1000},
        make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_customer_cannot_approve_other_customers_estimate_unauthorized(api):
    """PRD §3.3: "A customer acting on a ticket whose `customer_id` is not their
    `X-User-ID` is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/customer_cannot_approve_other_customers_estimate_unauthorized
    """
    from test_helpers import setup_estimate_sent
    scn = setup_estimate_sent(market_value_cents=40000, spend_cap_cents=100000, labor_hours=2)
    other = create_customer()
    resp = api.approve_estimate(scn["ticket"]["id"], scn["estimate"]["id"],
                                make_customer_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    tkt = validate_success(api.get_repair_ticket(scn["ticket"]["id"], SM))
    assert tkt["status"] == "AWAITING_APPROVAL"
