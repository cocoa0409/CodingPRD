"""Multi-link cascades fired by a single write."""

from test_helpers import assert_money, assert_posture, validate_success
from test_helpers.constants import CLOCK_TEST_UTC, ELEMENT_NAME_LOW
from test_helpers.factories import (
    belay_equipment_payload,
    operational_log_payload,
    professional_inspection_payload,
)
from test_helpers.fixtures import (
    add_blocks,
    add_participant,
    confirm_booking,
    create_booking,
    create_element,
    create_funded_client,
    quote_booking,
    set_clock,
    staffed_course,
    with_inspector,
)
from test_helpers.test_users import PROGRAM_DIRECTOR


def _confirmed_booking_on_a_low_element(api):
    """A confirmed booking whose middle block is rigged to the course's low element."""
    set_clock(api, CLOCK_TEST_UTC)
    world = staffed_course(api)
    l_id = create_element(
        api, world["course_id"], "LOW_ELEMENT", element_name=ELEMENT_NAME_LOW
    )
    gc_id = create_funded_client(api)
    b_id, _ = create_booking(api, world["course_id"], gc_id, 1)
    add_participant(api, gc_id, b_id, "ADULT")
    blocks = add_blocks(
        api,
        b_id,
        [
            (1, "ICEBREAKER", "2026-09-15T09:00:00Z", "2026-09-15T09:45:00Z", None),
            (2, "LOW_ELEMENT", "2026-09-15T09:45:00Z", "2026-09-15T10:45:00Z", l_id),
            (3, "DEBRIEF", "2026-09-15T10:45:00Z", "2026-09-15T11:15:00Z", None),
        ],
    )
    quote_booking(api, b_id)
    confirm_booking(api, gc_id, b_id)
    world.update({"l_id": l_id, "gc_id": gc_id, "b_id": b_id, "blk2_id": blocks[1]})
    return world


class TestDefectMajorCascade:
    """One pre-use log walks element, block, booking and course posture."""

    def test_defect_major_log_restricts_the_element_and_blocks_its_block(self, api):
        """The log restricts the element and pushes its scheduled block to BLOCKED_UNSAFE.

        PRD 2.6: "**Cascade A — a major defect restricts an element.** An operational
        inspection log whose `result` is `DEFECT_MAJOR` moves the element from
        `SERVICEABLE` to `RESTRICTED`, records the new log's identifier in the element's
        `restricting_log_id`, sets the log's `caused_restriction` to true and adds one to
        the course's `restricted_element_count`."

        Design: Difficulty/transitive_cascade/defect_major_log_cascades_four_links_to_course_posture
        """
        world = _confirmed_booking_on_a_low_element(api)

        booking = validate_success(api.get_booking(world["b_id"], PROGRAM_DIRECTOR))
        assert_money(booking["raw_subtotal_cents"], 3468, "raw_subtotal_cents")
        assert_money(booking["deposit_required_cents"], 867, "deposit_required_cents")

        log = validate_success(
            api.create_operational_log(
                operational_log_payload(world["l_id"], world["f1_id"], "DEFECT_MAJOR"),
                world["f1_headers"],
            ),
            201,
        )

        assert log["caused_restriction"] is True
        element = validate_success(api.get_element(world["l_id"], PROGRAM_DIRECTOR))
        assert element["status"] == "RESTRICTED"
        assert element["restricting_log_id"] == log["id"]
        block = validate_success(api.get_program_block(world["blk2_id"], PROGRAM_DIRECTOR))
        assert block["status"] == "BLOCKED_UNSAFE"

    def test_defect_major_log_reaches_the_booking_and_the_course_posture(self, api):
        """The blocked block puts the booking at risk and the course into RESTRICTED.

        PRD 2.6: "Because those blocks are now blocked, each owning booking recomputes
        `blocked_block_count` and, if its `status` is `CONFIRMED`, moves to `AT_RISK`."

        PRD 2.6: "Because those bookings are now at risk, the course's
        `at_risk_booking_count` rises by one per booking, posture and `posture_reason` are
        re-derived, and the course's `version` increments."

        Design: Difficulty/transitive_cascade/defect_major_log_cascades_four_links_to_course_posture
        """
        world = _confirmed_booking_on_a_low_element(api)

        validate_success(
            api.create_operational_log(
                operational_log_payload(world["l_id"], world["f1_id"], "DEFECT_MAJOR"),
                world["f1_headers"],
            ),
            201,
        )

        booking = validate_success(api.get_booking(world["b_id"], PROGRAM_DIRECTOR))
        assert booking["blocked_block_count"] == 1
        assert booking["status"] == "AT_RISK"

        course = validate_success(api.get_course(world["course_id"], PROGRAM_DIRECTOR))
        assert course["restricted_element_count"] == 1
        assert course["at_risk_booking_count"] == 1
        assert_posture(course, "RESTRICTED", "ELEMENT_RESTRICTED")


