"""Two resources with two different interval rules: elements and facilitators."""

from test_helpers import (
    ERR_ELEMENT_SCHEDULE_CONFLICT,
    ERR_FACILITATOR_SCHEDULE_CONFLICT,
    validate_error,
    validate_success,
)
from test_helpers.constants import CLOCK_TEST_UTC, ELEMENT_NAME_GROUND, ELEMENT_NAME_LOW
from test_helpers.factories import program_block_payload
from test_helpers.fixtures import (
    add_blocks,
    assign_facilitator,
    create_booking,
    create_course,
    create_element,
    create_funded_client,
    create_staff_facilitator,
    set_clock,
)
from test_helpers.test_users import PROGRAM_DIRECTOR


def _element_occupied_until_half_past_ten(api):
    """A draft program whose low-element block holds the element from 09:45 to 10:30."""
    set_clock(api, CLOCK_TEST_UTC)
    course_id = create_course(api)
    l_id = create_element(api, course_id, "LOW_ELEMENT", element_name=ELEMENT_NAME_LOW)
    gc_id = create_funded_client(api, amount_cents=0)
    b_id, _ = create_booking(api, course_id, gc_id, 1)
    add_blocks(
        api,
        b_id,
        [
            (1, "ICEBREAKER", "2026-09-15T09:00:00Z", "2026-09-15T09:45:00Z", None),
            (2, "LOW_ELEMENT", "2026-09-15T09:45:00Z", "2026-09-15T10:30:00Z", l_id),
        ],
    )
    return {"course_id": course_id, "l_id": l_id, "b_id": b_id}


class TestElementOccupancyIsHalfOpen:
    """The interval includes its start instant and excludes its end instant."""

    def test_a_block_starting_at_the_previous_end_instant_is_accepted(self, api):
        """Exact adjacency on one element is deliberately legal.

        PRD 3.7: "Adjacency is deliberately permitted — one block ending at 10:30
        and another starting at 10:30 on the same element is accepted."

        Design: Difficulty/resource_temporal_overlap/element_occupancy_rejects_overlap_but_allows_exact_adjacency
        """
        world = _element_occupied_until_half_past_ten(api)

        block = validate_success(
            api.create_program_block(
                program_block_payload(
                    world["b_id"],
                    3,
                    "LOW_ELEMENT",
                    "2026-09-15T10:30:00Z",
                    "2026-09-15T11:30:00Z",
                    element_id=world["l_id"],
                ),
                PROGRAM_DIRECTOR,
            ),
            201,
        )

        assert block["status"] == "SCHEDULED"
        assert block["sequence_index"] == 3
        booking = validate_success(api.get_booking(world["b_id"], PROGRAM_DIRECTOR))
        assert booking["block_count"] == 3

    def test_a_single_minute_of_true_overlap_is_refused(self, api):
        """One minute inside an occupied window is a conflict.

        PRD 3.7: "Elements are also single-occupancy: the new block's interval,
        treated as half-open so that it includes its start instant and excludes
        its end instant, may not overlap any non-terminal block already booked on
        the same element, or the refusal is `ERR_ELEMENT_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/element_occupancy_rejects_overlap_but_allows_exact_adjacency
        """
        world = _element_occupied_until_half_past_ten(api)
        add_blocks(
            api,
            world["b_id"],
            [(3, "LOW_ELEMENT", "2026-09-15T10:30:00Z", "2026-09-15T11:30:00Z", world["l_id"])],
        )

        validate_error(
            api.create_program_block(
                program_block_payload(
                    world["b_id"],
                    4,
                    "LOW_ELEMENT",
                    "2026-09-15T11:29:00Z",
                    "2026-09-15T12:00:00Z",
                    element_id=world["l_id"],
                ),
                PROGRAM_DIRECTOR,
            ),
            ERR_ELEMENT_SCHEDULE_CONFLICT,
            409,
        )

        booking = validate_success(api.get_booking(world["b_id"], PROGRAM_DIRECTOR))
        assert booking["block_count"] == 3


