"""Marshal shift overlap (half-open intervals) and the completion window."""
import test_helpers as th
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, assert_marshal_assignment,
)

COMMITTEE = th.make_committee_admin_headers()
MARSHAL1 = th.make_marshal_headers("marshal_1")


def _parade_with_segment(name):
    parade = th.create_parade(name=name)
    segment = th.add_route_segment(parade["id"])
    return parade, segment


class TestMarshalWindowOverlap:
    """Difficulty: marshal_half_open_adjacency_allowed_overlap_rejected."""

    def test_adjacent_shift_accepted_half_open(self, api):
        """PRD §3.6: "The overlap rule here is the mirror image of the staging
        rule: marshal shifts are half-open intervals, so a new shift is
        rejected with `ERR_MARSHAL_WINDOW_OVERLAP` only when some existing
        assignment of the same `marshal_user_id` in `ASSIGNED` or `CONFIRMED`
        status starts before the new shift ends and ends after the new shift
        starts. Adjacency is expressly allowed — a new shift starting at the
        exact instant another of the marshal's shifts ends does not overlap
        it."

        Design: Difficulty/resource_temporal_overlap/marshal_half_open_adjacency_allowed_overlap_rejected
        """
        parade, segment = _parade_with_segment("Marshal Parade")
        first = get_success_data(
            api.create_marshal_assignment(
                parade["id"],
                th.create_marshal_assignment_payload(
                    segment["id"], "marshal_1",
                    shift_start="2026-07-04T08:00:00Z", shift_end="2026-07-04T09:00:00Z",
                ),
                COMMITTEE,
            )
        )
        get_success_data(api.confirm_marshal_assignment(first["id"], MARSHAL1))

        adjacent = validate_success(
            api.create_marshal_assignment(
                parade["id"],
                th.create_marshal_assignment_payload(
                    segment["id"], "marshal_1",
                    shift_start="2026-07-04T09:00:00Z", shift_end="2026-07-04T10:00:00Z",
                ),
                COMMITTEE,
            ),
            201,
        )
        assert_marshal_assignment(adjacent)
        assert adjacent["status"] == "ASSIGNED", (
            "shift_start == prior shift_end is adjacency, not overlap"
        )

    def test_overlapping_shift_rejected(self, api):
        """PRD §3.6: "The overlap rule here is the mirror image of the staging
        rule: marshal shifts are half-open intervals, so a new shift is
        rejected with `ERR_MARSHAL_WINDOW_OVERLAP` only when some existing
        assignment of the same `marshal_user_id` in `ASSIGNED` or `CONFIRMED`
        status starts before the new shift ends and ends after the new shift
        starts."

        Design: Difficulty/resource_temporal_overlap/marshal_half_open_adjacency_allowed_overlap_rejected
        """
        parade, segment = _parade_with_segment("Marshal Parade 2")
        get_success_data(
            api.create_marshal_assignment(
                parade["id"],
                th.create_marshal_assignment_payload(
                    segment["id"], "marshal_1",
                    shift_start="2026-07-04T08:00:00Z", shift_end="2026-07-04T09:00:00Z",
                ),
                COMMITTEE,
            )
        )
        # [08:30, 09:30) overlaps [08:00, 09:00): 08:00 < 09:30 and 08:30 < 09:00.
        resp = api.create_marshal_assignment(
            parade["id"],
            th.create_marshal_assignment_payload(
                segment["id"], "marshal_1",
                shift_start="2026-07-04T08:30:00Z", shift_end="2026-07-04T09:30:00Z",
            ),
            COMMITTEE,
        )
        validate_error(resp, ApiErrorId.ERR_MARSHAL_WINDOW_OVERLAP)


class TestMarshalCompletionWindow:

    def test_complete_before_shift_end_rejected(self, api):
        """PRD §3.6: "Completing moves it from `CONFIRMED` to `COMPLETED`,
        again only by the named marshal, and only once the logical clock reads
        at or after `shift_end`; an early completion fails with
        `ERR_CHECKIN_WINDOW_NOT_OPEN`."

        Design: Corner/validations/marshal_complete_before_shift_end_rejected
        """
        parade, segment = _parade_with_segment("Shift Parade")
        assignment = get_success_data(
            api.create_marshal_assignment(
                parade["id"],
                th.create_marshal_assignment_payload(
                    segment["id"], "marshal_1",
                    shift_start="2026-07-04T08:00:00Z", shift_end="2026-07-04T09:00:00Z",
                ),
                COMMITTEE,
            )
        )
        get_success_data(api.confirm_marshal_assignment(assignment["id"], MARSHAL1))
        th.set_clock("2026-07-04T08:30:00Z")

        resp = api.complete_marshal_assignment(assignment["id"], MARSHAL1)
        validate_error(resp, ApiErrorId.ERR_CHECKIN_WINDOW_NOT_OPEN)

        after = validate_success(api.get_marshal_assignment(assignment["id"], COMMITTEE))
        assert after["status"] == "CONFIRMED"
