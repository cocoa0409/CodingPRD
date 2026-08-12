"""Entity defaults and common-fields shape."""
import pytest

from test_helpers import (
    ADMIN,
    api_client,
    assert_order_line,
    create_product_payload,
    create_retailer_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    order_line,
    create_order_guide_payload,
    create_purchase_order_payload,
)
from test_helpers import SALES, setup_product, setup_retailer, setup_guide


def test_retailer_computed_defaults_on_create(api, admin_headers):
    """PRD §3.1: "New retailers begin with `credit_status` of `GOOD_STANDING`,
    an `ar_balance_cents` of zero, and an `exposure_forward_cents` of zero."
    PRD §2.5: "The `version` field is an integer that starts at creation and
    increments by one on every mutation of the resource".

    Design: Corner/entities/retailer_computed_defaults_on_create
    """
    resp = api_client.create_retailer(create_retailer_payload(), admin_headers)
    data = validate_success = get_success_data(resp)
    assert data["ar_balance_cents"] == 0
    assert data["exposure_forward_cents"] == 0
    assert data["credit_status"] == "GOOD_STANDING"
    assert data["version"] == 1


def test_product_system_fields_on_create(api, admin_headers):
    """PRD §2.5: "The `id` is a server-minted UUID with no type prefix."
    PRD §3.1: "A product's `status` is `ACTIVE`."
    PRD §2.5: "The `version` field is an integer that starts at creation".

    Design: Corner/entities/product_system_fields_on_create
    """
    resp = api_client.create_product(create_product_payload(sku="P1"), admin_headers)
    data = get_success_data(resp)
    assert is_valid_uuid(data["id"])
    assert data["version"] == 1
    assert data["status"] == "ACTIVE"
    assert is_iso8601_timestamp(data["created_at"])


def test_order_line_immutability_no_version(api):
    """PRD §2.5: "One exception applies: order lines are simple child records
    and carry only `id` and `created_at`. Both `updated_at` and `version` are
    absent from order lines."

    Design: Corner/entities/order_line_immutability_no_version
    """
    retailer, sm = setup_retailer()
    product = setup_product(sku="P1")
    guide = setup_guide(retailer_id=retailer["id"],
                        lines=[{"product_id": product["id"], "par_cases": 0}])
    order = get_success_data(api_client.create_purchase_order(
        create_purchase_order_payload(
            retailer_id=retailer["id"],
            order_guide_id=guide["id"],
            lines=[order_line(product["id"], cases_qty=1, split_units_qty=0)],
        ),
        sm,
    ))
    resp = api_client.list_order_lines(order["id"], ADMIN)
    data = get_success_data(resp)
    assert isinstance(data, list) and len(data) >= 1
    line0 = data[0]
    assert is_valid_uuid(line0["id"])
    assert "version" not in line0
    assert "updated_at" not in line0
    assert_order_line(line0)
