"""When two gates fail on one call, only the higher-precedence code is returned."""

from test_helpers import (
    ERR_BLOCK_NOT_SCHEDULED,
    ERR_COURSE_CLOSED,
    ERR_ELEMENT_PHASE_MISMATCH,
    ERR_ELEMENT_SCHEDULE_CONFLICT,
    ERR_INSUFFICIENT_CLIENT_CREDIT,
    ERR_RESCUE_READINESS_UNMET,
    assert_money,
    assert_posture,
    validate_error,
    validate_success,
)
from test_helpers.constants import CLOCK_TEST_UTC, ELEMENT_NAME_LOW
from test_helpers.factories import program_block_payload, weather_observation_payload
from test_helpers.fixtures import (
    add_blocks,
    add_participant,
    assign_facilitator,
    confirm_booking,
    create_booking,
    create_course,
    create_element,
    create_funded_client,
    create_staff_facilitator,
    quote_booking,
    set_clock,
    staffed_course,
)
from test_helpers.test_users import PROGRAM_DIRECTOR, make_group_coordinator_headers

TWO_BLOCK_PROGRAM = [
    (1, "ICEBREAKER", "2026-09-15T09:00:00Z", "2026-09-15T09:45:00Z"),
    (2, "DEBRIEF", "2026-09-15T09:45:00Z", "2026-09-15T10:15:00Z"),
]


def _closed_course_with_a_finished_icebreaker(api):
    """A lightning-closed course whose first block has already run to COMPLETED.

    The observation is timed at the clock instant, which is the latest instant an
    observation may carry, and its thirty-minute hold therefore still lies ahead
    of the clock.
    """
    set_clock(api, CLOCK_TEST_UTC)
    world = staffed_course(api)
    gc_id = create_funded_client(api)
    b_id, _ = create_booking(api, world["course_id"], gc_id, 1)
    add_participant(api, gc_id, b_id, "ADULT")
    block_ids = add_blocks(api, b_id, TWO_BLOCK_PROGRAM)
    quote_booking(api, b_id)
    confirm_booking(api, gc_id, b_id)

    assign_facilitator(api, block_ids[0], world["f1_id"])
    validate_success(api.start_program_block(block_ids[0], world["f1_headers"]))
    validate_success(api.complete_program_block(block_ids[0], {}, world["f1_headers"]))

    validate_success(
        api.create_weather_observation(
            weather_observation_payload(
                world["course_id"],
                observed_at=CLOCK_TEST_UTC,
                lightning_distance_km=5.0,
                wind_speed_kph=14.0,
                air_temp_c=21.0,
            ),
            world["f1_headers"],
        ),
        201,
    )

    world.update({"gc_id": gc_id, "b_id": b_id, "blk1_id": block_ids[0], "blk2_id": block_ids[1]})
    return world


class TestBlockStateOutranksCoursePosture:
    """At block start the state precondition is read before the course posture."""

    def test_restarting_a_completed_block_reports_the_state_error(self, api):
        """A completed block on a closed course answers the block-state code.

        PRD 2.12: "When a request violates several rules at once, exactly one
        error is returned, and which one is fully determined. Checks are
        evaluated in the following order, and the first failure ends the
        request."

        PRD 3.8: "The block's `status` must be `SCHEDULED` or `SUSPENDED`, or the
        refusal is `ERR_BLOCK_NOT_SCHEDULED`."

        Design: Difficulty/priority_pair_validation_conflict/completed_block_state_error_outranks_course_closed_on_start
        """
        world = _closed_course_with_a_finished_icebreaker(api)

        validate_error(
            api.start_program_block(world["blk1_id"], world["f1_headers"]),
            ERR_BLOCK_NOT_SCHEDULED,
            409,
        )

        block = validate_success(api.get_program_block(world["blk1_id"], PROGRAM_DIRECTOR))
        assert block["status"] == "COMPLETED"
        course = validate_success(api.get_course(world["course_id"], PROGRAM_DIRECTOR))
        assert_posture(course, "CLOSED", "LIGHTNING_STOP")

    def test_the_posture_gate_is_live_for_a_block_that_is_still_scheduled(self, api):
        """The outranked check fires on its own once the state precondition passes.

        PRD 3.8: "The course posture must not be `CLOSED`, and for a
        `HIGH_ELEMENT` phase it must be exactly `OPEN`, per §2.5."

        PRD 2.12: "11. Course posture — `ERR_COURSE_CLOSED`, or
        `ERR_COURSE_RESTRICTED_HIGH_ELEMENT` for a high-element phase. Applies to
        block start."

        Design: Difficulty/priority_pair_validation_conflict/completed_block_state_error_outranks_course_closed_on_start
        """
        world = _closed_course_with_a_finished_icebreaker(api)

        scheduled = validate_success(api.get_program_block(world["blk2_id"], PROGRAM_DIRECTOR))
        assert scheduled["status"] == "SCHEDULED"

        validate_error(
            api.start_program_block(world["blk2_id"], world["f1_headers"]),
            ERR_COURSE_CLOSED,
            409,
        )

        after = validate_success(api.get_program_block(world["blk2_id"], PROGRAM_DIRECTOR))
        assert after["status"] == "SCHEDULED"


