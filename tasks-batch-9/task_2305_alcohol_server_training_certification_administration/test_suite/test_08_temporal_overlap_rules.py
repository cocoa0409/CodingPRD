"""The same 18:00 boundary, judged by two deliberately opposite interval rules.

The trainer's interval is closed and buffered, so touching it conflicts; the server's window
is half-open and unbuffered, so touching it is fine.
"""
from test_helpers import (
    ApiErrorId,
    add_certified_proctor,
    assert_class_session,
    assert_enrollment,
    assert_same_instant,
    class_session_payload,
    create_scheduled_session,
    enroll_server,
    enrollment_payload,
    get_session,
    make_alcohol_server_headers,
    register_alcohol_server,
    setup_training_base,
    validate_error,
    validate_paginated,
    validate_success,
)

HELD_START = "2026-08-10T14:00:00Z"
HELD_END = "2026-08-10T18:00:00Z"
ADJACENT_START = "2026-08-10T18:00:00Z"
ADJACENT_END = "2026-08-10T22:00:00Z"
CLEAR_OF_BUFFER_START = "2026-08-10T19:01:00Z"
CLEAR_OF_BUFFER_END = "2026-08-10T23:00:00Z"
OVERLAPPING_START = "2026-08-10T17:00:00Z"
OVERLAPPING_END = "2026-08-10T21:00:00Z"


def _session_request(base, scheduled_start_at, scheduled_end_at):
    return class_session_payload(
        base["course"]["id"], base["jurisdiction"]["id"], base["trainer"]["id"],
        scheduled_start_at=scheduled_start_at, scheduled_end_at=scheduled_end_at,
        capacity=20)


class TestTrainerBufferedClosedInterval:
    def test_a_class_starting_when_the_previous_one_ends_conflicts(self, api):
        """PRD §3.5: "The requested window is widened by one hour on each side into a closed
        interval running from `scheduled_start_at` minus sixty minutes to `scheduled_end_at`
        plus sixty minutes."
        PRD §3.5: "If that widened closed interval intersects the closed interval from
        `scheduled_start_at` to `scheduled_end_at` of any other class session with the same
        instructing trainer whose `session_status` is `SCHEDULED`, `ROSTER_LOCKED` or
        `EXAM_OPEN`, the request is refused with `ERR_TRAINER_SCHEDULE_CONFLICT`."
        PRD §3.5: "Because both intervals are closed, a class beginning exactly one hour after
        another ends still conflicts."

        Design: Difficulty/resource_temporal_overlap/trainer_buffered_closed_interval_rejects_exact_adjacency_but_admits_a_sixty_one_minute_gap
        """
        base = setup_training_base(
            session_overrides={"scheduled_start_at": HELD_START,
                               "scheduled_end_at": HELD_END})

        response = api.create_class_session(
            _session_request(base, ADJACENT_START, ADJACENT_END), base["trainer_headers"])
        validate_error(response, ApiErrorId.ERR_TRAINER_SCHEDULE_CONFLICT, 409)

    def test_a_sixty_one_minute_gap_clears_the_buffer(self, api):
        """PRD §3.5: "Trainers are also protected from back-to-back bookings. The requested
        window is widened by one hour on each side into a closed interval running from
        `scheduled_start_at` minus sixty minutes to `scheduled_end_at` plus sixty minutes."
        PRD §3.5: "A new session lands in `SCHEDULED` with `enrolled_count` and `passed_count`
        at zero, `proctor_trainer_id`, `exam_opened_at`, `completed_at` and
        `cancellation_reason` unset."
        PRD §3.5: "Sessions can be read individually or listed with filters on `course_id`,
        `state_jurisdiction_id`, `trainer_id`, `proctor_trainer_id`,
        `pinned_course_approval_id` and `session_status`."

        Design: Difficulty/resource_temporal_overlap/trainer_buffered_closed_interval_rejects_exact_adjacency_but_admits_a_sixty_one_minute_gap
        """
        base = setup_training_base(
            session_overrides={"scheduled_start_at": HELD_START,
                               "scheduled_end_at": HELD_END})
        api.create_class_session(
            _session_request(base, ADJACENT_START, ADJACENT_END), base["trainer_headers"])

        admitted = validate_success(api.create_class_session(
            _session_request(base, CLEAR_OF_BUFFER_START, CLEAR_OF_BUFFER_END),
            base["trainer_headers"]), 201)
        assert_class_session(admitted)
        assert admitted["session_status"] == "SCHEDULED", (
            "a buffered start of 18:01 is strictly after the held end of 18:00, got "
            f"{admitted['session_status']}")

        sessions, meta = validate_paginated(api.list_class_sessions(
            base["trainer_headers"], {"trainer_id": base["trainer"]["id"]}))
        assert meta["total_count"] == 2, (
            "only the adjacent request was refused, got "
            f"{meta['total_count']} sessions")
        assert {s["id"] for s in sessions} == {base["session"]["id"], admitted["id"]}

        held = get_session(base["session"]["id"])
        assert_same_instant(held["scheduled_end_at"], HELD_END, "scheduled_end_at")


