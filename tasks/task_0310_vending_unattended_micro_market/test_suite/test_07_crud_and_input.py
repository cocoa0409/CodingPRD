"""CRUD and input validation on the catalog and machine entities: creation
defaults, required/enum/uniqueness checks, not-found discipline (path and body
FK), the immutable Sale shape, and forced machine posture on creation.
"""
from test_helpers import (
    validate_success, validate_error, api_client, assert_host_site,
    assert_sale_immutable_shape, MISSING_UUID,
)
from test_helpers import (
    set_clock, make_host, make_product, make_machine, make_slot, make_driver,
    make_route, make_stop, dispatch, open_visit, reconcile, make_sale, counted_line,
)
from test_helpers.test_users import TEST_USERS

FIELD_OPS = TEST_USERS["field_ops_headers"]


# ─── Corner/entities/create_host_site_minimal_returns_201_with_defaults ────

def test_create_host_site_minimal_applies_defaults():
    """PRD §3.1: "The commission_model is one of FLAT or TIERED and defaults to
    FLAT".
    PRD §3.1: "The flat_commission_pct ... defaults to 0.10."
    PRD §3.1: "The monthly_guarantee_cents ... defaults to 0".
    PRD §3.1: "On creation the host's status is set to ACTIVE and its read-only
    lifetime_commission_cents is initialized to 0."
    PRD §2.4: "The version field is an integer that begins at its initial value on
    creation".

    Design: Corner/entities/create_host_site_minimal_returns_201_with_defaults
    """
    res = api_client.create_host_site({"name": "H1", "contact_email": "h1@x.com"}, FIELD_OPS)
    host = validate_success(res, 201)
    assert_host_site(host)
    assert host["commission_model"] == "FLAT", host
    assert host["flat_commission_pct"] == 0.10, host
    assert host["monthly_guarantee_cents"] == 0, host
    assert host["status"] == "ACTIVE", host
    assert host["lifetime_commission_cents"] == 0, host
    assert host["version"] == 1, host


# ─── Corner/entities/create_product_missing_required_field_rejected ────────

def test_create_product_missing_unit_cost_rejected():
    """PRD §2.8: "Malformed requests — a missing required field, a wrong type, or
    an unparseable body — are rejected with ERR_INVALID_REQUEST (HTTP 400)."

    unit_cost_cents has no default and is a required input (PRD §3.1).

    Design: Corner/entities/create_product_missing_required_field_rejected
    """
    res = api_client.create_product({"sku": "NOCOST", "name": "No Cost", "category": "SNACK"}, FIELD_OPS)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


# ─── Corner/entities/create_product_invalid_category_enum_rejected ─────────

def test_create_product_invalid_category_rejected():
    """PRD §2.8: "When an enum-typed field carries a value outside its declared
    set, the request is rejected with ERR_INVALID_ENUM (HTTP 422)."

    category must be one of BEVERAGE, SNACK, FRESH_FOOD (PRD §3.1).

    Design: Corner/entities/create_product_invalid_category_enum_rejected
    """
    res = api_client.create_product(
        {"sku": "BAD", "name": "Bad", "category": "CANDY", "unit_cost_cents": 30}, FIELD_OPS)
    validate_error(res, "ERR_INVALID_ENUM", expected_status=422)


# ─── Corner/entities/duplicate_product_sku_rejected ────────────────────────

def test_duplicate_product_sku_rejected():
    """PRD §2.8: "a Product's sku is unique across all products and a duplicate is
    rejected with ERR_DUPLICATE_SKU (HTTP 422)".

    Design: Corner/entities/duplicate_product_sku_rejected
    """
    validate_success(api_client.create_product(
        {"sku": "DUP", "name": "First", "category": "SNACK", "unit_cost_cents": 30}, FIELD_OPS), 201)
    res = api_client.create_product(
        {"sku": "DUP", "name": "Second", "category": "SNACK", "unit_cost_cents": 35}, FIELD_OPS)
    validate_error(res, "ERR_DUPLICATE_SKU", expected_status=422)


# ─── Corner/entities/duplicate_machine_asset_tag_rejected ──────────────────

def test_duplicate_machine_asset_tag_rejected():
    """PRD §2.8: "a Machine's asset_tag is unique across all machines and a
    duplicate is rejected with ERR_DUPLICATE_ASSET_TAG (HTTP 422)".

    Design: Corner/entities/duplicate_machine_asset_tag_rejected
    """
    host = make_host(name="Hd", contact_email="hd@x.com")
    validate_success(api_client.create_machine(
        {"host_site_id": host["id"], "asset_tag": "TAG1", "machine_type": "SNACK_VENDOR"}, FIELD_OPS), 201)
    res = api_client.create_machine(
        {"host_site_id": host["id"], "asset_tag": "TAG1", "machine_type": "BEVERAGE_VENDOR"}, FIELD_OPS)
    validate_error(res, "ERR_DUPLICATE_ASSET_TAG", expected_status=422)


