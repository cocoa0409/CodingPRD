"""Concurrency: serialised races and OCC (PRD §2.9, §2.5)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    run_race,
    assert_exactly_one_succeeds,
    ApiErrorId,
    create_active_student,
    create_default_package,
    create_active_instructor,
    create_active_vehicle,
    book_practice,
    file_complaint,
    assign_handler_payload,
    create_practice_payload,
    iso_z,
    future_window,
    _server_clock_now,
    ADMIN_HEADERS,
)


class TestRaceConditions:

    def test_two_concurrent_assign_handler_calls_serialise(self, api):
        """PRD §2.9: "Two simultaneous assign-handler calls on the same OPEN
        complaint serialise to exactly one winner that moves the complaint to
        IN_REVIEW; the loser receives ERR_COMPLAINT_NOT_ASSIGNABLE."

        Claim: exactly one of two concurrent assign-handler calls succeeds.
        """
        student, _ = create_active_student(api)
        complaint = file_complaint(api, student=student, category="BILLING")

        results = run_race(
            lambda: api.assign_handler(complaint["id"],
                                         assign_handler_payload(handler_id="h1",
                                                                  handler_role="ComplaintHandler"),
                                         ADMIN_HEADERS),
            lambda: api.assign_handler(complaint["id"],
                                         assign_handler_payload(handler_id="h2",
                                                                  handler_role="ComplaintHandler"),
                                         ADMIN_HEADERS),
        )
        assert_exactly_one_succeeds(results[0], results[1])

    def test_two_concurrent_practice_bookings_same_instructor_serialise(self, api):
        """PRD §2.9: "Two simultaneous practice bookings for the same instructor
        at overlapping times serialise to exactly one winner; the loser receives
        ERR_INSTRUCTOR_TIME_CONFLICT."

        Claim: exactly one of two simultaneous overlapping bookings succeeds.
        """
        package = create_default_package(api)
        s1, _ = create_active_student(api, package_id=package["id"])
        s2, _ = create_active_student(api, package_id=package["id"])
        instructor = create_active_instructor(api)
        v1 = create_active_vehicle(api)
        v2 = create_active_vehicle(api)

        start, end, _ = future_window(api, offset_minutes=24*60, duration_minutes=60)

        results = run_race(
            lambda: api.book_practice(create_practice_payload(
                student_id=s1["id"], instructor_id=instructor["id"], vehicle_id=v1["id"],
                training_stage="THEORY",
                scheduled_start_at=start, scheduled_end_at=end,
            ), ADMIN_HEADERS),
            lambda: api.book_practice(create_practice_payload(
                student_id=s2["id"], instructor_id=instructor["id"], vehicle_id=v2["id"],
                training_stage="THEORY",
                scheduled_start_at=start, scheduled_end_at=end,
            ), ADMIN_HEADERS),
        )
        assert_exactly_one_succeeds(results[0], results[1])