def _quoted_booking_short_of_rescue_cover_and_money(api):
    """A quoted booking whose course has one active facilitator and whose client has nothing.

    Both the rescue-readiness gate and the client-credit gate of confirmation are
    violated by the same call.
    """
    set_clock(api, CLOCK_TEST_UTC)
    course_id = create_course(api)
    f1_id = create_staff_facilitator(api, course_id)
    gc_id = create_funded_client(api, amount_cents=0)
    b_id, _ = create_booking(api, course_id, gc_id, 1)
    add_participant(api, gc_id, b_id, "ADULT")
    add_blocks(api, b_id, TWO_BLOCK_PROGRAM)
    quoted = quote_booking(api, b_id)

    return {
        "course_id": course_id,
        "f1_id": f1_id,
        "gc_id": gc_id,
        "b_id": b_id,
        "quoted": quoted,
    }


class TestRescueReadinessOutranksClientCredit:
    """At confirmation the safety gate is read before the money gate."""

    def test_confirm_reports_the_readiness_code_and_allocates_nothing(self, api):
        """One active facilitator refuses the confirmation before the empty ledger does.

        PRD 2.12: "At booking confirmation, the order is inspection currency,
        then rescue readiness, then screening completeness, then the debrief
        block, then chaperone coverage, and finally client credit"

        PRD 2.5: "`rescue_readiness_ok` is true only when both halves hold:
        `rescue_ready_facilitator_count` — the number of the course's
        facilitators whose `cert_status` is `ACTIVE` — is at least two, and
        `ems_response_minutes` is at most 30."

        Design: Difficulty/priority_pair_validation_conflict/rescue_readiness_outranks_insufficient_client_credit_on_confirm
        """
        world = _quoted_booking_short_of_rescue_cover_and_money(api)
        assert_money(world["quoted"]["deposit_required_cents"], 341, "deposit_required_cents")

        validate_error(
            api.confirm_booking(world["b_id"], make_group_coordinator_headers(world["gc_id"])),
            ERR_RESCUE_READINESS_UNMET,
            409,
        )

        booking = validate_success(api.get_booking(world["b_id"], PROGRAM_DIRECTOR))
        assert booking["status"] == "QUOTED"
        assert_money(booking["deposit_required_cents"], 341, "deposit_required_cents")
        assert booking["deposit_allocated_cents"] == 0

        client = validate_success(api.get_group_client(world["gc_id"], PROGRAM_DIRECTOR))
        assert client["credit_balance_cents"] == 0

        course = validate_success(api.get_course(world["course_id"], PROGRAM_DIRECTOR))
        assert course["rescue_ready_facilitator_count"] == 1
        assert course["rescue_readiness_ok"] is False

    def test_the_credit_gate_answers_once_rescue_cover_is_restored(self, api):
        """Staffing the second active facilitator exposes the money shortfall underneath.

        PRD 3.5: "and finally the client's `credit_balance_cents` must be at
        least `deposit_required_cents`, or the confirmation is refused with
        `ERR_INSUFFICIENT_CLIENT_CREDIT` (HTTP 402)"

        PRD 2.5: "Adding a facilitator or recording a training record refreshes
        `rescue_ready_facilitator_count` and `rescue_readiness_ok` immediately,
        but does not re-derive `posture`"

        Design: Difficulty/priority_pair_validation_conflict/rescue_readiness_outranks_insufficient_client_credit_on_confirm
        """
        world = _quoted_booking_short_of_rescue_cover_and_money(api)
        create_staff_facilitator(api, world["course_id"], full_name="Dana Reyes")

        course = validate_success(api.get_course(world["course_id"], PROGRAM_DIRECTOR))
        assert course["rescue_ready_facilitator_count"] == 2
        assert course["rescue_readiness_ok"] is True

        validate_error(
            api.confirm_booking(world["b_id"], make_group_coordinator_headers(world["gc_id"])),
            ERR_INSUFFICIENT_CLIENT_CREDIT,
            402,
        )

        booking = validate_success(api.get_booking(world["b_id"], PROGRAM_DIRECTOR))
        assert booking["status"] == "QUOTED"
        assert booking["deposit_allocated_cents"] == 0


