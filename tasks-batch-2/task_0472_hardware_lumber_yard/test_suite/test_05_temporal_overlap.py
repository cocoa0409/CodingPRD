"""Resource temporal overlap: half-open rental intervals (back-to-back allowed,
interior overlap rejected) and buffer-expanded service-station booking windows.

Covers Difficulty queue rule resource_temporal_overlap.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_rental_asset, create_reservation, create_station, book_ticket,
    api_client, SALES, INVENTORY, RENTAL,
)


# ─── Difficulty: resource_temporal_overlap (rental) ─────────────────────────

def test_rental_back_to_back_adjacency_allowed(api):
    """PRD 3.7: "The reservation is rejected with ERR_RENTAL_OVERLAP if its
    interval overlaps any non-terminal agreement already on the same asset;
    because the interval is half-open, two agreements that meet exactly
    end-to-start do not overlap and are both allowed."

    Design: Difficulty/resource_temporal_overlap/rental_half_open_overlap_backtoback_allowed
    """
    asset = create_rental_asset(category="TILLER", daily_rate_cents=5000,
                                deposit_cents=0)
    a = create_reservation(asset["id"], "2026-03-01T08:00:00Z", "2026-03-02T08:00:00Z")
    assert a["status"] == "RESERVED"
    # B starts exactly at A's due_at -> adjacency, no overlap.
    res_b = api.create_rental_agreement(
        {"rental_asset_id": asset["id"], "start_at": "2026-03-02T08:00:00Z",
         "due_at": "2026-03-03T08:00:00Z"}, RENTAL)
    b = validate_success(res_b, 201)
    assert b["status"] == "RESERVED"


def test_rental_interior_overlap_rejected(api):
    """PRD 3.7: "The reservation is rejected with ERR_RENTAL_OVERLAP if its
    interval overlaps any non-terminal agreement already on the same asset."

    Design: Difficulty/resource_temporal_overlap/rental_half_open_overlap_backtoback_allowed
    """
    asset = create_rental_asset(category="TILLER", daily_rate_cents=5000,
                                deposit_cents=0)
    create_reservation(asset["id"], "2026-03-01T08:00:00Z", "2026-03-02T08:00:00Z")
    # A window inside A's [08:00, next-08:00) interval overlaps it.
    res = api.create_rental_agreement(
        {"rental_asset_id": asset["id"], "start_at": "2026-03-01T12:00:00Z",
         "due_at": "2026-03-01T18:00:00Z"}, RENTAL)
    validate_error(res, "ERR_RENTAL_OVERLAP")


# ─── Difficulty: resource_temporal_overlap (service station) ────────────────

def test_station_buffer_expanded_overlap_rejected(api):
    """PRD 3.8: "The booking is checked for conflicts against the station: the
    requested window, expanded by the station's buffer_minutes on both ends,
    must not overlap any non-terminal ticket on that station, or the booking is
    rejected with ERR_STATION_BOOKING_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/service_station_buffer_expanded_overlap
    """
    station = create_station(buffer_minutes=30)
    book_ticket(station["id"], "PAINT_MIX",
                "2026-04-01T09:00:00Z", "2026-04-01T09:30:00Z")
    # 09:45 falls inside the 30-minute clean-down buffer after the 09:30 end.
    res = api.create_service_ticket(
        {"service_station_id": station["id"], "service_type": "KEY_CUT",
         "scheduled_start": "2026-04-01T09:45:00Z",
         "scheduled_end": "2026-04-01T10:00:00Z"}, SALES)
    validate_error(res, "ERR_STATION_BOOKING_CONFLICT")


def test_station_booking_well_clear_of_buffer_allowed(api):
    """PRD 3.8: "the requested window, expanded by the station's buffer_minutes
    on both ends, must not overlap any non-terminal ticket on that station."
    PRD 3.8: "A ticket begins in status BOOKED with fee_cents at 0."

    Design: Difficulty/resource_temporal_overlap/service_station_buffer_expanded_overlap
    """
    station = create_station(buffer_minutes=30)
    book_ticket(station["id"], "PAINT_MIX",
                "2026-04-01T09:00:00Z", "2026-04-01T09:30:00Z")
    # A window hours later is clear even if both windows are buffer-expanded by
    # 30 minutes on every end — no PRD-faithful reading produces a conflict.
    res = api.create_service_ticket(
        {"service_station_id": station["id"], "service_type": "KEY_CUT",
         "scheduled_start": "2026-04-01T13:00:00Z",
         "scheduled_end": "2026-04-01T13:15:00Z"}, SALES)
    ticket = validate_success(res, 201)
    assert ticket["status"] == "BOOKED"
    assert ticket["fee_cents"] == 0
