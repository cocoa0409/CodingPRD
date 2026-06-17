"""Catalog entity CRUD: part creation defaults, required-field and type constraints,
duplicate SKU, core-charge consistency, not-found, listing/pagination, computed
inventory, vehicle year range, and immutable fitments.

Queue B: entities.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data, api_client,
    create_part_payload, create_vehicle_payload, create_fitment_payload,
    assert_part, assert_fitment,
    ApiErrorId, NONEXISTENT_UUID, TEST_USERS,
)

INV = TEST_USERS["inventory_manager_headers"]


# ─── entity_part_create_returns_201_with_computed_inventory_zeroed ────────────

def test_part_create_zeroes_inventory_and_defaults(api):
    """PRD §3.1: "On creation the three inventory counters on_hand_qty, reserved_qty,
    and available_qty all start at zero and the part's status starts at ACTIVE."
    PRD §3.1: "through core_charge_cents (defaulting to zero, meaning no core) and a
    boolean is_rebuildable flag (defaulting to false)".
    PRD §2.4: "version: an integer that begins at its initial value on creation and
    increments by one on every mutation of the resource."

    Design: Corner/entities/entity_part_create_returns_201_with_computed_inventory_zeroed
    """
    resp = api.create_part(create_part_payload(
        sku="BRK-1", description="Brake kit", list_price_cents=12000, cost_cents=5000), INV)
    part = validate_success(resp, 201)
    assert_part(part)
    assert part["on_hand_qty"] == 0 and part["reserved_qty"] == 0 and part["available_qty"] == 0
    assert part["status"] == "ACTIVE"
    assert part["version"] == 1
    assert part["core_charge_cents"] == 0
    assert part["is_rebuildable"] is False


# ─── entity_part_missing_required_list_price_returns_invalid_request ──────────

def test_part_missing_list_price_rejected(api):
    """PRD §2.8: "then request-body well-formedness - required fields present and
    correctly typed, enum members valid, and numeric fields within their declared
    ranges (ERR_INVALID_REQUEST, HTTP 422)".

    POST /parts omitting list_price_cents returns ERR_INVALID_REQUEST 422.

    Design: Corner/entities/entity_part_missing_required_list_price_returns_invalid_request
    """
    resp = api.create_part(
        {"sku": "BRK-2", "description": "Brake kit", "cost_cents": 5000}, INV)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ─── entity_part_duplicate_sku_returns_conflict ──────────────────────────────

def test_part_duplicate_sku_rejected(api):
    """PRD §3.1: "The manufacturer part number must be unique across all parts; a
    creation that repeats an existing sku is rejected with ERR_DUPLICATE_SKU."

    Design: Corner/entities/entity_part_duplicate_sku_returns_conflict
    """
    validate_success(api.create_part(create_part_payload(
        sku="DUP-1", description="First", list_price_cents=1000, cost_cents=400), INV), 201)
    resp = api.create_part(create_part_payload(
        sku="DUP-1", description="Second", list_price_cents=2000, cost_cents=800), INV)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SKU.value)


# ─── entity_part_core_charge_inconsistent_rebuildable_zero_core ───────────────

def test_part_rebuildable_with_zero_core_rejected(api):
    """PRD §3.1: "a rebuildable part must carry a positive core charge, and a
    non-rebuildable part must carry a core charge of exactly zero; any other
    combination is rejected with ERR_CORE_CHARGE_INCONSISTENT."

    Design: Corner/entities/entity_part_core_charge_inconsistent_rebuildable_zero_core
    """
    resp = api.create_part(create_part_payload(
        sku="REB-1", description="Reman", list_price_cents=15000, cost_cents=7000,
        core_charge_cents=0, is_rebuildable=True), INV)
    validate_error(resp, ApiErrorId.ERR_CORE_CHARGE_INCONSISTENT.value)


# ─── entity_part_not_found_on_get ────────────────────────────────────────────

def test_part_not_found(api):
    """PRD §2.7: "Each resource type has its own not-found error: ERR_PART_NOT_FOUND".
    PRD §2.7: "rejects the request at the first identifier that does not resolve."

    Design: Corner/entities/entity_part_not_found_on_get
    """
    resp = api.get_part(NONEXISTENT_UUID, INV)
    validate_error(resp, ApiErrorId.ERR_PART_NOT_FOUND.value)


# ─── entity_part_list_pagination_envelope ────────────────────────────────────

def test_part_list_pagination_envelope(api):
    """PRD §2.3: "when omitted it defaults to 10, with a minimum of 1 and a maximum
    of 100".
    PRD §2.3: "Every list response carries the pagination fields limit, offset,
    total_count, and has_more inside the meta object of the envelope."

    Design: Corner/entities/entity_part_list_pagination_envelope
    """
    validate_success(api.create_part(create_part_payload(
        sku="LST-1", description="P1", list_price_cents=1000, cost_cents=400), INV), 201)
    validate_success(api.create_part(create_part_payload(
        sku="LST-2", description="P2", list_price_cents=2000, cost_cents=800), INV), 201)
    data, meta = validate_paginated(api.list_parts(INV))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0


# ─── entity_part_computed_inventory_input_ignored ────────────────────────────

def test_part_computed_inventory_never_client_set(api):
    """PRD §2.6: "three quantity fields that the server maintains and the client
    never writes directly".
    PRD §3.1: "On creation the three inventory counters on_hand_qty, reserved_qty,
    and available_qty all start at zero".

    A created part always reports zero on hand, regardless of client input.

    Design: Corner/entities/entity_part_computed_inventory_input_ignored
    """
    resp = api.create_part(create_part_payload(
        sku="IGN-1", description="Ignore test", list_price_cents=3000, cost_cents=1000), INV)
    part = validate_success(resp, 201)
    assert part["on_hand_qty"] == 0, "computed on_hand_qty must start at 0"


# ─── entity_vehicle_year_out_of_range_rejected ───────────────────────────────

def test_vehicle_year_below_range_rejected(api):
    """PRD §3.1: "The model year must fall between 1900 and 2100 inclusive."
    PRD §2.8: "numeric fields within their declared ranges (ERR_INVALID_REQUEST, HTTP 422)".

    Design: Corner/entities/entity_vehicle_year_out_of_range_rejected
    """
    resp = api.create_vehicle(create_vehicle_payload(year=1800, make="FORD", model="MODEL-T"), INV)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ─── entity_fitment_immutable_no_version_field ───────────────────────────────

def test_fitment_immutable_reduced_field_set(api):
    """PRD §2.4: "A Fitment and a CrossReference each receive only an id (UUID) and a
    created_at; they have no updated_at and no version".
    PRD §3.1: "an optional position (one of FRONT, REAR, LEFT, RIGHT, or UNIVERSAL,
    defaulting to UNIVERSAL), and free-text notes (defaulting to empty)".

    Design: Corner/entities/entity_fitment_immutable_no_version_field
    """
    part = validate_success(api.create_part(create_part_payload(
        sku="FIT-1", description="Fit part", list_price_cents=1000, cost_cents=400), INV), 201)
    vehicle = validate_success(api.create_vehicle(
        create_vehicle_payload(year=2020, make="TOYOTA", model="CAMRY"), INV), 201)
    resp = api.create_fitment(create_fitment_payload(
        part["id"], vehicle["id"], position="FRONT"), INV)
    fitment = validate_success(resp, 201)
    assert_fitment(fitment)
    assert "version" not in fitment
    assert "updated_at" not in fitment
    assert fitment["position"] == "FRONT"
    assert fitment["notes"] == ""
