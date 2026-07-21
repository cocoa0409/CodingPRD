"""Membership and catalogue basics: hazmat derivation, not-found, enum validation."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, NON_EXISTENT_UUID,
    create_product_payload,
    make_product, assert_product,
    TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]


def test_battery_product_is_hazmat_and_kit_is_not(api):
    """PRD 2.7: "A product's `is_hazmat` flag is computed at creation and is
    true exactly when the product's `product_type` is `BATTERY`; for every
    other product type it is false."

    Design: Corner/entities/cn_product_is_hazmat_computed
    """
    bat = make_product(api, sku="BAT-CN", name="LiPo 2S",
                       product_type="BATTERY", price_cents=3000, stock_on_hand=5)
    kit = make_product(api, sku="KIT-CN", name="Glider",
                       product_type="KIT", price_cents=8000, stock_on_hand=5)
    assert_product(bat)
    assert_product(kit)
    assert bat["is_hazmat"] is True, "BATTERY product must have is_hazmat true"
    assert kit["is_hazmat"] is False, "KIT product must have is_hazmat false"


def test_get_nonexistent_customer_returns_not_found(api):
    """PRD 2.9: "the first identifier that does not resolve to an existing
    resource stops the request immediately with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/cn_customer_not_found_returns_404
    """
    resp = api.get_customer(NON_EXISTENT_UUID, STAFF)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_product_with_invalid_type_rejected(api):
    """PRD 3.2: "a `product_type` drawn from `KIT`, `RC_VEHICLE`, `PART`, or
    `BATTERY`".
    PRD 2.9: "Generic field-level validation — quantities and units at least 1,
    valid enum members, pagination bounds — is last, yielding `ERR_VALIDATION`."

    Design: Corner/entities/cn_product_bad_enum_type_returns_400
    """
    payload = create_product_payload(sku="X", name="X",
                                     product_type="SPACESHIP",
                                     price_cents=1000, stock_on_hand=1)
    resp = api.create_product(payload, STAFF)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)
