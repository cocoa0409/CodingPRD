"""Branching state machines: the inspection fork-join and the two booking dimensions."""

from test_helpers import assert_posture, validate_success
from test_helpers.constants import CLOCK_TEST_UTC, ELEMENT_NAME_LOW, ELEMENT_NAME_LOW_ALT
from test_helpers.factories import professional_inspection_payload, screening_packet_payload
from test_helpers.fixtures import (
    add_blocks,
    add_participant,
    booking_version,
    create_booking,
    create_course,
    create_element,
    create_funded_client,
    set_clock,
    staffed_course,
    with_inspector,
)
from test_helpers.test_users import PROGRAM_DIRECTOR, make_group_coordinator_headers


def _two_elements_under_inspection(api):
    """Two low elements, each carrying a DRAFT inspection by the same independent inspector."""
    set_clock(api, CLOCK_TEST_UTC)
    world = with_inspector(api, staffed_course(api))
    e1_id = create_element(
        api, world["course_id"], "LOW_ELEMENT", element_name=ELEMENT_NAME_LOW
    )
    e2_id = create_element(
        api, world["course_id"], "LOW_ELEMENT", element_name=ELEMENT_NAME_LOW_ALT
    )
    i1 = validate_success(
        api.create_professional_inspection(
            professional_inspection_payload(
                e1_id, world["insp_id"], findings_note="Annual visit; nothing found"
            ),
            world["insp_headers"],
        ),
        201,
    )
    i2 = validate_success(
        api.create_professional_inspection(
            professional_inspection_payload(
                e2_id,
                world["insp_id"],
                findings_note="Surface cracking on the left support post",
            ),
            world["insp_headers"],
        ),
        201,
    )
    world.update({"e1_id": e1_id, "e2_id": e2_id, "i1_id": i1["id"], "i2_id": i2["id"]})
    return world


class TestInspectionForkJoin:
    """DRAFT forks into three filed states that rejoin at DISPOSED differently."""

    def test_pass_branch_advances_the_due_date_by_twelve_months(self, api):
        """A disposed PASS leaves the element alone and pushes the cycle a year out.

        PRD 3.3: "A disposed `PASS` advances the element's
        `next_professional_inspection_due_on` by 12 months, sets
        `latest_inspection_outcome` to `PASS`, and resets `consecutive_conditional_count`
        to zero; this is the disposal that can clear an `INSPECTION_OVERDUE` posture."

        Design: Difficulty/non_linear_state_machine/inspection_fork_join_pass_and_conditional_branches_diverge
        """
        world = _two_elements_under_inspection(api)

        validate_success(
            api.file_professional_inspection(
                world["i1_id"], {"outcome": "PASS"}, world["insp_headers"]
            )
        )
        disposed = validate_success(
            api.dispose_professional_inspection(
                world["i1_id"], {"disposition_note": "Accepted; no findings"}, world["so_headers"]
            )
        )

        assert disposed["status"] == "DISPOSED"
        assert disposed["outcome"] == "PASS"
        assert disposed["disposed_on"] is not None

        element = validate_success(api.get_element(world["e1_id"], PROGRAM_DIRECTOR))
        assert element["status"] == "SERVICEABLE"
        assert element["next_professional_inspection_due_on"] == "2028-06-30"
        assert element["latest_inspection_outcome"] == "PASS"
        assert element["consecutive_conditional_count"] == 0

    def test_conditional_branch_restricts_and_advances_only_three_months(self, api):
        """A disposed CONDITIONAL restricts the element and accelerates re-inspection.

        PRD 3.3: "`DRAFT → FILED_CONDITIONAL` sets `outcome` to `CONDITIONAL` and moves an
        element that is `SERVICEABLE` or already `RESTRICTED` to `RESTRICTED`, leaving
        `restricting_log_id` null because no operational log caused it; the course's
        `restricted_element_count` rises, the element's `SCHEDULED` blocks move to
        `BLOCKED_UNSAFE`, their `CONFIRMED` bookings move to `AT_RISK`, and posture is
        re-derived."

        PRD 3.3: "A disposed `CONDITIONAL` advances `next_professional_inspection_due_on`
        by only 3 months — an accelerated re-inspection — sets `latest_inspection_outcome`
        to `CONDITIONAL`, and adds one to `consecutive_conditional_count`; once that count
        reaches two the element becomes retirement-eligible even though its forecast date
        is still years away."

        Design: Difficulty/non_linear_state_machine/inspection_fork_join_pass_and_conditional_branches_diverge
        """
        world = _two_elements_under_inspection(api)

        validate_success(
            api.file_professional_inspection(
                world["i2_id"], {"outcome": "CONDITIONAL"}, world["insp_headers"]
            )
        )
        disposed = validate_success(
            api.dispose_professional_inspection(
                world["i2_id"],
                {"disposition_note": "Accepted with conditions; re-inspect in three months"},
                world["so_headers"],
            )
        )

        assert disposed["status"] == "DISPOSED"
        assert disposed["outcome"] == "CONDITIONAL"

        element = validate_success(api.get_element(world["e2_id"], PROGRAM_DIRECTOR))
        assert element["status"] == "RESTRICTED"
        assert element["restricting_log_id"] is None
        assert element["next_professional_inspection_due_on"] == "2027-09-30"
        assert element["consecutive_conditional_count"] == 1
        assert element["latest_inspection_outcome"] == "CONDITIONAL"

        course = validate_success(api.get_course(world["course_id"], PROGRAM_DIRECTOR))
        assert course["restricted_element_count"] == 1
        assert_posture(course, "RESTRICTED", "ELEMENT_RESTRICTED")


