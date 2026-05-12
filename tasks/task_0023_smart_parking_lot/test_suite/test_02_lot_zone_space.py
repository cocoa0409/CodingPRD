"""ParkingLot, Zone, Space CRUD + availability cache (PRD §3.1)."""
from __future__ import annotations

import pytest

from test_helpers import (
    assert_parking_lot,
    assert_space,
    assert_zone,
    create_lot,
    create_lot_payload,
    create_space,
    create_zone,
    create_zone_payload,
    create_space_payload,
    setup_lot_zone_spaces,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.1 — Lot creation and pricing-knob defaults
# ===========================================================================
class TestLotCreation:
    def test_create_lot_minimal_payload(self, api, operator_headers):
        """PRD §3.1: 'A lot is materialized when an Operator creates it,
        supplying its display name, the IANA timezone whose calendar days
        bracket the daily-cap window, the base hourly_rate_cents charged
        per started hour after the free period, the per-calendar-day
        ceiling daily_cap_cents.'"""
        res = api.create_lot(create_lot_payload(), operator_headers)
        data = validate_success(res, expected_status=201)
        assert_parking_lot(data)

    def test_default_free_minutes_is_15(self, api, operator_headers):
        """PRD §3.1: 'free_minutes (the grace period in minutes from entry,
        default 15)'."""
        res = api.create_lot(
            create_lot_payload(free_minutes=None), operator_headers
        )
        data = validate_success(res, expected_status=201)
        assert data["free_minutes"] == 15

    def test_default_tow_grace_minutes_is_5(self, api, operator_headers):
        """PRD §3.1: 'tow_grace_minutes (the buffer in minutes after a
        session exit before the same space becomes re-bookable, default 5)'."""
        res = api.create_lot(
            create_lot_payload(tow_grace_minutes=None), operator_headers
        )
        data = validate_success(res, expected_status=201)
        assert data["tow_grace_minutes"] == 5

    def test_default_reservation_hold_minutes_is_15(self, api, operator_headers):
        """PRD §3.1: 'reservation_hold_minutes (the hold expiry duration in
        minutes after the requested start time before a no-show is realized,
        default 15)'."""
        res = api.create_lot(
            create_lot_payload(reservation_hold_minutes=None), operator_headers
        )
        data = validate_success(res, expected_status=201)
        assert data["reservation_hold_minutes"] == 15

    def test_default_no_show_penalty_is_500(self, api, operator_headers):
        """PRD §3.1: 'no_show_penalty_cents (the penalty applied to the payer
        of an unmatched reservation, default 500 cents)'."""
        res = api.create_lot(
            create_lot_payload(no_show_penalty_cents=None), operator_headers
        )
        data = validate_success(res, expected_status=201)
        assert data["no_show_penalty_cents"] == 500

    def test_default_partner_share_bps_is_0(self, api, operator_headers):
        """PRD §3.1: 'partner_share_bps (the partner's revenue share in
        basis points, default 0 — for example, 2000 means 20.00%)'."""
        res = api.create_lot(
            create_lot_payload(partner_share_bps=None), operator_headers
        )
        data = validate_success(res, expected_status=201)
        assert data["partner_share_bps"] == 0


# ===========================================================================
# §3.1 — Zone creation
# ===========================================================================
class TestZoneCreation:
    def test_create_zone(self, api, operator_headers):
        """PRD §3.1: 'an Operator defines zones each carrying a short code
        unique within its parent lot.'"""
        lot = create_lot()
        res = api.create_zone(
            lot["id"], create_zone_payload(zone_type="STANDARD"),
            operator_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_zone(data)
        assert data["zone_type"] == "STANDARD"
        assert data["lot_id"] == lot["id"]

    @pytest.mark.parametrize(
        "zone_type", ["STANDARD", "VIP", "DISABLED", "EMERGENCY"]
    )
    def test_zone_type_accepted_values(self, api, operator_headers, zone_type):
        """PRD §3.1: 'a zone_type drawn from STANDARD, VIP, DISABLED, or
        EMERGENCY.'"""
        lot = create_lot()
        res = api.create_zone(
            lot["id"], create_zone_payload(zone_type=zone_type),
            operator_headers,
        )
        data = validate_success(res, expected_status=201)
        assert data["zone_type"] == zone_type


# ===========================================================================
# §3.1 — Space creation and zone counter cascade
# ===========================================================================
class TestSpaceCreation:
    def test_create_space_returns_initial_state(self, api, operator_headers):
        """PRD §3.1: 'Both states default to FREE and UNRESERVED at creation.'"""
        lot = create_lot()
        zone = create_zone(lot["id"])
        res = api.create_space(
            lot["id"], zone["id"], create_space_payload(), operator_headers
        )
        data = validate_success(res, expected_status=201)
        assert_space(data)
        assert data["occupancy_status"] == "FREE"
        assert data["reservation_lock"] == "UNRESERVED"
        assert data.get("current_session_id") is None

    def test_space_creation_increments_zone_counters(self, api, operator_headers):
        """PRD §3.1: 'Adding a new space increments the parent zone's
        total_spaces and free_spaces each by one.'"""
        lot = create_lot()
        zone = create_zone(lot["id"])
        before_total = zone["total_spaces"]
        before_free = zone["free_spaces"]
        create_space(lot["id"], zone["id"], label="A-1")
        # Re-read availability for this lot.
        res = api.get_availability(lot["id"], operator_headers)
        body = res.json()
        zones = body.get("data", [])
        if not isinstance(zones, list):
            zones = [zones] if isinstance(zones, dict) else []
        # Find our zone in the response.
        our = [z for z in zones if z.get("id") == zone["id"]]
        assert our, f"Zone {zone['id']} missing from availability"
        z = our[0]
        assert z["total_spaces"] == before_total + 1
        assert z["free_spaces"] == before_free + 1

    def test_zone_free_spaces_definition(self, api, operator_headers):
        """PRD §3.1: 'The free_spaces count tracks how many child spaces
        simultaneously have occupancy_status equal to FREE and
        reservation_lock equal to UNRESERVED.'"""
        # Build lot with three spaces, all FREE/UNRESERVED.
        lot, zone, spaces = setup_lot_zone_spaces(space_count=3)
        z = api.get_availability(
            lot["id"], operator_headers, params={"zone_type": "STANDARD"}
        ).json().get("data", [])
        if isinstance(z, list):
            our = next((x for x in z if x["id"] == zone["id"]), None)
        elif isinstance(z, dict):
            our = z if z.get("id") == zone["id"] else None
        else:
            our = None
        assert our is not None
        assert our["total_spaces"] == 3
        assert our["free_spaces"] == 3


# ===========================================================================
# §3.1 — Real-time space read
# ===========================================================================
class TestSpaceRead:
    def test_read_space_exposes_state_dimensions(self, api, operator_headers):
        """PRD §3.1: 'Reading an individual space exposes its current
        occupancy_status, reservation_lock, and current_session_id so that
        gate operators and drivers can resolve a parking decision in real
        time.'"""
        lot, zone, spaces = setup_lot_zone_spaces(space_count=1)
        res = api.get_space(
            lot["id"], zone["id"], spaces[0]["id"], operator_headers
        )
        data = validate_success(res, expected_status=200)
        assert "occupancy_status" in data
        assert "reservation_lock" in data
        assert "current_session_id" in data


# ===========================================================================
# §2.6 — Hierarchy validation: zone must belong to lot
# ===========================================================================
class TestHierarchyValidation:
    def test_create_space_in_zone_of_other_lot_rejected(
        self, api, operator_headers
    ):
        """PRD §2.6: 'it confirms the lot exists, then the zone exists and
        belongs to that lot, then the space exists and belongs to that
        zone. The first identifier that fails to resolve causes the request
        to fail with ERR_NOT_FOUND.'"""
        lot_a = create_lot()
        lot_b = create_lot()
        zone_a = create_zone(lot_a["id"])
        # Use lot_b's id with zone_a's id — the zone belongs to lot_a.
        res = api.create_space(
            lot_b["id"], zone_a["id"], create_space_payload(), operator_headers
        )
        validate_error(res, "ERR_NOT_FOUND")
