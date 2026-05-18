"""Hearing room and officer scheduling conflicts (PRD §3.5).

Covers ERR_ROOM_DOUBLE_BOOKED with half-open interval semantics, and
ERR_OFFICER_BUFFER_VIOLATED with edge-to-edge buffer semantics.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_minutes_iso,
    create_hearing_officer,
    iso_now_utc,
    schedule_appeal,
    setup_two_appeals_for_scheduling_conflict,
    validate_error,
    validate_success,
)


# ===========================================================================
# Room overlap — PRD §3.5
# ===========================================================================
class TestRoomDoubleBooked:

    def test_overlapping_room_intervals_rejected(self, api):
        """PRD §3.5: 'No other Hearing in SCHEDULED status may already
        occupy the same hearing_room with a
        [scheduled_start, scheduled_end) interval that overlaps the
        requested one; intervals are half-open so two hearings that
        are instant-adjacent (one ends exactly when the next begins)
        are permitted. Conflicting overlap is rejected with
        ERR_ROOM_DOUBLE_BOOKED.'

        Claim: a SCHEDULED 10:00–11:00 hearing in ROOM_A blocks a new
        10:30–11:30 in ROOM_A with ERR_ROOM_DOUBLE_BOOKED.

        # difficulty: resource_temporal_overlap/hearing_room_half_open_overlap
        """
        ctx = setup_two_appeals_for_scheduling_conflict()
        base = iso_now_utc()
        # First booking: ROOM_A 10:00–11:00 (relative).
        start1 = add_minutes_iso(base, 60)
        end1 = add_minutes_iso(start1, 60)
        schedule_appeal(
            property_id=ctx["property1"]["id"], appeal_id=ctx["appeal1"]["id"],
            scheduled_start=start1, scheduled_end=end1,
            hearing_room="ROOM_A", officer_id=ctx["officer"]["id"],
        )
        # Second booking: ROOM_A 10:30–11:30 overlaps by 30 min.
        # Use a DIFFERENT officer to avoid OFFICER_BUFFER_VIOLATED
        # firing first (officer is also a constraint).
        officer2 = create_hearing_officer(full_name="Officer Two")
        start2 = add_minutes_iso(start1, 30)
        end2 = add_minutes_iso(start2, 60)
        from test_helpers import api_client, TEST_USERS, schedule_appeal_payload
        resp = api_client.schedule_appeal(
            ctx["property2"]["id"], ctx["appeal2"]["id"],
            schedule_appeal_payload(
                scheduled_start=start2, scheduled_end=end2,
                hearing_room="ROOM_A", officer_id=officer2["id"],
            ),
            TEST_USERS["treasurer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_ROOM_DOUBLE_BOOKED.value)

    def test_touching_intervals_in_same_room_permitted(self, api):
        """PRD §3.5: 'intervals are half-open so two hearings that
        are instant-adjacent (one ends exactly when the next begins)
        are permitted.'

        Claim: a SCHEDULED 10:00–11:00 hearing in ROOM_A does NOT
        block a new 11:00–12:00 in ROOM_A (touching boundary at the
        half-open join is permitted).

        # difficulty: resource_temporal_overlap/hearing_room_half_open_overlap
        """
        ctx = setup_two_appeals_for_scheduling_conflict()
        base = iso_now_utc()
        start1 = add_minutes_iso(base, 60)
        end1 = add_minutes_iso(start1, 60)
        schedule_appeal(
            property_id=ctx["property1"]["id"], appeal_id=ctx["appeal1"]["id"],
            scheduled_start=start1, scheduled_end=end1,
            hearing_room="ROOM_A", officer_id=ctx["officer"]["id"],
        )
        # Different officer to avoid buffer conflict.
        officer2 = create_hearing_officer(full_name="Officer Three")
        start2 = end1  # exactly touching
        end2 = add_minutes_iso(start2, 60)
        scheduled2 = schedule_appeal(
            property_id=ctx["property2"]["id"], appeal_id=ctx["appeal2"]["id"],
            scheduled_start=start2, scheduled_end=end2,
            hearing_room="ROOM_A", officer_id=officer2["id"],
        )
        assert scheduled2["status"] == "SCHEDULED", (
            f"touching half-open intervals must succeed; got status="
            f"{scheduled2['status']}"
        )


# ===========================================================================
# Officer buffer — PRD §3.5
# ===========================================================================
class TestOfficerBufferViolation:

    def test_officer_with_5min_gap_rejected_buffer_15(self, api):
        """PRD §3.5: 'No other Hearing in SCHEDULED for the same
        officer_id may sit within the system constant
        OFFICER_BUFFER_MIN minutes (15 minutes) of the requested
        interval — measured edge-to-edge, so even non-overlapping but
        tightly packed bookings are rejected with
        ERR_OFFICER_BUFFER_VIOLATED.'

        Claim: a 5-minute gap between two officer hearings (rooms
        different so room rule is not triggered) rejects with
        ERR_OFFICER_BUFFER_VIOLATED.

        # difficulty: resource_temporal_overlap/officer_buffer_separation_overlap
        """
        ctx = setup_two_appeals_for_scheduling_conflict()
        base = iso_now_utc()
        start1 = add_minutes_iso(base, 60)
        end1 = add_minutes_iso(start1, 60)
        schedule_appeal(
            property_id=ctx["property1"]["id"], appeal_id=ctx["appeal1"]["id"],
            scheduled_start=start1, scheduled_end=end1,
            hearing_room="ROOM_A", officer_id=ctx["officer"]["id"],
        )
        # Second booking with same officer, ROOM_B (no room conflict),
        # but only 5 minutes after end1 → buffer violation.
        start2 = add_minutes_iso(end1, 5)
        end2 = add_minutes_iso(start2, 60)
        from test_helpers import api_client, TEST_USERS, schedule_appeal_payload
        resp = api_client.schedule_appeal(
            ctx["property2"]["id"], ctx["appeal2"]["id"],
            schedule_appeal_payload(
                scheduled_start=start2, scheduled_end=end2,
                hearing_room="ROOM_B", officer_id=ctx["officer"]["id"],
            ),
            TEST_USERS["treasurer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_OFFICER_BUFFER_VIOLATED.value)

    def test_officer_with_30min_gap_accepted(self, api):
        """PRD §3.5: 'No other Hearing in SCHEDULED for the same
        officer_id may sit within the system constant
        OFFICER_BUFFER_MIN minutes (15 minutes) of the requested
        interval — measured edge-to-edge, so even non-overlapping but
        tightly packed bookings are rejected with
        ERR_OFFICER_BUFFER_VIOLATED.'

        Claim: a 30-minute gap (>= 15min buffer) satisfies the
        constraint and the second booking succeeds.

        # difficulty: resource_temporal_overlap/officer_buffer_separation_overlap
        """
        ctx = setup_two_appeals_for_scheduling_conflict()
        base = iso_now_utc()
        start1 = add_minutes_iso(base, 60)
        end1 = add_minutes_iso(start1, 60)
        schedule_appeal(
            property_id=ctx["property1"]["id"], appeal_id=ctx["appeal1"]["id"],
            scheduled_start=start1, scheduled_end=end1,
            hearing_room="ROOM_A", officer_id=ctx["officer"]["id"],
        )
        start2 = add_minutes_iso(end1, 30)
        end2 = add_minutes_iso(start2, 60)
        scheduled2 = schedule_appeal(
            property_id=ctx["property2"]["id"], appeal_id=ctx["appeal2"]["id"],
            scheduled_start=start2, scheduled_end=end2,
            hearing_room="ROOM_B", officer_id=ctx["officer"]["id"],
        )
        assert scheduled2["status"] == "SCHEDULED"