def _draft_booking_with_two_blocks(api):
    """A DRAFT PARTNER booking whose two-block program is already designed."""
    set_clock(api, CLOCK_TEST_UTC)
    course_id = create_course(api)
    gc_id = create_funded_client(api, amount_cents=0)
    b_id, _ = create_booking(api, course_id, gc_id, 2)
    add_blocks(
        api,
        b_id,
        [
            (1, "ICEBREAKER", "2026-09-15T09:00:00Z", "2026-09-15T09:45:00Z"),
            (2, "DEBRIEF", "2026-09-15T09:45:00Z", "2026-09-15T10:15:00Z"),
        ],
    )
    return {"course_id": course_id, "gc_id": gc_id, "b_id": b_id}


class TestBookingDimensionsAdvanceIndependently:
    """`status` and `roster_status` are two independent dimensions of one row."""

    def test_roster_dimension_moves_while_status_holds_at_draft(self, api):
        """Adding then screening a participant walks the roster without touching status.

        PRD 3.6: "Participant writes never move the booking's `status`, and status actions
        never move its `roster_status`; the two dimensions are genuinely independent."

        PRD 3.6: "A booking where any participant — chaperones included — is `BLOCKED` or
        `CONDITIONAL` is `BLOCKED`."

        Design: Difficulty/non_linear_state_machine/booking_status_and_roster_dimensions_advance_independently
        """
        world = _draft_booking_with_two_blocks(api)
        gc_headers = make_group_coordinator_headers(world["gc_id"])
        p1_id = add_participant(api, world["gc_id"], world["b_id"], "ADULT", screen=False)

        after_add = validate_success(api.get_booking(world["b_id"], PROGRAM_DIRECTOR))
        assert after_add["status"] == "DRAFT"
        assert after_add["roster_status"] == "BLOCKED"

        validate_success(
            api.submit_screening_packet(p1_id, screening_packet_payload(), gc_headers)
        )

        after_packet = validate_success(api.get_booking(world["b_id"], PROGRAM_DIRECTOR))
        assert after_packet["status"] == "DRAFT"
        assert after_packet["roster_status"] == "READY"

    def test_quote_moves_status_only_and_a_new_person_reblocks_the_roster(self, api):
        """Quoting moves status alone; the next unscreened person moves the roster alone.

        PRD 3.6: "Because participants are never deleted, a roster can move
        `READY → BLOCKED` simply by adding one unscreened person."

        Design: Difficulty/non_linear_state_machine/booking_status_and_roster_dimensions_advance_independently
        """
        world = _draft_booking_with_two_blocks(api)
        add_participant(api, world["gc_id"], world["b_id"], "ADULT")

        version = booking_version(api, world["b_id"])
        quoted = validate_success(
            api.quote_booking(
                world["b_id"], {"expected_booking_version": version}, PROGRAM_DIRECTOR
            )
        )
        assert quoted["status"] == "QUOTED"
        assert quoted["roster_status"] == "READY"
        assert quoted["billable_head_count"] == 1
        assert quoted["raw_subtotal_cents"] == 1364

        add_participant(
            api,
            world["gc_id"],
            world["b_id"],
            "ADULT",
            screen=False,
            full_name="Robin Vale",
            birth_date="1988-11-30",
            weight_kg=71.0,
        )

        after = validate_success(api.get_booking(world["b_id"], PROGRAM_DIRECTOR))
        assert after["status"] == "QUOTED"
        assert after["roster_status"] == "BLOCKED"
