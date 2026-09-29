"""Inclusive endpoints and empty-collection boundaries."""

from test_helpers import (
    ERR_BELAY_NOT_READY,
    assert_belay_requirement,
    assert_instant,
    assert_posture,
    validate_error,
    validate_success,
)
from test_helpers.constants import (
    CLOCK_TEST_UTC,
    COURSE_NAME_SECONDARY,
    COURSE_NOTE_SECONDARY,
    ELEMENT_NAME_LOW,
)
from test_helpers.factories import weather_observation_payload
from test_helpers.fixtures import (
    add_blocks,
    add_participant,
    assign_facilitator,
    clear_log,
    confirm_booking,
    create_booking,
    create_course,
    create_element,
    create_funded_client,
    create_safety_officer,
    create_staff_facilitator,
    quote_booking,
    rig_equipment,
    set_clock,
    staffed_course,
)
from test_helpers.test_users import PROGRAM_DIRECTOR, make_facilitator_headers

LIGHTNING_HOLD_UNTIL = "2026-08-10T08:30:00Z"


def _two_open_courses(api):
    """Two independently staffed sites, both sitting at posture OPEN.

    Each site carries two facilitators with a current drill and a full refresher
    block, which is what keeps rescue readiness — clause 5 of the posture walk —
    from pre-empting the weather clauses under test. The observations below are
    timed at the clock instant, the latest instant an observation may carry.
    """
    set_clock(api, CLOCK_TEST_UTC)
    course_a = staffed_course(api)

    course_b_id = create_course(
        api, course_name=COURSE_NAME_SECONDARY, ems_access_note=COURSE_NOTE_SECONDARY
    )
    create_safety_officer(api, course_b_id, full_name="Nia Brooks")
    fb1_id = create_staff_facilitator(api, course_b_id, full_name="Owen Diaz")

    return {
        "course_a": course_a["course_id"],
        "fa1_headers": course_a["f1_headers"],
        "course_b": course_b_id,
        "fb1_headers": make_facilitator_headers(fb1_id),
    }


class TestLightningStopEndpoint:
    """8.0 km is inside the stop band; 8.1 km is one tenth outside it."""

    def test_a_strike_at_exactly_eight_kilometres_closes_the_site(self, api):
        """The endpoint is inclusive, so 8.0 km opens a thirty-minute hold.

        PRD 3.9: "Lightning at 8.0 km or nearer is a stop: it sets the course's
        `lightning_hold_until` to the later of its existing value and the
        observation's `observed_at` plus thirty minutes. A strike at exactly 8.0
        km is a stop; one at 8.1 km is only a watch, and lightning beyond 8.0 km
        but at 16.0 km or nearer is a watch."

        Design: Difficulty/boundary_precision_check/lightning_at_exactly_eight_kilometres_closes_the_course
        """
        world = _two_open_courses(api)

        observation = validate_success(
            api.create_weather_observation(
                weather_observation_payload(
                    world["course_a"],
                    observed_at=CLOCK_TEST_UTC,
                    lightning_distance_km=8.0,
                    wind_speed_kph=10.0,
                    air_temp_c=22.0,
                ),
                world["fa1_headers"],
            ),
            201,
        )

        assert observation["resulting_posture"] == "CLOSED"
        assert observation["resulting_posture_reason"] == "LIGHTNING_STOP"
        assert_instant(observation["hold_until"], LIGHTNING_HOLD_UNTIL, "hold_until")

        course = validate_success(api.get_course(world["course_a"], PROGRAM_DIRECTOR))
        assert_posture(course, "CLOSED", "LIGHTNING_STOP")
        assert_instant(
            course["lightning_hold_until"], LIGHTNING_HOLD_UNTIL, "lightning_hold_until"
        )

    def test_a_strike_one_tenth_farther_out_is_only_a_watch(self, api):
        """At 8.1 km the site restricts instead of closing and opens no hold.

        PRD 3.9: "Watch-level signals move a course `OPEN → RESTRICTED` with
        `posture_reason` `LIGHTNING_WATCH` or `WIND_WATCH`, whichever clause of
        §2.5 matched first, provided no closing clause matched"

        PRD 3.9: "`hold_until` captures the resulting `lightning_hold_until`,
        which is null when the observation triggered no hold."

        Design: Difficulty/boundary_precision_check/lightning_at_exactly_eight_kilometres_closes_the_course
        """
        world = _two_open_courses(api)

        observation = validate_success(
            api.create_weather_observation(
                weather_observation_payload(
                    world["course_b"],
                    observed_at=CLOCK_TEST_UTC,
                    lightning_distance_km=8.1,
                    wind_speed_kph=10.0,
                    air_temp_c=22.0,
                ),
                world["fb1_headers"],
            ),
            201,
        )

        assert observation["resulting_posture"] == "RESTRICTED"
        assert observation["resulting_posture_reason"] == "LIGHTNING_WATCH"
        assert observation["hold_until"] is None

        course = validate_success(api.get_course(world["course_b"], PROGRAM_DIRECTOR))
        assert_posture(course, "RESTRICTED", "LIGHTNING_WATCH")
        assert course["lightning_hold_until"] is None


