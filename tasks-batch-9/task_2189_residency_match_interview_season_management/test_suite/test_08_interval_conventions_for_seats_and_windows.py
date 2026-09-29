"""Two interval rules with deliberately opposite conventions.

A panel seat's block is half-open with no buffer, so blocks that merely touch are
fine. A wave's window is closed and needs forty-eight hours of clearance, so
windows that merely touch are refused.
"""

from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    AssignmentStatus,
    PanelRole,
    WaveStatus,
    assert_load,
    build_interview_assignment_payload,
    build_interview_wave_payload,
    get_success_data,
    setup_screened_application,
    validate_error,
    validate_paginated,
    validate_success,
)

#: The held block, and the two blocks offered against it.
HELD_BLOCK = ("2026-10-05T13:00:00Z", "2026-10-05T16:00:00Z", "A-1")
ADJACENT_BLOCK = ("2026-10-05T16:00:00Z", "2026-10-05T18:00:00Z", "A-2")
OVERLAPPING_BLOCK = ("2026-10-05T15:00:00Z", "2026-10-05T17:00:00Z", "A-3")

#: The existing wave window every trigger is measured against.
EXISTING_RELEASE_AT = "2026-10-01T12:00:00Z"
EXISTING_DEADLINE_AT = "2026-10-08T12:00:00Z"

#: Three hours at the lead weight of 1.5.
LOAD_ONE_BLOCK = 4.50
#: Plus two hours at the same weight.
LOAD_TWO_BLOCKS = 7.50


def _one_held_lead_seat_and_two_offers():
    """A faculty member holding one lead seat, with two further blocks planned."""
    builder = setup_screened_application()
    builder.open_interviews()
    builder.create_wave(seat_capacity=4)
    for key, (start_at, end_at, room_label) in (
        ("slot1", HELD_BLOCK),
        ("slot2", ADJACENT_BLOCK),
        ("slot3", OVERLAPPING_BLOCK),
    ):
        builder.create_slot(
            key,
            start_at=start_at,
            end_at=end_at,
            room_label=room_label,
            applicant_capacity=4,
        )
    builder.assign("asg1", "slot1", "f1", PanelRole.LEAD)
    return builder


def _program_with_one_existing_wave():
    """One wave occupying the window from the first to the eighth of October."""
    builder = setup_screened_application()
    builder.open_interviews()
    builder.create_wave(
        seat_capacity=4,
        invite_release_at=EXISTING_RELEASE_AT,
        response_deadline_at=EXISTING_DEADLINE_AT,
    )
    return builder


def _second_wave(builder, api, wave_index, invite_release_at, response_deadline_at):
    return api.create_interview_wave(
        build_interview_wave_payload(
            builder.id("program"),
            wave_index=wave_index,
            invite_release_at=invite_release_at,
            response_deadline_at=response_deadline_at,
        ),
        builder.coordinator,
    )


def test_a_block_beginning_where_the_held_block_ends_is_permitted(api):
    """The held block ends at 16:00 and the offered one starts at 16:00.

    Half-open intervals that share only that endpoint do not intersect, so the
    seat is created and the load takes both blocks.

    PRD 3.5: "Exact adjacency — one block ending at the very instant the next begins — does **not** collide and is explicitly permitted, which is the opposite convention to the wave separation rule in §3.3."
    PRD 2.12: "Exact adjacency, one slot ending at the instant the next begins, does not intersect and is permitted."

    Design: Difficulty/resource_temporal_overlap/interviewer_half_open_adjacency_allowed_but_one_hour_overlap_rejected
    """
    builder = _one_held_lead_seat_and_two_offers()

    before = get_success_data(
        api.get_faculty_member(builder.id("f1"), builder.coordinator)
    )
    assert_load(before, scheduled=LOAD_ONE_BLOCK, realized=0.00)

    created = validate_success(
        api.create_interview_assignment(
            build_interview_assignment_payload(
                builder.id("slot2"), builder.id("f1"), PanelRole.LEAD
            ),
            builder.coordinator,
        ),
        expected_status=201,
    )
    assert created["status"] == AssignmentStatus.ASSIGNED, (
        f"the adjacent seat should be ASSIGNED, got {created['status']}"
    )

    after = get_success_data(api.get_faculty_member(builder.id("f1"), builder.coordinator))
    assert_load(after, scheduled=LOAD_TWO_BLOCKS, realized=0.00)


def test_a_block_overlapping_the_held_block_by_an_hour_is_refused(api):
    """The third block runs 15:00 to 17:00 against a seat held 13:00 to 16:00.

    That shared hour is a genuine intersection, so the seat is refused and the
    load stays where the two accepted seats left it.

    PRD 2.12: "**Priority 9 — interviewer double-booking.** On `POST /interview-assignments`, the assigned `FacultyMember` holds no other `ASSIGNED` `InterviewAssignment` whose slot interval intersects the target slot's interval, where intervals are **half-open** — they include `start_at` and exclude `end_at` — and **no buffer** is applied."
    PRD 3.5: "A collision is refused with `ERR_INTERVIEWER_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/interviewer_half_open_adjacency_allowed_but_one_hour_overlap_rejected
    """
    builder = _one_held_lead_seat_and_two_offers()
    builder.assign("asg2", "slot2", "f1", PanelRole.LEAD)

    response = api.create_interview_assignment(
        build_interview_assignment_payload(
            builder.id("slot3"), builder.id("f1"), PanelRole.LEAD
        ),
        builder.coordinator,
    )
    validate_error(response, ApiErrorId.ERR_INTERVIEWER_DOUBLE_BOOKED)

    rows, meta = validate_paginated(
        api.list_interview_assignments(
            builder.coordinator, params={"faculty_member_id": builder.id("f1")}
        )
    )
    assert meta["total_count"] == 2, (
        f"only the two permitted seats should exist, got {meta['total_count']}"
    )
    assert len(rows) == 2

    faculty = get_success_data(
        api.get_faculty_member(builder.id("f1"), builder.coordinator)
    )
    assert_load(faculty, scheduled=LOAD_TWO_BLOCKS, realized=0.00)


