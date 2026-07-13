"""Configuration, registration, computed fields, listing, and immediate consistency."""
from test_helpers import (
    api_client,  # noqa: F401
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    TEST_USERS, make_passenger_headers,
    create_passenger_payload, create_fare_product_payload,
    create_inspection_payload, create_disruption_payload,
    assert_passenger, assert_fare_product, assert_inspection, sum_allocations,
    UNKNOWN_UUID,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["fareadmin_headers"]
CONDUCTOR = TEST_USERS["conductor_headers"]


def test_passenger_creation_returns_system_fields(api):
    """PRD 3.1: "A newly registered passenger starts with no reduced-fare category, a
    zero wallet balance, and a zero evasion count."
    PRD 2.4: "an integer `version` that begins at 1 on creation and increments by one on
    every mutation."

    Design: Corner/entities/passenger_creation_returns_system_fields
    """
    fx.set_clock(api)
    resp = api.create_passenger(create_passenger_payload(email="sys@x.com", full_name="Sys"), ADMIN)
    data = validate_success(resp, 201)
    assert_passenger(data)
    fetched = validate_success(api.get_passenger(data["id"], ADMIN), 200)
    assert fetched["version"] == 1, f"version must begin at 1, got {fetched['version']}"
    assert fetched["wallet_credit_cents"] == 0
    assert fetched["evasion_count"] == 0
    assert fetched["reduced_fare_category"] == "NONE"


def test_passenger_missing_required_field_returns_invalid_request(api):
    """PRD 2.7: "Structural validity of a request body — required fields present, enum
    fields carrying a permitted value, and integers within their declared ranges — is
    enforced with `ERR_INVALID_REQUEST` (HTTP 422) on every write."

    Design: Corner/entities/passenger_missing_required_field_returns_invalid_request
    """
    resp = api.create_passenger({"full_name": "NoEmail", "date_of_birth": "1990-01-01"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_ticket_not_found_returns_404(api):
    """PRD 2.6: "a missing ticket yields `ERR_TICKET_NOT_FOUND`"
    PRD 2.6: "All existence failures return HTTP 404."

    Design: Corner/entities/get_ticket_not_found_returns_404
    """
    resp = api.get_ticket(UNKNOWN_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_TICKET_NOT_FOUND.value)


def test_fare_product_apportionment_method_defaults_zone_count(api):
    """PRD 3.1: "That method is either `ZONE_COUNT` or `DISTANCE`, and when omitted it
    defaults to `ZONE_COUNT`."

    Design: Corner/entities/fare_product_apportionment_method_defaults_zone_count
    """
    payload = create_fare_product_payload()
    payload.pop("apportionment_method")
    data = validate_success(api.create_fare_product(payload, ADMIN), 201)
    assert_fare_product(data)
    assert data["apportionment_method"] == "ZONE_COUNT"


def test_inspection_evasion_result_computed_no_ticket(api):
    """PRD 3.5: "`EVASION` when no ticket is presented or the presented ticket is expired
    or otherwise not valid for the travel. For an evasion result the shortfall is fixed at
    the evasion fare estimate of 1000 cents."

    Design: Corner/entities/inspection_evasion_result_computed_no_ticket
    """
    fx.set_clock(api)
    pax = fx.create_passenger(api)
    data = validate_success(
        api.create_inspection(create_inspection_payload(pax["id"], 3), CONDUCTOR), 201
    )
    assert_inspection(data)
    assert data["result"] == "EVASION"
    assert data["fare_shortfall_cents"] == 1000


def test_disruption_severity_computed_major(api):
    """PRD 3.8: "a `severity` derived from it: `MINOR` for a delay under 30 minutes,
    `MAJOR` for a delay from 30 up to but not including 120 minutes, and `SEVERE` for a
    delay of 120 minutes or more."

    Design: Corner/entities/disruption_severity_computed_major
    """
    fx.set_clock(api)
    payload = create_disruption_payload(
        "S1", "2026-03-02T08:00:00Z", "2026-03-02T08:45:00Z",
        "2026-03-02T08:00:00Z", "2026-03-02T09:00:00Z",
    )
    data = validate_success(api.create_disruption(payload, ADMIN), 201)
    assert data["delay_minutes"] == 45
    assert data["severity"] == "MAJOR"


def test_purchase_response_includes_allocations_immediately(api):
    """PRD 3.3: "Every non-refunded ticket carries a `revenue_allocations` array of
    per-agency shares, each entry pairing an `agency_id` and `agency_code` with an
    `amount_cents`, whose sum equals the purchase price."

    Design: Corner/consistency_model/purchase_response_includes_allocations_immediately
    """
    fx.set_clock(api)
    fx.create_agencies_abc(api)
    fp = fx.create_fare_product(api)
    pax = fx.create_passenger(api)
    data = validate_success(
        api.create_ticket(
            {"passenger_id": pax["id"], "fare_product_id": fp["id"], "travel_period": "PEAK"},
            make_passenger_headers(pax["id"]),
        ),
        201,
    )
    assert data["purchase_price_cents"] == 1300
    assert data["status"] == "PURCHASED"
    assert sum_allocations(data) == 1300


def test_list_tickets_by_passenger_paginated(api):
    """PRD 2.3: "Each list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope, where `total_count` is the total
    number of matching records before pagination and `has_more` indicates whether records
    remain beyond the current page."

    Design: Corner/endpoints/list_tickets_by_passenger_paginated
    """
    fx.set_clock(api)
    fp = fx.create_fare_product(api)
    pax = fx.create_passenger(api)
    fx.purchase_ticket(api, pax["id"], fp["id"], "PEAK")
    fx.purchase_ticket(api, pax["id"], fp["id"], "OFF_PEAK")
    data, meta = validate_paginated(api.list_tickets(ADMIN, params={"passenger_id": pax["id"]}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert all(t["passenger_id"] == pax["id"] for t in data)
