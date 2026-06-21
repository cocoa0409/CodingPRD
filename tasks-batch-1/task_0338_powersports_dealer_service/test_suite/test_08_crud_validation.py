"""CRUD and input validation: unit creation contract, not-found, malformed-body
and uniqueness rejections, listing envelope, and the receive-into-stock guard.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    create_unit_payload, create_part_payload, TEST_USERS, NON_EXISTENT_UUID,
    create_unit,
)

SM = TEST_USERS["sales_manager_headers"]
PC = TEST_USERS["parts_clerk_headers"]


def test_create_unit_returns_201_with_system_fields(api):
    """PRD 3.1: "The acquisition_kind is one of NEW_FLOORED, TRADE_IN, or
    CASH_OWNED; when omitted it defaults to NEW_FLOORED. Newly created units begin
    life in the IN_TRANSIT inventory status."
    PRD 2.4: "version — an integer that starts at 1 when the resource is created
    and increases by exactly 1 on every mutation."

    Design: Corner/entities/create_unit_returns_201_with_system_fields
    """
    unit = validate_success(api.create_unit(
        {"vin": "1HD1KB4197YT00200", "category": "MOTORCYCLE", "model_year": 2024,
         "msrp_cents": 1_500_000, "dealer_cost_cents": 1_100_000}, SM), 201)
    assert unit["status"] == "IN_TRANSIT"
    assert unit["version"] == 1
    assert unit["acquisition_kind"] == "NEW_FLOORED"


def test_get_unit_not_found_returns_404(api):
    """PRD 2.7: "The first identifier that does not resolve to an existing resource
    produces that resource's specific not-found error — ERR_CUSTOMER_NOT_FOUND,
    ERR_UNIT_NOT_FOUND ... — each at HTTP 404, and no further validation runs."

    Design: Corner/entities/get_unit_not_found_returns_404
    """
    res = api.get_unit(NON_EXISTENT_UUID, SM)
    validate_error(res, "ERR_UNIT_NOT_FOUND")


def test_create_unit_missing_vin_returns_invalid_request(api):
    """PRD 2.8: "the platform check that the request body is well formed — required
    fields present, enum values in range, and integer fields within their stated
    constraints — rejecting violations with ERR_INVALID_REQUEST (HTTP 422)."

    Design: Corner/entities/create_unit_missing_required_vin_returns_invalid_request
    """
    res = api.create_unit(
        {"category": "MOTORCYCLE", "model_year": 2024,
         "msrp_cents": 1_500_000, "dealer_cost_cents": 1_100_000}, SM)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_unit_bad_vin_length_returns_invalid_request(api):
    """PRD 3.1: "The vin must be exactly 17 characters of uppercase alphanumerics
    and is unique across all units; a duplicate VIN is rejected with
    ERR_DUPLICATE_RESOURCE, and a VIN of any other length is a malformed body."

    Design: Corner/entities/create_unit_bad_vin_length_returns_invalid_request
    """
    res = api.create_unit(
        {"vin": "SHORTVIN", "category": "ATV", "model_year": 2024,
         "msrp_cents": 900_000, "dealer_cost_cents": 700_000}, SM)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_unit_invalid_category_returns_invalid_request(api):
    """PRD 3.1: "The category is one of MOTORCYCLE, ATV, UTV, PWC, or SNOWMOBILE."
    PRD 2.8: "the platform check that the request body is well formed — required
    fields present, enum values in range ... rejecting violations with
    ERR_INVALID_REQUEST (HTTP 422)."

    Design: Corner/entities/create_unit_invalid_category_enum_returns_invalid_request
    """
    res = api.create_unit(
        {"vin": "1HD1KB4197YT00201", "category": "SPACESHIP", "model_year": 2024,
         "msrp_cents": 900_000, "dealer_cost_cents": 700_000}, SM)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_duplicate_vin_returns_duplicate_resource(api):
    """PRD 3.1: "The vin must be exactly 17 characters of uppercase alphanumerics
    and is unique across all units; a duplicate VIN is rejected with
    ERR_DUPLICATE_RESOURCE."

    Design: Corner/entities/duplicate_vin_returns_duplicate_resource
    """
    validate_success(api.create_unit(
        {"vin": "1HD1KB4197YT00202", "category": "ATV", "model_year": 2024,
         "msrp_cents": 900_000, "dealer_cost_cents": 700_000}, SM), 201)
    res = api.create_unit(
        {"vin": "1HD1KB4197YT00202", "category": "UTV", "model_year": 2024,
         "msrp_cents": 1_000_000, "dealer_cost_cents": 800_000}, SM)
    validate_error(res, "ERR_DUPLICATE_RESOURCE")


def test_duplicate_part_sku_returns_duplicate_resource(api):
    """PRD 3.9: "The sku is unique, and a duplicate is rejected with
    ERR_DUPLICATE_RESOURCE."

    Design: Corner/entities/duplicate_part_sku_returns_duplicate_resource
    """
    validate_success(api.create_part(
        {"sku": "OIL-FILT", "description": "Oil filter",
         "unit_price_cents": 1200, "on_hand_qty": 5}, PC), 201)
    res = api.create_part(
        {"sku": "OIL-FILT", "description": "Oil filter v2",
         "unit_price_cents": 1300, "on_hand_qty": 8}, PC)
    validate_error(res, "ERR_DUPLICATE_RESOURCE")


def test_list_units_pagination_envelope(api):
    """PRD 2.3: "Paginated list responses include the following fields in the meta
    object of the response envelope: limit, offset, total_count, and has_more."

    Design: Corner/entities/list_units_pagination_envelope
    """
    create_unit(category="ATV")
    create_unit(category="ATV")
    data, meta = validate_paginated(api.list_units(SM))
    assert meta["total_count"] >= 2
    assert "has_more" in meta


def test_receive_already_in_stock_unit_returns_invalid_state(api):
    """PRD 3.1: "Receiving a unit advances it from IN_TRANSIT to IN_STOCK; this is
    the only manually triggered unit transition."
    PRD 2.8: "any transition attempted from a state that is not a legal predecessor
    is rejected, and where a more specific state error is not named for that
    transition the generic ERR_INVALID_STATE (HTTP 409) is returned."

    Design: Corner/state_machines/receive_already_in_stock_unit_returns_invalid_state
    """
    unit = create_unit(category="ATV")
    validate_success(api.receive_unit(unit["id"], SM), 200)
    res = api.receive_unit(unit["id"], SM)
    validate_error(res, "ERR_INVALID_STATE")
    unit_after = validate_success(api.get_unit(unit["id"], SM), 200)
    assert unit_after["status"] == "IN_STOCK"
