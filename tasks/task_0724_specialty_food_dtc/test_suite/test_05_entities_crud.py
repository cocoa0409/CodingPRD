"""Customer and SKU creation, defaults, computed fields, and input validation.

Corner queue: entities section.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, is_valid_uuid,
    create_customer_payload, create_sku_payload,
    create_draft_sku, create_quarantine_lot, release_lot,
    make_customer_headers, TEST_USERS, ApiErrorId, NON_EXISTENT_UUID,
)

INV = TEST_USERS["inventory_manager_headers"]
COMP = TEST_USERS["compliance_officer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def test_create_customer_returns_201_with_defaults(api):
    """PRD §3.1: "A new account opens in ACTIVE status with a wallet_credit_cents balance of 0
    (store credit that is never allowed to go negative), a loyalty_points_balance of 0, and
    zeroed lifetime counters"

    Design: Corner/entities/customer_creation_returns_201_with_fields
    """
    res = api.create_customer(create_customer_payload(email="new@x.com", full_name="New Cust",
                                                      home_zone="Z1"), ADMIN)
    cust = validate_success(res, 201)
    assert cust["status"] == "ACTIVE"
    assert cust["wallet_credit_cents"] == 0
    assert cust["loyalty_points_balance"] == 0


def test_get_nonexistent_customer_returns_not_found(api):
    """PRD §2.10: "For any such path that embeds an identifier, the system validates that
    identifier's existence before returning the collection; a request scoped to a non-existent
    parent raises ERR_NOT_FOUND."
    PRD §2.9: "Next the system confirms that every resource named in the path or body exists"

    Design: Corner/entities/customer_get_nonexistent_returns_not_found
    """
    res = api.get_customer(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_create_customer_missing_home_zone_rejected(api):
    """PRD §3.1: "A customer account is opened by a PlatformAdmin or a CorporateBuyer who
    supplies the account email, the full_name, and a home_zone chosen from Z1, Z2, Z3, or Z4."
    PRD §2.9: "required body fields present and well-typed raises ERR_INVALID_REQUEST when violated"

    Design: Corner/entities/customer_create_missing_required_field_returns_invalid_request
    """
    payload = {"email": "x@x.com", "full_name": "X"}  # no home_zone
    res = api.create_customer(payload, ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_customer_invalid_zone_enum_rejected(api):
    """PRD §2.9: "and enum values within their declared domains — category, home_zone/ship_zone,
    tier, and cadence_days restricted to 14, 28, or 56 — raises ERR_INVALID_ENUM when violated."

    Design: Corner/entities/customer_create_invalid_zone_enum_returns_invalid_enum
    """
    res = api.create_customer(create_customer_payload(email="z9@x.com", full_name="Z9",
                                                      home_zone="Z9"), ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_ENUM.value)


def test_duplicate_customer_email_rejected(api):
    """PRD §3.1: "The email must be unique across all customers; a second registration of an
    existing address is rejected with ERR_DUPLICATE_EMAIL."

    Design: Corner/entities/customer_duplicate_email_rejected
    """
    get_success_data(api.create_customer(create_customer_payload(email="dup@x.com",
                                         full_name="First", home_zone="Z1"), ADMIN))
    res = api.create_customer(create_customer_payload(email="dup@x.com", full_name="Second",
                                                      home_zone="Z2"), ADMIN)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_EMAIL.value)


def test_sku_opens_draft_with_label_unapproved(api):
    """PRD §3.2: "A new SKU opens in DRAFT status with label_approved false, available_units 0,
    and reserved_units 0."

    Design: Corner/entities/sku_system_fields_generated_input_ignored
    """
    res = api.create_sku(create_sku_payload(name="Sys Sauce", category="HOT_SAUCE",
                                            storage_class="AMBIENT", unit_price_cents=1000), INV)
    sku = validate_success(res, 201)
    assert sku["status"] == "DRAFT"
    assert sku["label_approved"] is False
    assert is_valid_uuid(sku["id"])


def test_sku_default_allergens_empty(api):
    """PRD §3.2: "and an optional allergens array drawn from the token set MILK, EGG, FISH,
    SHELLFISH, TREE_NUT, PEANUT, WHEAT, SOY, and SESAME. A new SKU opens in DRAFT status with
    label_approved false, available_units 0, and reserved_units 0."

    Design: Corner/entities/sku_default_allergens_empty
    """
    res = api.create_sku(create_sku_payload(name="Plain Coffee", category="COFFEE",
                                            storage_class="AMBIENT", unit_price_cents=2000), INV)
    sku = validate_success(res, 201)
    assert sku["allergens"] == []


def test_sku_available_units_computed_from_released_lots(api):
    """PRD §2.6: "A SKU's available_units is always the sum of remaining_units over that SKU's
    lots that are in RELEASED status and whose expiry has not passed, minus that SKU's
    reserved_units"
    PRD §3.2: "release sets remaining_units equal to produced_units and recomputes the parent
    SKU's available_units."

    Design: Corner/entities/sku_available_units_computed_from_released_lots
    """
    sku = create_draft_sku(name="Avail Sauce", category="HOT_SAUCE",
                           storage_class="AMBIENT", unit_price_cents=1000)
    get_success_data(api.approve_label(sku["id"], COMP))
    lot = create_quarantine_lot(sku["id"], produced_units=7)
    release_lot(lot)
    sku_after = validate_success(api.get_sku(sku["id"], INV), 200)
    assert sku_after["available_units"] == 7
