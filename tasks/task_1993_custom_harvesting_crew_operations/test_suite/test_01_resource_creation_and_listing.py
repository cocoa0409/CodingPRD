"""Resource creation defaults, required-field rejection, not-found errors,
listing envelopes, pagination defaults, filtering, and read-after-write
visibility."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_customer_contract,
    assert_crew_member,
    assert_harvest_season,
    assert_machine,
    create_contract,
    create_crew_member_payload,
    create_machine_payload,
    create_season,
    create_season_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

TEST_LIAISON_HEADERS = TEST_USERS["grower_liaison_headers"]


def test_harvest_season_creation_returns_defaults(api, harvest_operator_headers):
    """PRD section 3.1: "A new season begins in `DRAFT` status."
    PRD section 3.1: "Both start at 0 and are recomputed by the system as
    contracts and stops change."

    Design: Corner/entities/harvest_season_creation_returns_defaults
    """
    resp = api.create_season(
        create_season_payload(
            season_year=2026,
            diesel_baseline_per_gallon_cents=300,
            current_diesel_per_gallon_cents=320,
        ),
        harvest_operator_headers,
    )
    season = validate_success(resp, 201)
    assert_harvest_season(season)
    assert season["status"] == "DRAFT", f"new season must be DRAFT, got {season['status']!r}"
    assert season["committed_acres_total"] == 0, (
        f"committed_acres_total must start at 0, got {season['committed_acres_total']!r}"
    )
    assert season["harvested_acres_total"] == 0, (
        f"harvested_acres_total must start at 0, got {season['harvested_acres_total']!r}"
    )


def test_harvest_season_missing_required_field_returns_invalid_request(
    api, harvest_operator_headers
):
    """PRD section 2.6: "Requests with a malformed body — a missing required
    field or a value of the wrong type — are rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/harvest_season_missing_required_field_returns_invalid_request
    """
    resp = api.create_season(
        {"diesel_baseline_per_gallon_cents": 300, "current_diesel_per_gallon_cents": 320},
        harvest_operator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_contract_not_found_returns_404(api, harvest_operator_headers):
    """PRD section 2.6: "A missing identifier yields the corresponding
    not-found error — `ERR_SEASON_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
    `ERR_STOP_NOT_FOUND`, `ERR_MACHINE_NOT_FOUND`, `ERR_CREW_NOT_FOUND`,
    `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`,
    `ERR_SETTLEMENT_NOT_FOUND`, `ERR_LODGING_SITE_NOT_FOUND`, or
    `ERR_RESERVATION_NOT_FOUND` — each with HTTP 404."

    Design: Corner/entities/contract_not_found_returns_404
    """
    resp = api.get_contract(NON_EXISTENT_UUID, harvest_operator_headers)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_FOUND)


def test_err_settlement_not_found(api, billing_clerk_headers):
    """PRD section 2.6: "A missing identifier yields the corresponding
    not-found error — `ERR_SEASON_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
    `ERR_STOP_NOT_FOUND`, `ERR_MACHINE_NOT_FOUND`, `ERR_CREW_NOT_FOUND`,
    `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`,
    `ERR_SETTLEMENT_NOT_FOUND`, `ERR_LODGING_SITE_NOT_FOUND`, or
    `ERR_RESERVATION_NOT_FOUND` — each with HTTP 404."

    Design: Corner/errors/err_settlement_not_found
    """
    resp = api.get_settlement(NON_EXISTENT_UUID, billing_clerk_headers)
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_FOUND)


def test_machine_creation_defaults_to_available(api, harvest_operator_headers):
    """PRD section 3.3: "Machines are born `AVAILABLE`."

    Design: Corner/entities/machine_creation_defaults_to_available
    """
    season = create_season()
    resp = api.create_machine(
        season["id"],
        create_machine_payload(machine_kind="COMBINE", label="C1", daily_capacity_acres=200),
        harvest_operator_headers,
    )
    machine = validate_success(resp, 201)
    assert_machine(machine)
    assert machine["status"] == "AVAILABLE", (
        f"new machine must be AVAILABLE, got {machine['status']!r}"
    )


def test_crew_member_default_requires_housing_true(api, harvest_operator_headers):
    """PRD section 3.3: "Seasonal labor is onboarded as **crew members** under
    the season, recording `full_name`, `visa_type` (one of `US_CITIZEN`,
    `H2A`, `TN`, `PERMANENT_RESIDENT`), `hourly_rate_cents`, and whether the
    operator must provide lodging (`requires_housing`, which defaults to true
    when not supplied)."

    Design: Corner/entities/crew_member_default_requires_housing_true
    """
    season = create_season()
    payload = create_crew_member_payload(
        full_name="X", visa_type="US_CITIZEN",
        visa_expiry_date="2099-01-01", hourly_rate_cents=2000,
    )
    assert "requires_housing" not in payload
    resp = api.create_crew_member(season["id"], payload, harvest_operator_headers)
    member = validate_success(resp, 201)
    assert_crew_member(member)
    assert member["requires_housing"] is True, (
        f"requires_housing must default to true, got {member['requires_housing']!r}"
    )


def test_route_stop_list_pagination_envelope(api, harvest_operator_headers):
    """PRD section 2.3: "The `meta` object of every list response includes the
    pagination fields `limit`, `offset`, `total_count`, and `has_more`."
    PRD section 2.2: "The `response_type` is either "object" for a single
    resource or "array" for a list of resources."

    Design: Corner/entities/route_stop_list_pagination_envelope
    """
    season = create_season()
    contract = create_contract(season["id"])
    resp = api.list_contract_route_stops(
        contract["id"], harvest_operator_headers, params={"limit": 10, "offset": 0}
    )
    body = resp.json()
    assert body.get("response_type") == "array", (
        f"list endpoint must return response_type 'array', got {body.get('response_type')!r}"
    )
    assert isinstance(body["meta"].get("api_request_id"), str), (
        "meta.api_request_id must be present on list responses"
    )
    data, meta = validate_paginated(resp)
    assert data == [], f"expected no stops yet, got {data!r}"
    assert meta["total_count"] == 0
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["has_more"] is False


def test_pagination_defaults_on_list_endpoints(api, harvest_operator_headers):
    """PRD section 2.3: "The `limit` parameter defaults to 10, with a minimum
    of 1 and a maximum of 100. The `offset` parameter defaults to 0."

    Design: Corner/cross_cutting_complexity_layers/pagination_defaults_on_list_endpoints
    """
    create_season()
    resp = api.list_seasons(harvest_operator_headers)
    data, meta = validate_paginated(resp)
    assert meta["limit"] == 10, f"default limit must be 10, got {meta['limit']!r}"
    assert meta["offset"] == 0, f"default offset must be 0, got {meta['offset']!r}"
    assert meta["total_count"] == 1, f"expected one season, got {meta['total_count']!r}"
    assert meta["has_more"] is False
    assert len(data) == 1


def test_immediate_visibility_of_created_contract(api, harvest_operator_headers):
    """PRD section 2.2: "Unless otherwise noted, operations that create or
    modify a resource will return the created or updated resource object in
    the data field."
    PRD section 3.2: "A new contract is `DRAFT`."

    Design: Corner/consistency_model/immediate_visibility_of_created_contract
    """
    season = create_season()
    resp = api.create_contract(
        season["id"],
        {
            "grower_name": "G", "state_code": "KS", "crop": "WHEAT",
            "rate_basis": "PER_ACRE", "rate_cents_per_acre": 3200,
            "rate_cents_per_bushel": 0, "committed_acres": 100,
        },
        TEST_LIAISON_HEADERS,
    )
    created = validate_success(resp, 201)
    assert created["status"] == "DRAFT"
    reread = validate_success(api.get_contract(created["id"], harvest_operator_headers))
    assert_customer_contract(reread)
    assert reread["grower_name"] == "G"
    assert reread["status"] == "DRAFT"


def test_contract_list_filter_by_season_id(api, harvest_operator_headers):
    """PRD section 4: "List contracts; filterable by `season_id` and
    `status`".

    Design: Corner/endpoints/contract_list_filter_by_season_id
    """
    s1 = create_season(season_year=2026)
    s2 = create_season(season_year=2027)
    create_contract(s1["id"], grower_name="A")
    create_contract(s2["id"], grower_name="B", state_code="NE", crop="CORN")
    resp = api.list_contracts(harvest_operator_headers, params={"season_id": s1["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"expected exactly one contract, got {meta['total_count']!r}"
    assert len(data) == 1
    assert all(c["season_id"] == s1["id"] for c in data), (
        "filtered list must contain only contracts of the requested season"
    )
