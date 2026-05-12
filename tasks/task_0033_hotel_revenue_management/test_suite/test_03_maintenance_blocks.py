"""MaintenanceBlock half-open intervals, overlap, occupied check, lifecycle.

Covers PRD §3.1 maintenance-block prose, including:
- half-open [start_date, end_date) overlap semantics
- ERR_MAINTENANCE_OVERLAP
- ERR_ROOM_CURRENTLY_OCCUPIED
- SCHEDULED -> CANCELLED
- ACTIVE -> RELEASED cascade restoring the room

Boundary precision: abutting blocks (end == start) MUST NOT collide
because end_date is exclusive.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_maintenance_block,
    create_checked_in_reservation,
    create_maintenance_block_payload,
    create_room,
    create_room_type,
    date_plus_days,
    setup_active_maintenance_block,
    setup_basic_distribution,
    validate_error,
    validate_success,
)


# ===========================================================================
# Half-open overlap semantics + abutting allowed
# ===========================================================================
class TestMaintenanceOverlap:
    def test_abutting_blocks_allowed(self, api, housekeeping_headers):
        """PRD §3.1: 'an end_date (exclusive — the window is the half-open
        interval beginning at start_date and ending strictly before
        end_date, so the day equal to end_date is not part of the block)'.

        Therefore abutting blocks (block1.end_date == block2.start_date)
        do not overlap and the second create must succeed.
        """
        rt = create_room_type()
        room = create_room(room_type_id=rt["id"])
        first = api.create_maintenance_block(
            create_maintenance_block_payload(
                room_id=room["id"],
                start_date="2027-02-01", end_date="2027-02-05",
            ),
            housekeeping_headers,
        )
        validate_success(first, expected_status=201)
        second = api.create_maintenance_block(
            create_maintenance_block_payload(
                room_id=room["id"],
                start_date="2027-02-05", end_date="2027-02-08",
            ),
            housekeeping_headers,
        )
        block2 = validate_success(second, expected_status=201)
        assert_maintenance_block(block2)

    def test_overlapping_blocks_rejected(self, api, housekeeping_headers):
        """PRD §3.1: 'Any attempt to create a block whose half-open
        interval overlaps any other block on the same room whose status
        is SCHEDULED or ACTIVE is rejected with ERR_MAINTENANCE_OVERLAP.'"""
        rt = create_room_type()
        room = create_room(room_type_id=rt["id"])
        first = api.create_maintenance_block(
            create_maintenance_block_payload(
                room_id=room["id"],
                start_date="2027-02-01", end_date="2027-02-05",
            ),
            housekeeping_headers,
        )
        validate_success(first, expected_status=201)
        # 1-day overlap on 2027-02-04
        second = api.create_maintenance_block(
            create_maintenance_block_payload(
                room_id=room["id"],
                start_date="2027-02-04", end_date="2027-02-06",
            ),
            housekeeping_headers,
        )
        validate_error(second, "ERR_MAINTENANCE_OVERLAP")

    def test_end_date_must_be_after_start_date(
        self, api, housekeeping_headers,
    ):
        """PRD §3.1: 'The end_date must be strictly later than the
        start_date.'"""
        rt = create_room_type()
        room = create_room(room_type_id=rt["id"])
        # equal dates → invalid
        bad = api.create_maintenance_block(
            create_maintenance_block_payload(
                room_id=room["id"],
                start_date="2027-03-01", end_date="2027-03-01",
            ),
            housekeeping_headers,
        )
        validate_error(bad, "ERR_INVALID_INPUT")


# ===========================================================================
# Currently occupied room cannot host a new block
# ===========================================================================
class TestMaintenanceOccupiedRoom:
    def test_block_on_occupied_room_rejected(
        self, api, clerk_headers, housekeeping_headers,
    ):
        """PRD §3.1: 'a block cannot be created on a room whose
        housekeeping_status is currently OCCUPIED; that attempt is
        rejected with ERR_ROOM_CURRENTLY_OCCUPIED.'"""
        scaffold = setup_basic_distribution(n_rooms=1)
        ci = "2026-08-10"
        co = date_plus_days(ci, 2)
        _, room = create_checked_in_reservation(
            scaffold, check_in_date=ci, check_out_date=co,
        )
        # Room is OCCUPIED. Try to create a block.
        block_resp = api.create_maintenance_block(
            create_maintenance_block_payload(
                room_id=room["id"],
                start_date="2026-08-13", end_date="2026-08-14",
            ),
            housekeeping_headers,
        )
        validate_error(block_resp, "ERR_ROOM_CURRENTLY_OCCUPIED")


# ===========================================================================
# SCHEDULED -> CANCELLED
# ===========================================================================
class TestCancelScheduledBlock:
    def test_cancel_scheduled_block_succeeds(self, api, housekeeping_headers):
        """PRD §3.1: 'A SCHEDULED block may also be cancelled by a
        HousekeepingStaff member, advancing status to CANCELLED.'"""
        rt = create_room_type()
        room = create_room(room_type_id=rt["id"])
        block_resp = api.create_maintenance_block(
            create_maintenance_block_payload(
                room_id=room["id"],
                start_date="2030-01-01", end_date="2030-01-05",
            ),
            housekeeping_headers,
        )
        block = validate_success(block_resp, expected_status=201)
        cancel_resp = api.cancel_maintenance_block(
            block["id"], housekeeping_headers,
        )
        cancelled = validate_success(cancel_resp, expected_status=200)
        assert cancelled["status"] == "CANCELLED"

    def test_cannot_cancel_active_block(self, api, housekeeping_headers):
        """PRD §3.1: 'the precondition is that the block is still
        SCHEDULED (an ACTIVE block cannot be cancelled — it must be
        released).'"""
        ctx = setup_active_maintenance_block(
            block_start_date="2026-12-15",
            block_end_date="2026-12-20",
            activate_at_iso="2026-12-16T10:00:00.000Z",
        )
        cancel_resp = api.cancel_maintenance_block(
            ctx["block"]["id"], housekeeping_headers,
        )
        validate_error(cancel_resp, "ERR_INVALID_STATE")


# ===========================================================================
# ACTIVE -> RELEASED cascade
# ===========================================================================
class TestReleaseActiveBlock:
    def test_release_active_block_restores_room_state(
        self, api, housekeeping_headers, admin_headers,
    ):
        """PRD §3.1: 'The release cascade restores the room only if no
        other ACTIVE block still covers it — in that case
        operational_status returns to IN_SERVICE, and housekeeping_status
        is set to DIRTY on the assumption the technician left the room
        dusty.'"""
        ctx = setup_active_maintenance_block(
            block_start_date="2026-10-01",
            block_end_date="2026-10-05",
            activate_at_iso="2026-10-02T08:00:00.000Z",
        )
        # Room should be OUT_OF_ORDER now.
        rel_resp = api.release_maintenance_block(
            ctx["block"]["id"], housekeeping_headers,
        )
        block = validate_success(rel_resp, expected_status=200)
        assert block["status"] == "RELEASED"
        # Verify the room cascaded back to IN_SERVICE + DIRTY.
        rooms_resp = api.list_rooms(
            admin_headers, params={"room_type_id": ctx["room_type"]["id"]},
        )
        rooms = validate_success(rooms_resp, expected_status=200)
        rooms = rooms if isinstance(rooms, list) else [rooms]
        room_after = next(r for r in rooms if r["id"] == ctx["room"]["id"])
        assert room_after["operational_status"] == "IN_SERVICE"
        assert room_after["housekeeping_status"] == "DIRTY"
