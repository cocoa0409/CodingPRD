"""Corner queue B — Section 1: entities (creation, defaults, retrieval, not-found, validation)."""

from test_helpers import (
    api_client,
    validate_error,
    validate_paginated,
    get_success_data,
    is_valid_uuid,
    is_iso8601_timestamp,
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    make_driver_headers,
    create_customer_payload,
    create_tank_site_payload,
    create_tank_payload,
    create_driver_payload,
    create_route_payload,
    create_route_stop_payload,
    create_active_customer_with_installed_tank,
    create_customer,
    create_driver,
    create_route,
)


def test_customer_create_required_fields_and_defaults(api):
    """PRD §3.1: "New customers start in `PROSPECT` with `prepaid_balance_cents`, `outstanding_charge_cents`, and `halogen_violation_count` all at zero" and PRD §2.4: "The `id` is a server-minted UUID with no type prefix."

    Design: Corner/entities/customer_create_required_fields_and_defaults
    """
    resp = api_client.create_customer(
        create_customer_payload(legal_name="NewCo", epa_generator_id="EPAGEN000100",
                                 market_zone="COASTAL", credit_terms="NET30"),
        TEST_USERS["route_planner_headers"],
    )
    data = get_success_data(resp)
    assert resp.status_code == 201
    assert data["status"] == "PROSPECT"
    assert data["prepaid_balance_cents"] == 0
    assert data["outstanding_charge_cents"] == 0
    assert data["halogen_violation_count"] == 0
    assert data["version"] == 1
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])


def test_customer_get_by_id_returns_stored_data(api):
    """PRD §3.1: "A `RoutePlanner` onboards a generator by creating a `Customer` with its `legal_name`, its `epa_generator_id`..., its `market_zone`..., and its `credit_terms`."

    Design: Corner/entities/customer_get_by_id_returns_stored_data
    """
    created = get_success_data(api_client.create_customer(
        create_customer_payload(legal_name="Fetch Me", epa_generator_id="EPAGEN000101",
                                 market_zone="SOUTH", credit_terms="CHARGE_ONLY"),
        TEST_USERS["route_planner_headers"],
    ))
    got = get_success_data(api_client.get_customer(created["id"], TEST_USERS["route_planner_headers"]))
    assert got["legal_name"] == "Fetch Me"
    assert got["market_zone"] == "SOUTH"
    assert got["credit_terms"] == "CHARGE_ONLY"


def test_customer_get_nonexistent_returns_404(api):
    """PRD §2.5: "The request is rejected immediately with the 404 error corresponding to the first path identifier that does not resolve to an existing resource" and the per-resource catalog names `ERR_CUSTOMER_NOT_FOUND`.

    Design: Corner/entities/customer_get_nonexistent_returns_404
    """
    resp = api_client.get_customer(NON_EXISTENT_UUID, TEST_USERS["route_planner_headers"])
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_FOUND)


def test_customer_create_missing_required_field_returns_400(api):
    """PRD §2.5: "Independently of existence, a malformed request body or a missing required field is rejected with `ERR_INVALID_REQUEST` (HTTP 400)".

    Design: Corner/entities/customer_create_missing_required_field_returns_400
    """
    resp = api_client.create_customer(
        {"epa_generator_id": "EPAGEN000102", "market_zone": "NORTH", "credit_terms": "NET30"},
        TEST_USERS["route_planner_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_customer_create_invalid_enum_returns_400(api):
    """PRD §2.5: "a value supplied for an enum-typed field that is not a member of the field's declared set is rejected with `ERR_INVALID_ENUM` (HTTP 400)" and PRD §3.1: "its `market_zone` — one of `NORTH`, `SOUTH`, or `COASTAL`".

    Design: Corner/entities/customer_create_invalid_enum_returns_400
    """
    resp = api_client.create_customer(
        create_customer_payload(legal_name="BadEnum", epa_generator_id="EPAGEN000103",
                                 market_zone="CENTRAL", credit_terms="NET30"),
        TEST_USERS["route_planner_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)


def test_customer_computed_field_input_ignored(api):
    """PRD §3.1: "New customers start in `PROSPECT` with `prepaid_balance_cents`, `outstanding_charge_cents`, and `halogen_violation_count` all at zero."

    Design: Corner/entities/customer_computed_field_input_ignored
    """
    payload = create_customer_payload(legal_name="Hacker", epa_generator_id="EPAGEN000104",
                                       market_zone="NORTH", credit_terms="PREPAY")
    payload["prepaid_balance_cents"] = 99999  # client attempts to override computed field
    data = get_success_data(api_client.create_customer(payload, TEST_USERS["route_planner_headers"]))
    assert data["prepaid_balance_cents"] == 0


def test_tank_system_fields_input_ignored(api):
    """PRD §3.2: "New tanks begin with `ownership_status` `PENDING_INSTALL`, `quarantine_status` `CLEAR`, and `current_volume_gallons` zero".

    Design: Corner/entities/tank_system_fields_input_ignored
    """
    cust = create_customer(legal_name="SysT", epa_generator_id="EPAGEN000105")
    site = get_success_data(api_client.create_tank_site(
        create_tank_site_payload(cust["id"], site_address="1 Sys Rd"),
        TEST_USERS["route_planner_headers"],
    ))
    payload = create_tank_payload(site["id"], ownership="COMPANY_OWNED")
    payload["current_volume_gallons"] = 999  # attempt to override computed field
    tank = get_success_data(api_client.create_tank(payload, TEST_USERS["tank_installer_headers"]))
    assert tank["current_volume_gallons"] == 0
    assert tank["ownership_status"] == "PENDING_INSTALL"
    assert tank["quarantine_status"] == "CLEAR"


def test_route_stop_window_validation(api):
    """PRD §3.3: "a `scheduled_window_start` and `scheduled_window_end` in 24-hour local `HH:MM` form with the end strictly after the start, ... A duplicated sequence or an inverted window is rejected with `ERR_INVALID_STOP_WINDOW` (HTTP 400)".

    Design: Corner/entities/route_stop_window_validation
    """
    base = create_active_customer_with_installed_tank()
    driver = create_driver()
    route = create_route(driver["id"], scheduled_date="2026-08-05", route_code="WND")
    resp = api_client.create_route_stop(
        route["id"],
        create_route_stop_payload(
            base["site"]["id"], base["tank"]["id"], route["version"],
            scheduled_window_start="10:00", scheduled_window_end="09:00",
        ),
        TEST_USERS["route_planner_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STOP_WINDOW)


def test_pagination_default_and_fields(api):
    """PRD §2.3: "The `limit` parameter caps the number of returned items; it defaults to 10... The `offset` parameter skips a number of items from the front of the result set and defaults to 0" and "Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/pagination_default_and_fields
    """
    for i in range(3):
        api_client.create_customer(
            create_customer_payload(legal_name=f"P{i+1}", epa_generator_id=f"EPAGEN0001{10+i}"),
            TEST_USERS["route_planner_headers"],
        )
    resp = api_client.list_customers(TEST_USERS["route_planner_headers"])
    data_list, meta = validate_paginated(resp)
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert len(data_list) == 3
