"""Entity-level claims: declared defaults, not-found routing, required fields,
server-minted identity, and zeroed computed totals on a fresh order."""
from test_helpers import (
    HEADERS_WITHOUT_ROLE,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_jurisdiction,
    assert_search_order,
    create_jurisdiction_payload,
    create_search_order_payload,
    is_valid_uuid,
    make_provider_admin_headers,
    make_title_agent_headers,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = make_provider_admin_headers()
AGENT = make_title_agent_headers("agent_1")


def test_jurisdiction_creation_applies_default_rush_capacity(api):
    """PRD 3.1: "A `ProviderAdmin` creates each jurisdiction with a unique `code`,
    a display `name`, a two-letter `state_code`, and an optional
    `rush_daily_capacity` governing how many rush orders the jurisdiction accepts
    per service date; the capacity defaults to 5 when omitted."
    PRD 3.1: "A jurisdiction is born `ACTIVE`, and only an `ACTIVE` jurisdiction
    accepts jurisdiction identification"

    Design: Corner/entities/jurisdiction_creation_applies_defaults
    """
    set_clock()
    response = api.create_jurisdiction(
        create_jurisdiction_payload(code="FL-DADE", name="Miami-Dade"),
        ADMIN,
    )
    jurisdiction = validate_success(response, 201)
    assert_jurisdiction(jurisdiction)
    assert jurisdiction["rush_daily_capacity"] == 5, (
        f"Default rush_daily_capacity must be 5, got {jurisdiction['rush_daily_capacity']}"
    )
    assert jurisdiction["status"] == "ACTIVE"


def test_get_missing_jurisdiction_returns_not_found(api):
    """PRD 2.8: "whether every referenced resource — path identifiers and body
    references alike, spanning jurisdictions, statutes, departments, associations,
    orders, tasks, estoppels, discrepancies, and deliveries — actually exists
    (`ERR_NOT_FOUND`)"

    Design: Corner/entities/get_missing_jurisdiction_returns_not_found
    """
    set_clock()
    response = api.get_jurisdiction(NON_EXISTENT_UUID, ADMIN)
    validate_error(response, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_order_without_parcel_number_rejected(api):
    """PRD 3.2: "A `TitleAgent` opens a search order by supplying the
    `property_address`, the assessor `parcel_number`, the scheduled `closing_date`,
    the `order_class` (`STANDARD` or `RUSH`)"

    Design: Corner/entities/create_order_missing_required_parcel_returns_invalid_request
    """
    set_clock()
    payload = create_search_order_payload("P-M1")
    del payload["parcel_number"]
    response = api.create_search_order(payload, AGENT)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_order_with_unknown_order_class_rejected(api):
    """PRD 3.2: "A `TitleAgent` opens a search order by supplying the
    `property_address`, the assessor `parcel_number`, the scheduled `closing_date`,
    the `order_class` (`STANDARD` or `RUSH`)"

    Design: Corner/entities/create_order_invalid_enum_returns_invalid_request
    """
    set_clock()
    response = api.create_search_order(
        create_search_order_payload("P-N1", order_class="EXPRESS"), AGENT
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_rush_order_without_service_date_rejected(api):
    """PRD 3.2: "A `RUSH` order must declare its `service_date` — the date its
    research slot is reserved — and a candidate `jurisdiction_id` at creation,
    both of which are required and whose absence is `ERR_INVALID_REQUEST`; a
    `STANDARD` order leaves both null."

    Design: Corner/entities/rush_order_missing_required_service_date_returns_invalid_request
    """
    set_clock()
    response = api.create_search_order(
        create_search_order_payload("P-S1", order_class="RUSH"), AGENT
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_server_mints_identity_fields_on_create(api):
    """PRD 2.5: "Every resource carries a server-minted `id` formatted as a bare
    UUID with no type prefix, a `created_at` timestamp in ISO 8601 UTC with three
    fractional digits recording when the server accepted the create, an
    `updated_at` timestamp of the same format refreshed on every mutation, and a
    `version` integer that increments by exactly 1 on every accepted mutation of
    that resource"

    Design: Corner/entities/system_fields_input_ignored
    """
    set_clock()
    forged_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    response = api.create_jurisdiction(
        create_jurisdiction_payload(
            code="FL-PIN", name="Pinellas", id=forged_id, version=99
        ),
        ADMIN,
    )
    jurisdiction = validate_success(response, 201)
    assert_jurisdiction(jurisdiction)
    assert jurisdiction["id"] != forged_id, (
        "Client-supplied id must be ignored; the server mints its own UUID"
    )
    assert is_valid_uuid(jurisdiction["id"])


def test_new_order_reports_zeroed_totals(api):
    """PRD 3.2: "The order is born in `INTAKE`, and its `title_agent_id` is copied
    from the caller's `X-User-ID`; the `jurisdiction_id` and `statute_id` remain
    null until jurisdiction identification."
    PRD 3.4: "`total_payoff_cents` is the sum of `unpaid_balance_cents` over the
    order's `COMPLETED` research tasks plus the sum of `payoff_amount_cents` over
    its `RECEIVED` estoppel orders — tasks in any other state and estoppels in any
    other state contribute zero."

    Design: Corner/entities/computed_totals_zero_at_creation
    """
    set_clock()
    response = api.create_search_order(
        create_search_order_payload("P-C2", property_address="2 C St"), AGENT
    )
    order = validate_success(response, 201)
    assert_search_order(order)
    assert order["status"] == "INTAKE"
    assert order["total_payoff_cents"] == 0
    assert order["total_fees_cents"] == 0
    assert order["pending_claims_cents"] == 0
    assert order["total_liability_cents"] == 0
