"""Customers, components, inbound lots, and their create-time constraints."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, is_valid_uuid,
    create_customer, create_component,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import RECEIVER, SCHEDULER
from test_helpers.constants import RANDOM_UUID


# ---------------------------------------------------------------------------
# Queue B — entities / create_customer_returns_201_with_system_fields
# ---------------------------------------------------------------------------

def test_create_customer_returns_201_with_system_fields(api):
    """PRD 2.4: "The `version` field is an integer that begins at its initial value on creation and increments by one on every mutation of the resource"
    PRD 3.1: "this flag defaults to false when omitted"

    Design: Corner/entities/create_customer_returns_201_with_system_fields
    """
    data = validate_success(
        api.create_customer({"name": "Acme Foods", "code": "ACME"}, RECEIVER),
        expected_status=201,
    )
    assert is_valid_uuid(data["id"]), f"id must be a bare UUID, got {data['id']!r}"
    assert data["version"] == 1, f"version must begin at 1, got {data['version']}"
    assert data["owns_components"] is False, (
        f"owns_components must default to false, got {data['owns_components']!r}"
    )


# ---------------------------------------------------------------------------
# Queue B — entities / component_customer_owned_computed_from_owner_flag
# ---------------------------------------------------------------------------

def test_component_customer_owned_computed_from_owner_flag(api):
    """PRD 3.1: "At the moment a component is created the system snapshots whether its owning customer currently has `owns_components` set to true and records the result on the component's `customer_owned` flag"

    Design: Corner/entities/component_customer_owned_computed_from_owner_flag
    """
    customer = create_customer(owns_components=True)
    data = validate_success(
        api.create_component(
            {"customer_id": customer["id"], "sku": "ALMOND",
             "name": "Almonds", "kind": "INGREDIENT"},
            RECEIVER,
        ),
        expected_status=201,
    )
    assert data["customer_owned"] is True, (
        "customer_owned must be computed true when the owner's "
        "owns_components is true at create time"
    )


# ---------------------------------------------------------------------------
# Queue B — entities / get_customer_nonexistent_returns_not_found
# ---------------------------------------------------------------------------

def test_get_nonexistent_customer_returns_not_found(api):
    """PRD 2.6: "the system validates the path identifiers left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource"

    Design: Corner/entities/get_customer_nonexistent_returns_not_found
    """
    resp = api.get_customer(RANDOM_UUID, RECEIVER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Queue B — entities / create_component_missing_required_kind_returns_invalid_request
# ---------------------------------------------------------------------------

def test_create_component_missing_kind_returns_invalid_request(api):
    """PRD 3.8: "Then comes request well-formedness on write endpoints — a present, JSON-parseable body carrying the required fields of the correct type, else `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_component_missing_required_kind_returns_invalid_request
    """
    customer = create_customer()
    resp = api.create_component(
        {"customer_id": customer["id"], "sku": "ALMOND", "name": "Almonds"},
        RECEIVER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# Queue B — entities / create_component_invalid_kind_enum_rejected
# ---------------------------------------------------------------------------

def test_create_component_invalid_kind_enum_rejected(api):
    """PRD 3.1: "a `kind` that classifies the component's role as one of `INGREDIENT`, `PACKAGING`, or `LABEL`. A value of `kind` outside that set is rejected with `ERR_INVALID_ENUM`."

    Design: Corner/entities/create_component_invalid_kind_enum_rejected
    """
    customer = create_customer()
    resp = api.create_component(
        {"customer_id": customer["id"], "sku": "WIDGET",
         "name": "Widget", "kind": "WIDGET"},
        RECEIVER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM.value)


# ---------------------------------------------------------------------------
# Queue B — entities / receive_lot_nonpositive_qty_rejected
# ---------------------------------------------------------------------------

def test_receive_lot_nonpositive_qty_rejected(api):
    """PRD 3.1: "the `received_qty` in the component's base units (which must be greater than zero, else `ERR_INVALID_QUANTITY`)"

    Design: Corner/entities/receive_lot_nonpositive_qty_rejected
    """
    customer = create_customer()
    comp = create_component(customer["id"], "ALMOND", "Almonds", "INGREDIENT")
    resp = api.receive_lot(
        comp["id"],
        {"supplier_lot_code": "ALM-0", "received_qty": 0,
         "expiration_date": "2026-12-31T00:00:00Z"},
        RECEIVER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_QUANTITY.value)


# ---------------------------------------------------------------------------
# Queue B — entities / recipe_fill_tolerance_out_of_range_rejected
# ---------------------------------------------------------------------------

def test_recipe_fill_tolerance_out_of_range_rejected(api):
    """PRD 3.2: "the fill_tolerance_pct ... which must be greater than zero and at most 50 ... A violation of any of these bounds is rejected with `ERR_INVALID_QUANTITY`."

    Design: Corner/entities/recipe_fill_tolerance_out_of_range_rejected
    """
    customer = create_customer()
    resp = api.create_recipe(
        {"customer_id": customer["id"], "name": "Granola",
         "target_fill_weight_g": 200, "fill_tolerance_pct": 60, "shelf_life_days": 90},
        SCHEDULER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_QUANTITY.value)


# ---------------------------------------------------------------------------
# Queue B — entities / duplicate_customer_code_rejected
# ---------------------------------------------------------------------------

def test_duplicate_customer_code_rejected(api):
    """PRD 3.1: "a short `code` — two to six uppercase alphanumeric characters that must be unique across all customers; a collision is rejected with `ERR_DUPLICATE_CODE`."

    Design: Corner/entities/duplicate_customer_code_rejected
    """
    create_customer(name="Acme One", code="ACME")
    resp = api.create_customer({"name": "Acme Two", "code": "ACME"}, RECEIVER)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CODE.value)


# ---------------------------------------------------------------------------
# Queue B — entities / duplicate_sku_within_customer_rejected
# ---------------------------------------------------------------------------

def test_duplicate_sku_within_customer_rejected(api):
    """PRD 3.1: "a `sku` that must be unique within that one customer ... but a repeat within the same `customer_id` is rejected with `ERR_DUPLICATE_SKU"

    Design: Corner/entities/duplicate_sku_within_customer_rejected
    """
    customer = create_customer()
    create_component(customer["id"], "ALMOND", "Almonds", "INGREDIENT")
    resp = api.create_component(
        {"customer_id": customer["id"], "sku": "ALMOND",
         "name": "Almonds 2", "kind": "INGREDIENT"},
        RECEIVER,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SKU.value)


# ---------------------------------------------------------------------------
# Queue B — entities / same_sku_different_customer_allowed
# ---------------------------------------------------------------------------

def test_same_sku_different_customer_allowed(api):
    """PRD 3.1: "the same SKU string may recur under a different customer"

    Design: Corner/entities/same_sku_different_customer_allowed
    """
    c1 = create_customer(name="Acme", code="ACME")
    c2 = create_customer(name="Beta", code="BETA")
    create_component(c1["id"], "ALMOND", "Almonds", "INGREDIENT")
    validate_success(
        api.create_component(
            {"customer_id": c2["id"], "sku": "ALMOND",
             "name": "Almonds", "kind": "INGREDIENT"},
            RECEIVER,
        ),
        expected_status=201,
    )


# ---------------------------------------------------------------------------
# Queue B — entities / create_lot_sets_remaining_equal_received
# ---------------------------------------------------------------------------

def test_create_lot_sets_remaining_equal_received(api):
    """PRD 3.1: "On receipt the lot's `remaining_qty` is set equal to its `received_qty`, the lot's `status` begins at `AVAILABLE"

    Design: Corner/entities/create_lot_sets_remaining_equal_received
    """
    customer = create_customer()
    comp = create_component(customer["id"], "ALMOND", "Almonds", "INGREDIENT")
    data = validate_success(
        api.receive_lot(
            comp["id"],
            {"supplier_lot_code": "ALM-1", "received_qty": 500,
             "expiration_date": "2026-12-31T00:00:00Z"},
            RECEIVER,
        ),
        expected_status=201,
    )
    assert float(data["remaining_qty"]) == 500.000, (
        f"remaining_qty must equal received_qty, got {data['remaining_qty']}"
    )
    assert data["status"] == "AVAILABLE", (
        f"a freshly received lot starts AVAILABLE, got {data['status']}"
    )