def _draft_booking_occupying_a_low_element(api):
    """A draft program whose second block holds the low element from 10:30 to 11:30."""
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
            (2, "LOW_ELEMENT", "2026-09-15T10:30:00Z", "2026-09-15T11:30:00Z", l_id),
        ],
    )
    return {"course_id": course_id, "l_id": l_id, "gc_id": gc_id, "b_id": b_id}


class TestPhaseMismatchOutranksScheduleConflict:
    """At program-block creation the family check is read before the occupancy check."""

    def test_a_high_phase_on_a_low_element_reports_the_mismatch(self, api):
        """The referential mismatch wins even though the same call also double-books.

        PRD 3.7: "A `GROUND_INITIATIVE` block requires an element of type
        `GROUND_INITIATIVE`; a `LOW_ELEMENT` block requires an element of type
        `LOW_ELEMENT`; a `HIGH_ELEMENT` block requires an element of type
        `HIGH_ELEMENT`, `CLIMBING_WALL` or `ZIP_LINE`. Any other pairing is
        refused with `ERR_ELEMENT_PHASE_MISMATCH`."

        PRD 2.12: "26. Phase and element-type compatibility —
        `ERR_ELEMENT_PHASE_MISMATCH`. Applies to program-block creation."

        Design: Difficulty/priority_pair_validation_conflict/element_phase_mismatch_outranks_element_schedule_conflict
        """
        world = _draft_booking_occupying_a_low_element(api)

        validate_error(
            api.create_program_block(
                program_block_payload(
                    world["b_id"],
                    3,
                    "HIGH_ELEMENT",
                    "2026-09-15T10:45:00Z",
                    "2026-09-15T11:15:00Z",
                    element_id=world["l_id"],
                ),
                PROGRAM_DIRECTOR,
            ),
            ERR_ELEMENT_PHASE_MISMATCH,
            422,
        )

        booking = validate_success(api.get_booking(world["b_id"], PROGRAM_DIRECTOR))
        assert booking["block_count"] == 2

    def test_the_occupancy_gate_answers_when_the_families_agree(self, api):
        """With the phase corrected the very same window is refused as a conflict.

        PRD 3.7: "Elements are also single-occupancy: the new block's interval,
        treated as half-open so that it includes its start instant and excludes
        its end instant, may not overlap any non-terminal block already booked on
        the same element, or the refusal is `ERR_ELEMENT_SCHEDULE_CONFLICT`."

        PRD 2.12: "32. Element occupancy overlap —
        `ERR_ELEMENT_SCHEDULE_CONFLICT`. Applies to program-block creation."

        Design: Difficulty/priority_pair_validation_conflict/element_phase_mismatch_outranks_element_schedule_conflict
        """
        world = _draft_booking_occupying_a_low_element(api)

        validate_error(
            api.create_program_block(
                program_block_payload(
                    world["b_id"],
                    3,
                    "LOW_ELEMENT",
                    "2026-09-15T10:45:00Z",
                    "2026-09-15T11:15:00Z",
                    element_id=world["l_id"],
                ),
                PROGRAM_DIRECTOR,
            ),
            ERR_ELEMENT_SCHEDULE_CONFLICT,
            409,
        )

        booking = validate_success(api.get_booking(world["b_id"], PROGRAM_DIRECTOR))
        assert booking["block_count"] == 2
