"""Difficulty rule: resource_temporal_overlap.

  (A) Officer shifts use bare half-open intervals: a genuine overlap is
      rejected, but bare adjacency (end == next start) is permitted;
  (B) Hearing rooms use a 15-minute buffered window: a gap strictly below
      15 minutes is rejected, exactly 15 minutes is permitted.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_enforcement_officer_headers,
    create_officer,
    create_beat,
    open_shift,
    setup_issuing_context,
    issue_in_context,
    file_contest,
    create_hearing_room,
    schedule_hearing,
)

HEARING = TEST_USERS["hearing_officer_headers"]


class TestOfficerShiftOverlapHalfOpen:
    def _officer_with_open_shift(self):
        officer = create_officer(badge_number="B-TO1")
        beat = create_beat(patrol_zone="RESIDENTIAL", beat_code="RESD")
        open_shift(officer["id"], beat["id"],
                   scheduled_start="2026-03-02T08:00:00Z",
                   scheduled_end="2026-03-02T12:00:00Z")
        return officer, beat

    def test_overlapping_shift_rejected(self, api):
        """PRD §3.2: "a candidate window collides with an existing `OPEN` shift of
        that officer when the candidate's start falls before that shift's
        `scheduled_end` and that shift's `scheduled_start` falls before the
        candidate's end. Two shifts that merely touch — one ending exactly when the
        next begins — do not overlap and are permitted. A genuine overlap is rejected
        with `ERR_SHIFT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/officer_shift_overlap_halfopen
        """
        officer, beat = self._officer_with_open_shift()
        validate_error(
            api.create_shift(
                {"officer_id": officer["id"], "beat_id": beat["id"],
                 "scheduled_start": "2026-03-02T10:00:00Z",
                 "scheduled_end": "2026-03-02T14:00:00Z"},
                make_enforcement_officer_headers(officer["id"])),
            ApiErrorId.ERR_SHIFT_OVERLAP.value)

    def test_adjacent_shift_permitted(self, api):
        """PRD §3.2: "Two shifts that merely touch — one ending exactly when the next
        begins — do not overlap and are permitted."

        Design: Difficulty/resource_temporal_overlap/officer_shift_overlap_halfopen
        """
        officer, beat = self._officer_with_open_shift()
        second = validate_success(
            api.create_shift(
                {"officer_id": officer["id"], "beat_id": beat["id"],
                 "scheduled_start": "2026-03-02T12:00:00Z",
                 "scheduled_end": "2026-03-02T16:00:00Z"},
                make_enforcement_officer_headers(officer["id"])),
            201)
        assert second["status"] == "OPEN"


class TestHearingRoomOverlapBuffered:
    def _two_contests_and_first_hearing(self):
        ctx = setup_issuing_context()
        c1 = issue_in_context(ctx, evidence_photo_url="https://ev/r1.jpg")
        c2 = issue_in_context(ctx, evidence_photo_url="https://ev/r2.jpg")
        contest1 = file_contest(c1["id"], grounds="Reason 1")
        contest2 = file_contest(c2["id"], grounds="Reason 2")
        room = create_hearing_room(room_code="HR9", name="Room 9")
        schedule_hearing(contest1["id"], room["id"],
                         scheduled_start="2026-03-05T09:00:00Z",
                         scheduled_end="2026-03-05T10:00:00Z")
        return contest2, room

    def test_gap_below_buffer_rejected(self, api):
        """PRD §3.6: "a candidate window collides with an existing `SCHEDULED`
        hearing in the same room when the candidate's start falls before that
        hearing's `scheduled_end` extended forward by 15 minutes, and that hearing's
        `scheduled_start` pulled back by 15 minutes falls before the candidate's end.
        In other words, any gap strictly smaller than 15 minutes of turnaround
        between two hearings in a room is rejected with `ERR_ROOM_UNAVAILABLE`."

        Design: Difficulty/resource_temporal_overlap/hearing_room_overlap_buffered
        """
        contest2, room = self._two_contests_and_first_hearing()
        # first hearing ends 10:00; candidate 10:10 -> 10-min gap < 15.
        validate_error(
            api.create_hearing(
                {"contest_id": contest2["id"], "room_id": room["id"],
                 "scheduled_start": "2026-03-05T10:10:00Z",
                 "scheduled_end": "2026-03-05T11:00:00Z"}, HEARING),
            ApiErrorId.ERR_ROOM_UNAVAILABLE.value)

    def test_gap_at_buffer_permitted(self, api):
        """PRD §3.6: "any gap strictly smaller than 15 minutes of turnaround between
        two hearings in a room is rejected with `ERR_ROOM_UNAVAILABLE`."

        Design: Difficulty/resource_temporal_overlap/hearing_room_overlap_buffered
        """
        contest2, room = self._two_contests_and_first_hearing()
        # candidate 10:15 -> exactly 15-min gap, permitted.
        hearing2 = validate_success(
            api.create_hearing(
                {"contest_id": contest2["id"], "room_id": room["id"],
                 "scheduled_start": "2026-03-05T10:15:00Z",
                 "scheduled_end": "2026-03-05T11:00:00Z"}, HEARING),
            201)
        assert hearing2["status"] == "SCHEDULED"
