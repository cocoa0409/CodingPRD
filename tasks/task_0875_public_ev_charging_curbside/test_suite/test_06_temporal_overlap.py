"""Reservation half-open overlap and maintenance-window buffer overlap.

Difficulty: resource_temporal_overlap/{reservation_half_open...,maintenance_window_buffer...}.
"""
from test_helpers import (
    validate_success, validate_error,
    admin_headers, make_driver_headers,
    new_site, new_station, site_with_port, new_reservation, confirmed_reservation,
    create_maintenance_window_payload,
)


# --------------------------------------------------------------------------- #
# resource_temporal_overlap / reservation_half_open_overlap_on_port
# --------------------------------------------------------------------------- #
def test_overlapping_reservation_confirm_rejected(api):
    """PRD §3.5: "Overlap is judged on half-open intervals `[window_start, window_end)`:
    two windows conflict when one starts strictly before the other ends and vice versa,
    so windows that merely touch at an endpoint do not conflict. A genuine overlap is
    refused with `ERR_RESERVATION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/reservation_half_open_overlap_on_port
    """
    _, _, port = site_with_port(power_kw=100)
    confirmed_reservation(port["id"], driver_id="drv-1",
                          window_start="2026-05-04T10:00:00Z", window_end="2026-05-04T11:00:00Z")
    r2 = new_reservation(port["id"], driver_id="drv-2",
                         window_start="2026-05-04T10:30:00Z", window_end="2026-05-04T11:30:00Z")
    res = api.confirm_reservation(r2["id"], make_driver_headers("drv-2"))
    validate_error(res, "ERR_RESERVATION_OVERLAP")


def test_endpoint_touching_reservation_is_not_an_overlap(api):
    """PRD §3.5: "Overlap is judged on half-open intervals `[window_start, window_end)`:
    two windows conflict when one starts strictly before the other ends and vice versa,
    so windows that merely touch at an endpoint do not conflict."

    A window starting exactly when the confirmed one ends does not overlap, so the
    overlap gate does not fire — the confirm instead trips the availability gate.

    Design: Difficulty/resource_temporal_overlap/reservation_half_open_overlap_on_port
    """
    _, _, port = site_with_port(power_kw=100)
    confirmed_reservation(port["id"], driver_id="drv-1",
                          window_start="2026-05-04T10:00:00Z", window_end="2026-05-04T11:00:00Z")
    r2 = new_reservation(port["id"], driver_id="drv-2",
                         window_start="2026-05-04T11:00:00Z", window_end="2026-05-04T12:00:00Z")
    res = api.confirm_reservation(r2["id"], make_driver_headers("drv-2"))
    # touching windows do NOT conflict, so this is NOT an overlap rejection.
    validate_error(res, "ERR_PORT_NOT_AVAILABLE")


# --------------------------------------------------------------------------- #
# resource_temporal_overlap / maintenance_window_buffer_overlap_on_station
# --------------------------------------------------------------------------- #
def test_maintenance_window_within_buffer_rejected(api):
    """PRD §3.6: "A new window is refused with `ERR_MAINTENANCE_WINDOW_OVERLAP` when its
    closed interval `[window_start, window_end]` falls within 60 minutes of another
    `SCHEDULED` or `IN_PROGRESS` window on the same station — that is, consecutive
    windows on one station must be separated by at least an hour of clearance."

    Design: Difficulty/resource_temporal_overlap/maintenance_window_buffer_overlap_on_station
    """
    site = new_site()
    station = new_station(site["id"])
    validate_success(api.create_maintenance_window(
        create_maintenance_window_payload(station["id"], "2026-05-05T08:00:00Z",
                                           "2026-05-05T10:00:00Z", "inspection"),
        admin_headers()), 201)
    res = api.create_maintenance_window(
        create_maintenance_window_payload(station["id"], "2026-05-05T10:30:00Z",
                                           "2026-05-05T12:00:00Z", "repair"),
        admin_headers())
    validate_error(res, "ERR_MAINTENANCE_WINDOW_OVERLAP")


def test_maintenance_window_beyond_buffer_allowed(api):
    """PRD §3.6: "A new window is refused with `ERR_MAINTENANCE_WINDOW_OVERLAP` when its
    closed interval `[window_start, window_end]` falls within 60 minutes of another
    `SCHEDULED` or `IN_PROGRESS` window on the same station — that is, consecutive
    windows on one station must be separated by at least an hour of clearance."

    Design: Difficulty/resource_temporal_overlap/maintenance_window_buffer_overlap_on_station
    """
    site = new_site()
    station = new_station(site["id"])
    validate_success(api.create_maintenance_window(
        create_maintenance_window_payload(station["id"], "2026-05-05T08:00:00Z",
                                           "2026-05-05T10:00:00Z", "inspection"),
        admin_headers()), 201)
    # 2-hour gap (>= 60 minutes clearance) — allowed.
    created = validate_success(api.create_maintenance_window(
        create_maintenance_window_payload(station["id"], "2026-05-05T12:00:00Z",
                                           "2026-05-05T13:00:00Z", "repair"),
        admin_headers()), 201)
    assert created["status"] == "SCHEDULED"
