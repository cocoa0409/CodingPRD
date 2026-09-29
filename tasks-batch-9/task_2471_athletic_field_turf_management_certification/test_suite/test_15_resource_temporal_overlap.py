"""Two overlap guards on two different resources, with different interval rules."""

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


def _practice_payload(roster, field_id, start_utc, end_utc):
    """A thirty-strong practice request on one field between two instants."""
    return factories.make_usage_booking_payload(
        field_id=field_id,
        requested_by_staff_member_id=roster.id_of("coordinator"),
        activity_type="PRACTICE",
        window_start_utc=start_utc,
        window_end_utc=end_utc,
        expected_participant_count=30,
    )


class TestBookingChangeoverBuffer:
    def test_zero_gap_collides_and_exactly_thirty_minutes_does_not(
        self, client, roster
    ):
        """The buffer widens an existing window by half an hour on each side.

        "Two bookings may not collide on the same surface, and the collision test
        builds in a **changeover buffer of thirty minutes** on each side, applied
        symmetrically."

        "Considering only bookings on the same field whose `status` is `SCHEDULED` or
        `CONFIRMED` — terminal-status bookings are excluded from the candidate set
        entirely — the requested window conflicts with an existing one when the
        requested `window_start_utc` falls strictly before the existing
        `window_end_utc` extended forward by thirty minutes **and** the existing
        `window_start_utc` falls strictly before the requested `window_end_utc`
        extended forward by thirty minutes."

        "The practical consequence is worth stating plainly: two back-to-back
        bookings with a gap of zero **do** conflict, because the trailing edge of the
        earlier one, widened by the buffer, still covers the leading edge of the
        later; a gap of exactly thirty minutes is accepted."

        "A conflict is refused with `ERR_BOOKING_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/booking_changeover_buffer_rejects_zero_gap_and_accepts_thirty_minutes
        """
        field = fixtures.register_grass_practice_3(client, roster)
        first = fixtures.request_booking(
            client,
            roster,
            field["id"],
            activity_type="PRACTICE",
            window_start_utc="2026-08-05T19:00:00Z",
            window_end_utc="2026-08-05T21:00:00Z",
            expected_participant_count=30,
        )
        assert first["status"] == "SCHEDULED"

        # 21:00 is the instant the first window ends, and the buffer covers it.
        validate_error(
            client.create_usage_booking(
                _practice_payload(
                    roster,
                    field["id"],
                    "2026-08-05T21:00:00Z",
                    "2026-08-05T23:00:00Z",
                ),
                roster.coordinator_headers,
            ),
            ApiErrorId.BOOKING_WINDOW_CONFLICT,
            409,
        )

        # Half an hour later and the same two-hour slot is free.
        accepted = validate_success(
            client.create_usage_booking(
                _practice_payload(
                    roster,
                    field["id"],
                    "2026-08-05T21:30:00Z",
                    "2026-08-05T23:30:00Z",
                ),
                roster.coordinator_headers,
            ),
            201,
        )
        assert accepted["status"] == "SCHEDULED"

        untouched = fixtures.read_booking(client, roster, first["id"])
        assert untouched["status"] == "SCHEDULED"
        _items, meta = validate_paginated(
            client.list_usage_bookings(
                roster.coordinator_headers,
                params={"limit": 100, "field_id": field["id"]},
            )
        )
        assert meta["total_count"] == 2, "one request was refused and minted no row"

        # The buffer is symmetric, so a slot ending thirty minutes before the
        # existing window opens is equally acceptable.
        leading = validate_success(
            client.create_usage_booking(
                _practice_payload(
                    roster,
                    field["id"],
                    "2026-08-05T17:30:00Z",
                    "2026-08-05T18:30:00Z",
                ),
                roster.coordinator_headers,
            ),
            201,
        )
        assert leading["status"] == "SCHEDULED"
        _items, meta = validate_paginated(
            client.list_usage_bookings(
                roster.coordinator_headers,
                params={"limit": 100, "field_id": field["id"]},
            )
        )
        assert meta["total_count"] == 3

    def test_the_candidate_set_is_one_field_and_excludes_terminal_bookings(
        self, client, roster
    ):
        """Whose windows count: same surface, and not yet finished with.

        "Considering only bookings on the same field whose `status` is `SCHEDULED` or
        `CONFIRMED` — terminal-status bookings are excluded from the candidate set
        entirely — the requested window conflicts with an existing one when the
        requested `window_start_utc` falls strictly before the existing
        `window_end_utc` extended forward by thirty minutes **and** the existing
        `window_start_utc` falls strictly before the requested `window_end_utc`
        extended forward by thirty minutes."

        "And in neither case are the bookings that hop four already cancelled
        reinstated: `CANCELLED_UNSAFE` is terminal, and re-establishing the fixture
        requires a fresh allocation."

        "A permitted void takes the assessment `RECORDED → VOIDED`, records the
        supplied `void_reason`, cancels the remediation orders it opened as described
        in §3.4, decrements whichever field remediation counter those orders were
        populating, recomputes `play_status`, and increments `Field.version` by 1."

        Design: Difficulty/resource_temporal_overlap/booking_changeover_buffer_rejects_zero_gap_and_accepts_thirty_minutes
        """
        field = fixtures.register_grass_practice_3(client, roster)
        other_field = fixtures.register_grass_main_1(client, roster)
        doomed = fixtures.request_booking(
            client,
            roster,
            field["id"],
            activity_type="PRACTICE",
            window_start_utc="2026-08-05T19:00:00Z",
            window_end_utc="2026-08-05T21:00:00Z",
            expected_participant_count=30,
        )
        fixtures.confirm_booking(client, roster, doomed["id"])

        # An identical window on a different surface is not a peer at all.
        elsewhere = validate_success(
            client.create_usage_booking(
                _practice_payload(
                    roster,
                    other_field["id"],
                    "2026-08-05T19:00:00Z",
                    "2026-08-05T21:00:00Z",
                ),
                roster.coordinator_headers,
            ),
            201,
        )
        assert elsewhere["status"] == "SCHEDULED"

        # Take the first booking to a terminal status through the unsafe cascade,
        # then lift the closure again so only the buffer rule is left standing.
        assessment, _order = fixtures.fail_field_unsafe(client, roster, field["id"])
        assert (
            fixtures.read_booking(client, roster, doomed["id"])["status"]
            == "CANCELLED_UNSAFE"
        )
        fixtures.void_assessment(client, roster, assessment["id"])
        recovered = fixtures.read_field(client, roster, field["id"])
        assert recovered["open_mandatory_remediation_count"] == 0
        assert recovered["play_status"] == "OPEN"

        # The cancelled fixture is not reinstated and no longer defends its window.
        assert (
            fixtures.read_booking(client, roster, doomed["id"])["status"]
            == "CANCELLED_UNSAFE"
        )
        replacement = validate_success(
            client.create_usage_booking(
                _practice_payload(
                    roster,
                    field["id"],
                    "2026-08-05T20:00:00Z",
                    "2026-08-05T22:00:00Z",
                ),
                roster.coordinator_headers,
            ),
            201,
        )
        assert replacement["status"] == "SCHEDULED"

        # And the new fixture does defend it, buffer and all.
        validate_error(
            client.create_usage_booking(
                _practice_payload(
                    roster,
                    field["id"],
                    "2026-08-05T22:00:00Z",
                    "2026-08-05T23:00:00Z",
                ),
                roster.coordinator_headers,
            ),
            ApiErrorId.BOOKING_WINDOW_CONFLICT,
            409,
        )


