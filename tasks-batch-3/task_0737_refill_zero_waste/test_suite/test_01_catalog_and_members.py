"""Catalog and member basics: creation, computed projections, existence and
input validation, and list pagination. Translations of Corner/entities and one
Corner/validations instance.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    factories, fixtures,
    assert_member, assert_container,
)
from test_helpers.test_users import TEST_USERS

CLERK = TEST_USERS["store_clerk_headers"]
IM = TEST_USERS["inventory_manager_headers"]


def test_create_member_defaults_to_basic_tier(api):
    """PRD §3.1: "A clerk registers a member at the counter by supplying an
    `email` and a `full_name`, and optionally a `membership_tier`; when omitted
    the tier defaults to `BASIC`."

    Design: Corner/entities/corner_create_member_success
    """
    resp = api.create_member(
        factories.create_member_payload(full_name="Corner One"), CLERK)
    data = validate_success(resp, 201)
    assert_member(data)
    assert data["membership_tier"] == "BASIC", "omitted tier must default to BASIC"
    assert data["wallet_balance_cents"] == 0


def test_get_unknown_member_returns_not_found(api):
    """PRD §2.9: "A miss returns the matching 404: `ERR_MEMBER_NOT_FOUND`,
    `ERR_PRODUCT_NOT_FOUND`, `ERR_STATION_NOT_FOUND`, ..."

    Design: Corner/entities/corner_err_member_not_found_returns_404
    """
    resp = api.get_member(NON_EXISTENT_UUID, CLERK)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_FOUND.value)


def test_create_product_missing_unit_price_rejected(api):
    """PRD §2.9: "A malformed body, a missing required field, or a bad type or
    enum value is rejected up front with `ERR_VALIDATION` (400)."

    Design: Corner/entities/corner_err_product_create_missing_required_field
    """
    payload = {
        "name": "Bad",
        "category": "GRAINS",
        "bulk_tier_threshold_g": 1000,
        "bulk_tier_price_cents_per_100g": 30,
    }  # unit_price_cents_per_100g omitted (required per §3.2)
    resp = api.create_product(payload, IM)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_new_member_balances_start_zero(api):
    """PRD §3.1: "A newly registered member starts with all three projected
    balances at zero: `wallet_balance_cents`, `deposit_liability_cents`, and
    `loyalty_points_balance`."

    Design: Corner/entities/corner_member_computed_balances_start_zero
    """
    member = fixtures.create_member(api)
    data = validate_success(api.get_member(member["id"], CLERK), 200)
    assert data["wallet_balance_cents"] == 0
    assert data["deposit_liability_cents"] == 0
    assert data["loyalty_points_balance"] == 0


def test_glass_1000_container_deposit_is_250(api):
    """PRD §3.3: "a `GLASS_500` carries a 150-cent deposit, a `GLASS_1000`
    carries 250 cents, and a member-owned `BYO` carries a zero deposit."

    Design: Corner/entities/corner_container_deposit_derived_from_type
    """
    resp = api.create_container(
        factories.create_container_payload("GLASS_1000", declared_tare_g=400), CLERK)
    data = validate_success(resp, 201)
    assert_container(data)
    assert data["deposit_cents"] == 250, "GLASS_1000 deposit is derived as 250 cents"


def test_create_order_invalid_channel_rejected(api):
    """PRD §3.4: "optionally a `fulfillment_channel` of `IN_STORE` (the default)
    or `DELIVERY`."
    PRD §2.9: "A malformed body, a missing required field, or a bad type or enum
    value is rejected up front with `ERR_VALIDATION` (400)."

    Design: Corner/entities/corner_order_invalid_channel_enum_rejected
    """
    member = fixtures.create_member(api)
    station = fixtures.create_station(api)
    payload = factories.create_order_payload(
        member["id"], station["id"], fulfillment_channel="AIR")
    resp = api.create_order(payload, CLERK)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_bin_unknown_product_rejected(api):
    """PRD §2.9: "**Existence** — every path identifier and every foreign-key
    reference in the body resolves to an existing resource, validated left to
    right with **path identifiers checked before body foreign keys**."

    Design: Corner/entities/corner_err_bin_create_unknown_product_not_found
    """
    station = fixtures.create_station(api)
    payload = factories.create_bin_payload(NON_EXISTENT_UUID, station["id"])
    resp = api.create_bin(payload, IM)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND.value)


def test_list_orders_pagination_meta(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/corner_list_orders_pagination
    """
    member = fixtures.create_member(api)
    station = fixtures.create_station(api)
    # Two CART orders on distinct, non-overlapping (adjacent) station windows.
    fixtures.create_order(api, member_id=member["id"], station_id=station["id"],
                          fill_window_start_at="2026-03-02T09:00:00Z",
                          fill_window_end_at="2026-03-02T10:00:00Z")
    fixtures.create_order(api, member_id=member["id"], station_id=station["id"],
                          fill_window_start_at="2026-03-02T10:00:00Z",
                          fill_window_end_at="2026-03-02T11:00:00Z")
    resp = api.list_orders(CLERK, params={"member_id": member["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, "limit=1 must return exactly one item"
    assert meta["total_count"] == 2, "two orders exist for this member"
    assert meta["has_more"] is True, "one of two remains beyond limit=1"


def test_duplicate_member_email_rejected(api):
    """PRD §3.1: "The `email` must be unique across all members — a collision is
    rejected with `ERR_DUPLICATE_EMAIL`."

    Design: Corner/validations/corner_err_duplicate_email_on_member_create
    """
    email = factories.unique_email("dup")
    first = api.create_member(
        factories.create_member_payload(email=email, full_name="First"), CLERK)
    validate_success(first, 201)
    second = api.create_member(
        factories.create_member_payload(email=email, full_name="Second"), CLERK)
    validate_error(second, ApiErrorId.ERR_DUPLICATE_EMAIL.value)
