"""CRUD, input validation, defaults, system fields, listing, and simple endpoints.

Covers Corner queue (B) instances from the entities and endpoints sections.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    assert_fare_product, assert_rider, assert_funding_source, assert_tap,
    create_fare_product_payload, create_rider_payload, create_funding_source_payload,
    create_fare_week_payload, create_tap_payload, load_payload,
    TEST_USERS, make_rider_headers, make_anonymous_headers,
    set_clock, make_fare_product, register_rider, add_funding_source, open_week,
    ApiErrorId,
)

MISSING_UUID = "11111111-1111-4111-8111-111111111111"


def test_create_fare_product_applies_defaults(api):
    """PRD §3.1: "The `transfer_window_minutes`, the number of minutes after a
    charged tap during which a following tap qualifies as a transfer, must be
    greater than zero and defaults to 120. The `transfer_discount_pct`, the fraction
    of the base fare removed from a qualifying transfer tap, must be between 0.0 and
    1.0 inclusive and defaults to 1.0, where 1.0 means the transfer is free."
    PRD §3.1: "The `reduced_fare_pct`, the fraction discount applied to the base fare
    and to both caps for a rider holding a verified reduced-fare card, must be at
    least 0.0 and strictly less than 1.0 and defaults to 0.5."
    PRD §3.1: "A new product is born `ACTIVE`, the value of its system-managed
    `status`, which is either `ACTIVE` or `RETIRED`."
    PRD §2.4: "an integer `version` that begins at 1 on creation and increments by
    one with each mutation."

    Design: Corner/entities/create_fare_product_returns_201_with_defaults_applied
    """
    res = api.create_fare_product(
        create_fare_product_payload(zone_code="ZONEA", base_fare_cents=250,
                                    daily_cap_cents=500, weekly_cap_cents=2000),
        TEST_USERS["fare_admin_headers"])
    product = validate_success(res, 201)
    assert_fare_product(product)
    assert product["transfer_window_minutes"] == 120
    assert product["transfer_discount_pct"] == 1.0
    assert product["reduced_fare_pct"] == 0.5
    assert product["status"] == "ACTIVE"
    assert product["version"] == 1


def test_register_rider_defaults_standard_active(api):
    """PRD §3.2: "The `income_tier` is the rider's self-declared tier, either
    `STANDARD` or `LOW_INCOME`, defaulting to `STANDARD`."
    PRD §3.2: "A freshly registered rider has `status` `ACTIVE` (the other value
    being `SUSPENDED`) and `version` 1."

    Design: Corner/entities/register_rider_returns_201_with_status_active
    """
    make_fare_product(zone_code="ZONEA")
    res = api.create_rider(
        create_rider_payload(email="cr@x.com", full_name="C R", home_zone_code="ZONEA"),
        make_anonymous_headers())
    rider = validate_success(res, 201)
    assert_rider(rider)
    assert rider["income_tier"] == "STANDARD"
    assert rider["status"] == "ACTIVE"
    assert rider["version"] == 1


def test_get_rider_not_found_returns_404(api):
    """PRD §2.9: "Existence comes fourth: every path id and every foreign-key
    reference in the body is checked left-to-right, and the first that does not
    resolve yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_rider_not_found_returns_404
    """
    res = api.get_rider(MISSING_UUID, TEST_USERS["fare_admin_headers"])
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_create_funding_source_missing_source_type_returns_422(api):
    """PRD §3.3: "A `Rider` creates a funding source against their own `rider_id`,
    choosing a `source_type` of `APPLE_PAY`, `GOOGLE_PAY`, or `CONTACTLESS_CARD`".
    PRD §2.9: "Body well-formedness comes fifth: missing required fields, wrong
    types, or enum values outside their declared sets yield `ERR_INVALID_REQUEST`
    (HTTP 422)."

    Design: Corner/entities/create_funding_source_missing_required_source_type_returns_422
    """
    make_fare_product(zone_code="ZONEA")
    rider = register_rider(home_zone_code="ZONEA", email="rf@x.com")
    res = api.create_funding_source({"rider_id": rider["id"]},
                                    make_rider_headers(rider["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=422)


def test_create_funding_source_invalid_enum_returns_422(api):
    """PRD §2.9: "missing required fields, wrong types, or enum values outside their
    declared sets yield `ERR_INVALID_REQUEST` (HTTP 422)."
    PRD §3.3: "choosing a `source_type` of `APPLE_PAY`, `GOOGLE_PAY`, or
    `CONTACTLESS_CARD`".

    Design: Corner/entities/create_funding_source_invalid_enum_source_type_returns_422
    """
    make_fare_product(zone_code="ZONEA")
    rider = register_rider(home_zone_code="ZONEA", email="rf2@x.com")
    res = api.create_funding_source(
        create_funding_source_payload(rider["id"], source_type="BITCOIN"),
        make_rider_headers(rider["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=422)


def test_load_increments_balance_and_version(api):
    """PRD §3.3: "A new source starts with `status` `ACTIVE` (the alternative being
    `REMOVED`) and a `prepaid_balance_cents` of 0."
    PRD §3.3: "Stored value is added through a load operation, available to the
    owning `Rider` and to a `FareAdmin`, which takes an `amount_cents` and increases
    `prepaid_balance_cents` by that amount while incrementing the source's
    `version`."

    Design: Corner/entities/load_funding_source_increments_balance_system_field
    """
    make_fare_product(zone_code="ZONEA")
    rider = register_rider(home_zone_code="ZONEA", email="rl@x.com")
    fs = add_funding_source(rider["id"], source_type="GOOGLE_PAY")
    assert fs["prepaid_balance_cents"] == 0
    assert fs["version"] == 1
    res = api.load_funding_source(fs["id"], load_payload(1500),
                                  make_rider_headers(rider["id"]))
    loaded = validate_success(res, 200)
    assert loaded["prepaid_balance_cents"] == 1500
    assert loaded["version"] == 2


def test_list_taps_pagination_envelope(api):
    """PRD §2.3: "Every list-based response includes the following fields inside the
    `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §3.6: "A tap is created in `PENDING` status".

    Design: Corner/entities/list_taps_pagination_envelope_fields_present
    """
    make_fare_product(zone_code="ZONEA")
    set_clock("2026-06-01T12:00:00Z")
    rider = register_rider(home_zone_code="ZONEA", email="rp@x.com")
    fs = add_funding_source(rider["id"])
    week = open_week(rider["id"], zone_code="ZONEA")
    api.create_tap(
        create_tap_payload(rider["id"], week["id"], fs["id"], "2026-06-01T09:00:00Z"),
        make_rider_headers(rider["id"]))
    res = api.list_taps(make_rider_headers(rider["id"]), params={"rider_id": rider["id"]})
    data, meta = validate_paginated(res)
    assert len(data) == 1
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_retire_fare_product_sets_status_retired(api):
    """PRD §3.1: "A `FareAdmin` may retire a product, moving its `status` to
    `RETIRED`; once retired it can no longer back new taps."

    Design: Corner/endpoints/retire_fare_product_sets_status_retired
    """
    product = make_fare_product(zone_code="ZONER")
    res = api.retire_fare_product(product["id"], TEST_USERS["fare_admin_headers"])
    retired = validate_success(res, 200)
    assert retired["status"] == "RETIRED"


def test_quote_clean_week_returns_full_fare_no_credits(api):
    """PRD §3.9: "The quote response reports the `rider_id`, the `fare_week_id`, the
    `estimated_charge_cents`, and the breakdown fields `list_fare_cents`,
    `transfer_discount_cents`, and `cap_credit_cents`."
    PRD §3.9: "it takes the smaller of the effective daily cap and that combined
    list total, subtracts the day's already-charged total, and floors the result
    at 0."

    Design: Corner/endpoints/quote_endpoint_returns_inline_estimate_schema
    """
    make_fare_product(zone_code="ZONEX", base_fare_cents=300, daily_cap_cents=500,
                      weekly_cap_cents=2500, transfer_discount_pct=0)
    set_clock("2026-06-01T12:00:00Z")
    rider = register_rider(home_zone_code="ZONEX", email="rq@x.com")
    week = open_week(rider["id"], zone_code="ZONEX")
    res = api.quote_tap(make_rider_headers(rider["id"]),
                        {"rider_id": rider["id"], "fare_week_id": week["id"],
                         "tapped_at": "2026-06-01T09:00:00Z"})
    quote = validate_success(res, 200)
    assert quote["estimated_charge_cents"] == 300
    assert quote["cap_credit_cents"] == 0
    assert quote["transfer_discount_cents"] == 0


def test_list_funding_sources_filtered_by_rider(api):
    """PRD §3.3: "Funding sources are listable, filterable by `rider_id`, and
    individually fetchable — the single fetch surfaces the current
    `prepaid_balance_cents` — by a `FareAdmin` or the owning rider."

    Design: Corner/endpoints/fk_filtered_list_funding_sources_by_rider
    """
    make_fare_product(zone_code="ZONEX")
    rider = register_rider(home_zone_code="ZONEX", email="rk@x.com")
    add_funding_source(rider["id"], source_type="APPLE_PAY")
    add_funding_source(rider["id"], source_type="GOOGLE_PAY", is_default=False)
    res = api.list_funding_sources(make_rider_headers(rider["id"]),
                                   params={"rider_id": rider["id"]})
    data, meta = validate_paginated(res)
    assert len(data) == 2
    for fs in data:
        assert fs["rider_id"] == rider["id"]