def test_a_wave_window_starting_at_the_existing_deadline_is_refused(api):
    """Zero hours of clearance is a conflict, unlike the touching panel blocks.

    The new window opens at the very instant the existing one closes, and the
    closed-interval convention rejects that.

    PRD 3.3: "Windows that merely touch are **rejected**, which is the opposite convention to the interviewer overlap rule in §3.5, and a violation is reported as `ERR_WAVE_WINDOW_CONFLICT`."
    PRD 2.12: "Exact adjacency is **rejected** here, unlike the interviewer rule."

    Design: Difficulty/resource_temporal_overlap/wave_closed_interval_requires_forty_eight_hour_buffer_both_directions
    """
    builder = _program_with_one_existing_wave()

    response = _second_wave(
        builder, api, 2, EXISTING_DEADLINE_AT, "2026-10-14T12:00:00Z"
    )
    validate_error(response, ApiErrorId.ERR_WAVE_WINDOW_CONFLICT)


def test_a_wave_window_forty_seven_hours_clear_is_refused(api):
    """One hour short of the mandated gap is still a conflict.

    The new window opens at 11:00 on the tenth, forty-seven hours after the
    existing deadline.

    PRD 3.3: "The window a wave occupies is the **closed** interval running from `invite_release_at` through `response_deadline_at` inclusive, and a new wave's window must stand clear of every existing wave of the same program by at least 48 hours — two full days of separation."
    PRD 3.3: "The create succeeds only when the new wave's `invite_release_at` falls at or after the other wave's `response_deadline_at` plus that 48-hour gap, or the new wave's `response_deadline_at` plus that gap falls at or before the other wave's `invite_release_at`."

    Design: Difficulty/resource_temporal_overlap/wave_closed_interval_requires_forty_eight_hour_buffer_both_directions
    """
    builder = _program_with_one_existing_wave()

    response = _second_wave(
        builder, api, 2, "2026-10-10T11:00:00Z", "2026-10-15T12:00:00Z"
    )
    validate_error(response, ApiErrorId.ERR_WAVE_WINDOW_CONFLICT)


def test_a_wave_window_exactly_forty_eight_hours_clear_is_accepted(api):
    """The gap comparison is inclusive, so the boundary value succeeds.

    The existing deadline plus forty-eight hours lands exactly on the new
    window's release instant.

    PRD 2.12: "Concretely, the create succeeds only when the new wave's `invite_release_at` is at or after the other wave's `response_deadline_at` plus 48 hours, or the new wave's `response_deadline_at` plus 48 hours is at or before the other wave's `invite_release_at`."
    PRD 3.3: "The wave materialises with `status` `PLANNED` and `issued_count` at 0, where `issued_count` is by definition the number of invitations in the wave whose `status` is `ISSUED` or `ACCEPTED`."

    Design: Difficulty/resource_temporal_overlap/wave_closed_interval_requires_forty_eight_hour_buffer_both_directions
    """
    builder = _program_with_one_existing_wave()

    created = validate_success(
        _second_wave(builder, api, 2, "2026-10-10T12:00:00Z", "2026-10-15T12:00:00Z"),
        expected_status=201,
    )

    assert created["status"] == WaveStatus.PLANNED, (
        f"a new wave materialises PLANNED, got {created['status']}"
    )
    assert created["issued_count"] == 0, (
        f"a new wave holds no invitations, got {created['issued_count']}"
    )


def test_the_gap_is_measured_on_the_earlier_side_too(api):
    """A window that closes forty-eight hours before the existing one opens is fine.

    The rule is symmetric, so the program ends up holding three waves once both
    admissible windows are planned.

    PRD 3.3: "Wave windows may not crowd each other."
    PRD 3.3: "A `ProgramCoordinator` plans a wave by supplying the owning `program_id`, a `wave_index` that is a 1-based ordinal at least 1 and unique within the program, an `invite_release_at` instant at which the wave's invitations become releasable, a `response_deadline_at` instant that must fall strictly after `invite_release_at` and after which an issued invitation in this wave lapses, and a `seat_capacity` of at least 1 that caps how many invitations the wave may hold in `ISSUED` or `ACCEPTED` state."

    Design: Difficulty/resource_temporal_overlap/wave_closed_interval_requires_forty_eight_hour_buffer_both_directions
    """
    builder = _program_with_one_existing_wave()
    validate_success(
        _second_wave(builder, api, 2, "2026-10-10T12:00:00Z", "2026-10-15T12:00:00Z"),
        expected_status=201,
    )

    earlier = validate_success(
        _second_wave(builder, api, 3, "2026-09-20T12:00:00Z", "2026-09-29T12:00:00Z"),
        expected_status=201,
    )
    assert earlier["status"] == WaveStatus.PLANNED

    rows, meta = validate_paginated(
        api.list_interview_waves(
            builder.coordinator, params={"program_id": builder.id("program")}
        )
    )
    assert meta["total_count"] == 3, (
        f"three admissible windows should coexist, got {meta['total_count']}"
    )
    assert sorted(row["wave_index"] for row in rows) == [1, 2, 3], (
        f"the three waves carry indices 1, 2 and 3, got "
        f"{sorted(row['wave_index'] for row in rows)}"
    )
