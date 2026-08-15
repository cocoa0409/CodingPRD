"""Master-data claims: terminal/product/customer/exchange-agreement creation,
defaults, envelope shape, existence, and server-minted system fields."""
from test_helpers import (
    ADMIN,
    EXCH,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_customer,
    assert_exchange_agreement,
    assert_terminal,
    create_customer,
    create_customer_payload,
    create_exchange_agreement_payload,
    create_product,
    create_product_payload,
    create_terminal,
    create_terminal_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_terminal_creation_defaults(api):
    """PRD §3.1: "A new terminal opens with `rack_status` of `OPEN`, zero
    `inventory_gallons`, and zero `daily_allocation_pool_gallons`."

    Design: Corner/entities/terminal_creation_with_required_fields_returns_201
    """
    set_clock()
    resp = api.create_terminal(
        create_terminal_payload(
            terminal_code="OKC-01", legal_name="OKC Terminal",
            state_code="OK", county_code="40109", city_code="OKC",
        ),
        ADMIN,
    )
    data = validate_success(resp, 201)
    assert_terminal(data)
    assert data["rack_status"] == "OPEN"
    assert data["inventory_gallons"] == 0
    assert data["daily_allocation_pool_gallons"] == 0
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])


def test_product_is_brandable_defaults_false(api):
    """PRD §3.1: "an optional `is_brandable` flag that defaults to false and
    governs whether branded additive injection may be sold against the
    product."

    Design: Corner/entities/product_is_brandable_default_false_when_omitted
    """
    set_clock()
    resp = api.create_product(
        {
            "product_code": "REG87",
            "display_name": "Regular",
            "product_family": "GASOLINE",
        },
        ADMIN,
    )
    data = validate_success(resp, 201)
    assert data["is_brandable"] is False


def test_customer_initial_state_good(api):
    """PRD §3.2: "New customers start with `credit_status` of `GOOD`, zero
    `open_lifting_exposure_cents`, and no `hold_reason`."

    Design: Corner/entities/customer_credit_status_initial_good
    """
    set_clock()
    resp = api.create_customer(
        create_customer_payload(credit_limit_cents=500000), ADMIN,
    )
    data = validate_success(resp, 201)
    assert_customer(data)
    assert data["credit_status"] == "GOOD"
    assert data["open_lifting_exposure_cents"] == 0


def test_terminal_not_found_returns_404(api):
    """PRD §2.8: "every identifier in the path and every referenced resource
    in the body must resolve, or the request fails with `ERR_NOT_FOUND`
    (HTTP 404)."

    Design: Corner/entities/terminal_not_found_returns_404
    """
    set_clock()
    resp = api.get_terminal(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


def test_terminal_list_pagination_envelope(api):
    """PRD §2.3: "The `meta` object of a list response carries the pagination
    fields `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.2: "The `response_type` is either "object" for a single resource
    or "array" for a list of resources."

    Design: Corner/entities/terminal_list_pagination_envelope
    """
    set_clock()
    create_terminal(terminal_code="T1")
    create_terminal(terminal_code="T2")

    resp = api.list_terminals(ADMIN)
    rows, meta = validate_paginated(resp)
    assert isinstance(meta["total_count"], int)
    assert isinstance(meta["has_more"], bool)
    assert meta["limit"] >= 1
    assert meta["offset"] >= 0
    assert resp.json()["response_type"] == "array"
    assert isinstance(resp.json()["meta"].get("api_request_id"), str)
    assert isinstance(resp.json()["meta"].get("api_request_timestamp"), str)
    assert len(rows) == 2


def test_terminal_system_fields_input_ignored(api):
    """PRD §2.5: "`id` (string): a server-minted UUID with no type prefix."
    PRD §2.5: "`version` (integer): a system-managed integer that increments
    with every mutation, including mutations driven by cascading side
    effects."

    Design: Corner/entities/terminal_system_fields_input_ignored
    """
    set_clock()
    supplied_id = "00000000-1111-1111-1111-111111111111"
    resp = api.create_terminal(
        create_terminal_payload(id=supplied_id, version=99),
        ADMIN,
    )
    data = validate_success(resp, 201)
    assert data["id"] != supplied_id, "server must mint its own id"
    assert is_valid_uuid(data["id"])
    assert data["version"] != 99, "client-supplied version must not be honored"
    assert isinstance(data["version"], int)


def test_exchange_agreement_initial_state(api):
    """PRD §3.5: "The lifecycle runs `PROPOSED` → `ACTIVE` → `SUSPENDED` →
    back to `ACTIVE`, with `TERMINATED` as the terminal state reachable from
    either `ACTIVE` or `SUSPENDED`."
    PRD §3.5: "The agreement's `delivered_this_month_gallons` starts at zero
    and tracks gallons delivered under the agreement in the calendar month of
    the logical clock."

    Design: Corner/entities/exchange_agreement_initial_state_proposed
    """
    set_clock()
    terminal = create_terminal()
    product = create_product()
    resp = api.create_exchange_agreement(
        create_exchange_agreement_payload(terminal["id"], product["id"]),
        EXCH,
    )
    data = validate_success(resp, 201)
    assert_exchange_agreement(data)
    assert data["status"] == "PROPOSED"
    assert data["delivered_this_month_gallons"] == 0
