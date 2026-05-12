"""Concurrency / race-resolution tests (PRD §2.5, §2.7).

Each race in PRD §2.7 explicitly names a winner-loser pair and the
loser's specific error_id, so we can assert exact loser error here
(rather than the silence-pattern generic).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock,
    api_client,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    check_in_payload,
    create_confirmed_reservation,
    create_maintenance_block_payload,
    create_pending_reservation,
    create_room,
    create_room_type,
    date_plus_days,
    get_success_data,
    run_race,
    setup_basic_distribution,
    setup_channel_share_boundary,
    setup_with_n_confirmed_for_date,
    submit_rate_override,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# Race: two confirms on the same Reservation
# ===========================================================================
class TestConfirmSameReservationRace:
    def test_double_confirm_loser_invalid_state(self, api):
        """PRD §2.7: 'Two confirms on the same reservation. Serialization
        is on Reservation.booking_status; the first writer wins, and the
        second writer — finding the reservation already advanced past
        PENDING — is rejected with ERR_INVALID_STATE (HTTP 409).'"""
        scaffold = setup_basic_distribution(n_rooms=2)
        pending = create_pending_reservation(
            scaffold,
            check_in_date="2032-04-01", check_out_date="2032-04-03",
        )
        results = run_race(
            lambda: api.confirm_reservation(
                pending["id"], TEST_USERS["agent_headers"]),
            lambda: api.confirm_reservation(
                pending["id"], TEST_USERS["agent_headers"]),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_INVALID_STATE")


# ===========================================================================
# Race: per-channel inventory race
# ===========================================================================
class TestPerChannelInventoryRace:
    def test_confirm_race_for_last_channel_slot(self, api):
        """PRD §2.7: 'Confirms on different reservations competing for
        the last channel-allotted slot. Serialization is on the
        (room_type_id, stay_date, channel_id) per-channel inventory
        decrement. Exactly one confirm succeeds; the loser receives
        ERR_INVENTORY_EXHAUSTED (HTTP 409).'"""
        scaffold = setup_channel_share_boundary(
            physical_capacity=4, inventory_share_basis_points=2500,
        )
        ci = "2032-05-01"
        co = date_plus_days(ci, 1)
        a = create_pending_reservation(
            scaffold, check_in_date=ci, check_out_date=co,
            guest_name="A",
        )
        b = create_pending_reservation(
            scaffold, check_in_date=ci, check_out_date=co,
            guest_name="B",
        )
        results = run_race(
            lambda: api.confirm_reservation(
                a["id"], TEST_USERS["agent_headers"]),
            lambda: api.confirm_reservation(
                b["id"], TEST_USERS["agent_headers"]),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_INVENTORY_EXHAUSTED")


# ===========================================================================
# Race: overbooking ceiling
# ===========================================================================
class TestOverbookingRace:
    def test_two_confirms_at_ceiling_one_wins(self, api):
        """PRD §2.7: 'Confirms that together push a (room_type_id,
        stay_date) past its overbooking ceiling. Serialization is on the
        (room_type_id, stay_date) overbooking counter. The loser receives
        ERR_OVERBOOKING_LIMIT_EXCEEDED (HTTP 409).'"""
        # capacity=4, ratio=2500bp → ceiling=5. Pre-fill 5 confirmed.
        scaffold = setup_with_n_confirmed_for_date(
            physical_capacity=4, overbook_ratio_basis_points=2500,
            stay_date="2032-06-01", initial_confirmed=5,
        )
        # Two pending reservations both await confirmation; only zero
        # additional confirms are legal — both must be denied. Use this
        # variant: pre-fill 4 (cumulative=4), then race two confirms
        # — one is allowed (becomes 5, == ceiling), one is denied
        # (would become 6, > ceiling).
        scaffold = setup_with_n_confirmed_for_date(
            physical_capacity=4, overbook_ratio_basis_points=2500,
            stay_date="2032-06-02", initial_confirmed=4,
        )
        a = create_pending_reservation(
            scaffold,
            check_in_date=scaffold["check_in_date"],
            check_out_date=scaffold["check_out_date"],
            guest_name="A",
        )
        b = create_pending_reservation(
            scaffold,
            check_in_date=scaffold["check_in_date"],
            check_out_date=scaffold["check_out_date"],
            guest_name="B",
        )
        results = run_race(
            lambda: api.confirm_reservation(
                a["id"], TEST_USERS["agent_headers"]),
            lambda: api.confirm_reservation(
                b["id"], TEST_USERS["agent_headers"]),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_OVERBOOKING_LIMIT_EXCEEDED")


# ===========================================================================
# Race: two check-ins on the same room
# ===========================================================================
class TestCheckInRoomRace:
    def test_two_check_ins_same_room_one_wins(self, api):
        """PRD §2.7: 'Two check-ins targeting the same physical room.
        Serialization is on the Room.housekeeping_status transition from
        VACANT_CLEAN to OCCUPIED. At most one wins; the loser receives
        ERR_ROOM_UNAVAILABLE (HTTP 409).'"""
        scaffold = setup_basic_distribution(n_rooms=1)
        ci = "2032-07-01"
        co = date_plus_days(ci, 1)
        advance_clock(f"{ci}T08:00:00.000Z")
        res_a = create_confirmed_reservation(
            scaffold, check_in_date=ci, check_out_date=co,
            guest_name="A",
        )
        # Add a second room so there's enough capacity for two
        # CONFIRMED reservations, but race them onto the SAME room.
        from test_helpers import create_room
        create_room(room_type_id=scaffold["room_type"]["id"])
        res_b = create_confirmed_reservation(
            scaffold, check_in_date=ci, check_out_date=co,
            guest_name="B",
        )
        target_room = scaffold["rooms"][0]
        payload = check_in_payload(room_id=target_room["id"])
        results = run_race(
            lambda: api.check_in_reservation(
                res_a["id"], payload, TEST_USERS["clerk_headers"]),
            lambda: api.check_in_reservation(
                res_b["id"], payload, TEST_USERS["clerk_headers"]),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_ROOM_UNAVAILABLE")


# ===========================================================================
# Race: approve and reject on the same RateOverride
# ===========================================================================
class TestApproveRejectRace:
    def test_approve_reject_race(self, api):
        """PRD §2.7: 'Approve and reject racing on the same RateOverride.
        Serialization is on RateOverride.status. Exactly one transition
        wins; the loser receives ERR_INVALID_STATE (HTTP 409).'"""
        rt = create_room_type()
        pending = submit_rate_override(
            room_type_id=rt["id"], stay_date="2032-08-15",
        )
        results = run_race(
            lambda: api.approve_rate_override(
                pending["id"], TEST_USERS["manager_headers"]),
            lambda: api.reject_rate_override(
                pending["id"], TEST_USERS["manager_headers_alt"]),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_INVALID_STATE")


# ===========================================================================
# Race: two maintenance blocks overlap
# ===========================================================================
class TestMaintenanceOverlapRace:
    def test_two_overlapping_block_creates_one_wins(self, api):
        """PRD §2.7: 'Two maintenance blocks with overlapping windows on
        the same room. Serialization is on the (room_id, date)
        maintenance occupation. The first writer wins; the second
        receives ERR_MAINTENANCE_OVERLAP (HTTP 409).'"""
        rt = create_room_type()
        room = create_room(room_type_id=rt["id"])
        payload_a = create_maintenance_block_payload(
            room_id=room["id"],
            start_date="2032-09-01", end_date="2032-09-05",
        )
        payload_b = create_maintenance_block_payload(
            room_id=room["id"],
            start_date="2032-09-03", end_date="2032-09-07",
        )
        results = run_race(
            lambda: api.create_maintenance_block(
                payload_a, TEST_USERS["housekeeping_headers"]),
            lambda: api.create_maintenance_block(
                payload_b, TEST_USERS["housekeeping_headers"]),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_MAINTENANCE_OVERLAP")


# ===========================================================================
# OCC version conflict (PRD §2.5)
# ===========================================================================
class TestOptimisticConcurrency:
    def test_modify_with_stale_version_rejected(self, api):
        """PRD §2.5: 'When supplied and mismatched, the request is
        rejected with ERR_VERSION_CONFLICT (HTTP 409).'"""
        from test_helpers import modify_reservation_payload
        scaffold = setup_basic_distribution(n_rooms=4, channel_type="DIRECT")
        advance_clock("2032-10-01T09:00:00.000Z")
        res = create_confirmed_reservation(
            scaffold,
            check_in_date="2032-10-15", check_out_date="2032-10-17",
        )
        stale_version = res["version"] + 99
        payload = modify_reservation_payload(
            check_in_date="2032-10-16", check_out_date="2032-10-18",
            version=stale_version,
        )
        bad = api.modify_reservation(
            res["id"], payload, TEST_USERS["agent_headers"],
        )
        validate_error(bad, "ERR_VERSION_CONFLICT")
