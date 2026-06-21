"""Resource temporal overlap: zone aggregate-capacity peak-load (half-open intervals)
and the strict point-ordering of a lot's CCP reading timeline.

Queue A — Difficulty/resource_temporal_overlap.
"""
import pytest
from test_helpers import (
    api_client, validate_error,
    setup_zone_with_lots, create_booking,
    setup_released_lot_for_readings, post_reading,
    create_booking_payload, create_ccp_reading_payload, ApiErrorId,
    TEST_USERS,
)

QM = TEST_USERS["quality_manager_headers"]
OP = TEST_USERS["production_operator_headers"]


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/storage_zone_aggregate_capacity_overlap
# ---------------------------------------------------------------------------

def test_overlapping_bookings_exceeding_capacity_rejected():
    """PRD 3.8: "If at any such overlapping sub-interval the summed capacity, including
    the candidate, exceeds the zone's `capacity_units`, the booking is rejected with
    `ERR_ZONE_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/storage_zone_aggregate_capacity_overlap
    """
    facility, zone_id, lots = setup_zone_with_lots(capacity_units=100, num_lots=2)
    # Booking A=70 over [00:00,06:00).
    create_booking(zone_id, lots[0], "2026-01-01T00:00:00Z", "2026-01-01T06:00:00Z", 70)
    # Candidate B=40 over [03:00,09:00) overlaps A during [03:00,06:00): peak 110 > 100.
    res = api_client.create_booking(
        zone_id, create_booking_payload(lots[1], "2026-01-01T03:00:00Z",
                                        "2026-01-01T09:00:00Z", 40), QM)
    validate_error(res, ApiErrorId.ERR_ZONE_CAPACITY_EXCEEDED.value)


def test_nonoverlapping_window_allows_full_capacity_each():
    """PRD 3.8: "two bookings that merely touch at an endpoint — where one ends exactly
    when the other begins — do not overlap."

    Design: Difficulty/resource_temporal_overlap/storage_zone_aggregate_capacity_overlap
    """
    facility, zone_id, lots = setup_zone_with_lots(capacity_units=100, num_lots=2)
    # A=70 over [00:00,06:00); B=70 over [06:00,12:00) touches A's end — no overlap.
    create_booking(zone_id, lots[0], "2026-01-01T00:00:00Z", "2026-01-01T06:00:00Z", 70)
    from test_helpers import validate_success
    booking = validate_success(
        api_client.create_booking(
            zone_id, create_booking_payload(lots[1], "2026-01-01T06:00:00Z",
                                            "2026-01-01T12:00:00Z", 70), QM), 201)
    assert booking["capacity_units"] == 70


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/ccp_reading_timeline_strict_point_ordering
# ---------------------------------------------------------------------------

def test_reading_before_latest_prior_rejected():
    """PRD 3.5: "A reading whose `measured_at` is in the future relative to the clock,
    or at or before the lot's latest prior reading, collides with the timeline and is
    rejected with `ERR_READING_OUT_OF_ORDER`."

    Design: Difficulty/resource_temporal_overlap/ccp_reading_timeline_strict_point_ordering
    """
    facility, ingredient, lot_id = setup_released_lot_for_readings(
        target_c=0, tolerance_c=2, clock_utc="2026-01-02T05:00:00Z",
        shelf_life_days=30, declared_allergen_codes=["SHELLFISH"])
    post_reading(lot_id, 0, "2026-01-02T02:00:00Z")
    # New reading at 01:00 is before the latest prior (02:00) -> collides with timeline.
    res = api_client.create_ccp_reading(
        create_ccp_reading_payload(lot_id, 0, "2026-01-02T01:00:00Z"), OP)
    validate_error(res, ApiErrorId.ERR_READING_OUT_OF_ORDER.value)


def test_reading_in_future_relative_to_clock_rejected():
    """PRD 3.5: "A reading whose `measured_at` is in the future relative to the clock,
    or at or before the lot's latest prior reading, collides with the timeline and is
    rejected with `ERR_READING_OUT_OF_ORDER`."

    Design: Difficulty/resource_temporal_overlap/ccp_reading_timeline_strict_point_ordering
    """
    facility, ingredient, lot_id = setup_released_lot_for_readings(
        target_c=0, tolerance_c=2, clock_utc="2026-01-02T05:00:00Z",
        shelf_life_days=30, declared_allergen_codes=["SHELLFISH"])
    # Clock is at 2026-01-02T05:00; a reading at 06:00 is in the future.
    res = api_client.create_ccp_reading(
        create_ccp_reading_payload(lot_id, 0, "2026-01-02T06:00:00Z"), OP)
    validate_error(res, ApiErrorId.ERR_READING_OUT_OF_ORDER.value)
