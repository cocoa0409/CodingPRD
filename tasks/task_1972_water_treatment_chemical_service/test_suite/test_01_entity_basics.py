"""Entity creation defaults, request shape, existence, and envelope claims."""
from datetime import datetime, timezone

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_account,
    assert_asset,
    create_account,
    create_asset,
    create_asset_payload,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

MANAGER = TEST_USERS["manager_headers"]
CHEMIST = TEST_USERS["chemist_headers"]
ADMIN = TEST_USERS["admin_headers"]


def test_account_create_applies_defaults(api):
    """PRD §3.1: "The `credit_hold` boolean — defaulting to `false` — is the
    fiscal gate". "The `billing_model` enum — `PRODUCT` or `SERVICE_CONTRACT`,
    defaulting to `PRODUCT` — selects which invoice pricing variant applies to
    the account". "New accounts are born `ACTIVE` with an `open_balance_cents`
    of zero".

    Design: Corner/entities/account_create_applies_defaults
    """
    created = validate_success(
        api_client.create_account({"account_name": "Defaults Co"}, MANAGER),
        expected_status=201,
    )
    fetched = validate_success(api_client.get_account(created["id"], MANAGER))
    assert_account(fetched)
    assert fetched["credit_hold"] is False
    assert fetched["billing_model"] == "PRODUCT"
    assert fetched["status"] == "ACTIVE"
    assert fetched["open_balance_cents"] == 0


def test_account_create_missing_required_field_returns_400(api):
    """PRD §2.6 tier 5: "The body must contain all required input fields with
    correct primitive types, and every enum value must be a member of its
    declared enum set; failure is `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/account_create_missing_required_field_returns_400
    """
    resp = api_client.create_account({}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert resp.status_code == 400


def test_asset_get_not_found_returns_404(api):
    """PRD §2.6 tier 4: "Every path identifier must resolve to an existing
    resource, validated left-to-right across path segments, and then every
    foreign-key-valued body field must resolve, validated in the body's
    declared input order; the first unresolvable reference yields
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/asset_get_not_found_returns_404
    """
    resp = api_client.get_asset(NON_EXISTENT_UUID, CHEMIST)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert resp.status_code == 404


def test_asset_invalid_enum_rejected(api):
    """PRD §2.6 tier 5: "The body must contain all required input fields with
    correct primitive types, and every enum value must be a member of its
    declared enum set; failure is `ERR_INVALID_REQUEST` (HTTP 400)." PRD §3.2:
    "the `asset_type` — one of `COOLING_TOWER`, `BOILER`, or `CLOSED_LOOP`".

    Design: Corner/entities/asset_invalid_enum_rejected
    """
    account = create_account(account_name="Enum Co")
    payload = create_asset_payload(account["id"], asset_type="GEYSER")
    resp = api_client.create_asset(payload, CHEMIST)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert resp.status_code == 400


def test_asset_tag_unique_per_account(api):
    """PRD §3.2: "a human `asset_tag` that must be unique within that account
    (for example, CT-1 or BLR-2)". PRD §2.6 tier 10: "`asset_tag` must be
    unique per account" (ERR_FIELD_CONSTRAINT, HTTP 422).

    Design: Corner/entities/asset_tag_unique_per_account
    """
    acct_a = create_account(account_name="U1")
    acct_b = create_account(account_name="U2")
    create_asset(acct_a["id"], asset_tag="CT-1", asset_type="BOILER")

    dup = api_client.create_asset(
        create_asset_payload(acct_a["id"], asset_tag="CT-1", asset_type="BOILER"),
        CHEMIST,
    )
    validate_error(dup, ApiErrorId.ERR_FIELD_CONSTRAINT)
    assert dup.status_code == 422

    # The same tag on a different account is outside the uniqueness scope.
    other = validate_success(
        api_client.create_asset(
            create_asset_payload(acct_b["id"], asset_tag="CT-1", asset_type="BOILER"),
            CHEMIST,
        ),
        expected_status=201,
    )
    assert_asset(other)
    assert other["asset_tag"] == "CT-1"


def test_system_fields_server_stamped(api):
    """PRD §2.5: "`id` — a server-minted UUID, with no type prefix, assigned at creation."
    PRD §2.5: "`created_at` — an ISO 8601 UTC timestamp with three fractional digits, fixed at creation."
    PRD §2.4: "Before any call has been made, the logical clock reads exactly
    `2026-08-01T00:00:00Z`, and it must not fall back to wall-clock time under
    any circumstance."

    Design: Corner/entities/system_fields_server_stamped_input_ignored
    """
    from test_helpers import set_clock

    set_clock("2026-08-01T00:00:00Z")
    created = validate_success(
        api_client.create_account({"account_name": "Stamp Co"}, MANAGER),
        expected_status=201,
    )
    assert is_valid_uuid(created["id"]), "id must be a server-minted UUID"
    stamped = datetime.fromisoformat(created["created_at"].replace("Z", "+00:00"))
    assert stamped == datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc), (
        f"created_at must be stamped from the logical clock, got {created['created_at']}"
    )
    assert isinstance(created["version"], int), "version must be an integer"


def test_pagination_defaults_and_envelope(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
    parameter skips that many items from the start of the result set and
    defaults to 0." "The `meta` object of every list response carries the four
    pagination fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/pagination_defaults_and_envelope
    """
    create_account(account_name="Page Co")
    resp = api_client.list_accounts(MANAGER)
    data, meta = validate_paginated(resp)
    assert isinstance(data, list) and len(data) == 1
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    body = resp.json()
    assert body["response_type"] == "array"
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)


def test_child_creation_with_bogus_parent_fk_returns_404(api):
    """PRD §2.6 tier 4: "Every path identifier must resolve to an existing
    resource, validated left-to-right across path segments, and then every
    foreign-key-valued body field must resolve, validated in the body's
    declared input order; the first unresolvable reference yields
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/child_creation_with_bogus_parent_fk_returns_404
    """
    payload = create_asset_payload(NON_EXISTENT_UUID, asset_tag="X", asset_type="BOILER")
    resp = api_client.create_asset(payload, CHEMIST)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert resp.status_code == 404


def test_fk_reverse_reachability_subresource_lists(api):
    """PRD §4: "| GET | `/wt/test-routes/{id}/stops` | List stops of a route | Any |"
    PRD §4: "| GET | `/wt/feed-stations/{id}/telemetry` | List telemetry readings of a station | Any |"
    PRD §4: "| GET | `/wt/racks/{id}/coupons` | List coupons of a rack | Any |"
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."

    Design: Corner/endpoints/fk_reverse_reachability_subresource_lists
    """
    from test_helpers import create_product, create_rack, create_station, create_test_route_payload

    account = create_account(account_name="FK Co")
    asset = create_asset(account["id"], asset_type="BOILER", recirculation_rate_gpm=100,
                         system_volume_gal=500)
    route = validate_success(
        api_client.create_test_route(create_test_route_payload(account["id"]), CHEMIST),
        expected_status=201,
    )
    product = create_product()
    station = create_station(asset["id"], product["id"])
    rack = create_rack(asset["id"], position_count=2)

    for resp in (
        api_client.list_route_stops(route["id"], CHEMIST),
        api_client.list_telemetry(station["id"], CHEMIST),
        api_client.list_coupons(rack["id"], CHEMIST),
    ):
        data, meta = validate_paginated(resp)
        assert data == [], f"expected empty child list, got {data}"
        assert meta["total_count"] == 0
        assert resp.json()["response_type"] == "array"
