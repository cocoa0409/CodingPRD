"""The two interval rules that guard seating: the rest buffer and supervision capacity."""

from test_helpers import (
    ApiErrorId,
    ShiftAssignmentStatus,
    assert_hours,
    assert_shift_assignment,
    factories,
    fixtures,
    make_case_manager_headers,
    validate_error,
    validate_success,
)


class TestParticipantRestBuffer:
    """A gap of exactly sixty minutes is a gap; fifty-nine minutes is a conflict."""

    def test_a_gap_of_exactly_sixty_minutes_is_accepted(self, api):
        """The buffered exclusion is satisfied at exactly the full hour.

        "A gap of exactly 60 minutes between two shifts is therefore accepted, a gap
        of 59 minutes is rejected, and back-to-back shifts with no gap at all are
        rejected."

        Design: Difficulty/resource_temporal_overlap/participant_rest_buffer_accepts_60_rejects_59_minute_gap
        """
        program = fixtures.rest_buffer_program(api)

        response = api.create_shift_assignment(
            factories.shift_assignment_payload(
                program["shift_b"]["id"], program["participant"]["id"]
            ),
            make_case_manager_headers(),
        )
        assignment = validate_success(response, 201)

        assert_shift_assignment(assignment)
        assert assignment["status"] == ShiftAssignmentStatus.ASSIGNED

        shift_b = fixtures.read_work_shift(api, program["shift_b"]["id"])
        assert shift_b["assigned_count"] == 1

        participant = fixtures.read_participant(api, program["participant"]["id"])
        assert_hours(
            participant["scheduled_hours_current_week"],
            6.000,
            "scheduled_hours_current_week",
        )

    def test_a_gap_of_fifty_nine_minutes_is_refused(self, api):
        """One minute short of the buffer is a rest-buffer conflict.

        "The new seating is rejected when the new shift's `starts_at` is earlier
        than the other shift's `ends_at` plus 60 minutes **and** the other shift's
        `starts_at` is earlier than the new shift's `ends_at` plus 60 minutes."

        Design: Difficulty/resource_temporal_overlap/participant_rest_buffer_accepts_60_rejects_59_minute_gap
        """
        program = fixtures.rest_buffer_program(api)
        fixtures.seat_participant(
            api, program["shift_b"]["id"], program["participant"]["id"]
        )

        response = api.create_shift_assignment(
            factories.shift_assignment_payload(
                program["shift_c"]["id"], program["participant"]["id"]
            ),
            make_case_manager_headers(),
        )

        validate_error(response, ApiErrorId.ERR_PARTICIPANT_REST_BUFFER_CONFLICT, 409)

        shift_c = fixtures.read_work_shift(api, program["shift_c"]["id"])
        assert shift_c["assigned_count"] == 0

        participant = fixtures.read_participant(api, program["participant"]["id"])
        assert_hours(
            participant["scheduled_hours_current_week"],
            6.000,
            "scheduled_hours_current_week",
        )


class TestLineWideSupervisionCapacity:
    """One supervisor's worth of capacity, tested against overlap and adjacency."""

    def test_overlapping_shifts_contend_for_supervision_capacity(self, api):
        """Two concurrent seats exceed a capacity of one.

        "For every instant inside the new shift's half-open interval, the number of
        `ASSIGNED` seats across **all** `SCHEDULED` shifts of the same business line
        whose half-open intervals contain that instant must remain at or below the
        line's `supervisor_capacity`."

        Design: Difficulty/resource_temporal_overlap/supervision_capacity_rejects_overlap_allows_adjacency
        """
        program = fixtures.supervision_capacity_program(api)

        response = api.create_shift_assignment(
            factories.shift_assignment_payload(
                program["shift_y"]["id"], program["second_participant"]["id"]
            ),
            make_case_manager_headers(),
        )

        validate_error(response, ApiErrorId.ERR_SUPERVISION_CAPACITY_EXCEEDED, 409)

        shift_y = fixtures.read_work_shift(api, program["shift_y"]["id"])
        assert shift_y["assigned_count"] == 0
        shift_x = fixtures.read_work_shift(api, program["shift_x"]["id"])
        assert shift_x["assigned_count"] == 1

    def test_touching_shifts_never_contend(self, api):
        """Adjacency at the shared instant is explicitly allowed.

        "Adjacency is explicitly allowed here: touching shifts never contend,
        because the shared instant belongs to only one of the two half-open
        intervals."

        Design: Difficulty/resource_temporal_overlap/supervision_capacity_rejects_overlap_allows_adjacency
        """
        program = fixtures.supervision_capacity_program(api)

        response = api.create_shift_assignment(
            factories.shift_assignment_payload(
                program["shift_z"]["id"], program["second_participant"]["id"]
            ),
            make_case_manager_headers(),
        )
        assignment = validate_success(response, 201)

        assert assignment["status"] == ShiftAssignmentStatus.ASSIGNED

        shift_z = fixtures.read_work_shift(api, program["shift_z"]["id"])
        assert shift_z["assigned_count"] == 1
        shift_x = fixtures.read_work_shift(api, program["shift_x"]["id"])
        assert shift_x["assigned_count"] == 1

        participant = fixtures.read_participant(api, program["second_participant"]["id"])
        assert_hours(
            participant["scheduled_hours_current_week"],
            4.000,
            "scheduled_hours_current_week",
        )
