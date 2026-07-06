"""Corner queue — entities section.

Coverage: required fields, not-found, computed-defaults, enum-invalid.
"""
from test_helpers import (
    validate_error, validate_success, api_client, ApiErrorId,
    NON_EXISTENT_UUID,
    make_store_manager_headers, make_store_clerk_headers,
)
from test_helpers.fixtures import set_clock


def test_create_customer_missing_email_returns_invalid_request():
    """PRD §2.1: "A customer is created by a clerk with an email (unique
    across the customer table) and a full_name; on creation the
    customer's store_credit_cents is initialised to zero."
    PRD §3.9: "Finally, malformed or missing required input fields raise
    ERR_INVALID_REQUEST at nineteenth priority."

    Design: Corner/entities/create_customer_missing_required_email_returns_invalid_request
    """
    resp = api_client.create_customer(
        {"full_name": "Missing Email"}, make_store_clerk_headers()
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_sku_non_existent_returns_not_found():
    """PRD §3.9: "Path-referenced resource existence is fourth, raising
    ERR_NOT_FOUND."

    Design: Corner/entities/get_sku_non_existent_returns_not_found
    """
    resp = api_client.get_sku(NON_EXISTENT_UUID, make_store_manager_headers())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_create_sku_initialises_computed_on_hand_reserved_and_is_clearance():
    """PRD §3.1: "On creation the server initialises on_hand_qty and
    reserved_qty to zero, sets is_clearance to false, and sets
    clearance_pct to zero."

    Design: Corner/entities/create_sku_computed_on_hand_qty_defaults_to_zero_input_ignored
    """
    resp = api_client.create_sku(
        {"sku_code": "COMP-01", "category": "DECOR", "unit_price_cents": 100},
        make_store_manager_headers(),
    )
    sku = validate_success(resp, expected_status=201)
    assert sku["on_hand_qty"] == 0, (
        f"Newly-created Sku on_hand_qty must default to 0; "
        f"got {sku['on_hand_qty']}"
    )
    assert sku["reserved_qty"] == 0, (
        f"Newly-created Sku reserved_qty must default to 0; "
        f"got {sku['reserved_qty']}"
    )
    assert sku["is_clearance"] is False, (
        f"Newly-created Sku is_clearance must default to false; "
        f"got {sku['is_clearance']}"
    )


def test_create_sku_invalid_category_enum_returns_invalid_request():
    """PRD §3.1: "A SKU is created with a business sku_code that is
    unique across the catalog, a category from the enumeration
    BALLOON_LATEX, BALLOON_FOIL, COSTUME, TABLEWARE, DECOR, PRINT_CUSTOM,
    HELIUM, and SEASONAL_HALLOWEEN, a unit_price_cents retail price in
    whole cents..."
    PRD §3.9: "Finally, malformed or missing required input fields raise
    ERR_INVALID_REQUEST at nineteenth priority."

    Design: Corner/entities/create_sku_invalid_enum_category_returns_invalid_request
    """
    resp = api_client.create_sku(
        {"sku_code": "BAD-01", "category": "SNACKS", "unit_price_cents": 100},
        make_store_manager_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
