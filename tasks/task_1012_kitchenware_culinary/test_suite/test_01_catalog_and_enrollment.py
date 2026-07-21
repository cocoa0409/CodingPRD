"""Catalog creation and member enrollment — creation, defaults, system fields,
required-field and not-found handling."""
from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID,
    create_store_payload, create_sku_payload, create_member_payload,
    assert_store, assert_sku, assert_member,
    make_store,
)


def test_store_creation_defaults_open_and_version_one(api, admin_headers):
    """PRD §3.1: "A store is created with a display `name`, a `state_code` that fixes
    its tax jurisdiction — one of `CA`, `OR`, or `NY` — and an optional operational
    `status` that defaults to `OPEN` and may otherwise be `CLOSED`."
    PRD §2.4: "`version`: an integer that starts at 1 on creation and increments by one
    on every mutation."

    Design: Corner/entities/store_creation_success
    """
    res = api.create_store(create_store_payload(name="Corner Store", state_code="CA"), admin_headers)
    store = validate_success(res, 201)
    assert_store(store)
    assert store["status"] == "OPEN", "status must default to OPEN"
    assert store["version"] == 1, "version must start at 1 on creation"


def test_store_create_missing_state_code_rejected(api, admin_headers):
    """PRD §2.6: "Malformed bodies, missing required fields, and invalid enum or type
    values are rejected up front with `ERR_VALIDATION`."

    Design: Corner/entities/store_create_missing_required_field
    """
    payload = create_store_payload(name="No State")
    del payload["state_code"]
    res = api.create_store(payload, admin_headers)
    validate_error(res, "ERR_VALIDATION")


def test_get_nonexistent_member_returns_not_found(api, admin_headers):
    """PRD §2.6: "The first reference that resolves to nothing produces the corresponding
    not-found error: `ERR_STORE_NOT_FOUND`, `ERR_SKU_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
    `ERR_ORDER_NOT_FOUND`, `ERR_CLASS_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`,
    `ERR_SERVICE_TICKET_NOT_FOUND`, `ERR_RETURN_NOT_FOUND`, `ERR_SPECIAL_ORDER_NOT_FOUND`,
    `ERR_REGISTRY_NOT_FOUND`, or — when a return names a line that is absent from its
    order — `ERR_LINE_NOT_FOUND`."

    Design: Corner/entities/member_get_not_found
    """
    res = api.get_member(NON_EXISTENT_UUID, admin_headers)
    validate_error(res, "ERR_MEMBER_NOT_FOUND")


def test_sku_system_fields_server_set_on_create(api, admin_headers):
    """PRD §3.1: "On creation the reserved quantity begins at zero, the available quantity
    equals the on-hand quantity, and the catalog `status` defaults to `ACTIVE`, the
    alternative being `DISCONTINUED`."
    PRD §2.4: "`version`: an integer that starts at 1 on creation and increments by one
    on every mutation."

    Design: Corner/entities/sku_system_fields_generated
    """
    res = api.create_sku(create_sku_payload(name="Mandoline", category="KNIVES",
                                             list_price_cents=4000, on_hand_qty=12), admin_headers)
    sku = validate_success(res, 201)
    assert_sku(sku)
    assert sku["reserved_qty"] == 0, "reserved_qty must begin at zero"
    assert sku["available_qty"] == 12, "available_qty must equal on_hand_qty on create"
    assert sku["version"] == 1, "version must start at 1"


def test_member_enroll_sets_entry_defaults(api, admin_headers):
    """PRD §3.2: "Enrollment sets the member up at the entry tier: `tier` is `STANDARD`,
    `annual_spend_cents` is zero, `pending_points` is zero, `earned_points` is zero, and
    `wallet_credit_cents` is zero."

    Design: Corner/entities/member_enroll_defaults
    """
    store = make_store(state_code="OR")
    res = api.create_member(create_member_payload(store["id"], full_name="Enr Ollie"), admin_headers)
    member = validate_success(res, 201)
    assert_member(member)
    assert member["tier"] == "STANDARD"
    assert member["annual_spend_cents"] == 0
    assert member["pending_points"] == 0
    assert member["earned_points"] == 0
    assert member["wallet_credit_cents"] == 0
