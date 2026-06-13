"""Booking: zone-window capacity, florist daily capacity, selector availability.

Translates queue-A Difficulty boundary_precision_check (zone window fill),
resource_temporal_overlap (half-open window / aggregate daily capacity), and the
priority_pair conflict (state beats capacity) on the book endpoint.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    make_customer_headers,
    setup_authorized_order, set_clock, create_zone, create_arrangement,
    create_customer, create_florist, create_draft_order, quote_order,
    mark_authorized, book_order, TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def _authorized_order_in(ctx, delivery_date, start, end):
    """Create+quote+authorize another order in an existing catalog context."""
    order = create_draft_order(ctx["customer"], ctx["arrangement"], ctx["zone"],
                               delivery_date=delivery_date, window_start_minute=start,
                               window_end_minute=end)
    order = quote_order(order, ctx["customer"])
    return mark_authorized(order["id"])


def test_zone_window_capacity_exact_fill_boundary(api):
    """PRD §3.4: "the number of existing non-released bookings sharing that same
    zone, that same date, and that same `[window_start_minute, window_end_minute)`
    window is strictly fewer than the zone's `window_capacity_per_slot`; if that
    window is already full, booking is rejected with `ERR_ZONE_WINDOW_FULL`."

    Design: Difficulty/boundary_precision_check/zone_window_capacity_exact_fill_boundary
    """
    ctx, first = setup_authorized_order(
        "2026-07-04T08:00:00Z",
        zone_overrides={"zone_code": "Z11", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 1},
        arrangement_overrides={"sku": "A11", "display_name": "Bouquet11", "base_price_cents": 5000},
        florist_overrides={"shop_name": "Shop11", "daily_capacity": 5},
        order_overrides={"delivery_date": "2026-07-08", "window_start_minute": 540,
                         "window_end_minute": 720})
    book_order(first, ctx["customer"], first["version"])  # fills capacity 1
    second = _authorized_order_in(ctx, "2026-07-08", 540, 720)
    res = api.book_order(second["id"], {"expected_order_version": second["version"]},
                         make_customer_headers(ctx["customer"]["id"]))
    validate_error(res, "ERR_ZONE_WINDOW_FULL", expected_status=409)
    after = validate_success(api.get_order(second["id"], DISPATCHER), 200)
    assert after["fulfillment_status"] == "QUOTED"


def test_adjacent_halfopen_window_does_not_collide(api):
    """PRD §3.2: "the window is half-open, so the start is inclusive and the end
    exclusive".
    PRD §3.4: "the number of existing non-released bookings sharing that same zone,
    that same date, and that same `[window_start_minute, window_end_minute)`
    window is strictly fewer than the zone's `window_capacity_per_slot`".

    Design: Difficulty/resource_temporal_overlap/zone_window_same_halfopen_interval_collides
    """
    ctx, first = setup_authorized_order(
        "2026-09-01T08:00:00Z",
        zone_overrides={"zone_code": "Z14", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 1},
        arrangement_overrides={"sku": "A14", "display_name": "Bouquet14", "base_price_cents": 5000},
        florist_overrides={"shop_name": "Shop14", "daily_capacity": 5},
        order_overrides={"delivery_date": "2026-09-05", "window_start_minute": 540,
                         "window_end_minute": 720})
    book_order(first, ctx["customer"], first["version"])  # books [540,720)
    # Adjacent [720,900) shares only the endpoint 720; half-open => no overlap.
    second = _authorized_order_in(ctx, "2026-09-05", 720, 900)
    booked = validate_success(api.book_order(
        second["id"], {"expected_order_version": second["version"]},
        make_customer_headers(ctx["customer"]["id"])), 200)
    assert booked["fulfillment_status"] == "BOOKED"


def test_florist_daily_aggregate_capacity_blocks_disjoint_windows(api):
    """PRD §3.4: "whose count of non-released wire fulfillments for the order's
    `delivery_date` is strictly fewer than its `daily_capacity` (that is, the shop
    has headroom on that date)."
    PRD §3.4: "If the candidate set is empty — no in-zone, accepting florist has
    capacity headroom for that date — the booking is rejected with
    `ERR_NO_FLORIST_AVAILABLE`".

    Design: Difficulty/resource_temporal_overlap/florist_daily_aggregate_capacity_overlap
    """
    ctx, first = setup_authorized_order(
        "2026-09-08T08:00:00Z",
        zone_overrides={"zone_code": "Z15", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 5},
        arrangement_overrides={"sku": "A15", "display_name": "Bouquet15", "base_price_cents": 5000},
        florist_overrides={"shop_name": "Shop15", "daily_capacity": 1},
        order_overrides={"delivery_date": "2026-09-10", "window_start_minute": 540,
                         "window_end_minute": 600})
    book_order(first, ctx["customer"], first["version"])  # consumes the only daily slot
    # Same date, disjoint window — still consumes daily_capacity, so no florist free.
    second = _authorized_order_in(ctx, "2026-09-10", 800, 900)
    res = api.book_order(second["id"], {"expected_order_version": second["version"]},
                         make_customer_headers(ctx["customer"]["id"]))
    validate_error(res, "ERR_NO_FLORIST_AVAILABLE", expected_status=409)
    after = validate_success(api.get_order(second["id"], DISPATCHER), 200)
    assert after["fulfillment_status"] == "QUOTED"


def test_state_check_beats_capacity_on_book(api):
    """PRD §2.9: "first whether the requested state transition is defined from the
    resource's current state (`ERR_INVALID_STATE`), then the cross-dimension and
    cross-entity preconditions and the domain-specific temporal, capacity, and
    policy rules described in §3".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_capacity_on_book
    """
    ctx, other = setup_authorized_order(
        "2026-07-01T08:00:00Z",
        zone_overrides={"zone_code": "Z9", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 5},
        arrangement_overrides={"sku": "A9", "display_name": "Bouquet9", "base_price_cents": 5000},
        florist_overrides={"shop_name": "Shop9", "daily_capacity": 1},
        order_overrides={"delivery_date": "2026-07-05", "window_start_minute": 540,
                         "window_end_minute": 720})
    book_order(other, ctx["customer"], other["version"])  # exhausts daily_capacity 1
    # A DRAFT (never quoted) order: state check must fire before capacity check.
    draft = create_draft_order(ctx["customer"], ctx["arrangement"], ctx["zone"],
                               delivery_date="2026-07-05", window_start_minute=800,
                               window_end_minute=900)
    res = api.book_order(draft["id"], {"expected_order_version": draft["version"]},
                         make_customer_headers(ctx["customer"]["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_order(draft["id"], DISPATCHER), 200)
    assert after["fulfillment_status"] == "DRAFT"
