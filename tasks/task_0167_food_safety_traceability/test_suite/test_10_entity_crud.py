"""Entity creation, defaults, system fields, immutability, and not-found corners.

Queue B — Corner/entities.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_facility, create_supplier, create_ingredient,
    create_lot_payload, create_ingredient_payload, create_allergen_profile_payload,
    NON_EXISTENT_UUID, ApiErrorId,
    TEST_USERS,
)

QM = TEST_USERS["quality_manager_headers"]
CLERK = TEST_USERS["receiving_clerk_headers"]


def test_create_lot_returns_201_with_computed_fields():
    """PRD 3.2: "On receipt the lot's `status` is set to `RECEIVED`, its `available_qty`
    is initialized to the `received_qty`, and its `hold_status` is `FREE`."
    PRD 3.2: "The `coa_status` is set to `PENDING` when the originating supplier
    requires a certificate and the lot is raw material, and to `NOT_REQUIRED`
    otherwise."

    Design: Corner/entities/create_lot_returns_201_with_computed_fields
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    supplier = create_supplier(facility["id"], coa_required=False)
    ingredient = create_ingredient(facility["id"], storage_target_c=4,
                                   storage_tolerance_c=2, shelf_life_days=10,
                                   declared_allergen_codes=["MILK"])
    payload = create_lot_payload(facility["id"], ingredient["id"], "LC1",
                                 received_qty=25, supplier_id=supplier["id"])
    lot = validate_success(api_client.create_lot(payload, CLERK), 201)
    assert lot["available_qty"] == 25.0
    assert lot["status"] == "RECEIVED"
    assert lot["hold_status"] == "FREE"
    assert lot["coa_status"] == "NOT_REQUIRED"   # supplier coa_required=false


def test_get_lot_not_found_returns_404():
    """PRD 2.6: "the system validates them left to right and rejects on the first
    identifier that does not resolve to an existing resource, returning the not-found
    error appropriate to that position (`ERR_FACILITY_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
    `ERR_SUPPLIER_NOT_FOUND`, `ERR_COA_NOT_FOUND`, `ERR_RUN_NOT_FOUND`,
    `ERR_HOLD_NOT_FOUND`, `ERR_INGREDIENT_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`, or
    `ERR_BOOKING_NOT_FOUND`)."

    Design: Corner/entities/get_lot_not_found_returns_404
    """
    create_facility(initial_utc="2026-01-01T00:00:00Z")
    res = api_client.get_lot(NON_EXISTENT_UUID, QM)
    validate_error(res, ApiErrorId.ERR_LOT_NOT_FOUND.value)


def test_create_lot_missing_required_field_returns_invalid_request():
    """PRD 2.8: "Body well-formedness comes fourth: required body fields must be present
    and their types and enums valid — `received_qty` and `quantity` must be greater
    than zero, and `severity_rank` must lie within 1 through 5 — otherwise
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_lot_missing_required_field_returns_invalid_request
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    supplier = create_supplier(facility["id"], coa_required=False)
    ingredient = create_ingredient(facility["id"], storage_target_c=4, shelf_life_days=10)
    payload = create_lot_payload(facility["id"], ingredient["id"], "X",
                                 received_qty=5, supplier_id=supplier["id"])
    del payload["lot_code"]
    res = api_client.create_lot(payload, CLERK)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_ingredient_default_storage_tolerance_applied():
    """PRD 3.1: "the `storage_target_c` setpoint, optionally a `storage_tolerance_c`
    deviation (defaulting to 2 degrees), the `shelf_life_days` count"

    Design: Corner/entities/ingredient_default_storage_tolerance_applied
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    payload = create_ingredient_payload(facility["id"], storage_target_c=4,
                                        shelf_life_days=10)
    del payload["storage_tolerance_c"]
    ingredient = validate_success(api_client.create_ingredient(payload, QM), 201)
    assert ingredient["storage_tolerance_c"] == 2


def test_lot_status_system_minted_received_on_create():
    """PRD 3.2: "On receipt the lot's `status` is set to `RECEIVED`, its `available_qty`
    is initialized to the `received_qty`, and its `hold_status` is `FREE`."

    Design: Corner/entities/lot_id_system_minted_input_ignored
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    supplier = create_supplier(facility["id"], coa_required=False)
    ingredient = create_ingredient(facility["id"], storage_target_c=4, shelf_life_days=10)
    payload = create_lot_payload(facility["id"], ingredient["id"], "LX",
                                 received_qty=5, supplier_id=supplier["id"])
    payload["status"] = "RELEASED"   # client-supplied status must be ignored
    lot = validate_success(api_client.create_lot(payload, CLERK), 201)
    assert lot["status"] == "RECEIVED"


def test_allergen_profile_is_immutable_no_version():
    """PRD 2.4: "An `AllergenProfile` is immutable after creation and therefore carries
    only `id` and `created_at`; it has no `updated_at` field and no `version` field."

    Design: Corner/entities/allergen_profile_is_immutable_no_version
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    payload = create_allergen_profile_payload(facility["id"], "MILK", 4)
    ap = validate_success(api_client.create_allergen_profile(payload, QM), 201)
    assert ap["code"] == "MILK"
    assert "version" not in ap
    assert "updated_at" not in ap
