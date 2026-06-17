"""Entity creation, defaults, computed fields, not-found, and listing.

Translates queue B (Corner) instances under sections `entities` and
`consistency_model`.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
    create_account_payload, create_site_payload, create_contract_payload,
    create_plan_payload,
    assert_contract, assert_site,
    fixtures,
)
from test_helpers.test_users import TEST_USERS

AM = TEST_USERS["account_manager_headers"]


def _make_account_and_site(api):
    acct = get_success_data(api.create_account(create_account_payload(), AM))
    site = get_success_data(api.create_site(create_site_payload(acct["id"]), AM))
    return acct, site


def test_create_contract_returns_201_with_reconciled_ledger(api):
    """PRD §3.2: "On creation, the contract's `status` is `DRAFT`, its
    `committed_cents` is 0, and its `budget_remaining_cents` equals
    `annual_budget_cents`."
    PRD §2.4: "version (integer): a system-managed counter that begins at its
    initial value and increments by one with each modification to the resource."

    Design: Corner/entities/create_contract_returns_201_with_all_fields
    """
    acct, site = _make_account_and_site(api)
    resp = api.create_contract(
        create_contract_payload(acct["id"], site["id"], annual_budget_cents=5000000), AM
    )
    data = validate_success(resp, expected_status=201)
    assert_contract(data)
    assert data["status"] == "DRAFT"
    assert data["committed_cents"] == 0
    assert data["budget_remaining_cents"] == 5000000
    assert data["version"] == 1


def test_get_contract_not_found_returns_404(api):
    """PRD §2.5: "Each resource type has its own not-found code: ... `ERR_CONTRACT_NOT_FOUND`
    for a contract ...".

    Design: Corner/entities/get_contract_not_found_returns_404
    """
    get_success_data(api.create_account(create_account_payload(), AM))
    resp = api.get_contract(NON_EXISTENT_UUID, AM)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_FOUND.value, expected_status=404)


def test_create_site_missing_turf_area_returns_invalid_request(api):
    """PRD §2.5: "required fields must be present and well-typed ... Any missing
    field, wrong type, invalid enum member, or out-of-range integer is rejected
    with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: "`turf_area_sqft` (the mowable turf area in square feet, which must
    be a positive integer greater than zero)".

    Design: Corner/entities/create_site_missing_turf_area_returns_invalid_request
    """
    acct = get_success_data(api.create_account(create_account_payload(), AM))
    payload = {"service_account_id": acct["id"], "name": "Plaza", "address": "1 Main"}
    resp = api.create_site(payload, AM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_create_site_zero_turf_area_returns_invalid_request(api):
    """PRD §3.1: "`turf_area_sqft` (the mowable turf area in square feet, which
    must be a positive integer greater than zero)".
    PRD §2.5: "Any missing field, wrong type, invalid enum member, or
    out-of-range integer is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_site_zero_turf_area_returns_invalid_request
    """
    acct = get_success_data(api.create_account(create_account_payload(), AM))
    resp = api.create_site(create_site_payload(acct["id"], turf_area_sqft=0), AM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_site_snow_zone_defaults_to_standard(api):
    """PRD §3.1: "The `snow_zone` is one of `PRIORITY`, `STANDARD`, or `EXEMPT`
    and defaults to `STANDARD` when omitted".

    Design: Corner/entities/site_snow_zone_defaults_to_standard
    """
    acct = get_success_data(api.create_account(create_account_payload(), AM))
    resp = api.create_site(create_site_payload(acct["id"]), AM)
    data = validate_success(resp, expected_status=201)
    assert data["snow_zone"] == "STANDARD"


def test_visit_estimated_charge_is_server_computed(api):
    """PRD §3.4: "its `estimated_charge_cents` is computed ... It is the sum of
    three terms, each rounded up to a whole cent *before* the terms are added
    together."

    Design: Corner/entities/visit_estimated_charge_is_computed_not_client_supplied
    """
    scenario = fixtures.setup_active_contract_scenario(
        turf_area_sqft=5000, base_rate_cents=10000, hourly_rate_cents=6000
    )
    resp = api.create_visit(
        {
            "service_plan_id": scenario["plan"]["id"],
            "route_schedule_id": scenario["route"]["id"],
            "slot_start_minute": 480,
            "slot_duration_minute": 90,
            "expected_service_contract_version": scenario["contract_version"],
            "estimated_charge_cents": 999999,  # client-sent value must be ignored
        },
        TEST_USERS["crew_lead_headers"],
    )
    data = validate_success(resp, expected_status=201)
    # area = ceil(10000*5000/1000)=50000; planned labor = ceil(6000*90/60)=9000
    assert data["estimated_charge_cents"] == 59000


def test_list_sites_filtered_by_account_paginated(api):
    """PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`,
    `total_count`, `has_more`) are included for list endpoints."
    PRD §3.1: "Sites may be listed and optionally filtered by `service_account_id`."

    Design: Corner/entities/list_sites_filtered_by_account_paginated
    """
    acct = get_success_data(api.create_account(create_account_payload(), AM))
    get_success_data(api.create_site(create_site_payload(acct["id"], name="S1", turf_area_sqft=5000), AM))
    get_success_data(api.create_site(create_site_payload(acct["id"], name="S2", address="2 Main", turf_area_sqft=6000), AM))
    resp = api.list_sites(AM, params={"service_account_id": acct["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_list_plans_by_contract_fk_reverse(api):
    """PRD §3.2: "Plans may be listed and filtered by `service_contract_id` or
    `site_id`."

    Design: Corner/entities/fk_reverse_list_plans_by_contract
    """
    acct, site = _make_account_and_site(api)
    contract = get_success_data(api.create_contract(create_contract_payload(acct["id"], site["id"]), AM))
    plan = get_success_data(api.create_plan(create_plan_payload(contract["id"]), AM))
    resp = api.list_plans(AM, params={"service_contract_id": contract["id"]})
    data, meta = validate_paginated(resp)
    assert any(p["id"] == plan["id"] for p in data), "listed plans must include the created plan"


def test_visit_estimate_visible_immediately_in_create_response(api):
    """PRD §3.4: "When scheduling succeeds, the visit is created as
    `SCHEDULED`/`UNBILLED`, its `estimated_charge_cents` is computed (see below)".

    Design: Corner/consistency_model/visit_estimate_visible_immediately_in_create_response
    """
    scenario = fixtures.setup_active_contract_scenario(
        turf_area_sqft=5000, base_rate_cents=10000, hourly_rate_cents=6000
    )
    resp = api.create_visit(
        {
            "service_plan_id": scenario["plan"]["id"],
            "route_schedule_id": scenario["route"]["id"],
            "slot_start_minute": 480,
            "slot_duration_minute": 90,
            "expected_service_contract_version": scenario["contract_version"],
        },
        TEST_USERS["crew_lead_headers"],
    )
    data = validate_success(resp, expected_status=201)
    assert data["estimated_charge_cents"] == 59000
