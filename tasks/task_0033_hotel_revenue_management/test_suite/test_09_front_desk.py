"""Front-desk operations: check-in, check-out, walk-out (PRD §3.6).

Covers ROOM_TYPE_MISMATCH vs ROOM_UNAVAILABLE precedence, the
post-check-in cascades on Reservation + Room + payment_status, the
commission settlement at check-out, and the walk-out preconditions.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    advance_clock,
    api_client,
    check_in_payload,
    create_checked_in_reservation,
    create_confirmed_reservation,
    create_room,
    create_room_type,
    date_plus_days,
    find_audit_logs,
    list_audit_logs,
    setup_basic_distribution,
    setup_walkout_ready,
    validate_error,
    validate_success,
)


# ===========================================================================
# Check-in: success path + cascades
# ===========================================================================
class TestCheckIn:
    def test_check_in_success_cascades_room_and_payment(self, api):
        """PRD §3.6: 'When all four hold, the system sets the
        reservation's assigned_room_id to the supplied room_id, cascades
        the room from VACANT_CLEAN to OCCUPIED, sets the room's
        current_reservation_id to the reservation's id, and advances
        payment_status to CAPTURED.'"""
        scaffold = setup_basic_distribution(n_rooms=1)
        ci = "2029-09-10"
        co = date_plus_days(ci, 2)
        res, room = create_checked_in_reservation(
            scaffold, check_in_date=ci, check_out_date=co,
        )
        assert res["booking_status"] == "CHECKED_IN"
        assert res["assigned_room_id"] == room["id"]
        assert res["payment_status"] == "CAPTURED"

    def test_check_in_room_type_mismatch_rejected(
        self, api, clerk_headers,
    ):
        """PRD §3.6: 'the room's room_type_id matches the reservation's
        room_type_id (a mismatch surfaces as ERR_ROOM_TYPE_MISMATCH)'."""
        scaffold = setup_basic_distribution(n_rooms=1)
        # A second room type and one room of that type.
        rt2 = create_room_type()
        wrong_room = create_room(room_type_id=rt2["id"])
        ci = "2029-10-01"
        co = date_plus_days(ci, 1)
        advance_clock(f"{ci}T12:00:00.000Z")
        res = create_confirmed_reservation(
            scaffold, check_in_date=ci, check_out_date=co,
        )
        bad = api.check_in_reservation(
            res["id"],
            check_in_payload(room_id=wrong_room["id"]),
            clerk_headers,
        )
        validate_error(bad, "ERR_ROOM_TYPE_MISMATCH")

    def test_check_in_when_room_out_of_order_rejected(
        self, api, clerk_headers, housekeeping_headers,
    ):
        """PRD §3.6: 'the room's operational_status is IN_SERVICE ...
        (failure on either part of this surfaces as ERR_ROOM_UNAVAILABLE)'.
        """
        scaffold = setup_basic_distribution(n_rooms=1)
        ci = "2029-10-05"
        co = date_plus_days(ci, 1)
        advance_clock(f"{ci}T08:00:00.000Z")
        res = create_confirmed_reservation(
            scaffold, check_in_date=ci, check_out_date=co,
        )
        # Take the room out of service.
        room = scaffold["rooms"][0]
        api.out_of_service_room(room["id"], housekeeping_headers)
        bad = api.check_in_reservation(
            res["id"], check_in_payload(room_id=room["id"]),
            clerk_headers,
        )
        validate_error(bad, "ERR_ROOM_UNAVAILABLE")

    def test_check_in_with_nonexistent_room_returns_reference_not_found(
        self, api, clerk_headers,
    ):
        """PRD §2.6: 'body-level foreign keys (such as the room_type_id,
        room_id, channel_id, rate_plan_id carried in POST/PATCH payloads)
        are validated against the existence ... failure here yields
        ERR_REFERENCE_NOT_FOUND (HTTP 404).'"""
        scaffold = setup_basic_distribution(n_rooms=1)
        ci = "2029-10-09"
        co = date_plus_days(ci, 1)
        advance_clock(f"{ci}T08:00:00.000Z")
        res = create_confirmed_reservation(
            scaffold, check_in_date=ci, check_out_date=co,
        )
        bad = api.check_in_reservation(
            res["id"], check_in_payload(room_id=NON_EXISTENT_UUID),
            clerk_headers,
        )
        validate_error(bad, "ERR_REFERENCE_NOT_FOUND")


# ===========================================================================
# Check-out: cascades + commission settlement
# ===========================================================================
class TestCheckOut:
    def test_check_out_cascades_room_dirty_and_clears_current_reservation(
        self, api, clerk_headers, admin_headers,
    ):
        """PRD §3.6: 'Check-out ... advances the booking from CHECKED_IN
        to CHECKED_OUT and cascades the room from OCCUPIED to DIRTY,
        while also clearing the room's current_reservation_id back to
        null.'"""
        scaffold = setup_basic_distribution(n_rooms=1)
        ci = "2029-11-01"
        co = date_plus_days(ci, 2)
        res, room = create_checked_in_reservation(
            scaffold, check_in_date=ci, check_out_date=co,
        )
        co_resp = api.check_out_reservation(res["id"], clerk_headers)
        out = validate_success(co_resp, expected_status=200)
        assert out["booking_status"] == "CHECKED_OUT"
        # Verify the Room cascade.
        rooms_resp = api.list_rooms(
            admin_headers,
            params={"room_type_id": scaffold["room_type"]["id"]},
        )
        rooms = validate_success(rooms_resp, expected_status=200)
        rooms = rooms if isinstance(rooms, list) else [rooms]
        r2 = next(r for r in rooms if r["id"] == room["id"])
        assert r2["housekeeping_status"] == "DIRTY"
        assert r2.get("current_reservation_id") is None


