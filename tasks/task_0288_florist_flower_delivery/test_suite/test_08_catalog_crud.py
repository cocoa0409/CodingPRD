"""Catalog CRUD, input validation, listing, and schedule lifecycle corners.

Translates queue-B Corner entities / endpoints / state_machines instances:
creation echo+defaults, not-found, required-field, type constraints, FK
resolution, pagination envelope, filtered listing, schedule auto-pause.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    make_customer_headers,
    set_clock, create_zone, create_arrangement, create_customer, create_florist,
    create_draft_order, create_schedule, emit_schedule, TEST_USERS,
)

CATALOG_ADMIN = TEST_USERS["catalog_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
UNKNOWN_ORDER_ID = "11111111-1111-4111-8111-111111111111"
UNKNOWN_ARRANGEMENT_ID = "22222222-2222-4222-8222-222222222222"


def test_create_arrangement_returns_201_with_defaults(api):
    """PRD §3.1: "Each arrangement carries a `premium_tier`, one of `STANDARD` or
    `PREMIUM`, defaulting to `STANDARD`, which governs holiday surge eligibility."
    PRD §3.1: "a `substitution_policy`, one of `NONE`, `SAME_VALUE`, or
    `FLORIST_CHOICE`, defaulting to `SAME_VALUE`, together with a
    `substitution_cap_pct` (a fraction between 0 and 1 inclusive, defaulting to
    0.15)".
    PRD §3.1: "An `active` boolean, defaulting to true, marks whether the
    arrangement is orderable."

    Design: Corner/entities/create_arrangement_returns_201_with_all_fields
    """
    res = api.create_arrangement(
        {"sku": "C-ARR", "display_name": "Corner Arr", "base_price_cents": 4200}, CATALOG_ADMIN)
    arr = validate_success(res, 201)
    assert arr["base_price_cents"] == 4200
    assert arr["premium_tier"] == "STANDARD"
    assert arr["substitution_policy"] == "SAME_VALUE"
    assert arr["substitution_cap_pct"] == 0.15
    assert arr["active"] is True
    assert arr["version"] == 1


def test_get_unknown_order_returns_404(api):
    """PRD §2.8: "the parent identifier in the path is resolved first, and if it
    does not name an existing row the request fails immediately with `ERR_NOT_FOUND`
    before any child lookup is attempted".

    Design: Corner/entities/get_order_not_found_returns_404
    """
    res = api.get_order(UNKNOWN_ORDER_ID, DISPATCHER)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_zone_missing_required_field_returns_422(api):
    """PRD §2.9: "Then the request body is validated against its schema — required
    fields present, enumerated values in range, and the field-level numeric and
    length constraints described throughout §3 — failing with `ERR_INVALID_REQUEST`."
    PRD §3.1: "a `window_capacity_per_slot` (at least 1, the maximum number of
    bookings allowed for any one delivery time window in the zone".

    Design: Corner/entities/create_zone_missing_required_field_returns_422
    """
    res = api.create_zone(
        {"zone_code": "ZX", "base_delivery_fee_cents": 800, "same_day_cutoff_hour_utc": 14},
        CATALOG_ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_order_card_message_over_240_chars_returns_422(api):
    """PRD §3.2: "a `card_message` (gift-card text, defaulting to the empty string,
    at most 240 characters)".
    PRD §3.2: "a card message over 240 characters, an out-of-range window, an enum
    out of range, or a missing required field is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/order_card_message_over_240_chars_returns_422
    """
    set_clock("2026-10-20T08:00:00Z")
    zone = create_zone(zone_code="ZC1", base_delivery_fee_cents=800,
                       same_day_cutoff_hour_utc=14, window_capacity_per_slot=5)
    arr = create_arrangement(sku="CC1", display_name="CC1", base_price_cents=5000)
    cust = create_customer(email="cm@x.com", full_name="CM C")
    res = api.create_order(
        {"customer_id": cust["id"], "arrangement_id": arr["id"], "zone_id": zone["id"],
         "card_message": "x" * 241, "delivery_date": "2026-11-01",
         "window_start_minute": 540, "window_end_minute": 720},
        make_customer_headers(cust["id"]))
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_order_window_start_not_less_than_end_returns_422(api):
    """PRD §3.2: "The window must satisfy `window_start_minute` strictly less than
    `window_end_minute`, with `window_end_minute` no greater than 1440 and
    `window_start_minute` no less than 0; a card message over 240 characters, an
    out-of-range window, an enum out of range, or a missing required field is
    rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/order_window_start_not_less_than_end_returns_422
    """
    set_clock("2026-10-20T08:00:00Z")
    zone = create_zone(zone_code="ZC2", base_delivery_fee_cents=800,
                       same_day_cutoff_hour_utc=14, window_capacity_per_slot=5)
    arr = create_arrangement(sku="CC2", display_name="CC2", base_price_cents=5000)
    cust = create_customer(email="wn@x.com", full_name="WN C")
    res = api.create_order(
        {"customer_id": cust["id"], "arrangement_id": arr["id"], "zone_id": zone["id"],
         "delivery_date": "2026-11-01", "window_start_minute": 720, "window_end_minute": 720},
        make_customer_headers(cust["id"]))
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_order_invalid_occasion_enum_returns_422(api):
    """PRD §3.2: "an `occasion` — one of `GENERAL`, `BIRTHDAY`, `ANNIVERSARY`,
    `SYMPATHY`, or `ROMANCE`, defaulting to `GENERAL`".
    PRD §3.2: "an enum out of range, or a missing required field is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/order_invalid_occasion_enum_returns_422
    """
    set_clock("2026-10-20T08:00:00Z")
    zone = create_zone(zone_code="ZC3", base_delivery_fee_cents=800,
                       same_day_cutoff_hour_utc=14, window_capacity_per_slot=5)
    arr = create_arrangement(sku="CC3", display_name="CC3", base_price_cents=5000)
    cust = create_customer(email="oc@x.com", full_name="OC C")
    res = api.create_order(
        {"customer_id": cust["id"], "arrangement_id": arr["id"], "zone_id": zone["id"],
         "occasion": "WEDDING", "delivery_date": "2026-11-01",
         "window_start_minute": 540, "window_end_minute": 720},
        make_customer_headers(cust["id"]))
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_order_unknown_arrangement_fk_returns_404(api):
    """PRD §2.8: "every path identifier and every foreign-key reference carried in a
    request body must resolve to an existing row, validated in order, and the first
    unresolved reference yields `ERR_NOT_FOUND`."

    Design: Corner/entities/order_unknown_arrangement_fk_returns_404
    """
    set_clock("2026-10-20T08:00:00Z")
    zone = create_zone(zone_code="ZC4", base_delivery_fee_cents=800,
                       same_day_cutoff_hour_utc=14, window_capacity_per_slot=5)
    cust = create_customer(email="fk@x.com", full_name="FK C")
    res = api.create_order(
        {"customer_id": cust["id"], "arrangement_id": UNKNOWN_ARRANGEMENT_ID,
         "zone_id": zone["id"], "delivery_date": "2026-11-01",
         "window_start_minute": 540, "window_end_minute": 720},
        make_customer_headers(cust["id"]))
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_list_orders_pagination_envelope(api):
    """PRD §2.3: "Paginated list responses include the following fields in the
    `meta` object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."
    PRD §3.2: "Orders may be listed and filtered by `customer_id`".

    Design: Corner/entities/list_orders_pagination_envelope
    """
    set_clock("2026-10-20T08:00:00Z")
    zone = create_zone(zone_code="ZC6", base_delivery_fee_cents=800,
                       same_day_cutoff_hour_utc=14, window_capacity_per_slot=5)
    arr = create_arrangement(sku="CC6", display_name="CC6", base_price_cents=5000)
    cust = create_customer(email="lp@x.com", full_name="LP C")
    create_draft_order(cust, arr, zone, delivery_date="2026-11-01",
                       window_start_minute=540, window_end_minute=720)
    data, meta = validate_paginated(
        api.list_orders(DISPATCHER, params={"customer_id": cust["id"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_list_florists_filtered_by_zone(api):
    """PRD §3.1: "Florists may be listed and filtered by `covered_zone_id` for
    zone-coverage discovery."

    Design: Corner/endpoints/list_florists_filtered_by_zone
    """
    zone = create_zone(zone_code="ZE2", base_delivery_fee_cents=800,
                       same_day_cutoff_hour_utc=14, window_capacity_per_slot=5)
    create_florist(zone["id"], shop_name="ShopE2", daily_capacity=5)
    data, meta = validate_paginated(
        api.list_florists(DISPATCHER, params={"covered_zone_id": zone["id"]}))
    assert meta["total_count"] == 1


def test_schedule_emit_exhausted_auto_pauses(api):
    """PRD §3.8: "an emit (or a resume) against a schedule whose
    `occurrences_remaining` is 0 is rejected with `ERR_SCHEDULE_EXHAUSTED`."
    PRD §3.8: "When the decrement brings `occurrences_remaining` to 0, the schedule
    auto-pauses, moving its `status` to `PAUSED` in the same operation."

    Design: Corner/state_machines/schedule_emit_exhausted_auto_pauses
    """
    set_clock("2026-12-01T08:00:00Z")
    zone = create_zone(zone_code="ZS4", base_delivery_fee_cents=800,
                       same_day_cutoff_hour_utc=14, window_capacity_per_slot=5)
    arr = create_arrangement(sku="CS4", display_name="CS4", base_price_cents=5000)
    cust = create_customer(email="se@x.com", full_name="SE C")
    sched = create_schedule(cust, arr, zone, cadence="WEEKLY", next_delivery_date="2026-12-10",
                            window_start_minute=540, window_end_minute=720, occurrences_remaining=1)
    after_emit = emit_schedule(sched)
    assert after_emit["status"] == "PAUSED"
    assert after_emit["occurrences_remaining"] == 0
    res = api.emit_schedule(sched["id"], DISPATCHER)
    validate_error(res, "ERR_SCHEDULE_EXHAUSTED", expected_status=409)
