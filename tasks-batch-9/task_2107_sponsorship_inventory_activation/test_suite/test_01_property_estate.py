"""The sellable estate: registering a property, its season envelope and its assets."""

from prd_bench_local_runner.testing import build_user_headers

from test_helpers import (
    ApiErrorId,
    CLOCK_DEFAULT,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_inventory_asset,
    assert_property,
    create_property_payload,
    is_valid_uuid,
    set_clock,
    setup_contract_scenario,
    validate_error,
    validate_success,
)


def test_property_registration_opens_in_planning_at_version_one(api):
    """PRD §3.1: "A freshly registered property opens in `PLANNING` with
    `committed_gross_value_cents` at 0, `delivered_media_value_cents` at 0 and
    `sellout_pct` at 0.00."
    PRD §2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC
    timestamp in the same format that is refreshed on every mutation, and
    `version`, an integer that is set to 1 when the resource is created and
    increases by exactly 1 on every mutation of that resource — including
    mutations the server performs on its own initiative when a cascade
    reconciles a derived field."
    PRD §2.4: "Every resource is addressed by an `id`, a server-minted UUID
    carrying no type prefix; wherever a URL contains an `id` path variable, that
    variable is the UUID of the resource at that position in the path."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    Design: Corner/entities/property_create_applies_system_defaults_and_version_one
    """
    set_clock(CLOCK_DEFAULT)

    response = api.create_property(
        create_property_payload(), TEST_USERS["property_admin_headers"]
    )
    data = validate_success(response, 201)

    assert_property(data)
    assert data["status"] == "PLANNING", (
        f"A new property opens in PLANNING, got {data['status']}"
    )
    assert data["committed_gross_value_cents"] == 0
    assert data["delivered_media_value_cents"] == 0
    assert data["sellout_pct"] == 0.00
    assert data["version"] == 1, (
        f"version is set to 1 when the resource is created, got {data['version']}"
    )
    assert is_valid_uuid(data["id"]), (
        f"the id must be a bare UUID with no type prefix, got {data['id']!r}"
    )

    body = response.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_property_registration_without_season_end_is_rejected(api):
    """PRD §3.1: "A `PropertyAdmin` registers one by supplying a `name` between
    1 and 120 characters, a `sport_code` drawn from `FOOTBALL`, `BASKETBALL`,
    `SOCCER`, `HOCKEY` and `BASEBALL`, a `season_year` between 2020 and 2100
    inclusive, the two instants `season_start` and `season_end` that bracket the
    season, and an `inventory_target_value_cents` of zero or more that states how
    much sellable value the season is expected to carry."
    PRD §2.8: "Request-body and query-parameter shape: required fields present,
    declared types, enum membership, numeric ranges, `measured_value` of zero for
    `PHOTO` evidence, `reject_reason` present when the decision is `REJECTED`, a
    season whose `season_end` is strictly after its `season_start`, and
    `limit`/`offset` inside their permitted ranges — `ERR_VALIDATION_FAILED`."

    Design: Corner/entities/property_create_missing_required_field_returns_422
    """
    set_clock(CLOCK_DEFAULT)

    payload = create_property_payload()
    payload.pop("season_end")
    payload.pop("seasonality_index")

    response = api.create_property(payload, TEST_USERS["property_admin_headers"])
    error = validate_error(response, ApiErrorId.ERR_VALIDATION_FAILED.value)

    assert response.status_code == 422
    assert response.json()["response_type"] == "error"
    assert isinstance(error["message"], str) and error["message"].strip()


def test_inventory_asset_optional_settings_take_their_declared_defaults(api):
    """PRD §3.3: "`changeover_buffer_minutes`, an integer from 0 to 240
    defaulting to 0, is the idle gap the property insists on between two
    non-intersecting occupations that belong to different contracts — the time it
    takes to strike one sponsor's dressing and hang the next."
    PRD §3.3: "`requires_staffing`, a boolean defaulting to false, marks assets
    that cannot be reported as delivered unless activation staff were physically
    present."
    PRD §3.3: "`min_staff_count`, an integer from 0 to 20 defaulting to 0, is how
    many of them had to be checked in."
    PRD §3.3: "The asset's own `status` may be supplied at creation and is one of
    `AVAILABLE`, `MAINTENANCE` or `RETIRED`, defaulting to `AVAILABLE`; only an
    `AVAILABLE` asset accepts new occupations. A new asset opens with
    `reserved_units_total` at 0."

    Design: Corner/entities/inventory_asset_optional_fields_take_declared_defaults
    """
    prop = validate_success(
        api.create_property(
            create_property_payload(), TEST_USERS["property_admin_headers"]
        ),
        201,
    )

    response = api.create_inventory_asset(
        prop["id"],
        {
            "name": "South Fascia Board",
            "asset_class": "SIGNAGE",
            "capacity_units": 3,
        },
        TEST_USERS["property_admin_headers"],
    )
    asset = validate_success(response, 201)

    assert_inventory_asset(asset)
    assert asset["changeover_buffer_minutes"] == 0
    assert asset["requires_staffing"] is False
    assert asset["min_staff_count"] == 0
    assert asset["status"] == "AVAILABLE"
    assert asset["reserved_units_total"] == 0


