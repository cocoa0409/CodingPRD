"""Liaison meetings: quorum threshold semantics and half-open room slots."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_members,
    create_liaison_meeting_payload,
    create_officer,
    create_watch_group,
    make_officer_headers,
    mark_held_payload,
    set_clock,
    setup_group_with_registered_block,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


class TestMeetingQuorum:
    def test_quorum_threshold_inclusive_with_member_snapshot(self, api):
        """PRD §3.5: "Quorum is judged in a pinned order: first the system
        snapshots the count of the group's `ACTIVE` members at the instant of the
        mark-held call, before any side effect of the transition runs; then it
        computes the threshold as the larger of 2 and one quarter of that active
        count rounded up to a whole number; finally `quorum_met` is set to
        whether `attendee_count` is at least the threshold, with equality
        counting."

        Design: Corner/calculations/meeting_quorum_snapshot_and_inclusive_threshold
        """
        group, block = setup_group_with_registered_block(
            "Quorum Watch", "C01", "1-1 Calc St", 12,
        )
        add_members(group["id"], block["id"], 8, name_prefix="Q")
        officer = create_officer("BC01", "Officer Q", "C01")
        officer_headers = make_officer_headers(officer["id"])

        mt1 = validate_success(
            api.create_liaison_meeting(
                create_liaison_meeting_payload(
                    group["id"], officer["id"],
                    "2026-08-05T18:00:00Z", "2026-08-05T19:00:00Z",
                ),
                officer_headers,
            ),
            201,
        )
        mt2 = validate_success(
            api.create_liaison_meeting(
                create_liaison_meeting_payload(
                    group["id"], officer["id"],
                    "2026-08-05T19:00:00Z", "2026-08-05T20:00:00Z",
                ),
                officer_headers,
            ),
            201,
        )

        # 8 ACTIVE members -> threshold max(2, ceil(8 * 0.25)) = 2.
        set_clock("2026-08-05T18:30:00Z")
        held1 = validate_success(
            api.mark_meeting_held(mt1["id"], mark_held_payload(2), officer_headers)
        )
        assert held1["quorum_met"] is True, (
            "attendee_count 2 meets the threshold of 2 — equality counts"
        )

        set_clock("2026-08-05T19:30:00Z")
        held2 = validate_success(
            api.mark_meeting_held(mt2["id"], mark_held_payload(1), officer_headers)
        )
        assert held2["quorum_met"] is False, "attendee_count 1 is below 2"


class TestRoomSlotOverlap:
    def _two_groups_same_precinct(self, api):
        g1 = create_watch_group("Room Watch 1", "PCT15")
        g2 = create_watch_group("Room Watch 2", "PCT15")
        officer = create_officer("B150", "Officer M", "PCT15")
        return g1, g2, officer

    def test_adjacent_slots_allowed(self, api):
        """PRD §3.5: "The reservation is a half-open interval — it occupies from
        the start up to but not including the end — and it must not overlap any
        other `SCHEDULED` or `HELD` meeting's slot in the same precinct; overlap
        is rejected with `ERR_ROOM_SLOT_CONFLICT`, while adjacency, where one
        meeting's end equals the other's start, is allowed."

        Design: Difficulty/resource_temporal_overlap/meeting_room_half_open_adjacency_allowed
        """
        g1, g2, officer = self._two_groups_same_precinct(api)
        officer_headers = make_officer_headers(officer["id"])
        validate_success(
            api.create_liaison_meeting(
                create_liaison_meeting_payload(
                    g1["id"], officer["id"],
                    "2026-08-05T18:00:00Z", "2026-08-05T19:00:00Z",
                ),
                officer_headers,
            ),
            201,
        )
        adjacent = validate_success(
            api.create_liaison_meeting(
                create_liaison_meeting_payload(
                    g2["id"], officer["id"],
                    "2026-08-05T19:00:00Z", "2026-08-05T20:00:00Z",
                ),
                officer_headers,
            ),
            201,
        )
        assert adjacent["meeting_status"] == "SCHEDULED", (
            "start == existing.end is legal under half-open [start, end) semantics"
        )

    def test_overlapping_slot_rejected(self, api):
        """PRD §3.5: "it must not overlap any other `SCHEDULED` or `HELD`
        meeting's slot in the same precinct; overlap is rejected with
        `ERR_ROOM_SLOT_CONFLICT`"

        Design: Difficulty/resource_temporal_overlap/meeting_room_half_open_adjacency_allowed
        """
        g1, g2, officer = self._two_groups_same_precinct(api)
        officer_headers = make_officer_headers(officer["id"])
        validate_success(
            api.create_liaison_meeting(
                create_liaison_meeting_payload(
                    g1["id"], officer["id"],
                    "2026-08-05T18:00:00Z", "2026-08-05T19:00:00Z",
                ),
                officer_headers,
            ),
            201,
        )
        resp = api.create_liaison_meeting(
            create_liaison_meeting_payload(
                g2["id"], officer["id"],
                "2026-08-05T18:59:00Z", "2026-08-05T19:30:00Z",
            ),
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ROOM_SLOT_CONFLICT)