def _confirmed_program_with_unrigged_high_element(api):
    """A confirmed four-block program whose high element has no hardware at all.

    The high element carries today's `CLEAR` pre-use log, so the daily-inspection
    gate is satisfied and the belay-readiness gate is the one under test.
    """
    set_clock(api, CLOCK_TEST_UTC)
    world = staffed_course(api)
    l_id = create_element(
        api, world["course_id"], "LOW_ELEMENT", element_name=ELEMENT_NAME_LOW
    )
    h_id = create_element(api, world["course_id"], "HIGH_ELEMENT")
    gc_id = create_funded_client(api)
    b_id, _ = create_booking(api, world["course_id"], gc_id, 1)
    add_participant(api, gc_id, b_id, "ADULT")
    block_ids = add_blocks(
        api,
        b_id,
        [
            (1, "ICEBREAKER", "2026-09-15T09:00:00Z", "2026-09-15T09:45:00Z", None),
            (2, "LOW_ELEMENT", "2026-09-15T09:45:00Z", "2026-09-15T10:45:00Z", l_id),
            (3, "HIGH_ELEMENT", "2026-09-15T13:00:00Z", "2026-09-15T15:00:00Z", h_id),
            (4, "DEBRIEF", "2026-09-15T15:15:00Z", "2026-09-15T16:00:00Z", None),
        ],
    )
    quote_booking(api, b_id)
    confirm_booking(api, gc_id, b_id)

    clear_log(api, h_id, world["f1_id"], world["f1_headers"])
    assign_facilitator(api, block_ids[2], world["f1_id"])

    world.update({"l_id": l_id, "h_id": h_id, "gc_id": gc_id, "b_id": b_id, "blk3_id": block_ids[2]})
    return world


class TestEmptyBelayInventoryBoundary:
    """A two-set requirement met by an empty collection is a failure, not a pass."""

    def test_a_high_element_with_no_hardware_refuses_the_start(self, api):
        """Zero usable items against a requirement of two fails closed.

        PRD 3.4: "`belay_ready` is true only when the number of usable items is
        at least `required_belay_set_count` **and** no item rigged to the element
        sits at `QUARANTINED`."

        PRD 3.8: "When the element's `required_belay_set_count` is greater than
        zero, its `belay_ready` must be true, or the refusal is
        `ERR_BELAY_NOT_READY`."

        Design: Difficulty/boundary_precision_check/zero_rigged_belay_sets_rejects_high_element_block_start
        """
        world = _confirmed_program_with_unrigged_high_element(api)

        element = validate_success(api.get_element(world["h_id"], PROGRAM_DIRECTOR))
        assert_belay_requirement(element, required_sets=2, ready=False)

        validate_error(
            api.start_program_block(world["blk3_id"], world["f1_headers"]),
            ERR_BELAY_NOT_READY,
            409,
        )

        block = validate_success(api.get_program_block(world["blk3_id"], PROGRAM_DIRECTOR))
        assert block["status"] == "SCHEDULED"
        course = validate_success(api.get_course(world["course_id"], PROGRAM_DIRECTOR))
        assert course["quarantined_equipment_count"] == 0

    def test_the_zero_requirement_side_of_the_same_boundary_is_ready(self, api):
        """An empty inventory satisfies a zero requirement and two items satisfy a two.

        PRD 3.4: "The boundary case matters: an element requiring zero sets with
        no hardware rigged to it at all is ready, because the empty set trivially
        satisfies a zero requirement, whereas an element requiring two sets with
        no hardware rigged to it is not ready — a naive "nothing is quarantined,
        therefore ready" reading gets exactly this case wrong."

        PRD 3.4: "An item counts as usable for an element only when all four
        conditions hold: its `assigned_element_id` names that element, its
        `status` is `IN_SERVICE`, its `retirement_forecast_date` lies strictly
        after the clock date, and its `usage_cycles` is still below `max_cycles`."

        Design: Difficulty/boundary_precision_check/zero_rigged_belay_sets_rejects_high_element_block_start
        """
        world = _confirmed_program_with_unrigged_high_element(api)

        low = validate_success(api.get_element(world["l_id"], PROGRAM_DIRECTOR))
        assert_belay_requirement(low, required_sets=0, ready=True)

        rig_equipment(api, world["course_id"], world["h_id"], "ROPE")
        rig_equipment(api, world["course_id"], world["h_id"], "HARNESS")

        high = validate_success(api.get_element(world["h_id"], PROGRAM_DIRECTOR))
        assert_belay_requirement(high, required_sets=2, ready=True)
