"""Quote-time temporal and activeness validations.

Translates queue-A Difficulty boundary_precision_check (same-day cutoff hour),
priority_pair (existence beats temporal cutoff), and queue-B Corner validations
& errors (inactive arrangement/zone, past delivery date, surge-cutoff override).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    make_customer_headers,
    set_clock, create_zone, create_arrangement, create_holiday_window,
    create_customer, create_draft_order, quote_order, TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
FABRICATED_ORDER_ID = "00000000-0000-4000-8000-000000000000"


def test_same_day_cutoff_hour_exact_boundary_rejected(api):
    """PRD §3.3: "For a same-day order, the clock hour-of-day must be strictly less
    than the **effective cutoff hour**."
    PRD §3.3: "If the clock hour-of-day is at or past the effective cutoff, the
    same-day quote is rejected with `ERR_PAST_SAME_DAY_CUTOFF`."

    Design: Difficulty/boundary_precision_check/same_day_cutoff_hour_exact_boundary
    """
    set_clock("2026-07-03T14:00:00Z")  # clock hour exactly 14 == cutoff 14 => rejected
    zone = create_zone(zone_code="Z10", base_delivery_fee_cents=800,
                       same_day_cutoff_hour_utc=14, window_capacity_per_slot=5)
    arr = create_arrangement(sku="A10", display_name="Bouquet10", base_price_cents=5000)
    cust = create_customer(email="sd@x.com", full_name="SameDay C")
    order = create_draft_order(cust, arr, zone, delivery_date="2026-07-03",
                               window_start_minute=900, window_end_minute=1000)
    res = api.quote_order(order["id"], make_customer_headers(cust["id"]))
    validate_error(res, "ERR_PAST_SAME_DAY_CUTOFF", expected_status=409)
    after = validate_success(api.get_order(order["id"], DISPATCHER), 200)
    assert after["fulfillment_status"] == "DRAFT"


def test_existence_check_beats_temporal_cutoff_on_quote(api):
    """PRD §2.9: "After authorization comes existence: every path identifier and
    body foreign key must resolve, or the request fails with `ERR_NOT_FOUND`."
    PRD §2.9: "Only after all of the above does the system evaluate state and
    business rules".

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_temporal_cutoff_on_quote
    """
    set_clock("2026-07-02T16:00:00Z")  # 16:00 is past a 14 cutoff, but order doesn't exist
    res = api.quote_order(FABRICATED_ORDER_ID, DISPATCHER)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_quote_inactive_arrangement_rejected(api):
    """PRD §3.2: "a quote against an arrangement whose `active` is false is rejected
    with `ERR_ARRANGEMENT_INACTIVE`".

    Design: Corner/validations/quote_inactive_arrangement_returns_arrangement_inactive
    """
    set_clock("2027-04-01T08:00:00Z")
    zone = create_zone(zone_code="ZV1", base_delivery_fee_cents=800,
                       same_day_cutoff_hour_utc=14, window_capacity_per_slot=5)
    arr = create_arrangement(sku="CV1", display_name="CV1", base_price_cents=5000, active=False)
    cust = create_customer(email="ia@x.com", full_name="IA C")
    order = create_draft_order(cust, arr, zone, delivery_date="2027-04-10",
                               window_start_minute=540, window_end_minute=720)
    res = api.quote_order(order["id"], make_customer_headers(cust["id"]))
    validate_error(res, "ERR_ARRANGEMENT_INACTIVE", expected_status=409)


def test_quote_inactive_zone_rejected(api):
    """PRD §3.2: "a quote against a zone whose `active` is false is rejected with
    `ERR_ZONE_INACTIVE`".

    Design: Corner/errors/zone_inactive_quote_returns_zone_inactive
    """
    set_clock("2027-06-01T08:00:00Z")
    zone = create_zone(zone_code="ZR1", base_delivery_fee_cents=800,
                       same_day_cutoff_hour_utc=14, window_capacity_per_slot=5, active=False)
    arr = create_arrangement(sku="CR1", display_name="CR1", base_price_cents=5000)
    cust = create_customer(email="zi@x.com", full_name="ZI C")
    order = create_draft_order(cust, arr, zone, delivery_date="2027-06-10",
                               window_start_minute=540, window_end_minute=720)
    res = api.quote_order(order["id"], make_customer_headers(cust["id"]))
    validate_error(res, "ERR_ZONE_INACTIVE", expected_status=409)


def test_quote_past_delivery_date_rejected(api):
    """PRD §3.2: "The `delivery_date` must not be strictly before the clock date; a
    past delivery date is rejected with `ERR_DELIVERY_DATE_IN_PAST`."

    Design: Corner/validations/quote_delivery_date_in_past_returns_error
    """
    set_clock("2027-04-10T08:00:00Z")
    zone = create_zone(zone_code="ZV2", base_delivery_fee_cents=800,
                       same_day_cutoff_hour_utc=14, window_capacity_per_slot=5)
    arr = create_arrangement(sku="CV2", display_name="CV2", base_price_cents=5000)
    cust = create_customer(email="pd@x.com", full_name="PD C")
    order = create_draft_order(cust, arr, zone, delivery_date="2027-04-09",
                               window_start_minute=540, window_end_minute=720)
    res = api.quote_order(order["id"], make_customer_headers(cust["id"]))
    validate_error(res, "ERR_DELIVERY_DATE_IN_PAST", expected_status=409)


def test_surge_window_cutoff_overrides_zone_cutoff(api):
    """PRD §3.3: "The effective cutoff is the holiday window's `surge_cutoff_hour_utc`
    when the delivery date falls inside a holiday window, and otherwise the zone's
    `same_day_cutoff_hour_utc`."

    Design: Corner/validations/surge_window_cutoff_overrides_zone_cutoff
    """
    set_clock("2027-02-14T16:00:00Z")  # past zone cutoff 14, before window cutoff 20
    zone = create_zone(zone_code="ZV3", base_delivery_fee_cents=800,
                       same_day_cutoff_hour_utc=14, window_capacity_per_slot=5)
    arr = create_arrangement(sku="CV3", display_name="CV3", base_price_cents=5000,
                             premium_tier="PREMIUM")
    create_holiday_window(name="VV3", start_date="2027-02-14", end_date="2027-02-14",
                          surge_multiplier=2.0, applies_to_standard=False, surge_cutoff_hour_utc=20)
    cust = create_customer(email="sc@x.com", full_name="SC C")
    order = create_draft_order(cust, arr, zone, delivery_date="2027-02-14",
                               window_start_minute=1080, window_end_minute=1200)
    quoted = validate_success(api.quote_order(order["id"], make_customer_headers(cust["id"])), 200)
    assert quoted["fulfillment_status"] == "QUOTED"
    assert quoted["is_same_day"] is True
    # PREMIUM surge 2.0: 5000*2.0=10000 + delivery 800 = 10800
    assert quoted["estimated_total_cents"] == 10800, quoted["estimated_total_cents"]
