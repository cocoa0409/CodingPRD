"""Order and order-line creation, configuration, and listing (PRD §3.2)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    create_fixture, create_order,
    assert_order, assert_order_line,
)

SM = TEST_USERS["sm_headers"]


def test_create_order_defaults_draft_unpaid_version_one(api):
    """PRD §3.2: "A new order begins with `fulfillment_status` of `DRAFT` on its
    fulfillment axis and `payment_status` of `UNPAID` on its independent payment axis,
    and all of its estimate and final pricing figures start at their defaults."
    PRD §2.4: "an integer `version` that starts at 1 and increments by one on every mutation."

    Design: Corner/entities/create_order_returns_201_with_defaults
    """
    resp = api.create_order({"customer_name": "Walk-in"}, SM)
    data = validate_success(resp, 201)
    assert_order(data)
    assert data["fulfillment_status"] == "DRAFT"
    assert data["payment_status"] == "UNPAID"
    assert data["version"] == 1


def test_get_order_nonexistent_returns_not_found(api):
    """PRD §2.8: "the server validates that path-referenced resource exists before doing
    anything else with the body; a missing path resource yields `ERR_NOT_FOUND`."

    Design: Corner/entities/get_order_nonexistent_returns_not_found
    """
    resp = api.get_order(NON_EXISTENT_UUID, SM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_order_missing_customer_name_invalid_request(api):
    """PRD §2.8: "then structural validity of the request body — required fields present
    and enum and type values valid (`ERR_INVALID_REQUEST`)."
    PRD §3.2: "opens an order by supplying a `customer_name`".

    Design: Corner/entities/create_order_missing_required_returns_invalid_request
    """
    resp = api.create_order({}, SM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_order_bad_trade_account_fk_not_found(api):
    """PRD §2.8: "each referenced entity must exist, or the request is rejected with
    `ERR_FK_NOT_FOUND`."

    Design: Corner/entities/create_order_bad_trade_account_returns_fk_not_found
    """
    resp = api.create_order(
        {"customer_name": "x", "trade_account_id": "11111111-1111-1111-1111-111111111111"}, SM
    )
    validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND.value)


def test_order_line_computed_unit_price_and_sku(api):
    """PRD §3.2: "Its `unit_price_cents` is the fixture's `base_price_cents` plus the sum
    of the `price_delta_cents` of each selected option."
    PRD §3.2: "Its `configured_sku` is formed by taking the fixture's `sku_base` and
    appending the `sku_suffix` of each selected option, with the suffixes concatenated in
    the order the options are declared in the fixture's `options` array (not in the order
    they were selected)."

    Design: Corner/entities/order_line_computed_unit_price_and_sku_from_options
    """
    fx = create_fixture(
        api, sku_base="F-OPT", category="CEILING_FAN", base_price_cents=20000, base_wattage=60,
        options=[
            {"option_id": "O1", "group": "FINISH", "label": "Brushed Nickel",
             "price_delta_cents": 3000, "wattage_delta": 0, "sku_suffix": "-BN"},
            {"option_id": "O2", "group": "DOWNROD", "label": "24in",
             "price_delta_cents": 1500, "wattage_delta": 0, "sku_suffix": "-24"},
        ],
    )
    order = create_order(api, customer_name="OPT")
    resp = api.add_order_line(
        order["id"], {"fixture_model_id": fx["id"], "quantity": 1, "selected_option_ids": ["O1"]}, SM
    )
    line = validate_success(resp, 201)
    assert_order_line(line)
    assert line["unit_price_cents"] == 23000
    assert line["configured_sku"] == "F-OPT-BN"


def test_order_line_invalid_option_id_invalid_request(api):
    """PRD §3.2: "Every identifier in `selected_option_ids` must be one of the fixture's own
    `options[].option_id` values; a quantity below 1, a bad enum, or an option id that is
    not part of the fixture is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/order_line_invalid_option_returns_invalid_request
    """
    fx = create_fixture(api, sku_base="F-BADOPT", category="PENDANT", base_price_cents=10000, base_wattage=40)
    order = create_order(api, customer_name="BO")
    resp = api.add_order_line(
        order["id"], {"fixture_model_id": fx["id"], "quantity": 1, "selected_option_ids": ["NOPE"]}, SM
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_order_line_zero_quantity_invalid_request(api):
    """PRD §3.2: "Every identifier in `selected_option_ids` must be one of the fixture's own
    `options[].option_id` values; a quantity below 1, a bad enum, or an option id that is
    not part of the fixture is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/order_line_zero_quantity_returns_invalid_request
    """
    fx = create_fixture(api, sku_base="F-Q0", category="SCONCE", base_price_cents=5000, base_wattage=40)
    order = create_order(api, customer_name="Q0")
    resp = api.add_order_line(order["id"], {"fixture_model_id": fx["id"], "quantity": 0}, SM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_list_order_lines_filtered_by_order_id(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_order_lines_filtered_by_order_id
    """
    fx = create_fixture(api, sku_base="F-LST", category="SCONCE", base_price_cents=5000, base_wattage=40)
    order = create_order(api, customer_name="LST")
    api.add_order_line(order["id"], {"fixture_model_id": fx["id"], "quantity": 1}, SM)
    api.add_order_line(order["id"], {"fixture_model_id": fx["id"], "quantity": 1}, SM)

    resp = api.list_order_lines(SM, params={"order_id": order["id"]})
    data, meta = validate_paginated(resp)
    assert len(data) == 2
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
