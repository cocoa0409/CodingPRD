"""Room double-booking is half-open, pair-scoped and modality-filtered."""

from test_helpers import ApiErrorId
from test_helpers import assertions as ax
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success

MORNING = {"starts_at": "2026-09-01T09:00:00Z", "ends_at": "2026-09-01T13:00:00Z"}
ABUTTING = {"starts_at": "2026-09-01T13:00:00Z", "ends_at": "2026-09-01T17:00:00Z"}
ONE_MINUTE_EARLY = {"starts_at": "2026-09-01T12:59:00Z", "ends_at": "2026-09-01T16:00:00Z"}


def _incumbent_room_booking(api):
    """A four-hour test-centre session holding C1/R1 for the morning."""
    return fx.create_test_center_session(api, center_code="C1", room_code="R1", **MORNING)


class TestRoomWindowIsHalfOpen:
    """Four bookings against one incumbent, distinguished only by the interval test."""

    def test_a_session_starting_when_the_incumbent_ends_is_accepted(self, api):
        """Adjacency is not overlap on a half-open interval, so the afternoon booking
        takes the same room.

        PRD §3.7: "Adjacency is therefore permitted — a session beginning at the exact
        instant another ends is accepted — while any genuine intersection is refused
        with `ERR_ROOM_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/test_center_room_overlap_is_half_open_so_an_abutting_session_shares_the_room
        """
        _incumbent = _incumbent_room_booking(api)

        adjacent = validate_success(api.create_exam_session(
            f.create_test_center_session_payload(center_code="C1", room_code="R1", **ABUTTING),
            fx.EXAM_OPERATIONS), 201)

        assert str(adjacent["starts_at"]).startswith("2026-09-01T13:00:00")
        assert adjacent["status"] == "OPEN"
        ax.assert_exam_session(adjacent)

    def test_a_one_minute_intersection_is_refused_and_writes_nothing(self, api):
        """Moving the same booking one minute earlier creates a genuine intersection,
        and the refusal leaves the calendar with only the incumbent.

        PRD §3.7: "Two `TEST_CENTER` sessions sharing the same `center_code` and
        `room_code` pair may not overlap on the **half-open** interval that runs from
        `starts_at` up to but not including `ends_at`: a conflict exists when the new
        session's `starts_at` is strictly before an existing session's `ends_at` and
        that existing session's `starts_at` is strictly before the new session's
        `ends_at`."

        Design: Difficulty/resource_temporal_overlap/test_center_room_overlap_is_half_open_so_an_abutting_session_shares_the_room
        """
        incumbent = _incumbent_room_booking(api)

        refused = api.create_exam_session(
            f.create_test_center_session_payload(center_code="C1", room_code="R1",
                                                 **ONE_MINUTE_EARLY),
            fx.EXAM_OPERATIONS)

        validate_error(refused, ApiErrorId.ERR_ROOM_WINDOW_CONFLICT.value, 409)
        sessions, _meta = validate_paginated(api.list_exam_sessions(fx.EXAM_OPERATIONS))
        assert [session["id"] for session in sessions] == [incumbent["id"]]

    def test_the_identical_window_in_another_room_of_the_same_centre_is_accepted(self, api):
        """The rule is keyed on the centre-and-room pair, so a second room takes the
        very window that was refused a moment ago.

        PRD §2.7: "**Room window.** Test-centre sessions sharing a `center_code` and
        `room_code` pair may not overlap → otherwise `ERR_ROOM_WINDOW_CONFLICT` (409)."

        Design: Difficulty/resource_temporal_overlap/test_center_room_overlap_is_half_open_so_an_abutting_session_shares_the_room
        """
        incumbent = _incumbent_room_booking(api)

        other_room = validate_success(api.create_exam_session(
            f.create_test_center_session_payload(center_code="C1", room_code="R2", **MORNING),
            fx.EXAM_OPERATIONS), 201)

        assert other_room["room_code"] == "R2"
        assert other_room["starts_at"] == incumbent["starts_at"]
        assert other_room["ends_at"] == incumbent["ends_at"]

    def test_an_online_session_is_exempt_from_the_room_rule(self, api):
        """An online-proctored session with the incumbent's exact window is accepted,
        because the room rule reaches only test-centre sessions.

        PRD §3.7: "The location fields are modality-conditional and strictly so: a
        `TEST_CENTER` session requires both a `center_code` and a `room_code` and must
        leave `proctor_pool_code` null, while an `ONLINE_PROCTORED` session requires a
        `proctor_pool_code` and must leave both `center_code` and `room_code` null."

        Design: Difficulty/resource_temporal_overlap/test_center_room_overlap_is_half_open_so_an_abutting_session_shares_the_room
        """
        _incumbent = _incumbent_room_booking(api)

        online = validate_success(api.create_exam_session(
            f.create_online_session_payload(seat_capacity=50, proctor_pool_code="P1", **MORNING),
            fx.EXAM_OPERATIONS), 201)

        assert online["modality"] == "ONLINE_PROCTORED"
        assert online["center_code"] is None
        assert online["room_code"] is None
        assert online["seat_capacity"] == 50

    def test_the_pool_ceiling_admits_exactly_fifty_and_refuses_fifty_one(self, api):
        """Fifty committed seats are inside the ceiling; one more overlapping seat is
        outside it, and nothing is written.

        PRD §3.7: "Sum the `seat_capacity` of those overlapping sessions; if that
        committed total plus the new session's own `seat_capacity` is strictly greater
        than the pool ceiling of 50 concurrent seats, the creation is refused with
        `ERR_PROCTOR_POOL_CAPACITY_EXCEEDED`."

        PRD §3.7: "A combined total of exactly 50 is accepted and 51 is not."

        Design: Difficulty/resource_temporal_overlap/test_center_room_overlap_is_half_open_so_an_abutting_session_shares_the_room
        """
        _incumbent = _incumbent_room_booking(api)
        fx.create_online_session(api, seat_capacity=50, proctor_pool_code="P1", **MORNING)

        refused = api.create_exam_session(
            f.create_online_session_payload(seat_capacity=1, proctor_pool_code="P1",
                                            **ONE_MINUTE_EARLY),
            fx.EXAM_OPERATIONS)

        validate_error(refused, ApiErrorId.ERR_PROCTOR_POOL_CAPACITY_EXCEEDED.value, 409)
        sessions, _meta = validate_paginated(api.list_exam_sessions(fx.EXAM_OPERATIONS))
        assert len(sessions) == 2

    def test_the_incumbent_is_untouched_by_every_later_booking(self, api):
        """None of the four later calls — accepted or refused — moves the incumbent's
        occupancy or its version.

        PRD §3.7: "`seats_reserved` is the number of exam registrations pointing at the
        session whose `seat_status` is `SCHEDULED`, `CHECKED_IN`, or `COMPLETED`; the
        `UNSCHEDULED`, `NO_SHOW`, and `CANCELLED` states all release the seat."

        Design: Difficulty/resource_temporal_overlap/test_center_room_overlap_is_half_open_so_an_abutting_session_shares_the_room
        """
        incumbent = _incumbent_room_booking(api)
        first_version = incumbent["version"]

        fx.create_test_center_session(api, center_code="C1", room_code="R1", **ABUTTING)
        api.create_exam_session(
            f.create_test_center_session_payload(center_code="C1", room_code="R1",
                                                 **ONE_MINUTE_EARLY),
            fx.EXAM_OPERATIONS)
        fx.create_test_center_session(api, center_code="C1", room_code="R2", **MORNING)
        fx.create_online_session(api, seat_capacity=50, proctor_pool_code="P1", **MORNING)

        after = fx.read_session(api, incumbent["id"])
        assert after["seats_reserved"] == 0
        assert after["version"] == first_version
