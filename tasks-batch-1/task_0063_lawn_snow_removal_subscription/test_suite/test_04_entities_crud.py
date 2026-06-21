"""Breadth tests: entity creation, defaults, constraints, listing, system fields.

Covers queue B section: entities.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    fixtures as fx,
)


def test_create_contract_returns_draft_defaults(api):
    """PRD §3.2: "A freshly created contract is born in `DRAFT` status with its provisional `accrued_balance_cents` running balance at zero."
    PRD §2.4: "a `version`, an integer that begins at its initial value and increments by one on every mutation of the resource."

    Design: Corner/entities/create_contract_returns_all_fields
    """
    cust = fx.make_customer(service_zip="20001")
    prop = fx.make_property(cust["id"], zip="20001")
    con = validate_success(
        api.create_contract(
            {"customer_id": cust["id"], "property_id": prop["id"], "season": "WINTER",
             "contract_price_cents": 12000, "term_months": 3},
            fx.make_customer_headers(cust["id"]),
        ),
        expected_status=201,
    )
    assert con["status"] == "DRAFT"
    assert con["accrued_balance_cents"] == 0
    assert con["version"] == 1


def test_get_contract_not_found(api):
    """PRD §2.7: "the platform validates their existence left to right, in the order they appear, and rejects the first one that does not resolve with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_contract_not_found
    """
    resp = api.get_contract(NON_EXISTENT_UUID, TEST_USERS["admin_headers"])
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_list_properties_paginated(api):
    """PRD §2.3: "Every paginated response includes `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope, where `total_count` is the total
    number of matching resources before pagination."
    PRD §3.1: "Properties can be listed and filtered by their owning `customer_id`."

    Design: Corner/entities/list_properties_paginated
    """
    cust = fx.make_customer(service_zip="20002")
    fx.make_property(cust["id"], zip="20002", address="A", lawn_area_sqft=1000)
    fx.make_property(cust["id"], zip="20002", address="B", lawn_area_sqft=2000)
    resp = api.list_properties(fx.make_customer_headers(cust["id"]),
                               params={"customer_id": cust["id"], "limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 2
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_preference_grass_height_out_of_range_rejected(api):
    """PRD §3.1: "records `grass_height_mm`, the requested cut height in millimetres for lawn visits, which must fall between 20 and 120 inclusive; a value outside that band is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/preference_grass_height_out_of_range_rejected
    """
    cust = fx.make_customer(service_zip="20003")
    prop = fx.make_property(cust["id"], zip="20003")
    resp = api.create_preference(
        {"property_id": prop["id"], "grass_height_mm": 10},
        fx.make_customer_headers(cust["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=422)


def test_preference_boolean_defaults_false(api):
    """PRD §3.1: "`fertilization_enabled` defaults to false ... `snow_opt_out` also
    defaults to false; when true, the property is held out of snow auto-dispatch even
    when a storm crosses the dispatch threshold for its region."

    Omitting both booleans yields false/false.

    Design: Corner/entities/preference_fertilization_default_false
    """
    cust = fx.make_customer(service_zip="20004")
    prop = fx.make_property(cust["id"], zip="20004")
    pref = validate_success(
        api.create_preference({"property_id": prop["id"], "grass_height_mm": 50},
                              fx.make_customer_headers(cust["id"])),
        expected_status=201,
    )
    assert pref["fertilization_enabled"] is False
    assert pref["snow_opt_out"] is False


def test_duplicate_customer_email_rejected(api):
    """PRD §3.1: "The `email` is the customer's login identity and must be unique and non-empty across all customers; an attempt to register a second customer with an existing email is rejected with `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/entities/duplicate_customer_email_rejected
    """
    api.create_customer({"email": "dup-unique@x.com", "full_name": "Dup",
                         "service_zip": "20005"}, TEST_USERS["admin_headers"])
    resp = api.create_customer({"email": "dup-unique@x.com", "full_name": "Dup2",
                                "service_zip": "20006"}, TEST_USERS["admin_headers"])
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE.value, expected_status=409)


def test_equipment_system_fields_minted_by_server(api):
    """PRD §3.3: "New equipment is created `IDLE` with a `wear_score` of zero."
    PRD §2.4: "a `version`, an integer that begins at its initial value and increments by
    one on every mutation of the resource."

    The server mints wear_score == 0, status == IDLE, version == 1 regardless of input.

    Design: Corner/entities/equipment_system_fields_ignored_on_input
    """
    route = fx.make_route(region_zip="20007")
    eq = validate_success(
        api.create_equipment(
            {"asset_tag": "EQ-SYS-UNIQUE", "equipment_type": "SPREADER", "age_months": 1,
             "assigned_route_id": route["id"]},
            TEST_USERS["dispatcher_headers"],
        ),
        expected_status=201,
    )
    assert eq["wear_score"] == 0
    assert eq["status"] == "IDLE"
    assert eq["version"] == 1
