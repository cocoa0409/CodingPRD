"""Catalog, customer intake, and line configuration — creation, defaults,
computed pricing, configuration validation, and immutability claims.

All tests start against an empty database (the runner restarts the server
before each test) and build their own preconditions.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    assert_customer, assert_order_line, assert_payment,
    create_customer_payload, create_order_payload, create_order_line_payload,
    TEST_USERS, NON_EXISTENT_UUID,
    create_customer, create_sofa_product, create_draft_order,
    setup_active_financing_plan,
)

SA = TEST_USERS["sales_associate_headers"]
SM = TEST_USERS["store_manager_headers"]


def test_create_customer_returns_201_with_system_fields(api):
    """PRD 3.1: "The read-only open_financing_count is initialized to 0 at creation."
    PRD 2.4: "an integer version that begins at its initial value and increments by
    one on each mutation."

    Design: Corner/entities/create_customer_returns_201_with_system_fields
    """
    res = api.create_customer(create_customer_payload(
        full_name="Tess New", email="tess@x.com", credit_score=700,
        monthly_income_cents=5000000, existing_monthly_obligations_cents=0), SA)
    cust = validate_success(res, 201)
    assert_customer(cust)
    assert cust["open_financing_count"] == 0, "open_financing_count starts at 0"
    assert cust["version"] == 1, "version begins at its initial value 1"


def test_create_customer_returns_initialized_open_financing_count(api):
    """PRD 3.1: "The read-only open_financing_count is initialized to 0 at creation
    and thereafter tracks how many of this customer's financing plans sit in CURRENT
    or PAST_DUE status."

    Second test for this instance: confirm the field is server-minted and read-only,
    even when the client tries to seed it.

    Design: Corner/entities/create_customer_returns_201_with_system_fields
    """
    payload = create_customer_payload(
        full_name="Seed Attempt", email="seed@x.com", credit_score=700,
        monthly_income_cents=5000000, existing_monthly_obligations_cents=0)
    payload["open_financing_count"] = 99
    cust = validate_success(api.create_customer(payload, SA), 201)
    assert cust["open_financing_count"] == 0, "client-supplied count is ignored"


def test_create_customer_missing_credit_score_rejected(api):
    """PRD 3.1: "A Customer is recorded with full_name, email ... and three figures
    that gate financing: credit_score ..."
    PRD 2.9: "Request-shape validation rejects a body that omits a required field ...
    with ERR_INVALID_REQUEST."

    Design: Corner/entities/create_customer_missing_credit_score_returns_invalid_request
    """
    res = api.create_customer({
        "full_name": "No Score", "email": "noscore@x.com",
        "monthly_income_cents": 5000000}, SA)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_customer_missing_full_name_rejected(api):
    """PRD 2.9: "Request-shape validation rejects a body that omits a required field,
    carries a value of the wrong type, supplies an out-of-range number, or names an
    enum value outside its allowed set, all with ERR_INVALID_REQUEST."

    Second test for this instance: a different required field omitted.

    Design: Corner/entities/create_customer_missing_credit_score_returns_invalid_request
    """
    res = api.create_customer({
        "email": "noname@x.com", "credit_score": 700,
        "monthly_income_cents": 5000000}, SA)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_get_nonexistent_order_returns_not_found(api):
    """PRD 2.9: "rejects the first identifier that does not resolve to an existing
    resource with ERR_NOT_FOUND."

    Design: Corner/entities/get_order_nonexistent_returns_not_found
    """
    res = api.get_order("00000000-0000-4000-8000-000000000000", SA)
    validate_error(res, "ERR_NOT_FOUND")


def test_get_nonexistent_order_random_uuid_returns_not_found(api):
    """PRD 2.9: "rejects the first identifier that does not resolve to an existing
    resource with ERR_NOT_FOUND."

    Second test for this instance: framework's NON_EXISTENT_UUID also resolves to 404.

    Design: Corner/entities/get_order_nonexistent_returns_not_found
    """
    res = api.get_order(NON_EXISTENT_UUID, SA)
    validate_error(res, "ERR_NOT_FOUND")


def test_order_line_defaults_applied(api):
    """PRD 3.2: "optionally a quantity (a whole number of at least 1, defaulting to 1),
    add_assembly (defaulting to false), and add_haul_away (defaulting to false)."
    PRD 3.2: "when a flag is unset its contribution is zero."

    Design: Corner/entities/order_line_default_quantity_and_flags_applied
    """
    product = create_sofa_product()
    customer = create_customer()
    order = create_draft_order(customer["id"])
    res = api.create_order_line({
        "order_id": order["id"], "product_id": product["id"],
        "fabric_code": "STANDARD", "size_code": "STD"}, SA)
    line = validate_success(res, 201)
    assert_order_line(line)
    assert line["quantity"] == 1, "quantity defaults to 1"
    assert line["addon_fee_cents"] == 0, "no add-ons -> addon_fee 0"
    assert line["line_total_cents"] == 100000, "line_total == unit_config_price at qty 1"


def test_order_line_default_quantity_gives_unit_price_line_total(api):
    """PRD 3.2: "The line's merchandise figure, line_total_cents, is that per-unit price
    multiplied by quantity."

    Second test for this instance: with defaults, line_total equals unit_config_price.

    Design: Corner/entities/order_line_default_quantity_and_flags_applied
    """
    product = create_sofa_product()
    customer = create_customer()
    order = create_draft_order(customer["id"])
    line = validate_success(api.create_order_line({
        "order_id": order["id"], "product_id": product["id"],
        "fabric_code": "STANDARD", "size_code": "STD"}, SA), 201)
    assert line["line_total_cents"] == line["unit_config_price_cents"], \
        "default quantity 1 makes line_total == unit_config_price"
    assert line["add_assembly"] is False and line["add_haul_away"] is False


def test_line_unit_config_price_from_surcharges(api):
    """PRD 3.2: "The per-unit configured price, unit_config_price_cents, is the product's
    base_price_cents plus the surcharge of the chosen fabric ... plus the surcharge of
    the chosen size ..."

    Design: Corner/entities/line_unit_config_price_computed_from_surcharges
    """
    product = get_success_data(api.create_product({
        "sku": "SOFA-STD", "name": "Aspen Sofa", "category": "SOFA",
        "base_price_cents": 100000,
        "available_fabrics": [{"code": "STANDARD", "surcharge_cents": 0},
                              {"code": "VELVET", "surcharge_cents": 20000}],
        "available_sizes": [{"code": "STD", "surcharge_cents": 0}]}, SM))
    customer = create_customer()
    order = create_draft_order(customer["id"])
    line = validate_success(api.create_order_line(
        create_order_line_payload(order["id"], product["id"],
                                  fabric_code="VELVET", size_code="STD", quantity=3), SA), 201)
    assert line["unit_config_price_cents"] == 120000, "100000 base + 20000 velvet"
    assert line["line_total_cents"] == 360000, "120000 * 3"


def test_line_computed_price_ignores_client_override(api):
    """PRD 2.4: "Many fields are read-only and derived; clients never supply them. ...
    On an OrderLine, unit_config_price_cents, line_total_cents, and addon_fee_cents are
    computed."

    Second test for this instance: a client-supplied computed value is recalculated.

    Design: Corner/entities/line_unit_config_price_computed_from_surcharges
    """
    product = get_success_data(api.create_product({
        "sku": "SOFA-STD", "name": "Aspen Sofa", "category": "SOFA",
        "base_price_cents": 100000,
        "available_fabrics": [{"code": "STANDARD", "surcharge_cents": 0},
                              {"code": "VELVET", "surcharge_cents": 20000}],
        "available_sizes": [{"code": "STD", "surcharge_cents": 0}]}, SM))
    customer = create_customer()
    order = create_draft_order(customer["id"])
    payload = create_order_line_payload(order["id"], product["id"],
                                        fabric_code="VELVET", size_code="STD", quantity=3)
    payload["unit_config_price_cents"] = 1
    payload["line_total_cents"] = 1
    line = validate_success(api.create_order_line(payload, SA), 201)
    assert line["unit_config_price_cents"] == 120000, "computed, not client-supplied"
    assert line["line_total_cents"] == 360000, "computed, not client-supplied"


def test_order_line_invalid_fabric_rejected(api):
    """PRD 3.2: "a configuration naming a fabric or size the product does not offer is
    rejected with `ERR_INVALID_CONFIGURATION`."

    Design: Corner/entities/order_line_invalid_fabric_returns_invalid_configuration
    """
    product = create_sofa_product()  # only STANDARD fabric
    customer = create_customer()
    order = create_draft_order(customer["id"])
    res = api.create_order_line(
        create_order_line_payload(order["id"], product["id"],
                                  fabric_code="LEATHER", size_code="STD"), SA)
    validate_error(res, "ERR_INVALID_CONFIGURATION")


def test_order_line_invalid_size_rejected(api):
    """PRD 3.2: "The chosen `fabric_code` must appear among the product's
    `available_fabrics` codes and the `size_code` among its `available_sizes` codes; a
    configuration naming a fabric or size the product does not offer is rejected with
    `ERR_INVALID_CONFIGURATION`."

    Second test for this instance: an unoffered size_code triggers the same error.

    Design: Corner/entities/order_line_invalid_fabric_returns_invalid_configuration
    """
    product = create_sofa_product()  # only STD size
    customer = create_customer()
    order = create_draft_order(customer["id"])
    res = api.create_order_line(
        create_order_line_payload(order["id"], product["id"],
                                  fabric_code="STANDARD", size_code="KING"), SA)
    validate_error(res, "ERR_INVALID_CONFIGURATION")


def test_payment_immutable_no_version_field(api):
    """PRD 2.4: "The Payment resource is the sole exception: it is immutable after
    creation and therefore carries only id and created_at — it has neither an updated_at
    field nor a version field."
    PRD 3.6: "its applied_period_index — the 1-based monthly period it satisfies — is
    assigned in chronological order of created_at ascending."

    Design: Corner/entities/payment_immutable_no_version_field
    """
    customer, product, order, line, plan = setup_active_financing_plan()
    res = api.create_payment(plan["id"], {"amount_cents": 10902}, SA)
    payment = validate_success(res, 201)
    assert_payment(payment)
    assert payment["applied_period_index"] == 1, "first payment satisfies period 1"
    assert "version" not in payment, "Payment carries no version field"
    assert "updated_at" not in payment, "Payment carries no updated_at field"


def test_payment_first_payment_period_index_one(api):
    """PRD 3.6: "the payment is appended as a Payment row whose applied_period_index —
    the 1-based monthly period it satisfies — is assigned in chronological order of
    created_at ascending."

    Second test for this instance: the immutable Payment row's period index is 1-based.

    Design: Corner/entities/payment_immutable_no_version_field
    """
    customer, product, order, line, plan = setup_active_financing_plan()
    payment = validate_success(api.create_payment(plan["id"], {"amount_cents": 10902}, SA), 201)
    assert payment["applied_period_index"] == 1
    assert payment["financing_plan_id"] == plan["id"]


def test_new_order_starts_draft_unpaid(api):
    """PRD 3.1: "The order opens with payment_status of UNPAID and fulfillment_status
    of DRAFT, and its sales_associate_user_id is stamped from the acting associate's
    identity."

    Design: Corner/state_machines/new_order_starts_draft_unpaid
    """
    customer = create_customer()
    res = api.create_order(create_order_payload(customer["id"]), SA)
    order = validate_success(res, 201)
    assert order["fulfillment_status"] == "DRAFT"
    assert order["payment_status"] == "UNPAID"


def test_new_order_stamps_sales_associate(api):
    """PRD 3.1: "its sales_associate_user_id is stamped from the acting associate's
    identity."

    Second test for this instance: confirm both initial axes plus the associate stamp.

    Design: Corner/state_machines/new_order_starts_draft_unpaid
    """
    customer = create_customer()
    order = validate_success(api.create_order(create_order_payload(customer["id"]), SA), 201)
    assert order["fulfillment_status"] == "DRAFT"
    assert order["payment_status"] == "UNPAID"
    assert order["customer_id"] == customer["id"]