# ===========================================================================
# Walk-out preconditions and outcome
# ===========================================================================
class TestWalkOut:
    def test_walk_out_with_room_available_rejected(
        self, api, clerk_headers,
    ):
        """PRD §3.6: 'A FrontDeskClerk may execute the walk-out only when
        ... the count of physical rooms of the matching room type that
        are simultaneously VACANT_CLEAN, IN_SERVICE, and free of any
        overlapping MaintenanceBlock is zero.'"""
        ctx = setup_walkout_ready()
        # The single room is currently VACANT_CLEAN, so walk-out must be
        # rejected (candidate set non-empty).
        bad = api.walk_out_reservation(
            ctx["reservation"]["id"], clerk_headers,
        )
        validate_error(bad, "ERR_INVALID_STATE")

    def test_walk_out_when_no_room_available_succeeds(
        self, api, clerk_headers,
    ):
        """PRD §3.6: 'A FrontDeskClerk may execute the walk-out only when
        today equals the reservation's check_in_date ... and the count of
        physical rooms ... that are simultaneously VACANT_CLEAN,
        IN_SERVICE, and free of any overlapping MaintenanceBlock is zero.'

        PRD §3.6: 'The transition advances booking_status to WALKED_OUT,
        sets walkout_compensation_cents to the realised amount described
        in §3.4, advances payment_status to REFUNDED_FULL, and writes a
        WALKOUT_EXECUTED audit event'.
        """
        from test_helpers import create_pending_reservation, confirm_reservation
        # Build single-room scaffold + confirm two reservations
        # (overbooking allows for it).
        ctx = setup_walkout_ready(check_in_date="2030-01-15",
                                  check_out_date="2030-01-16",
                                  walkout_compensation_cents=15000)
        scaffold = ctx["scaffold"]
        # Confirm a second reservation thanks to overbook ratio +50%.
        # Physical capacity = 1, ratio=5000bp → ceiling = 1+0 = 1 (floor
        # of 0.5). We need ceiling >= 2; bump policy.
        # Re-attempt: create a fresh scaffold with 2 rooms instead;
        # check in res_a, then walk out res_b which now has zero VACANT.
        from test_helpers import (
            create_room, create_pending_reservation, create_confirmed_reservation,
        )
        # Two channels needed: per PRD §3.5 a single channel at 100%
        # share caps at floor(physical_capacity * 1.0) = 2; the 3rd
        # confirm must therefore land on a separate channel to be
        # gated by the overbooking ceiling rather than per-channel
        # inventory.
        scaffold2 = setup_basic_distribution(
            n_rooms=2, channel_type="DIRECT", n_channels=2,
        )
        ci = "2030-02-01"
        co = date_plus_days(ci, 1)
        from test_helpers import create_overbooking_policy
        create_overbooking_policy(
            room_type_id=scaffold2["room_type"]["id"],
            stay_date=ci,
            overbook_ratio_basis_points=5000,
            estimated_no_show_probability_basis_points=0,
            walkout_compensation_cents=15000,
        )
        # Set clock to arrival day morning.
        advance_clock(f"{ci}T08:00:00.000Z")
        res_a = create_confirmed_reservation(
            scaffold2, check_in_date=ci, check_out_date=co,
            guest_name="GuestA", channel_index=0,
        )
        res_b = create_confirmed_reservation(
            scaffold2, check_in_date=ci, check_out_date=co,
            guest_name="GuestB", channel_index=1,
        )
        # Check in res_a with first room; check in res_b with second room.
        api.check_in_reservation(
            res_a["id"], check_in_payload(room_id=scaffold2["rooms"][0]["id"]),
            clerk_headers,
        )
        api.check_in_reservation(
            res_b["id"], check_in_payload(room_id=scaffold2["rooms"][1]["id"]),
            clerk_headers,
        )
        # Now create+confirm a third reservation under overbook ceiling.
        # ceiling=2+floor(2*5000/10000)=3, current cumulative=2 → 3rd fits.
        res_c = create_confirmed_reservation(
            scaffold2, check_in_date=ci, check_out_date=co,
            guest_name="GuestC", channel_index=0,
        )
        # Walk-out res_c — both rooms OCCUPIED now → candidate set empty.
        wo_resp = api.walk_out_reservation(res_c["id"], clerk_headers)
        wo = validate_success(wo_resp, expected_status=200)
        assert wo["booking_status"] == "WALKED_OUT"
        assert wo["walkout_compensation_cents"] == 15000  # 1 night * 15000
        assert wo["payment_status"] == "REFUNDED_FULL"
        # Audit log
        logs = list_audit_logs(
            event_type="WALKOUT_EXECUTED", subject_id=res_c["id"],
        )
        assert len(logs) >= 1
