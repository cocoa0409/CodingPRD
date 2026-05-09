"""
Maintenance-window tests (PRD §2.5 / §2.7 priority 9 / priority 12).

Half-open interval semantics: touching is permitted, strict overlap rejected.
A SCHEDULED window covering clock.now() blocks borrow, return, return-retry.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    advance_clock_to,
    api_client,
    assert_maintenance_window,
    borrow_for,
    create_cabinet,
    create_device,
    create_location_partner,
    create_pricing_plan,
    heartbeat,
    make_user_headers,
    schedule_maintenance,
    setup_borrow_environment,
    setup_funded_user,
    setup_pricing_plans,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Half-open interval semantics (PRD §2.5)
# ---------------------------------------------------------------------------


def test_touching_windows_permitted(api):
    """PRD §2.5: "two windows where the first one's window_end exactly equals
    the second one's window_start are permitted (they touch but do not
    overlap)."
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    schedule_maintenance(
        cabinet["id"], "2026-02-01T10:00:00Z", "2026-02-01T12:00:00Z"
    )
    res = api.create_maintenance_window(
        {
            "cabinet_id": cabinet["id"],
            "window_start": "2026-02-01T12:00:00Z",  # exactly touches
            "window_end": "2026-02-01T14:00:00Z",
        },
        ADMIN_HEADERS,
    )
    mw2 = validate_success(res, 201)
    assert_maintenance_window(mw2)
    assert mw2["status"] == "SCHEDULED"


def test_strict_overlap_rejected(api):
    """PRD §2.5: "any strict overlap is rejected with
    ERR_MAINTENANCE_WINDOW_OVERLAP."
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    schedule_maintenance(
        cabinet["id"], "2026-02-01T10:00:00Z", "2026-02-01T12:00:00Z"
    )
    res = api.create_maintenance_window(
        {
            "cabinet_id": cabinet["id"],
            "window_start": "2026-02-01T11:00:00Z",  # strict overlap
            "window_end": "2026-02-01T13:00:00Z",
        },
        ADMIN_HEADERS,
    )
    validate_error(res, "ERR_MAINTENANCE_WINDOW_OVERLAP")


# ---------------------------------------------------------------------------
# ERR_CABINET_UNDER_MAINTENANCE blocks borrow (PRD §2.5 / §2.7 priority 9)
# ---------------------------------------------------------------------------


def test_borrow_blocked_during_maintenance_window(api):
    """PRD §2.5: "When a SCHEDULED MaintenanceWindow exists for a cabinet
    such that window_start is at or before the current logical clock value
    and window_end is strictly after it, the same three operations — borrow,
    return, and return-retry — are rejected with
    ERR_CABINET_UNDER_MAINTENANCE."
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-02-01T11:00:00Z")
    heartbeat(cabinet["id"], "2026-02-01T11:00:00Z")
    create_device(cabinet["id"], 0, battery_level=80)
    user = setup_funded_user()
    schedule_maintenance(
        cabinet["id"], "2026-02-01T10:00:00Z", "2026-02-01T12:00:00Z"
    )
    res = api.create_rental(
        {"cabinet_id": cabinet["id"]}, make_user_headers(user["id"])
    )
    validate_error(res, "ERR_CABINET_UNDER_MAINTENANCE")


def test_borrow_succeeds_at_window_end_boundary(api):
    """PRD §2.5: "window_end is strictly after it" — at window_end the gate
    no longer applies (half-open semantics)."""
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-02-01T12:00:00Z")  # exactly window_end
    heartbeat(cabinet["id"], "2026-02-01T12:00:00Z")
    create_device(cabinet["id"], 0, battery_level=80)
    user = setup_funded_user()
    schedule_maintenance(
        cabinet["id"], "2026-02-01T10:00:00Z", "2026-02-01T12:00:00Z"
    )
    res = api.create_rental(
        {"cabinet_id": cabinet["id"]}, make_user_headers(user["id"])
    )
    rental = validate_success(res, 201)
    assert rental["rental_status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Cabinet OFFLINE — heartbeat older than 300s (PRD §2.5)
# ---------------------------------------------------------------------------


def test_cabinet_offline_blocks_borrow(api):
    """PRD §2.5: "A cabinet's online_status is ONLINE when its most recent
    heartbeat is younger than the heartbeat-timeout threshold of 300 seconds
    ... otherwise the cabinet is considered OFFLINE. New rentals from an
    OFFLINE cabinet ... are all rejected with ERR_CABINET_OFFLINE."
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T09:00:00Z")  # 1h stale
    create_device(cabinet["id"], 0, battery_level=80)
    user = setup_funded_user()
    res = api.create_rental(
        {"cabinet_id": cabinet["id"]}, make_user_headers(user["id"])
    )
    validate_error(res, "ERR_CABINET_OFFLINE")


def test_cabinet_online_at_heartbeat_just_under_300s(api):
    """PRD §2.5: 300s threshold — a fresh heartbeat keeps cabinet ONLINE."""
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    # Heartbeat 299 seconds before clock — still ONLINE.
    heartbeat(cabinet["id"], "2026-01-01T09:55:01Z")
    cab_after = validate_success(api.get_cabinet(cabinet["id"], ADMIN_HEADERS), 200)
    assert cab_after["online_status"] == "ONLINE"
