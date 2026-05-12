"""RoomType and Room lifecycles (PRD §3.1).

Covers RoomType field constraints, Room creation, the housekeeping
state machine (VACANT_CLEAN <-> OCCUPIED <-> DIRTY) and the operational
state machine (IN_SERVICE <-> OUT_OF_ORDER), and the cross-dimension
guard rules.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_room,
    assert_room_type,
    create_room,
    create_room_payload,
    create_room_type,
    create_room_type_payload,
    setup_active_maintenance_block,
    setup_basic_distribution,
    validate_error,
    validate_success,
)


# ===========================================================================
# RoomType create — successful path + boundary on base_rate_cents
# ===========================================================================
class TestRoomTypeCreate:
    def test_create_room_type_success(self, api, admin_headers):
        """PRD §3.1: 'Every newly created room type begins life with status
        set to ACTIVE'."""
        res = api.create_room_type(
            create_room_type_payload(
                code="STD01", name="Standard Room",
                base_rate_cents=15000, max_occupancy=2,
            ),
            admin_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_room_type(data)
        assert data["status"] == "ACTIVE"
        assert data["base_rate_cents"] == 15000
        assert data["max_occupancy"] == 2

    def test_create_room_type_base_rate_below_minimum_rejected(
        self, api, admin_headers,
    ):
        """PRD §3.1: 'a default nightly base_rate_cents (which acts as a
        per-night floor when no override applies and must be at least
        1000, i.e. ten dollars).'"""
        payload = create_room_type_payload(base_rate_cents=999)
        res = api.create_room_type(payload, admin_headers)
        validate_error(res, "ERR_INVALID_INPUT")

    @pytest.mark.parametrize("bad_occ", [0, 11, -1])
    def test_create_room_type_max_occupancy_out_of_range_rejected(
        self, api, admin_headers, bad_occ,
    ):
        """PRD §3.1: 'a max_occupancy between 1 and 10 inclusive.'"""
        payload = create_room_type_payload(max_occupancy=bad_occ)
        res = api.create_room_type(payload, admin_headers)
        validate_error(res, "ERR_INVALID_INPUT")

    def test_room_type_total_physical_rooms_increments_on_room_create(
        self, api, admin_headers,
    ):
        """PRD §3.1: 'The system maintains a derived total_physical_rooms
        count for each room type — the number of ACTIVE Room records
        currently bound to it.'"""
        rt = create_room_type()
        # baseline 0, then 2 rooms → 2
        create_room(room_type_id=rt["id"])
        create_room(room_type_id=rt["id"])
        res = api.get_room_type(rt["id"], admin_headers)
        rt2 = validate_success(res, expected_status=200)
        assert rt2["total_physical_rooms"] == 2


# ===========================================================================
# Room create + initial state
# ===========================================================================
class TestRoomCreate:
    def test_create_room_initial_state(self, api, admin_headers):
        """PRD §3.1: 'Both default at creation: housekeeping_status to
        VACANT_CLEAN and operational_status to IN_SERVICE.'"""
        rt = create_room_type()
        res = api.create_room(
            create_room_payload(room_type_id=rt["id"]), admin_headers,
        )
        room = validate_success(res, expected_status=201)
        assert_room(room)
        assert room["housekeeping_status"] == "VACANT_CLEAN"
        assert room["operational_status"] == "IN_SERVICE"
        assert room["lifecycle_status"] == "ACTIVE"
        assert room.get("current_reservation_id") is None


# ===========================================================================
# Housekeeping state machine
# ===========================================================================
class TestHousekeepingStateMachine:
    def test_clean_dirty_room_returns_to_vacant_clean(
        self, api, admin_headers, clerk_headers, housekeeping_headers,
    ):
        """PRD §3.1: 'a HousekeepingStaff member explicitly cleans a
        DIRTY room — provided the room is IN_SERVICE — to return it to
        VACANT_CLEAN.'"""
        # Build a checked-out reservation so the room becomes DIRTY.
        from test_helpers import (
            create_checked_in_reservation,
            date_plus_days,
        )
        scaffold = setup_basic_distribution(n_rooms=1)
        ci = "2026-05-01"
        co = date_plus_days(ci, 1)
        res, room = create_checked_in_reservation(
            scaffold, check_in_date=ci, check_out_date=co,
        )
        co_resp = api.check_out_reservation(res["id"], clerk_headers)
        validate_success(co_resp, expected_status=200)
        # Room should now be DIRTY.
        clean_resp = api.clean_room(room["id"], housekeeping_headers)
        cleaned = validate_success(clean_resp, expected_status=200)
        assert cleaned["housekeeping_status"] == "VACANT_CLEAN"

    def test_clean_vacant_clean_room_rejected(
        self, api, housekeeping_headers,
    ):
        """PRD §3.1: 'a HousekeepingStaff member explicitly cleans a
        DIRTY room ... to return it to VACANT_CLEAN.' Cleaning a non-DIRTY
        room is not permitted by the housekeeping cycle."""
        rt = create_room_type()
        room = create_room(room_type_id=rt["id"])
        res = api.clean_room(room["id"], housekeeping_headers)
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# Operational state machine
# ===========================================================================
class TestOperationalStateMachine:
    def test_take_room_out_of_service_when_vacant(
        self, api, housekeeping_headers,
    ):
        """PRD §3.1: 'A HousekeepingStaff member can take a room out of
        service, transitioning operational_status from IN_SERVICE to
        OUT_OF_ORDER, but only when housekeeping_status is not OCCUPIED.'"""
        rt = create_room_type()
        room = create_room(room_type_id=rt["id"])
        res = api.out_of_service_room(room["id"], housekeeping_headers)
        updated = validate_success(res, expected_status=200)
        assert updated["operational_status"] == "OUT_OF_ORDER"

    def test_take_room_out_of_service_while_occupied_rejected(
        self, api, clerk_headers, housekeeping_headers,
    ):
        """PRD §3.1: '... but only when housekeeping_status is not
        OCCUPIED.'"""
        from test_helpers import create_checked_in_reservation, date_plus_days
        scaffold = setup_basic_distribution(n_rooms=1)
        ci = "2026-05-15"
        co = date_plus_days(ci, 1)
        _, room = create_checked_in_reservation(
            scaffold, check_in_date=ci, check_out_date=co,
        )
        # Room is now OCCUPIED.
        res = api.out_of_service_room(room["id"], housekeeping_headers)
        validate_error(res, "ERR_INVALID_STATE")

    def test_return_to_service_blocked_by_active_block(
        self, api, housekeeping_headers,
    ):
        """PRD §3.1: 'The corresponding return-to-service transition flips
        operational_status from OUT_OF_ORDER back to IN_SERVICE and is
        permitted only when no MaintenanceBlock for the room is currently
        in ACTIVE status.'"""
        ctx = setup_active_maintenance_block(
            block_start_date="2026-12-01",
            block_end_date="2026-12-05",
            activate_at_iso="2026-12-02T10:00:00.000Z",
        )
        # The room is now OUT_OF_ORDER (cascaded from ACTIVE block).
        res = api.return_to_service_room(
            ctx["room"]["id"], housekeeping_headers,
        )
        validate_error(res, "ERR_INVALID_STATE")
