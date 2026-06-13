"""Catalog, entity creation, defaults, computed fields, immutability, and auth.

Translates queue B (Corner) instances from sections `entities` and `errors`.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    assert_venue, assert_stand, assert_menu_item, assert_inventory_lot, assert_no_version_field,
    ApiErrorId, TEST_USERS, make_patron_headers,
    create_venue_payload, create_product_payload, create_event_payload, create_stand_payload,
    create_menu_item_payload, create_inventory_lot_payload, create_patron_payload,
    create_waste_record_payload,
    create_venue, create_product, setup_sellable_stand,
)
from test_helpers.fixtures import create_event_doors_open, create_lot

MANAGER = TEST_USERS["manager_headers"]
RUNNER = TEST_USERS["runner_headers"]
NON_EXISTENT_EVENT_ID = "00000000-0000-4000-8000-0000000000aa"
NON_EXISTENT_VENUE_ID = "00000000-0000-4000-8000-0000000000bb"


def test_create_venue_returns_201_with_contract_terms(api):
    """PRD §3.1: "A ConcessionsManager registers a venue with a display name
    (non-empty, at most 120 characters) and the commercial terms of the concession
    contract."
    PRD §2.4: "The version field is an integer that begins at the resource's
    creation and increments by one on each mutation".

    Design: Corner/entities/create_venue_returns_201_with_all_fields
    """
    resp = api.create_venue(create_venue_payload(name="Coliseum", venue_share_pct=15, service_fee_pct=5), MANAGER)
    data = validate_success(resp, 201)
    assert_venue(data)
    assert data["venue_share_pct"] == 15
    assert data["service_fee_pct"] == 5
    assert data["version"] == 1


def test_get_nonexistent_event_returns_not_found(api):
    """PRD §2.5: "the first identifier in the path that resolves to nothing
    produces ERR_NOT_FOUND for that resource."

    Design: Corner/entities/get_event_not_found_returns_404
    """
    resp = api.get_event(NON_EXISTENT_EVENT_ID, MANAGER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_create_product_missing_base_price_returns_invalid_request(api):
    """PRD §2.8: "body well-formedness (ERR_INVALID_REQUEST) catches malformed
    payloads: ... or any missing required field."
    PRD §3.1: "A product also has a non-empty display name, a base_price_cents
    (a whole-cent catalog price, zero or greater, before any event-day pricing)".

    Design: Corner/entities/create_product_missing_required_field_returns_invalid_request
    """
    venue = create_venue()
    payload = {"venue_id": venue["id"], "sku": "X", "name": "X", "unit_cost_cents": 10}
    resp = api.create_product(payload, MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_create_stand_applies_default_demand_tier_mid(api):
    """PRD §3.2: "demand_tier, one of LOW, MID, or HIGH (default MID), which
    drives the surge step in event-day pricing".
    PRD §3.2: "a stand also exposes computed fields: status, the operational enum
    (default CLOSED)".

    Design: Corner/entities/create_stand_applies_default_demand_tier_mid
    """
    venue = create_venue()
    event = api.create_event(create_event_payload(venue["id"]), MANAGER).json()["data"]
    payload = {"event_id": event["id"], "name": "S2", "expected_orders_per_hour": 40}
    data = validate_success(api.create_stand(payload, MANAGER), 201)
    assert_stand(data)
    assert data["demand_tier"] == "MID"
    assert data["status"] == "CLOSED"


def test_menu_item_price_is_server_computed_off_peak(api):
    """PRD §3.4: "The menu item's price_cents is computed at creation time".
    PRD §3.4: "a surge percentage is selected from the demand tier — 100 for a LOW
    stand, 115 for a MID stand, and 130 for a HIGH stand ... The raw price is then
    the product's base price multiplied by the event multiplier expressed as a
    fraction ... and again by the surge percentage expressed as a fraction".

    Soda base 400, mult 120, MID off-peak surge 115 -> round(400*1.20*1.15)=552.

    Design: Corner/entities/menu_item_price_computed_input_ignored
    """
    venue = create_venue()
    product = create_product(venue["id"], sku="SODA", name="Soda", base_price_cents=400, unit_cost_cents=50)
    base = create_event_doors_open(venue["id"], event_multiplier_pct=120)
    # create_event_doors_open makes a default MID stand.
    stand = base["stand"]
    data = validate_success(api.create_menu_item(create_menu_item_payload(stand["id"], product["id"]), MANAGER), 201)
    assert_menu_item(data)
    assert data["price_cents"] == 552, f"expected 552, got {data['price_cents']}"


def test_waste_record_is_immutable_no_version_field(api):
    """PRD §2.4: "A WasteRecord is immutable after creation: it carries only id
    and created_at, and it has neither an updated_at field nor a version field."

    Design: Corner/entities/waste_record_is_immutable_no_version_field
    """
    scenario = setup_sellable_stand(
        product_overrides={"sku": "BUN", "name": "Bun", "base_price_cents": 0,
                           "unit_cost_cents": 30, "perishable": True},
        lot_overrides={"received_qty": 50, "unit_cost_cents": 30, "par_level": 50, "reorder_point": 10},
    )
    resp = api.create_waste_record(
        create_waste_record_payload(scenario["stand"]["id"], scenario["product"]["id"], "SPILLAGE", 5), RUNNER
    )
    data = validate_success(resp, 201)
    assert data["cost_cents"] == 150
    assert_no_version_field(data)


def test_event_multiplier_above_range_returns_invalid_request(api):
    """PRD §3.2: "event_multiplier_pct, an integer event-day price multiplier
    expressed as a percentage ... that defaults to 100 and must be between 50 and
    300 inclusive."

    Design: Corner/entities/create_event_invalid_enum_multiplier_out_of_range
    """
    venue = create_venue()
    resp = api.create_event(create_event_payload(venue["id"], event_multiplier_pct=400), MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_event_end_before_doors_returns_invalid_request(api):
    """PRD §3.2: "both ISO 8601 UTC timestamps marking the start and end of the
    operating window, with end_time required to be strictly after doors_time."

    Design: Corner/entities/create_event_end_before_doors_returns_invalid_request
    """
    venue = create_venue()
    resp = api.create_event(
        create_event_payload(venue["id"], doors_time="2026-07-04T23:00:00.000Z",
                             end_time="2026-07-04T18:00:00.000Z"),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_lot_reorder_point_exceeds_par_returns_invalid_request(api):
    """PRD §3.5: "the reorder_point is the threshold at or below which
    replenishment is suggested, constrained so that it is between 0 and par_level
    inclusive — a reorder_point exceeding par_level is malformed."

    Design: Corner/entities/create_lot_reorder_point_exceeds_par_returns_invalid_request
    """
    venue = create_venue()
    product = create_product(venue["id"], sku="BUN", name="Bun", base_price_cents=0, unit_cost_cents=30, perishable=True)
    event = api.create_event(create_event_payload(venue["id"]), MANAGER).json()["data"]
    stand = api.create_stand(create_stand_payload(event["id"]), MANAGER).json()["data"]
    resp = api.create_inventory_lot(
        create_inventory_lot_payload(stand["id"], product["id"], received_qty=50,
                                     unit_cost_cents=30, par_level=50, reorder_point=80),
        RUNNER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_lot_remaining_qty_initialized_to_received_qty(api):
    """PRD §3.5: "The lot's remaining_qty is server-maintained: it is initialized
    to received_qty".
    PRD §3.5: "The lot's status begins at ACTIVE".

    Design: Corner/entities/lot_remaining_qty_initialized_to_received_qty
    """
    venue = create_venue()
    product = create_product(venue["id"], sku="BUN", name="Bun", base_price_cents=0, unit_cost_cents=30, perishable=True)
    event = api.create_event(create_event_payload(venue["id"]), MANAGER).json()["data"]
    stand = api.create_stand(create_stand_payload(event["id"]), MANAGER).json()["data"]
    data = validate_success(
        api.create_inventory_lot(
            create_inventory_lot_payload(stand["id"], product["id"], received_qty=100,
                                         unit_cost_cents=30, par_level=200, reorder_point=20),
            RUNNER,
        ),
        201,
    )
    assert_inventory_lot(data)
    assert data["remaining_qty"] == 100
    assert data["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# errors section (auth / forbidden / body well-formedness)
# ---------------------------------------------------------------------------
def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header is rejected with
    ERR_UNAUTHENTICATED."

    Design: Corner/errors/missing_auth_headers_returns_unauthenticated
    """
    resp = api.request_no_auth("GET", f"/concessions/venues/{NON_EXISTENT_VENUE_ID}")
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_patron_cannot_create_venue_forbidden_role(api):
    """PRD §2.1: "When both headers are present but the declared role is not
    permitted to invoke the requested endpoint, the request is rejected with
    ERR_FORBIDDEN_ROLE."

    Design: Corner/errors/patron_cannot_create_venue_forbidden_role
    """
    patron = validate_success(api.create_patron(create_patron_payload(display_name="PatX"), TEST_USERS["patron_headers"]), 201)
    resp = api.create_venue(create_venue_payload(name="Sneaky"), make_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_order_line_zero_qty_returns_invalid_request(api):
    """PRD §2.8: "body well-formedness (ERR_INVALID_REQUEST) catches malformed
    payloads: bad enum values, non-positive quantities".
    PRD §3.8: "A line names the menu_item_id and a qty greater than zero".

    Design: Corner/errors/invalid_request_negative_qty_on_line
    """
    scenario = setup_sellable_stand()
    patron = api.create_patron(create_patron_payload(display_name="Pat28"), TEST_USERS["patron_headers"]).json()["data"]
    ph = make_patron_headers(patron["id"])
    order = api.create_order(
        {"event_id": scenario["event"]["id"], "stand_id": scenario["stand"]["id"], "patron_id": patron["id"]}, ph
    ).json()["data"]
    resp = api.add_order_line(order["id"], {"menu_item_id": scenario["menu_item"]["id"], "qty": 0}, ph)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)
