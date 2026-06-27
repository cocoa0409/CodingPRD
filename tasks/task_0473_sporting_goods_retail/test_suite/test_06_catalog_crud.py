"""Catalog/customer/inventory CRUD: creation, computed fields, defaults, required
fields, type constraints, uniqueness, and license immutability.

Corner queue: entities section.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_fishing_license,
    create_sku_payload,
    create_customer_payload,
    create_store_inventory_payload,
    create_store,
    create_customer,
    issue_fishing_license,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ASSOCIATE = TEST_USERS["store_associate_headers"]


def test_create_footwear_sku_computes_is_footwear(api):
    """PRD §3.1: "The `is_footwear` flag is computed, not accepted: it is true
    exactly when the SKU's `sport` is `FOOTWEAR`, and any client-supplied value is
    ignored. Every new SKU begins with `lifecycle` equal to `STANDARD` and
    `active_markdown_id` equal to null".

    Design: Corner/entities/create_sku_returns_201_with_computed_is_footwear
    """
    res = api.create_sku(
        create_sku_payload(sport="FOOTWEAR", name="Trail Shoe",
                           base_price_cents=9500, size_label="10D"),
        ADMIN,
    )
    sku = validate_success(res, 201)
    assert sku["is_footwear"] is True
    assert sku["lifecycle"] == "STANDARD"
    assert sku["active_markdown_id"] is None


def test_get_nonexistent_sku_returns_not_found(api):
    """PRD §2.9: "the first identifier that does not resolve to an existing resource
    causes the request to be rejected with `ERR_NOT_FOUND` before any later
    identifier is examined."

    Design: Corner/entities/get_sku_not_found_returns_404
    """
    res = api.get_sku(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_sku_missing_base_price_rejected(api):
    """PRD §2.10: "Next, request-body well-formedness — required fields present, enum
    values legal, integers within their declared ranges, and any `quantity` at least
    1 (`ERR_INVALID_REQUEST`)."
    PRD §3.1: "a display `name`, and a `base_price_cents` list price (which must be
    zero or greater)."

    Design: Corner/entities/create_sku_missing_required_field_returns_invalid_request
    """
    payload = create_sku_payload(sport="HOCKEY", name="No Price")
    del payload["base_price_cents"]
    res = api.create_sku(payload, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_create_sku_bad_sport_enum_rejected(api):
    """PRD §3.1: "A SKU is created with a `sport` — one of `HOCKEY`, `BASEBALL`,
    `FOOTWEAR`, `FISHING`, `TEAMWEAR`, or `APPAREL`".
    PRD §2.10: "Next, request-body well-formedness — required fields present, enum
    values legal, integers within their declared ranges, and any `quantity` at least
    1 (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/create_sku_bad_enum_sport_returns_invalid_request
    """
    res = api.create_sku(
        {"sport": "CHESS", "name": "Bad", "base_price_cents": 100}, ADMIN
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_create_customer_default_loyalty_fields(api):
    """PRD §3.1: "Every customer starts with `loyalty_points` of 0 and
    `loyalty_tier` of `BRONZE`."

    Design: Corner/entities/create_customer_default_loyalty_fields
    """
    res = api.create_customer(
        create_customer_payload(email="def@x.com", full_name="Def Cust",
                                home_state_code="CA"),
        ADMIN,
    )
    cust = validate_success(res, 201)
    assert cust["loyalty_points"] == 0
    assert cust["loyalty_tier"] == "BRONZE"


def test_create_customer_duplicate_email_rejected(api):
    """PRD §3.1: "A customer is registered with a unique `email` (uniqueness is
    case-insensitive; a duplicate is rejected with `ERR_DUPLICATE_EMAIL`)".

    Design: Corner/entities/create_customer_duplicate_email_returns_conflict
    """
    api.create_customer(
        create_customer_payload(email="dup@x.com", full_name="First",
                                home_state_code="CA"),
        ADMIN,
    )
    res = api.create_customer(
        create_customer_payload(email="DUP@x.com", full_name="Second",
                                home_state_code="NV"),
        ADMIN,
    )
    validate_error(res, "ERR_DUPLICATE_EMAIL", expected_status=409)


def test_duplicate_store_inventory_row_rejected(api):
    """PRD §2.5: "At most one stock row may exist for any given store-and-SKU pair;
    an attempt to create a second row for the same `store_id` and `sku_id` is
    rejected with `ERR_DUPLICATE_INVENTORY_ROW`."

    Design: Corner/entities/duplicate_store_inventory_row_returns_conflict
    """
    from test_helpers import create_sku
    store = create_store(state_code="CA")
    sku = create_sku(sport="HOCKEY", name="Skate", base_price_cents=12000, size_label="9D")
    api.create_store_inventory(create_store_inventory_payload(store["id"], sku["id"]), ADMIN)

    res = api.create_store_inventory(
        create_store_inventory_payload(store["id"], sku["id"]), ADMIN
    )
    validate_error(res, "ERR_DUPLICATE_INVENTORY_ROW", expected_status=409)


def test_fishing_license_has_no_version_field(api):
    """PRD §2.4: "a `FishingLicense` is immutable after issuance and therefore
    carries only `id` and `created_at`. It has neither an `updated_at` field nor a
    `version` field."

    Design: Corner/entities/fishing_license_immutable_no_version_field
    """
    store = create_store(state_code="CA")
    customer = create_customer(home_state_code="CA")
    license_ = issue_fishing_license(customer["id"], store["id"])

    res = api.get_fishing_license(license_["id"], ASSOCIATE)
    data = validate_success(res, 200)
    assert data["status"] == "ACTIVE"
    assert "version" not in data
    assert_fishing_license(data)