class TestServerHalfOpenEnrollmentWindow:
    def _three_sessions_with_three_trainers(self):
        """Three overlapping-in-time classes, each with its own instructor."""
        base = setup_training_base(
            session_overrides={"scheduled_start_at": HELD_START,
                               "scheduled_end_at": HELD_END})
        second_trainer = add_certified_proctor(base, full_name="Kim Osei",
                                               email="kim@tips.example")
        third_trainer = add_certified_proctor(base, full_name="Lee Park",
                                              email="lee@tips.example")
        adjacent = create_scheduled_session(
            base["course"]["id"], base["jurisdiction"]["id"], second_trainer["id"],
            scheduled_start_at=ADJACENT_START, scheduled_end_at=ADJACENT_END, capacity=20)
        overlapping = create_scheduled_session(
            base["course"]["id"], base["jurisdiction"]["id"], third_trainer["id"],
            scheduled_start_at=OVERLAPPING_START, scheduled_end_at=OVERLAPPING_END,
            capacity=20)

        server = register_alcohol_server(base["jurisdiction"]["id"])
        held_seat = enroll_server(base["session"]["id"], server["id"],
                                  headers=make_alcohol_server_headers(server["id"]))
        return base, server, held_seat, adjacent, overlapping

    def test_a_class_starting_when_the_held_one_ends_is_admitted(self, api):
        """PRD §3.5: "And a server may not be booked into two classes at once: if the requested
        session's half-open window from `scheduled_start_at` up to but excluding
        `scheduled_end_at` intersects the half-open window of another session on which this
        server holds an enrollment in `REGISTERED`, `ATTENDED`, `EXAM_SCHEDULED`,
        `EXAM_IN_PROGRESS` or `EXAM_FAILED`, the request is refused with
        `ERR_SERVER_SESSION_OVERLAP`."
        PRD §3.5: "Because both windows are half-open, a class starting at the exact instant
        another ends is allowed — there is no buffer here, in deliberate contrast to the trainer
        rule."
        PRD §3.5: "An accepted enrollment lands in `REGISTERED`, raises the session's
        `enrolled_count` by one and increments the session's `version` by one."

        Design: Difficulty/resource_temporal_overlap/server_half_open_enrollment_window_admits_exact_adjacency_but_rejects_a_one_hour_overlap
        """
        base, server, held_seat, adjacent, overlapping = (
            self._three_sessions_with_three_trainers())

        seat = validate_success(api.create_enrollment(
            enrollment_payload(adjacent["id"], server["id"], adjacent["version"]),
            make_alcohol_server_headers(server["id"])), 201)
        assert_enrollment(seat)
        assert seat["enrollment_state"] == "REGISTERED", (
            "half-open windows that merely touch do not overlap, got "
            f"{seat['enrollment_state']}")
        assert get_session(adjacent["id"])["enrolled_count"] == 1

    def test_a_one_hour_overlap_is_refused(self, api):
        """PRD §3.5: "And a server may not be booked into two classes at once: if the requested
        session's half-open window from `scheduled_start_at` up to but excluding
        `scheduled_end_at` intersects the half-open window of another session on which this
        server holds an enrollment in `REGISTERED`, `ATTENDED`, `EXAM_SCHEDULED`,
        `EXAM_IN_PROGRESS` or `EXAM_FAILED`, the request is refused with
        `ERR_SERVER_SESSION_OVERLAP`."
        PRD §3.5: "Enrollments can be read individually or listed with filters on
        `class_session_id`, `alcohol_server_id`, `sponsoring_employer_account_id` and
        `enrollment_state`."
        PRD §3.5: "An accepted enrollment lands in `REGISTERED`, raises the session's
        `enrolled_count` by one and increments the session's `version` by one."

        Design: Difficulty/resource_temporal_overlap/server_half_open_enrollment_window_admits_exact_adjacency_but_rejects_a_one_hour_overlap
        """
        base, server, held_seat, adjacent, overlapping = (
            self._three_sessions_with_three_trainers())
        server_headers = make_alcohol_server_headers(server["id"])

        adjacent_seat = validate_success(api.create_enrollment(
            enrollment_payload(adjacent["id"], server["id"], adjacent["version"]),
            server_headers), 201)

        response = api.create_enrollment(
            enrollment_payload(overlapping["id"], server["id"], overlapping["version"]),
            server_headers)
        validate_error(response, ApiErrorId.ERR_SERVER_SESSION_OVERLAP, 409)

        refused = get_session(overlapping["id"])
        assert refused["enrolled_count"] == 0
        assert refused["version"] == overlapping["version"], (
            "a refused seat claim does not bump the roster revision, got "
            f"{refused['version']} against {overlapping['version']}")

        seats, meta = validate_paginated(api.list_enrollments(
            base["trainer_headers"], {"alcohol_server_id": server["id"]}))
        assert meta["total_count"] == 2, (
            f"only two seats were ever accepted, got {meta['total_count']}")
        assert {s["id"] for s in seats} == {held_seat["id"], adjacent_seat["id"]}