def test_reading_an_unknown_contract_id_returns_contract_not_found(api):
    """PRD §2.8: "Identifiers embedded in a URL are resolved strictly left to
    right, and the first identifier that fails to resolve determines the error."
    PRD §2.8: "The 404 vocabulary is `ERR_PROPERTY_NOT_FOUND`,
    `ERR_RATE_CARD_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
    `ERR_INVENTORY_ASSET_NOT_FOUND`, `ERR_SPONSOR_NOT_FOUND`,
    `ERR_ENTITLEMENT_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_PROOF_NOT_FOUND`,
    `ERR_STAFF_MEMBER_NOT_FOUND` and `ERR_ASSIGNMENT_NOT_FOUND`, each naming the
    kind of resource that could not be found."

    Design: Corner/entities/contract_get_unknown_id_not_found
    """
    set_clock(CLOCK_DEFAULT)

    response = api.get_contract(NON_EXISTENT_UUID, TEST_USERS["approver_headers"])
    validate_error(response, ApiErrorId.ERR_CONTRACT_NOT_FOUND.value)
    assert response.status_code == 404


def test_property_transition_skipping_selling_is_rejected(api):
    """PRD §3.1: "Any other requested move — a backwards step, a skip such as
    `PLANNING` straight to `IN_SEASON`, or a repeat of the state the property
    already holds — is rejected unconditionally with `ERR_INVALID_STATE`, and in
    that case no field is written and the property's `version` does not change."
    PRD §3.1: "Moving to `SELLING` requires that at least one of the property's
    rate cards has already reached `PUBLISHED`, since there is nothing to sell
    against otherwise; without one the request fails with
    `ERR_NO_PUBLISHED_RATE_CARD`."

    Design: Corner/state_machines/property_transition_skipping_selling_returns_invalid_state
    """
    admin = TEST_USERS["property_admin_headers"]
    prop = validate_success(api.create_property(create_property_payload(), admin), 201)
    version_before = prop["version"]

    forward_leap = api.transition_property(
        prop["id"], {"to_status": "IN_SEASON"}, admin
    )
    validate_error(forward_leap, ApiErrorId.ERR_INVALID_STATE.value)

    no_card = api.transition_property(prop["id"], {"to_status": "SELLING"}, admin)
    validate_error(no_card, ApiErrorId.ERR_NO_PUBLISHED_RATE_CARD.value)

    after = validate_success(api.get_property(prop["id"], admin))
    assert after["status"] == "PLANNING"
    assert after["version"] == version_before, (
        "a rejected transition writes no field and leaves version unchanged"
    )


def test_property_close_with_active_contract_returns_open_contracts(api):
    """PRD §3.1: "Moving to `CLOSED` requires that the property carries no
    contract whose `status` is `COUNTERSIGNED` or `ACTIVE`; if one remains, the
    request fails with `ERR_OPEN_CONTRACTS`."

    Design: Corner/state_machines/property_close_transition_with_active_contract_returns_open_contracts
    """
    scenario = setup_contract_scenario(
        stage="ACTIVE", contract_overrides={"exclusivity_scope": "CATEGORY"}
    )
    admin = TEST_USERS["property_admin_headers"]

    response = api.transition_property(
        scenario["property"]["id"], {"to_status": "CLOSED"}, admin
    )
    validate_error(response, ApiErrorId.ERR_OPEN_CONTRACTS.value)
    assert response.status_code == 409

    after = validate_success(api.get_property(scenario["property"]["id"], admin))
    assert after["status"] == "IN_SEASON"


def test_error_envelope_carries_error_id_and_message(api):
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/errors/error_envelope_carries_error_id_and_message
    """
    set_clock(CLOCK_DEFAULT)

    not_found = api.get_property(
        NON_EXISTENT_UUID, TEST_USERS["property_admin_headers"]
    )
    not_found_error = validate_error(
        not_found, ApiErrorId.ERR_PROPERTY_NOT_FOUND.value
    )

    bad_enum = api.create_sponsor(
        {
            "name": "Zephyr Cola",
            "category": "SPACECRAFT",
            "contact_email": "ops@zephyr.example",
        },
        TEST_USERS["seller_headers"],
    )
    bad_enum_error = validate_error(
        bad_enum, ApiErrorId.ERR_VALIDATION_FAILED.value
    )

    for response, error in ((not_found, not_found_error), (bad_enum, bad_enum_error)):
        body = response.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert isinstance(error["message"], str) and error["message"].strip(), (
            "the message provides a human-readable explanation"
        )


def test_unrecognized_role_header_is_unauthenticated_before_lookup(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of
    the six roles declared below, the request is rejected with
    `ERR_UNAUTHENTICATED` (401)."
    PRD §2.8: "1. Header presence and role validity — `ERR_UNAUTHENTICATED`."
    PRD §2.8: "3. Resolution of every identifier in the path, left to right — the
    matching 404."

    Design: Corner/rbac/unrecognized_role_header_returns_unauthenticated
    """
    set_clock(CLOCK_DEFAULT)

    stranger = build_user_headers("u-nobody", "MarketingIntern")
    response = api.get_property(NON_EXISTENT_UUID, stranger)

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert response.status_code == 401, (
        "role validity is checked before the path identifier is resolved, so an "
        f"unknown property id still yields 401, got {response.status_code}"
    )
    assert response.json()["response_type"] == "error"
