"""Slot reservation uniqueness, alignment, and right-of-way semantics.

PRD section 3.6 governs slot reservation; section 2.10 names the
concurrency error_id.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_slot_reservation,
    create_fleet,
    create_map_node,
    create_robot,
    create_slot_reservation_payload,
    epoch_iso,
    setup_intersection_for_slot_reservations,
    validate_error,
    validate_success,
)


class TestSlotUniqueness:
    def test_first_reservation_succeeds_with_held_status(self):
        """PRD section 3.6: 'The reservation enters HELD and remains so
        until it is consumed during a step (flipping to CONSUMED) or
        released...'

        Claim: a fresh slot reservation has status='HELD'.
        """
        fleet, inter, ra, rb = setup_intersection_for_slot_reservations()
        resp = api_client.create_slot_reservation(
            fleet["id"],
            create_slot_reservation_payload(
                node_id=inter["id"],
                robot_id=ra["id"],
                scheduled_at=epoch_iso(0),
            ),
            TEST_USERS["operator_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "HELD"
        assert_slot_reservation(data)

    def test_duplicate_node_and_slot_index_rejected(self):
        """PRD section 3.6: 'The same node and slot ordinal may carry at
        most one HELD reservation; a duplicate creation is rejected with
        ERR_SLOT_ALREADY_RESERVED.'

        Claim: two reservations on the same (node_id, slot_index=0)
        produce ERR_SLOT_ALREADY_RESERVED on the second.
        """
        fleet, inter, ra, rb = setup_intersection_for_slot_reservations()
        # First reservation succeeds.
        api_client.create_slot_reservation(
            fleet["id"],
            create_slot_reservation_payload(
                node_id=inter["id"],
                robot_id=ra["id"],
                scheduled_at=epoch_iso(0),
            ),
            TEST_USERS["operator_headers"],
        )
        # Second reservation with the same slot_index collides.
        resp = api_client.create_slot_reservation(
            fleet["id"],
            create_slot_reservation_payload(
                node_id=inter["id"],
                robot_id=rb["id"],
                scheduled_at=epoch_iso(0),
            ),
            TEST_USERS["operator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_ALREADY_RESERVED.value)


class TestSlotAlignment:
    def test_unaligned_scheduled_at_rejected(self):
        """PRD section 3.6: 'The supplied scheduled_at must be aligned
        to Fleet.slot_seconds — that is, its UNIX-epoch second value
        modulo Fleet.slot_seconds must be zero — and it must be at or
        after the current Fleet.clock_now; either failure yields
        ERR_SLOT_TIME_INVALID.'

        Claim: with slot_seconds=10 (default), scheduled_at at second 5
        is rejected with ERR_SLOT_TIME_INVALID.
        """
        fleet, inter, ra, rb = setup_intersection_for_slot_reservations()
        resp = api_client.create_slot_reservation(
            fleet["id"],
            create_slot_reservation_payload(
                node_id=inter["id"],
                robot_id=ra["id"],
                scheduled_at=epoch_iso(5),  # 5 % 10 != 0
            ),
            TEST_USERS["operator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_TIME_INVALID.value)

    def test_scheduled_at_in_past_rejected(self):
        """PRD section 3.6: 'it must be at or after the current
        Fleet.clock_now; either failure yields ERR_SLOT_TIME_INVALID.'

        Claim: with Fleet.clock_now advanced to 20s, a scheduled_at=10s
        (aligned to slot_seconds=10 but in the past) -> ERR_SLOT_TIME_INVALID.
        """
        from test_helpers import advance_clock
        fleet, inter, ra, rb = setup_intersection_for_slot_reservations()
        # Advance the clock so 'now' is at 20.
        advance_clock(fleet["id"], 20)
        resp = api_client.create_slot_reservation(
            fleet["id"],
            create_slot_reservation_payload(
                node_id=inter["id"],
                robot_id=ra["id"],
                scheduled_at=epoch_iso(10),  # aligned but < clock_now
            ),
            TEST_USERS["operator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_TIME_INVALID.value)
