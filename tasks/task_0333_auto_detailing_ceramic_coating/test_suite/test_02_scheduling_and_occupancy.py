"""Scheduling: the occupancy window (SHOP blocks through cure, MOBILE crew
leaves before cure), bay half-open overlap, and mobile travel-buffer overlap.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    make_customer_headers,
    set_clock, seed_package, seed_vehicle_size_rate,
    create_customer, create_service_bay, create_mobile_unit,
    book_shop_appointment, book_mobile_appointment,
)
from test_helpers.factories import create_appointment_payload


# ──────────────────────────────────────────────────────────────────────
# Corner / calculations / occupancy_window_shop_ceramic_blocks_through_cure
# ──────────────────────────────────────────────────────────────────────

def test_shop_ceramic_occupancy_blocks_through_cure():
    """PRD §3.2: "for a `SHOP` job the bay stays blocked through the cure, so `occupancy_end_utc` equals `scheduled_start_utc` plus busy minutes plus cure minutes (the same instant as release)"
    PRD §3.2: "The `vehicle_release_utc` — the earliest instant the customer may take the vehicle — is the `scheduled_start_utc` advanced by the busy minutes plus the cure minutes, and this holds for both location modes."

    Design: Corner/calculations/occupancy_window_shop_ceramic_blocks_through_cure
    """
    set_clock("2026-06-15T07:00:00Z")
    seed_package(tier="CERAMIC")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="ow1@x.com", full_name="Ow One")
    bay = create_service_bay(bay_code="OW1", supports_ceramic=True)
    appt = book_shop_appointment(
        cust["id"], bay, tier="CERAMIC", vehicle_size="SEDAN",
        scheduled_start_utc="2026-06-15T08:00:00Z",
    )
    # prep45 + service240 + cure1440 = 1725 min from 08:00 -> next day 12:45.
    assert appt["occupancy_end_utc"] == "2026-06-16T12:45:00.000Z"
    assert appt["vehicle_release_utc"] == "2026-06-16T12:45:00.000Z"


# ──────────────────────────────────────────────────────────────────────
# Corner / calculations / occupancy_window_mobile_ceramic_crew_leaves_before_cure
# ──────────────────────────────────────────────────────────────────────

def test_mobile_ceramic_crew_leaves_before_cure():
    """PRD §3.2: "for a `MOBILE` job the crew leaves before the cure, so `occupancy_end_utc` equals `scheduled_start_utc` plus busy minutes only."
    PRD §3.2: "The `vehicle_release_utc` — the earliest instant the customer may take the vehicle — is the `scheduled_start_utc` advanced by the busy minutes plus the cure minutes, and this holds for both location modes."

    Design: Corner/calculations/occupancy_window_mobile_ceramic_crew_leaves_before_cure
    """
    set_clock("2026-06-15T07:00:00Z")
    seed_package(tier="CERAMIC")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="om1@x.com", full_name="Om One")
    unit = create_mobile_unit(unit_code="OM1", travel_buffer_minutes=30)
    appt = book_mobile_appointment(
        cust["id"], unit["id"], tier="CERAMIC", vehicle_size="SEDAN",
        scheduled_start_utc="2026-06-15T08:00:00Z",
    )
    # busy = prep45 + service240 = 285 min -> 12:45 same day; release adds cure.
    assert appt["occupancy_end_utc"] == "2026-06-15T12:45:00.000Z"
    assert appt["vehicle_release_utc"] == "2026-06-16T12:45:00.000Z"


# ──────────────────────────────────────────────────────────────────────
# Difficulty / resource_temporal_overlap /
#   shop_bay_half_open_overlap_rejected_adjacent_allowed
# ──────────────────────────────────────────────────────────────────────

def _seed_bay_with_ceramic_occupancy():
    set_clock("2026-06-15T07:00:00Z")
    seed_package(tier="CERAMIC")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="xan@x.com", full_name="Xan C")
    bay = create_service_bay(bay_code="B10", supports_ceramic=True)
    appt1 = book_shop_appointment(
        cust["id"], bay, tier="CERAMIC", vehicle_size="SEDAN",
        scheduled_start_utc="2026-06-15T08:00:00Z",
    )
    # Bay version advanced by the booking; re-read for a fresh OCC version.
    bay_after = validate_success(
        api_client.get_service_bay(bay["id"], make_customer_headers(cust["id"])), 200
    )
    return cust, bay_after, appt1


def test_shop_bay_overlap_one_minute_before_end_rejected():
    """PRD §3.3: "A candidate booking conflicts with an existing appointment on the same `service_bay_id` when the candidate's start is strictly before the existing appointment's `occupancy_end_utc` and the existing appointment's start is strictly before the candidate's `occupancy_end_utc"
    PRD §3.3: "A conflict is rejected with `ERR_BAY_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/shop_bay_half_open_overlap_rejected_adjacent_allowed
    """
    cust, bay_after, _ = _seed_bay_with_ceramic_occupancy()
    payload = create_appointment_payload(
        cust["id"], tier="CERAMIC", vehicle_size="SEDAN", location_mode="SHOP",
        scheduled_start_utc="2026-06-16T12:44:00Z", service_bay_id=bay_after["id"],
        expected_service_bay_version=bay_after["version"],
    )
    res = api_client.create_appointment(payload, make_customer_headers(cust["id"]))
    validate_error(res, "ERR_BAY_TIME_CONFLICT", 409)


def test_shop_bay_adjacent_booking_at_boundary_allowed():
    """PRD §3.3: "because the comparison is strict, two intervals that merely touch at a boundary (the candidate starting exactly when the other ends) do not conflict."

    Design: Difficulty/resource_temporal_overlap/shop_bay_half_open_overlap_rejected_adjacent_allowed
    """
    cust, bay_after, _ = _seed_bay_with_ceramic_occupancy()
    payload = create_appointment_payload(
        cust["id"], tier="CERAMIC", vehicle_size="SEDAN", location_mode="SHOP",
        scheduled_start_utc="2026-06-16T12:45:00Z", service_bay_id=bay_after["id"],
        expected_service_bay_version=bay_after["version"],
    )
    appt2 = validate_success(
        api_client.create_appointment(payload, make_customer_headers(cust["id"])), 201
    )
    assert appt2["work_status"] == "BOOKED"


# ──────────────────────────────────────────────────────────────────────
# Corner / calculations / shop_bay_adjacent_booking_allowed_boundary
#   (NOTE: this corner instance asserts the same adjacency-allowed boundary as
#   the difficulty instance above; it is a non-stub corner instance and gets its
#   own test tagged to Corner.)
# ──────────────────────────────────────────────────────────────────────

def test_shop_bay_adjacent_booking_allowed_corner_boundary():
    """PRD §3.3: "because the comparison is strict, two intervals that merely touch at a boundary (the candidate starting exactly when the other ends) do not conflict."

    Design: Corner/calculations/shop_bay_adjacent_booking_allowed_boundary
    """
    set_clock("2026-06-15T07:00:00Z")
    seed_package(tier="CERAMIC")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="ab1@x.com", full_name="Ab One")
    bay = create_service_bay(bay_code="AB1", supports_ceramic=True)
    appt1 = book_shop_appointment(
        cust["id"], bay, tier="CERAMIC", vehicle_size="SEDAN",
        scheduled_start_utc="2026-06-15T08:00:00Z",
    )
    bay_after = validate_success(
        api_client.get_service_bay(bay["id"], make_customer_headers(cust["id"])), 200
    )
    payload = create_appointment_payload(
        cust["id"], tier="CERAMIC", vehicle_size="SEDAN", location_mode="SHOP",
        scheduled_start_utc="2026-06-16T12:45:00Z", service_bay_id=bay_after["id"],
        expected_service_bay_version=bay_after["version"],
    )
    appt2 = validate_success(
        api_client.create_appointment(payload, make_customer_headers(cust["id"])), 201
    )
    assert appt2["work_status"] == "BOOKED"


# ──────────────────────────────────────────────────────────────────────
# Difficulty / resource_temporal_overlap /
#   mobile_unit_travel_buffer_overlap_rejected_gap_below_buffer
# ──────────────────────────────────────────────────────────────────────

def _seed_unit_with_full_occupancy(email, unit_code):
    set_clock("2026-06-16T08:00:00Z")
    seed_package(tier="FULL")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email=email, full_name="Buffer Test")
    unit = create_mobile_unit(unit_code=unit_code, travel_buffer_minutes=30)
    book_mobile_appointment(
        cust["id"], unit["id"], tier="FULL", vehicle_size="SEDAN",
        scheduled_start_utc="2026-06-16T09:00:00Z",
    )
    return cust, unit


def test_mobile_buffer_gap_below_buffer_rejected():
    """PRD §3.3: "Two jobs on the same `mobile_unit_id` need a gap of at least that unit's `travel_buffer_minutes` between them."
    PRD §3.3: "A gap of exactly the buffer is allowed; only a gap strictly shorter than the buffer conflicts. As with bays, only existing appointments on that unit whose `work_status` is not `CANCELLED`, `NO_SHOW`, or `RELEASED` are considered, and a violation is rejected with `ERR_MOBILE_BUFFER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/mobile_unit_travel_buffer_overlap_rejected_gap_below_buffer
    """
    cust, unit = _seed_unit_with_full_occupancy("yas@x.com", "M5")
    # First occupancy_end = 09:00 + 140 = 11:20. Candidate at 11:49 -> gap 29 < 30.
    payload = create_appointment_payload(
        cust["id"], tier="FULL", vehicle_size="SEDAN", location_mode="MOBILE",
        scheduled_start_utc="2026-06-16T11:49:00Z", mobile_unit_id=unit["id"],
    )
    res = api_client.create_appointment(payload, make_customer_headers(cust["id"]))
    validate_error(res, "ERR_MOBILE_BUFFER_CONFLICT", 409)


def test_mobile_buffer_exact_gap_allowed():
    """PRD §3.3: "A gap of exactly the buffer is allowed; only a gap strictly shorter than the buffer conflicts."

    Design: Difficulty/resource_temporal_overlap/mobile_unit_travel_buffer_overlap_rejected_gap_below_buffer
    """
    cust, unit = _seed_unit_with_full_occupancy("yas2@x.com", "M5b")
    # gap exactly 30 min: candidate at 11:50.
    payload = create_appointment_payload(
        cust["id"], tier="FULL", vehicle_size="SEDAN", location_mode="MOBILE",
        scheduled_start_utc="2026-06-16T11:50:00Z", mobile_unit_id=unit["id"],
    )
    appt2 = validate_success(
        api_client.create_appointment(payload, make_customer_headers(cust["id"])), 201
    )
    assert appt2["work_status"] == "BOOKED"


# ──────────────────────────────────────────────────────────────────────
# Corner / calculations / mobile_buffer_exact_gap_allowed_boundary
# ──────────────────────────────────────────────────────────────────────

def test_mobile_buffer_exact_gap_allowed_corner_boundary():
    """PRD §3.3: "A gap of exactly the buffer is allowed; only a gap strictly shorter than the buffer conflicts."

    Design: Corner/calculations/mobile_buffer_exact_gap_allowed_boundary
    """
    cust, unit = _seed_unit_with_full_occupancy("mb1@x.com", "MB1")
    payload = create_appointment_payload(
        cust["id"], tier="FULL", vehicle_size="SEDAN", location_mode="MOBILE",
        scheduled_start_utc="2026-06-16T11:50:00Z", mobile_unit_id=unit["id"],
    )
    appt2 = validate_success(
        api_client.create_appointment(payload, make_customer_headers(cust["id"])), 201
    )
    assert appt2["work_status"] == "BOOKED"