def _facilitator_busy_until_three_o_clock(api):
    """One facilitator staffing a low-element block that runs 13:00 to 15:00.

    Two later blocks are waiting for them: a ground initiative ten minutes after
    that block ends and a low element twenty minutes after it ends.
    """
    set_clock(api, CLOCK_TEST_UTC)
    course_id = create_course(api)
    f1_id = create_staff_facilitator(api, course_id)
    g_id = create_element(
        api, course_id, "GROUND_INITIATIVE", element_name=ELEMENT_NAME_GROUND
    )
    l_id = create_element(api, course_id, "LOW_ELEMENT", element_name=ELEMENT_NAME_LOW)
    gc_id = create_funded_client(api, amount_cents=0)
    b_id, _ = create_booking(api, course_id, gc_id, 1)
    block_ids = add_blocks(
        api,
        b_id,
        [
            (1, "ICEBREAKER", "2026-09-15T09:00:00Z", "2026-09-15T09:45:00Z", None),
            (2, "LOW_ELEMENT", "2026-09-15T13:00:00Z", "2026-09-15T15:00:00Z", l_id),
            (3, "GROUND_INITIATIVE", "2026-09-15T15:10:00Z", "2026-09-15T15:40:00Z", g_id),
            (4, "LOW_ELEMENT", "2026-09-15T15:20:00Z", "2026-09-15T16:00:00Z", l_id),
            (5, "DEBRIEF", "2026-09-15T16:00:00Z", "2026-09-15T16:30:00Z", None),
        ],
    )
    assign_facilitator(api, block_ids[1], f1_id, assignment_role="LEAD")

    return {
        "course_id": course_id,
        "f1_id": f1_id,
        "b_id": b_id,
        "blk2_id": block_ids[1],
        "blk3_id": block_ids[2],
        "blk4_id": block_ids[3],
    }


class TestFacilitatorTurnaroundBuffer:
    """The facilitator rule pads twenty minutes onto the earlier block's end."""

    def test_a_ten_minute_gap_is_refused_even_without_any_overlap(self, api):
        """Non-overlapping blocks still collide inside the buffer.

        PRD 3.7: "And a turnaround buffer of twenty minutes separates a person's
        consecutive blocks: an assignment is refused with
        `ERR_FACILITATOR_SCHEDULE_CONFLICT` when the later block starts before the
        earlier block's end plus twenty minutes, so a block ending at 15:00
        permits a next assignment starting at 15:20 exactly but refuses one
        starting at 15:10."

        Design: Difficulty/resource_temporal_overlap/facilitator_turnaround_buffer_rejects_ten_minute_gap_and_accepts_twenty
        """
        world = _facilitator_busy_until_three_o_clock(api)

        validate_error(
            api.create_block_assignment(
                world["blk3_id"],
                {"facilitator_id": world["f1_id"], "assignment_role": "LEAD"},
                PROGRAM_DIRECTOR,
            ),
            ERR_FACILITATOR_SCHEDULE_CONFLICT,
            409,
        )

        blk3 = validate_success(api.get_program_block(world["blk3_id"], PROGRAM_DIRECTOR))
        assert blk3["assigned_facilitator_count"] == 0
        blk2 = validate_success(api.get_program_block(world["blk2_id"], PROGRAM_DIRECTOR))
        assert blk2["assigned_facilitator_count"] == 1

    def test_a_gap_of_exactly_twenty_minutes_is_accepted(self, api):
        """The buffer endpoint is inclusive of the twenty-minute mark.

        PRD 3.7: "Each accepted assignment freezes
        `rescue_current_at_assignment`, a boolean snapshot of whether that
        facilitator's `rescue_drill_last_passed_on` was within 180 days of the
        clock date at the moment of assignment."

        PRD 3.7: "The block's `assigned_facilitator_count` — simply the number of
        assignments on the block — rises by one, and the supervision arithmetic is
        re-derived."

        Design: Difficulty/resource_temporal_overlap/facilitator_turnaround_buffer_rejects_ten_minute_gap_and_accepts_twenty
        """
        world = _facilitator_busy_until_three_o_clock(api)

        assignment = validate_success(
            api.create_block_assignment(
                world["blk4_id"],
                {"facilitator_id": world["f1_id"], "assignment_role": "LEAD"},
                PROGRAM_DIRECTOR,
            ),
            201,
        )

        assert assignment["program_block_id"] == world["blk4_id"]
        assert assignment["facilitator_id"] == world["f1_id"]
        assert assignment["rescue_current_at_assignment"] is True

        blk4 = validate_success(api.get_program_block(world["blk4_id"], PROGRAM_DIRECTOR))
        assert blk4["assigned_facilitator_count"] == 1
