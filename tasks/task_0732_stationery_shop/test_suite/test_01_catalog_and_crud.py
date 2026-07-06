"""CRUD, defaults, invalid inputs, and 404s across catalog entities."""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error, get_success_data,
    NON_EXISTENT_UUID, TEST_USERS,
    create_customer_payload, create_paper_stock_payload,
    create_event_package_payload, create_finish_option_payload,
    create_design_payload,
    assert_customer, assert_paper_stock,
    make_customer_headers,
    create_customer, create_paper_stock, create_finish_option, create_event_package,
)


def test_create_customer_returns_201_with_defaults_and_version_one(api, shop_admin_headers):
    """PRD §3.1: "A Customer record is registered by a ShopAdmin with the customer's contact
    email (which must be unique), full_name, and phone; the newly created customer begins with
    credit_balance_cents of zero and cumulative_deposits_paid_cents of zero."
    PRD §2.9: "Both fields default to zero when a customer is created."
    PRD §2.4: "version is a system-managed integer that starts at 1 and is incremented by one
    on every mutation of that resource."

    Design: Corner/entities/create_customer_returns_201_with_all_required_fields
    """
    payload = create_customer_payload(email="u@x.com", full_name="U", phone="555-0100")
    res = api.create_customer(payload, shop_admin_headers)
    customer = validate_success(res, 201)
    assert_customer(customer)
    assert customer["email"] == "u@x.com"
    assert customer["credit_balance_cents"] == 0
    assert customer["cumulative_deposits_paid_cents"] == 0
    assert customer["version"] == 1


def test_get_customer_returns_stored_data(api, shop_admin_headers):
    """PRD §2.2: "operations that create or modify a resource will return the created or
    updated resource object in the data field."

    Design: Corner/entities/get_customer_returns_stored_data
    """
    created = create_customer(email="get@x.com", full_name="G", phone="555")
    res = api.get_customer(created["id"], shop_admin_headers)
    fetched = validate_success(res, 200)
    assert fetched["id"] == created["id"]
    assert fetched["email"] == "get@x.com"


def test_get_customer_nonexistent_returns_404(api, shop_admin_headers):
    """PRD §2.5: "When any identifier in the path does not correspond to an existing resource,
    the server rejects the request with the corresponding 404 error before evaluating deeper
    checks: ERR_CUSTOMER_NOT_FOUND, ERR_DESIGNER_NOT_FOUND, ..."

    Design: Corner/entities/customer_not_found_returns_404
    """
    res = api.get_customer(NON_EXISTENT_UUID, shop_admin_headers)
    validate_error(res, "ERR_CUSTOMER_NOT_FOUND", expected_status=404)


def test_create_customer_missing_email_returns_invalid_request(api, shop_admin_headers):
    """PRD §2.5: "A malformed body, missing required key, invalid enum value, or type mismatch
    on any of the input fields is rejected before further business rules run, with
    ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/create_customer_missing_email_returns_invalid_request
    """
    payload = {"full_name": "N", "phone": "555"}
    res = api.create_customer(payload, shop_admin_headers)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_paper_stock_default_status_is_active(api, shop_admin_headers):
    """PRD §3.1: "Both PaperStock.status and FinishOption.status default to ACTIVE at creation
    and may be flipped later; flipping a paper stock to DISCONTINUED is a first-class capability
    described later in this section."

    Design: Corner/entities/create_paper_stock_default_status_is_active
    """
    payload = create_paper_stock_payload(name="Def", base_price_cents=500, lead_days=7)
    payload.pop("status", None)
    res = api.create_paper_stock(payload, shop_admin_headers)
    paper = validate_success(res, 201)
    assert paper["status"] == "ACTIVE"


def test_paper_stock_reserved_units_is_computed_zero_at_creation(api, shop_admin_headers):
    """PRD §2.8: "Each PaperStock exposes an aggregated read-only reserved_units field.
    This field is the sum of LineItem.quantity across every line whose parent Order is
    currently in DEPOSIT_PENDING, IN_PRODUCTION, or READY_TO_SHIP."

    Design: Corner/entities/paper_stock_reserved_units_is_computed
    """
    payload = create_paper_stock_payload(name="Odd", base_price_cents=500, lead_days=7)
    res = api.create_paper_stock(payload, shop_admin_headers)
    paper = validate_success(res, 201)
    assert_paper_stock(paper)
    assert paper["reserved_units"] == 0


def test_paper_stock_invalid_enum_status_returns_invalid_request(api, shop_admin_headers):
    """PRD §2.5: "A malformed body, missing required key, invalid enum value, or type
    mismatch on any of the input fields is rejected before further business rules run,
    with ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/paper_stock_invalid_enum_status_returns_invalid_request
    """
    payload = create_paper_stock_payload(name="X", base_price_cents=500, lead_days=7,
                                          status="ORANGE")
    res = api.create_paper_stock(payload, shop_admin_headers)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_new_order_version_starts_at_1(api, shop_admin_headers):
    """PRD §2.4: "version is a system-managed integer that starts at 1 and is incremented
    by one on every mutation of that resource."

    Design: Corner/entities/order_version_starts_at_1
    """
    customer = create_customer()
    paper = create_paper_stock()
    finish = create_finish_option()
    pkg = create_event_package()
    cust_headers = make_customer_headers(customer["id"])
    d = get_success_data(api.create_design(
        create_design_payload(customer["id"], pkg["id"], paper["id"], finish["id"]),
        cust_headers,
    ))
    res = api.create_order({"customer_id": customer["id"], "design_id": d["id"]}, cust_headers)
    order = validate_success(res, 201)
    assert order["version"] == 1


def test_design_creation_with_unknown_customer_returns_customer_not_found(api):
    """PRD §2.5: "When any identifier in the path does not correspond to an existing resource,
    the server rejects the request with the corresponding 404 error before evaluating deeper
    checks: ERR_CUSTOMER_NOT_FOUND, ERR_DESIGNER_NOT_FOUND, ERR_DESIGN_NOT_FOUND, ..."

    Design: Corner/entities/design_requires_valid_customer_and_package
    """
    paper = create_paper_stock()
    finish = create_finish_option()
    pkg = create_event_package()
    non_existent_headers = make_customer_headers(NON_EXISTENT_UUID)
    payload = create_design_payload(NON_EXISTENT_UUID, pkg["id"], paper["id"], finish["id"])
    res = api.create_design(payload, non_existent_headers)
    validate_error(res, "ERR_CUSTOMER_NOT_FOUND")
