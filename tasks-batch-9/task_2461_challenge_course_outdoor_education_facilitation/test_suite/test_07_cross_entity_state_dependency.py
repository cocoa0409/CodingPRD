"""A write is refused because of the state of a different entity."""

from test_helpers import (
    ERR_ELEMENT_NOT_SERVICEABLE,
    ERR_INSPECTOR_NOT_INDEPENDENT,
    validate_error,
    validate_success,
)
from test_helpers.constants import CLOCK_TEST_UTC, ELEMENT_NAME_LOW, TRAINING_COMPLETED_ON
from test_helpers.factories import professional_inspection_payload
from test_helpers.fixtures import (
    add_blocks,
    add_participant,
    assign_facilitator,
    clear_log,
    confirm_booking,
    create_booking,
    create_contract_inspector,
    create_course,
    create_element,
    create_funded_client,
    defect_major_log,
    make_current,
    quote_booking,
    set_clock,
    staffed_course,
)
from test_helpers.test_users import PROGRAM_DIRECTOR


def _confirmed_program_on_an_already_restricted_element(api):
    """A confirmed program whose low element was restricted before any block existed.

    Because the major defect was logged first, no cascade ever touched these
    blocks: the low-element block is `SCHEDULED`, its predecessor has run to
    `COMPLETED`, and the booking is still `CONFIRMED`.
    """
    set_clock(api, CLOCK_TEST_UTC)
    world = staffed_course(api)
    l_id = create_element(
        api, world["course_id"], "LOW_ELEMENT", element_name=ELEMENT_NAME_LOW
    )
    defect_major_log(
        api,
        l_id,
        world["f1_id"],
        world["f1_headers"],
        defect_note="Frayed guy line noticed on the morning walk",
    )

    gc_id = create_funded_client(api)
    b_id, _ = create_booking(api, world["course_id"], gc_id, 1)
    add_participant(api, gc_id, b_id, "ADULT")
    block_ids = add_blocks(
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

    assign_facilitator(api, block_ids[0], world["f1_id"])
    validate_success(api.start_program_block(block_ids[0], world["f1_headers"]))
    validate_success(api.complete_program_block(block_ids[0], {}, world["f1_headers"]))

    world.update(
        {
            "l_id": l_id,
            "gc_id": gc_id,
            "b_id": b_id,
            "blk1_id": block_ids[0],
            "blk2_id": block_ids[1],
        }
    )
    return world


class TestBlockStartDependsOnTheRiggedElement:
    """Nothing on the block row predicts the refusal; the element carries it."""

    def test_a_restricted_element_refuses_a_faultless_block(self, api):
        """The block is next in sequence on a confirmed booking and still cannot start.

        PRD 3.8: "When the block carries an `element_id`, that element's `status`
        must be `SERVICEABLE`; an element at `RESTRICTED` or `OUT_OF_SERVICE` is
        refused with `ERR_ELEMENT_NOT_SERVICEABLE`, and an element at `RETIRED`
        with the more specific `ERR_ELEMENT_RETIRED`."

        PRD 3.3: "A `DEFECT_MAJOR` result against a `SERVICEABLE` element fires
        Cascade A of §2.6 in full and sets the log's `caused_restriction` to true,
        which is the flag that later identifies this log as the restriction's
        origin."

        Design: Difficulty/cross_entity_state_dependency/program_block_start_depends_on_rigged_element_status
        """
        world = _confirmed_program_on_an_already_restricted_element(api)

        element = validate_success(api.get_element(world["l_id"], PROGRAM_DIRECTOR))
        assert element["status"] == "RESTRICTED"

        validate_error(
            api.start_program_block(world["blk2_id"], world["f1_headers"]),
            ERR_ELEMENT_NOT_SERVICEABLE,
            409,
        )

        blk1 = validate_success(api.get_program_block(world["blk1_id"], PROGRAM_DIRECTOR))
        blk2 = validate_success(api.get_program_block(world["blk2_id"], PROGRAM_DIRECTOR))
        assert blk1["status"] == "COMPLETED"
        assert blk2["status"] == "SCHEDULED"

        booking = validate_success(api.get_booking(world["b_id"], PROGRAM_DIRECTOR))
        assert booking["status"] == "CONFIRMED"
        assert booking["blocked_block_count"] == 0

    def test_returning_the_element_to_service_releases_the_same_block(self, api):
        """Repairing the other entity is what makes the unchanged block startable.

        PRD 3.3: "From `RESTRICTED → SERVICEABLE` three preconditions apply: the
        newest operational log for the element, ordered by `log_date` descending
        then `created_at` descending, must have `result` `CLEAR`, or the request
        is refused with `ERR_DEFECT_NOT_CLEARED`"

        PRD 3.8: "A successful start moves the block `SCHEDULED → IN_PROGRESS`,
        stamps `started_at` with the clock instant, freezes `actual_head_count` as
        the number of participants on the booking whose `screening_status` is
        `ELIGIBLE`, and increments the block's `version`."

        Design: Difficulty/cross_entity_state_dependency/program_block_start_depends_on_rigged_element_status
        """
        world = _confirmed_program_on_an_already_restricted_element(api)

        clear_log(api, world["l_id"], world["so_id"], world["so_headers"])
        restored = validate_success(
            api.return_element_to_service(
                world["l_id"],
                {"note": "Guy line replaced and re-tensioned; walk repeated"},
                world["so_headers"],
            )
        )
        assert restored["status"] == "SERVICEABLE"
        assert restored["restricting_log_id"] is None

        assign_facilitator(api, world["blk2_id"], world["so_id"])
        started = validate_success(
            api.start_program_block(world["blk2_id"], world["f1_headers"])
        )

        assert started["status"] == "IN_PROGRESS"
        assert started["actual_head_count"] == 1


def _untrained_contract_inspector(api):
    """An independent contract inspector who has filed no drill and no refresher."""
    set_clock(api, CLOCK_TEST_UTC)
    course_id = create_course(api)
    l_id = create_element(api, course_id, "LOW_ELEMENT", element_name=ELEMENT_NAME_LOW)
    insp_id = create_contract_inspector(api, course_id, trained=False)
    return {"course_id": course_id, "l_id": l_id, "insp_id": insp_id}


class TestInspectionCreationDependsOnInspectorCertification:
    """The inspection is refused for the state of the facilitator row behind it."""

    def test_a_probation_inspector_cannot_open_an_inspection(self, api):
        """Correctly typed and genuinely independent is not enough without currency.

        PRD 3.3: "The named inspector must genuinely be independent: their
        `staff_type` must be `CONTRACT_INSPECTOR`, their `is_operator_employee`
        must be false, and their `cert_status` must be `ACTIVE`. Any of those
        failing yields `ERR_INSPECTOR_NOT_INDEPENDENT`."

        PRD 3.2: "Otherwise, if `rescue_drill_last_passed_on` is null, or more
        than 180 days have elapsed between the drill date and the clock date, or
        `refresher_hours_24mo` is below eight hours, the status is `PROBATION`."

        Design: Difficulty/cross_entity_state_dependency/professional_inspection_create_depends_on_inspector_certification_state
        """
        world = _untrained_contract_inspector(api)

        inspector = validate_success(api.get_facilitator(world["insp_id"], PROGRAM_DIRECTOR))
        assert inspector["cert_status"] == "PROBATION"
        assert inspector["is_operator_employee"] is False
        assert inspector["rescue_drill_last_passed_on"] is None
        assert inspector["refresher_hours_24mo"] == 0

        validate_error(
            api.create_professional_inspection(
                professional_inspection_payload(world["l_id"], world["insp_id"]),
                PROGRAM_DIRECTOR,
            ),
            ERR_INSPECTOR_NOT_INDEPENDENT,
            422,
        )

        element = validate_success(api.get_element(world["l_id"], PROGRAM_DIRECTOR))
        assert element["latest_inspection_outcome"] == "NONE"

    def test_recording_the_missing_training_opens_the_same_inspection(self, api):
        """Lifting the inspector to ACTIVE is what admits the identical request.

        PRD 3.2: "Recording a drill or refresher can lift a facilitator from
        `PROBATION` to `ACTIVE`, but only when the certification has not expired"

        PRD 3.3: "The record opens with `status` `DRAFT` and `outcome` `NONE`, and
        its `disposition_note`, `disposed_on` fields stay empty and null
        respectively until disposal."

        Design: Difficulty/cross_entity_state_dependency/professional_inspection_create_depends_on_inspector_certification_state
        """
        world = _untrained_contract_inspector(api)
        make_current(api, world["insp_id"])

        inspector = validate_success(api.get_facilitator(world["insp_id"], PROGRAM_DIRECTOR))
        assert inspector["cert_status"] == "ACTIVE"
        assert inspector["rescue_drill_last_passed_on"] == TRAINING_COMPLETED_ON
        assert inspector["refresher_hours_24mo"] == 8

        inspection = validate_success(
            api.create_professional_inspection(
                professional_inspection_payload(world["l_id"], world["insp_id"]),
                PROGRAM_DIRECTOR,
            ),
            201,
        )

        assert inspection["status"] == "DRAFT"
        assert inspection["outcome"] == "NONE"
        assert inspection["disposed_on"] is None