# ─── Corner/entities/get_machine_nonexistent_returns_not_found ─────────────

def test_get_nonexistent_machine_returns_not_found():
    """PRD §2.6: "When a path contains a resource identifier, the system validates
    existence left-to-right and rejects the request at the first identifier that
    does not resolve, returning the not-found error specific to that resource type
    — ... ERR_MACHINE_NOT_FOUND ... each carrying HTTP 404."

    Design: Corner/entities/get_machine_nonexistent_returns_not_found
    """
    res = api_client.get_machine(MISSING_UUID, FIELD_OPS)
    validate_error(res, "ERR_MACHINE_NOT_FOUND", expected_status=404)


# ─── Corner/entities/create_machine_with_unknown_host_returns_host_not_found ─

def test_create_machine_unknown_host_returns_host_not_found():
    """PRD §2.6: "The same not-found discipline applies to body foreign keys on
    creation: when a POST payload references a machine_id, slot_id, product_id,
    host_site_id, route_id, driver_id, or route_stop_id that does not exist, the
    request is rejected with the corresponding not-found error."

    Design: Corner/entities/create_machine_with_unknown_host_returns_host_not_found
    """
    res = api_client.create_machine(
        {"host_site_id": MISSING_UUID, "asset_tag": "T2", "machine_type": "SNACK_VENDOR"}, FIELD_OPS)
    validate_error(res, "ERR_HOST_SITE_NOT_FOUND", expected_status=404)


# ─── Corner/entities/sale_is_immutable_event_no_version_field ──────────────

def test_sale_has_no_version_or_updated_at():
    """PRD §2.4: "A Sale is an immutable event record: it carries only id and
    created_at, and it has neither updated_at nor version."

    Design: Corner/entities/sale_is_immutable_event_no_version_field
    """
    set_clock("2026-06-20T00:00:00Z")
    host = make_host(name="Hi", contact_email="hi@x.com")
    prod = make_product(sku="IM", name="Imm", category="SNACK", unit_cost_cents=20)
    machine = make_machine(host["id"], asset_tag="IMT", machine_type="SNACK_VENDOR")
    slot = make_slot(machine["id"], prod["id"], slot_code="Z1",
                     capacity=10, par_level=10, price_cents=100)
    driver = make_driver(full_name="Imm Drv", employee_code="EMPI")
    route = make_route(driver["id"], "2026-06-20T00:00:00Z")
    stop = make_stop(route["id"], machine["id"])
    dispatch(route["id"])
    v0 = machine["version"]
    visit = open_visit(stop["id"], [counted_line(slot["id"], 0, 10)], v0, driver["id"])
    reconcile(visit["id"], v0, driver["id"])

    res = api_client.create_sale(
        {"machine_id": machine["id"], "slot_id": slot["id"], "quantity": 1, "payment_method": "CASHLESS"},
        FIELD_OPS)
    sale = validate_success(res, 201)
    assert "id" in sale and "created_at" in sale, sale
    assert_sale_immutable_shape(sale)


# ─── Corner/entities/computed_machine_posture_input_ignored_on_create ──────

def test_machine_posture_forced_on_create():
    """PRD §3.2: "A freshly placed machine has no slots, so its stock_status is
    STOCKOUT, its cash_status is CASH_OK, its service_status is IN_SERVICE, and
    its cash_on_hand_cents is 0."
    PRD §2.5: "A number of fields are read-only and computed; clients never set
    them directly".

    Design: Corner/entities/computed_machine_posture_input_ignored_on_create
    """
    host = make_host(name="Hc", contact_email="hc@x.com")
    # Even if a client tries to set posture fields, the server forces them.
    res = api_client.create_machine(
        {"host_site_id": host["id"], "asset_tag": "CT1", "machine_type": "SNACK_VENDOR",
         "stock_status": "STOCKED", "cash_on_hand_cents": 9999}, FIELD_OPS)
    machine = validate_success(res, 201)
    assert machine["stock_status"] == "STOCKOUT", machine
    assert machine["cash_on_hand_cents"] == 0, machine
    assert machine["cash_status"] == "CASH_OK", machine
    assert machine["service_status"] == "IN_SERVICE", machine
