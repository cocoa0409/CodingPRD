"""Resource creation, defaults, system-managed fields, not-found and
input-validation behavior for the core entities.

Covers Corner queue section entities.
"""
from prd_bench_local_runner.testing import validate_success, validate_error, is_valid_uuid
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, fixtures, factories,
    make_agency_coordinator_headers, NON_EXISTENT_UUID,
)

MGR = TEST_USERS["allocation_manager_headers"]
OP = TEST_USERS["food_bank_operator_headers"]


def test_create_cold_storage_unit_returns_201_with_computed_defaults(api):
    """PRD §3.1: "On creation its stored_lbs is initialized to 0 and its status to
    AVAILABLE; both are computed thereafter and never set directly by a client."
    PRD §2.4: "The id is a server-minted UUID with no type prefix."

    Design: Corner/entities/create_cold_storage_unit_returns_201_with_defaults
    """
    resp = api.create_cold_storage_unit(
        factories.create_cold_storage_unit_payload(
            name="Freezer A", temp_zone="FROZEN", capacity_lbs=1000),
        OP)
    unit = validate_success(resp, expected_status=201)
    assert unit["stored_lbs"] == 0.00, f"stored_lbs should init to 0, got {unit['stored_lbs']}"
    assert unit["status"] == "AVAILABLE", f"status should init AVAILABLE, got {unit['status']}"
    assert is_valid_uuid(unit["id"]), f"id must be a server-minted UUID, got {unit['id']!r}"


def test_get_inventory_lot_not_found_returns_404(api):
    """PRD §2.6: "the system validates each identifier left to right and rejects
    the request with ERR_NOT_FOUND at the first identifier in the path that does
    not resolve to an existing resource"

    Design: Corner/entities/get_inventory_lot_not_found_returns_404
    """
    resp = api.get_inventory_lot(NON_EXISTENT_UUID, OP)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_inventory_lot_missing_required_field_rejected(api):
    """PRD §3.1: "To intake an InventoryLot, a FoodBankOperator names the holding
    cold_storage_unit_id, the food_category, the source_type, the intake_lbs, and
    the expiration_date, and may optionally supply unit_cost_cents."
    PRD §5: error catalogue maps ERR_INVALID_REQUEST to 422.

    Design: Corner/entities/create_inventory_lot_missing_required_field_returns_invalid_request
    """
    unit = fixtures.create_cold_storage_unit(temp_zone="REFRIGERATED", capacity_lbs=5000)
    # omit intake_lbs
    resp = api.create_inventory_lot(
        {"cold_storage_unit_id": unit["id"], "food_category": "PRODUCE",
         "source_type": "DONATION", "expiration_date": "2026-07-01T00:00:00.000Z"},
        OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_inventory_lot_invalid_enum_food_category_rejected(api):
    """PRD §2.5: "Each InventoryLot carries a food_category — one of PRODUCE,
    DAIRY, FROZEN_MEAT, DRY_GOODS, or BAKERY"
    PRD §5: error catalogue maps ERR_INVALID_REQUEST to 422.

    Design: Corner/entities/create_inventory_lot_invalid_enum_food_category_rejected
    """
    unit = fixtures.create_cold_storage_unit(name="DryShelf", temp_zone="DRY", capacity_lbs=5000)
    resp = api.create_inventory_lot(
        {"cold_storage_unit_id": unit["id"], "food_category": "CANDY",
         "source_type": "DONATION", "intake_lbs": 10,
         "expiration_date": "2026-07-01T00:00:00.000Z"},
        OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_agency_fair_share_weight_and_status_defaults_applied(api):
    """PRD §3.2: "The fair_share_weight is a relative integer weight — higher means
    a larger slice of each cycle's pool — and defaults to 1, never falling below 1.
    The status is ACTIVE or SUSPENDED, defaulting to ACTIVE"

    Design: Corner/entities/agency_fair_share_weight_default_applied
    """
    resp = api.create_agency(
        {"name": "Pantry Default", "service_area": "County-X"}, MGR)
    agency = validate_success(resp, expected_status=201)
    assert agency["fair_share_weight"] == 1, \
        f"fair_share_weight defaults to 1, got {agency['fair_share_weight']}"
    assert agency["status"] == "ACTIVE", f"status defaults ACTIVE, got {agency['status']}"


def test_inventory_lot_system_fields_set_by_server(api):
    """PRD §3.1: "On a successful intake the lot's remaining_lbs is set equal to its
    intake_lbs, its disposition starts at AVAILABLE, and the holding unit's
    stored_lbs and status are recomputed."
    PRD §2.5: "produce and dairy require REFRIGERATED"

    Design: Corner/entities/inventory_lot_system_fields_input_ignored
    """
    unit = fixtures.create_cold_storage_unit(temp_zone="REFRIGERATED", capacity_lbs=5000)
    resp = api.create_inventory_lot(
        {"cold_storage_unit_id": unit["id"], "food_category": "DAIRY",
         "source_type": "PURCHASED", "intake_lbs": 250,
         "expiration_date": "2026-07-01T00:00:00.000Z", "unit_cost_cents": 90},
        OP)
    lot = validate_success(resp, expected_status=201)
    assert lot["remaining_lbs"] == 250.00, \
        f"remaining_lbs = intake_lbs 250, got {lot['remaining_lbs']}"
    assert lot["disposition"] == "AVAILABLE", f"disposition AVAILABLE, got {lot['disposition']}"
    assert lot["version"] == 1, f"version starts at 1, got {lot['version']}"
    assert lot["required_temp_zone"] == "REFRIGERATED", \
        f"DAIRY derives REFRIGERATED, got {lot['required_temp_zone']}"
