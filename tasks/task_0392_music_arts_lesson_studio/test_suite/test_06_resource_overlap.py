"""Resource temporal-overlap rules: the room recurring-slot turnover buffer and the
instrument-unit closed-interval rental overlap.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    create_room_payload,
    create_student_payload,
    create_instructor_payload,
    create_rental_payload,
    create_family_payload,
    setup_roster,
    create_studio,
    create_enrollment,
    activate_enrollment,
)
from test_helpers import api_client

ADMIN = TEST_USERS["studio_admin_headers"]


# ===========================================================================
# Difficulty / resource_temporal_overlap / room_recurring_overlap_with_turnover_buffer
# ===========================================================================
class TestRoomTurnoverBufferOverlap:
    def _setup_back_to_back_same_room(self, api):
        # One room (buffer 10), two DIFFERENT instructors so the instructor double-book
        # check does not pre-empt the room check. A: Mon 10:00-11:00; B: Mon 11:00-12:00.
        studio = create_studio()
        sid = studio["id"]
        family = get_success_data(api.create_family(sid, create_family_payload(), ADMIN))
        s1 = get_success_data(api.create_student(sid, create_student_payload(family["id"]), ADMIN))
        s2 = get_success_data(api.create_student(sid, create_student_payload(family["id"]), ADMIN))
        inA = get_success_data(
            api.create_instructor(
                sid,
                create_instructor_payload(
                    instruments=["PIANO"],
                    weekly_availability=[{"weekday": 0, "start_min": 540, "end_min": 780}],
                    hourly_rate_cents=6000,
                ),
                ADMIN,
            )
        )
        inB = get_success_data(
            api.create_instructor(
                sid,
                create_instructor_payload(
                    instruments=["PIANO"],
                    weekly_availability=[{"weekday": 0, "start_min": 540, "end_min": 780}],
                    hourly_rate_cents=6000,
                ),
                ADMIN,
            )
        )
        room = get_success_data(
            api.create_room(
                sid,
                create_room_payload(supported_instruments=["PIANO"], turnover_buffer_min=10),
                ADMIN,
            )
        )
        eA = create_enrollment(sid, s1["id"], inA["id"], room["id"], instrument="PIANO", weekday=0, start_min=600, duration_min=60)
        eA = activate_enrollment(sid, eA)
        eB = create_enrollment(sid, s2["id"], inB["id"], room["id"], instrument="PIANO", weekday=0, start_min=660, duration_min=60)
        return sid, eB

    def test_buffer_expanded_back_to_back_room_collision(self, api):
        """PRD 3.2: "no other `ACTIVE` enrollment for the same `room_id` may collide on
        the same `weekday`, where the room's collision test expands each window by the
        room's `turnover_buffer_min` before testing overlap — two enrollments on the
        same room conflict when the interval from one enrollment's start to its end plus
        the buffer intersects the corresponding interval of the other — or the result is
        `ERR_ROOM_DOUBLE_BOOKED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/room_recurring_overlap_with_turnover_buffer
        """
        sid, eB = self._setup_back_to_back_same_room(api)
        res = api.activate_enrollment(
            sid, eB["id"], {"expected_enrollment_version": eB["version"]}, ADMIN
        )
        validate_error(res, "ERR_ROOM_DOUBLE_BOOKED", expected_status=409)

    def test_room_collision_fires_not_instructor_collision(self, api):
        """PRD 3.2: "The slot must be free on the instructor: no other `ACTIVE`
        enrollment for the same `instructor_id` may collide ... or the result is
        `ERR_INSTRUCTOR_DOUBLE_BOOKED` (HTTP 409)." Here the two lessons use different
        instructors, so only the room turnover-buffer rule can fire.

        Design: Difficulty/resource_temporal_overlap/room_recurring_overlap_with_turnover_buffer
        """
        sid, eB = self._setup_back_to_back_same_room(api)
        res = api.activate_enrollment(
            sid, eB["id"], {"expected_enrollment_version": eB["version"]}, ADMIN
        )
        body = res.json()
        assert body["data"]["error_id"] == "ERR_ROOM_DOUBLE_BOOKED"
        assert body["data"]["error_id"] != "ERR_INSTRUCTOR_DOUBLE_BOOKED"


# ===========================================================================
# Difficulty / resource_temporal_overlap /
#   instrument_unit_closed_interval_touching_endpoints_collide
# ===========================================================================
class TestInstrumentUnitClosedInterval:
    def _setup_first_rental(self, api):
        studio = create_studio()
        sid = studio["id"]
        family = get_success_data(api.create_family(sid, create_family_payload(), ADMIN))
        get_success_data(
            api.create_rental(
                sid,
                create_rental_payload(
                    family["id"], "CELLO-7", 5000,
                    "2026-02-01T00:00:00.000Z", "2026-02-10T00:00:00.000Z",
                ),
                ADMIN,
            )
        )
        return sid, family

    def test_touching_endpoint_rental_collides(self, api):
        """PRD 3.8: "a new rental is rejected with `ERR_INSTRUMENT_UNIT_UNAVAILABLE`
        (HTTP 409) when any `RESERVED` or `ACTIVE` rental on the same `instrument_unit_code`
        overlaps it, where overlap holds when the new rental's `rental_start_utc` is at or
        before the existing rental's `rental_end_utc` and the new rental's `rental_end_utc`
        is at or after the existing rental's `rental_start_utc`. Because endpoints are
        inclusive, a return at one instant blocks a new pickup at the very same instant."

        Design: Difficulty/resource_temporal_overlap/instrument_unit_closed_interval_touching_endpoints_collide
        """
        sid, family = self._setup_first_rental(api)
        # Second rental starts exactly when the first ends — closed interval => collide.
        res = api.create_rental(
            sid,
            create_rental_payload(
                family["id"], "CELLO-7", 5000,
                "2026-02-10T00:00:00.000Z", "2026-02-20T00:00:00.000Z",
            ),
            ADMIN,
        )
        validate_error(res, "ERR_INSTRUMENT_UNIT_UNAVAILABLE", expected_status=409)

    def test_non_touching_window_on_same_unit_allowed(self, api):
        """PRD 3.8: "A physical unit is a finite resource that only one rental may occupy
        at a time" — overlap holds only when the new start is at or before the existing
        end AND the new end is at or after the existing start; a window strictly after the
        existing one does not overlap and is accepted (status `RESERVED`).

        Design: Difficulty/resource_temporal_overlap/instrument_unit_closed_interval_touching_endpoints_collide
        """
        sid, family = self._setup_first_rental(api)
        # Strictly after the first window's end => no overlap, accepted.
        rental2 = validate_success(
            api.create_rental(
                sid,
                create_rental_payload(
                    family["id"], "CELLO-7", 5000,
                    "2026-02-10T00:00:00.001Z", "2026-02-20T00:00:00.000Z",
                ),
                ADMIN,
            ),
            201,
        )
        assert rental2["status"] == "RESERVED"
