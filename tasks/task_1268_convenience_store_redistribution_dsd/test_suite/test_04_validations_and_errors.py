"""Validation errors, duplicate checks, not-found envelope shape."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    NON_EXISTENT_UUID,
    SALES,
    api_client,
    create_fuel_surcharge_rate_payload,
    create_order_guide_payload,
    create_product_payload,
    create_purchase_order_payload,
    create_retailer_payload,
    create_tax_stamp_supply_payload,
    get_success_data,
    make_store_manager_headers,
    order_line,
    setup_guide,
    setup_product,
    setup_retailer,
    setup_stamp_supply,
    validate_error,
)


def test_not_found_error_shape(api, admin_headers):
    """PRD §2.8: "the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the
    first identifier that does not correspond to an existing resource".
    PRD §2.2: error envelope carries `response_type` of 'error' and a
    `data.error_id`.

    Design: Corner/errors/not_found_error_shape
    """
    resp = api_client.get_purchase_order(NON_EXISTENT_UUID, admin_headers)
    body = resp.json()
    assert body.get("response_type") == "error"
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_duplicate_sku_error(api, admin_headers):
    """PRD §3.1: "Each product is created with a globally unique `sku` — a
    duplicate is rejected with `ERR_DUPLICATE_SKU` (HTTP 409)".

    Design: Corner/errors/duplicate_sku_error
    """
    get_success_data(api_client.create_product(create_product_payload(sku="P1"), admin_headers))
    resp = api_client.create_product(
        create_product_payload(sku="P1", description="dupe", case_pack_units=6,
                               case_cost_cents=600, unit_cost_cents=60,
                               weight_lbs_per_case=5),
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SKU, expected_status=409)


def test_duplicate_rate_week_error(api, admin_headers):
    """PRD §3.3: "Only one rate may exist per week; a second record for the
    same `week_start_date` is rejected with `ERR_DUPLICATE_RATE_WEEK` (HTTP 409)."

    Design: Corner/errors/duplicate_rate_week_error
    """
    get_success_data(api_client.create_fuel_surcharge_rate(
        create_fuel_surcharge_rate_payload(week_start_date="2026-05-25", doe_index_usd=3.75),
        admin_headers,
    ))
    resp = api_client.create_fuel_surcharge_rate(
        create_fuel_surcharge_rate_payload(week_start_date="2026-05-25", doe_index_usd=3.80),
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RATE_WEEK, expected_status=409)


def test_duplicate_jurisdiction_error(api, admin_headers):
    """PRD §3.3: "A `WholesaleAdmin` creates one tax-stamp supply per
    `jurisdiction_code` — a duplicate jurisdiction is rejected with
    `ERR_DUPLICATE_JURISDICTION` (HTTP 409)".

    Design: Corner/errors/duplicate_jurisdiction_error
    """
    setup_stamp_supply(jurisdiction="CA_NORTH")
    resp = api_client.create_tax_stamp_supply(
        create_tax_stamp_supply_payload(jurisdiction_code="CA_NORTH",
                                        stamp_rate_cents_per_pack=210,
                                        handling_fee_per_roll_cents=1600),
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_JURISDICTION, expected_status=409)


def test_missing_required_field_error(api, admin_headers):
    """PRD §2.1: "A request whose body is malformed, omits a required field, or
    supplies a value of the wrong type is rejected with `ERR_VALIDATION`
    (HTTP 400)."

    Design: Corner/validations/missing_required_field_error
    """
    payload = {
        "description": "no sku",
        "case_pack_units": 12,
        "case_cost_cents": 1200,
        "unit_cost_cents": 110,
        "split_case_allowed": True,
        "is_tobacco": False,
        "weight_lbs_per_case": 10,
    }
    resp = api_client.create_product(payload, admin_headers)
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_split_case_not_allowed_error(api):
    """PRD §3.4: "a line with `split_units_qty` above zero is permitted only
    when the product's `split_case_allowed` flag is true, else
    `ERR_SPLIT_CASE_NOT_ALLOWED` (HTTP 422)".

    Design: Corner/validations/split_case_not_allowed_error
    """
    retailer, sm = setup_retailer()
    product = setup_product(sku="PNS", split_case_allowed=False)
    guide = setup_guide(retailer_id=retailer["id"],
                        lines=[{"product_id": product["id"], "par_cases": 0}])
    resp = api_client.create_purchase_order(
        create_purchase_order_payload(
            retailer_id=retailer["id"],
            order_guide_id=guide["id"],
            lines=[order_line(product["id"], cases_qty=0, split_units_qty=3)],
        ),
        sm,
    )
    validate_error(resp, ApiErrorId.ERR_SPLIT_CASE_NOT_ALLOWED, expected_status=422)


def test_product_not_on_guide_error(api):
    """PRD §3.4: "every ordered product must appear in the referenced `ACTIVE`
    guide's lines, else `ERR_PRODUCT_NOT_ON_GUIDE` (HTTP 422)".

    Design: Corner/validations/product_not_on_guide_error
    """
    retailer, sm = setup_retailer()
    p1 = setup_product(sku="P1")
    p2 = setup_product(sku="P2", split_case_allowed=False)
    guide = setup_guide(retailer_id=retailer["id"],
                        lines=[{"product_id": p1["id"], "par_cases": 0}])
    resp = api_client.create_purchase_order(
        create_purchase_order_payload(
            retailer_id=retailer["id"],
            order_guide_id=guide["id"],
            lines=[order_line(p2["id"], cases_qty=1, split_units_qty=0)],
        ),
        sm,
    )
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_ON_GUIDE, expected_status=422)


def test_guide_day_mismatch_error(api, sales_rep_headers):
    """PRD §3.1: "The guide's `delivery_day` must equal the retailer's
    `delivery_day`; a mismatch is rejected with `ERR_GUIDE_DAY_MISMATCH`
    (HTTP 422)."

    Design: Corner/validations/guide_day_mismatch_error
    """
    retailer, _ = setup_retailer(delivery_day="MON")
    resp = api_client.create_order_guide(
        create_order_guide_payload(retailer_id=retailer["id"], delivery_day="TUE",
                                   cutoff_hours_before=24, lines=[]),
        sales_rep_headers,
    )
    validate_error(resp, ApiErrorId.ERR_GUIDE_DAY_MISMATCH, expected_status=422)