def _rigged_high_element_under_inspection(api):
    """A high element with a rope and a harness rigged to it, and a DRAFT inspection open."""
    set_clock(api, CLOCK_TEST_UTC)
    world = with_inspector(api, staffed_course(api))
    h_id = create_element(api, world["course_id"], "HIGH_ELEMENT")
    rope = validate_success(
        api.create_belay_equipment(
            belay_equipment_payload(
                world["course_id"],
                "ROPE",
                assigned_element_id=h_id,
                first_use_on="2024-08-10",
            ),
            world["so_headers"],
        ),
        201,
    )
    harness = validate_success(
        api.create_belay_equipment(
            belay_equipment_payload(
                world["course_id"],
                "HARNESS",
                assigned_element_id=h_id,
                first_use_on="2024-08-10",
            ),
            world["so_headers"],
        ),
        201,
    )
    inspection = validate_success(
        api.create_professional_inspection(
            professional_inspection_payload(
                h_id,
                world["insp_id"],
                findings_note="Cable corrosion beyond allowable tolerance",
            ),
            world["insp_headers"],
        ),
        201,
    )
    world.update(
        {
            "h_id": h_id,
            "rope_id": rope["id"],
            "harness_id": harness["id"],
            "insp1_id": inspection["id"],
        }
    )
    return world


class TestInspectionFailCascade:
    """A failed filing takes the element out of service, then its hardware with it."""

    def test_fail_filing_quarantines_every_item_rigged_to_the_element(self, api):
        """Both rigged items are quarantined because the element left service.

        PRD 2.6: "Because it is out of service, every belay item whose
        `assigned_element_id` names it and whose `status` is `IN_SERVICE` moves to
        `QUARANTINED`, processed in ascending `created_at` order."

        Design: Difficulty/transitive_cascade/inspection_fail_cascades_element_then_equipment_then_belay_readiness
        """
        world = _rigged_high_element_under_inspection(api)

        filed = validate_success(
            api.file_professional_inspection(
                world["insp1_id"], {"outcome": "FAIL"}, world["insp_headers"]
            )
        )

        assert filed["status"] == "FILED_FAIL"
        assert filed["outcome"] == "FAIL"
        element = validate_success(api.get_element(world["h_id"], PROGRAM_DIRECTOR))
        assert element["status"] == "OUT_OF_SERVICE"
        rope = validate_success(api.get_belay_equipment(world["rope_id"], PROGRAM_DIRECTOR))
        harness = validate_success(
            api.get_belay_equipment(world["harness_id"], PROGRAM_DIRECTOR)
        )
        assert rope["status"] == "QUARANTINED"
        assert harness["status"] == "QUARANTINED"

    def test_quarantine_costs_the_element_its_belay_readiness(self, api):
        """Losing the hardware flips belay_ready false and moves the course counters.

        PRD 2.6: "Because that hardware is quarantined, the element's `belay_ready`
        re-derives to false, the course's `quarantined_equipment_count` rises, posture and
        `posture_reason` are re-derived and the course's `version` increments."

        Design: Difficulty/transitive_cascade/inspection_fail_cascades_element_then_equipment_then_belay_readiness
        """
        world = _rigged_high_element_under_inspection(api)

        validate_success(
            api.file_professional_inspection(
                world["insp1_id"], {"outcome": "FAIL"}, world["insp_headers"]
            )
        )

        element = validate_success(api.get_element(world["h_id"], PROGRAM_DIRECTOR))
        assert element["required_belay_set_count"] == 2
        assert element["belay_ready"] is False

        course = validate_success(api.get_course(world["course_id"], PROGRAM_DIRECTOR))
        assert course["quarantined_equipment_count"] == 2
        assert course["out_of_service_element_count"] == 1
        assert_posture(course, "RESTRICTED", "ELEMENT_RESTRICTED")