class TestStaffTaskCapacity:
    def _two_touching_tasks(self, client, roster, field_id):
        """Aeration 08:00-10:00 and overseeding 10:00-12:00 for one agronomist."""
        first = fixtures.schedule_task(
            client,
            roster,
            field_id,
            task_type="AERATION",
            scheduled_start_utc="2026-08-10T08:00:00Z",
            scheduled_end_utc="2026-08-10T10:00:00Z",
        )
        second = fixtures.schedule_task(
            client,
            roster,
            field_id,
            task_type="OVERSEEDING",
            scheduled_start_utc="2026-08-10T10:00:00Z",
            scheduled_end_utc="2026-08-10T12:00:00Z",
        )
        assert first["status"] == "SCHEDULED"
        assert second["status"] == "SCHEDULED"
        return first, second

    def test_the_third_concurrent_task_is_refused_but_a_touching_one_is_not(
        self, client, full_roster
    ):
        """Closed intervals, a cap of two, and the person as the resource.

        "Counting only tasks assigned to the same `assigned_staff_member_id` whose
        `status` is `SCHEDULED` or `IN_PROGRESS`, and treating each task's window as
        the closed interval running from `scheduled_start_utc` to `scheduled_end_utc`
        inclusive — so two tasks that merely touch at an endpoint *do* intersect —
        the request is refused with `ERR_STAFF_TASK_CAPACITY_EXCEEDED` when that
        count already stands at two or more."

        "There is no buffer and a single overlap is perfectly legal; it is the
        aggregate of two concurrent tasks that is the cap."

        "`AERATION`, `OVERSEEDING`, `FERTILITY` and `IRRIGATION` are agronomic
        operations and may only be scheduled on a field whose `surface_type` is
        `NATURAL_GRASS`; `GROOMING`, `INFILL_REDISTRIBUTION` and `SEAM_INSPECTION`
        are synthetic operations and may only be scheduled on a field whose
        `surface_type` is `SYNTHETIC_TURF`."

        Design: Difficulty/resource_temporal_overlap/staff_task_capacity_counts_closed_interval_overlaps_at_two
        """
        field = fixtures.register_grass_practice_3(client, full_roster)
        first, second = self._two_touching_tasks(client, full_roster, field["id"])

        # 09:00-11:00 sits across both existing windows, so the count would be three.
        validate_error(
            client.create_maintenance_task(
                factories.make_maintenance_task_payload(
                    field_id=field["id"],
                    assigned_staff_member_id=full_roster.id_of("agronomist"),
                    task_type="IRRIGATION",
                    scheduled_start_utc="2026-08-10T09:00:00Z",
                    scheduled_end_utc="2026-08-10T11:00:00Z",
                ),
                full_roster.agronomist_headers,
            ),
            ApiErrorId.STAFF_TASK_CAPACITY_EXCEEDED,
            409,
        )

        # 12:00-13:00 touches only the overseeding, so the count is two.
        touching = fixtures.schedule_task(
            client,
            full_roster,
            field["id"],
            task_type="IRRIGATION",
            scheduled_start_utc="2026-08-10T12:00:00Z",
            scheduled_end_utc="2026-08-10T13:00:00Z",
        )
        assert touching["status"] == "SCHEDULED"

        assert (
            fixtures.read_task(client, full_roster, first["id"])["status"]
            == "SCHEDULED"
        )
        assert (
            fixtures.read_task(client, full_roster, second["id"])["status"]
            == "SCHEDULED"
        )
        _items, meta = validate_paginated(
            client.list_maintenance_tasks(
                full_roster.agronomist_headers,
                params={
                    "limit": 100,
                    "assigned_staff_member_id": full_roster.id_of("agronomist"),
                },
            )
        )
        assert meta["total_count"] == 3, "the refused request minted no row"

        # The cap belongs to the person: a colleague may take the refused window.
        colleague = validate_success(
            client.create_maintenance_task(
                factories.make_maintenance_task_payload(
                    field_id=field["id"],
                    assigned_staff_member_id=full_roster.id_of("agronomist_two"),
                    task_type="IRRIGATION",
                    scheduled_start_utc="2026-08-10T09:00:00Z",
                    scheduled_end_utc="2026-08-10T11:00:00Z",
                ),
                full_roster.headers_of("agronomist_two"),
            ),
            201,
        )
        assert colleague["status"] == "SCHEDULED"
        assert colleague["assigned_staff_member_id"] == full_roster.id_of(
            "agronomist_two"
        )

    def test_the_count_spans_fields_and_ignores_cancelled_work(
        self, client, full_roster
    ):
        """The resource is the diary, not the surface, and only live work fills it.

        "Counting only tasks assigned to the same `assigned_staff_member_id` whose
        `status` is `SCHEDULED` or `IN_PROGRESS`, and treating each task's window as
        the closed interval running from `scheduled_start_utc` to `scheduled_end_utc`
        inclusive — so two tasks that merely touch at an endpoint *do* intersect —
        the request is refused with `ERR_STAFF_TASK_CAPACITY_EXCEEDED` when that
        count already stands at two or more."

        "`CANCEL` is permitted from either `SCHEDULED` or `IN_PROGRESS`, takes the
        task to `CANCELLED`, and requires a `cancellation_reason` in the body."

        "There is no buffer and a single overlap is perfectly legal; it is the
        aggregate of two concurrent tasks that is the cap."

        Design: Difficulty/resource_temporal_overlap/staff_task_capacity_counts_closed_interval_overlaps_at_two
        """
        one_field = fixtures.register_grass_practice_3(client, full_roster)
        another_field = fixtures.register_grass_main_1(client, full_roster)

        morning = fixtures.schedule_task(
            client,
            full_roster,
            one_field["id"],
            task_type="AERATION",
            scheduled_start_utc="2026-08-10T08:00:00Z",
            scheduled_end_utc="2026-08-10T10:00:00Z",
        )
        # The same agronomist, the same morning, a different surface entirely.
        across_town = fixtures.schedule_task(
            client,
            full_roster,
            another_field["id"],
            task_type="OVERSEEDING",
            scheduled_start_utc="2026-08-10T10:00:00Z",
            scheduled_end_utc="2026-08-10T12:00:00Z",
        )
        assert across_town["field_id"] == another_field["id"]
        assert morning["field_id"] == one_field["id"]

        third = factories.make_maintenance_task_payload(
            field_id=one_field["id"],
            assigned_staff_member_id=full_roster.id_of("agronomist"),
            task_type="IRRIGATION",
            scheduled_start_utc="2026-08-10T09:00:00Z",
            scheduled_end_utc="2026-08-10T11:00:00Z",
        )
        validate_error(
            client.create_maintenance_task(third, full_roster.agronomist_headers),
            ApiErrorId.STAFF_TASK_CAPACITY_EXCEEDED,
            409,
        )

        # Cancelling one of the two leaves a single live overlap, which is legal.
        cancelled = validate_success(
            client.transition_maintenance_task(
                morning["id"],
                factories.make_task_cancel_payload("CONTRACTOR_UNAVAILABLE"),
                full_roster.agronomist_headers,
            ),
            200,
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_reason"] == "CONTRACTOR_UNAVAILABLE"

        admitted = validate_success(
            client.create_maintenance_task(third, full_roster.agronomist_headers),
            201,
        )
        assert admitted["status"] == "SCHEDULED"
        assert (
            fixtures.read_task(client, full_roster, across_town["id"])["status"]
            == "SCHEDULED"
        )
