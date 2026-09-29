"""Write-then-read agreement, action endpoints, junction reads and filtered listings."""

from test_helpers import (
    ERR_RETIREMENT_CRITERIA_NOT_MET,
    assert_belay_requirement,
    assert_versioned_record,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    CLOCK_TEST_DATE,
    CLOCK_TEST_UTC,
    ELEMENT_NAME_HIGH,
    ELEMENT_NAME_LOW,
    FACILITATOR_NAME,
)
from test_helpers.factories import belay_equipment_payload, facilitator_payload
from test_helpers.fixtures import (
    add_blocks,
    create_booking,
    create_course,
    create_element,
    create_funded_client,
    create_safety_officer,
    create_staff_facilitator,
    set_clock,
)
from test_helpers.test_users import PROGRAM_DIRECTOR, make_safety_officer_headers

HARNESS_SERIAL = "HN-001"
FIRST_USE_ON = "2024-08-10"
DRILL_CYCLES = 100
PROBATION_NAME = "Sam Ito"
RETIREMENT_REASON = "Director wants the footprint back"


class TestBelayEquipmentWriteThenRead:
    """What the create endpoint mints is exactly what the read endpoint returns."""

    def test_a_rigged_harness_reads_back_field_for_field(self, api):
        """One write, one read, no second version: the row and its forecasts agree.

        PRD 3.4: "Each item names its owning `course_id`, an `equipment_kind` of
        `ROPE`, `HARNESS`, `CARABINER` or `LANYARD`, a `serial_number` unique within
        the course and compared case-sensitively (a duplicate is rejected as an
        invalid request with `ERR_INVALID_REQUEST`), the `manufactured_on` date, and
        a hard `max_cycles` cap of at least one cycle after which the item must
        leave service."

        PRD 3.4: "New items open at `status` `IN_SERVICE`."

        PRD 3.4: "`retirement_forecast_date` is the earlier of the two dates,
        ignoring a null."

        PRD 3.4: "`belay_ready` is true only when the number of usable items is at
        least `required_belay_set_count` **and** no item rigged to the element sits
        at `QUARANTINED`."

        Design: Corner/endpoints/belay_equipment_create_then_read_returns_the_same_row
        """
        set_clock(api, CLOCK_TEST_UTC)
        course_id = create_course(api)
        h_id = create_element(
            api, course_id, "HIGH_ELEMENT", element_name=ELEMENT_NAME_HIGH
        )

        created = validate_success(
            api.create_belay_equipment(
                belay_equipment_payload(
                    course_id,
                    "HARNESS",
                    assigned_element_id=h_id,
                    first_use_on=FIRST_USE_ON,
                ),
                PROGRAM_DIRECTOR,
            ),
            201,
        )

        stored = validate_success(api.get_belay_equipment(created["id"], PROGRAM_DIRECTOR))

        assert stored["id"] == created["id"]
        assert stored["serial_number"] == HARNESS_SERIAL
        assert stored["equipment_kind"] == "HARNESS"
        assert stored["assigned_element_id"] == h_id
        assert stored["first_use_on"] == FIRST_USE_ON
        assert stored["status"] == "IN_SERVICE"
        assert stored["usage_cycles"] == 0
        assert stored["mfg_life_forecast_date"] == "2032-06-01"
        assert stored["service_life_forecast_date"] == "2031-08-10"
        assert stored["retirement_forecast_date"] == "2031-08-10"
        assert stored["retirement_basis"] == "SERVICE"
        assert_versioned_record(stored, version=1)

        element = validate_success(api.get_element(h_id, PROGRAM_DIRECTOR))
        assert_belay_requirement(element, required_sets=2, ready=False)


class TestLogUsageOutsideAProgramBlock:
    """Drill cycles are booked directly against the item and start its service clock."""

    def test_logging_drill_cycles_stamps_the_first_use_date(self, api):
        """An unused rope switches from its shelf date to its service date on first use.

        PRD 3.4: "Outside a block — rescue drills, staff training, rigging practice
        — a `Facilitator` or `SafetyOfficer` logs usage directly by supplying a
        `cycles` figure, which is added to `usage_cycles`; the call also stamps
        `first_use_on` if this is the item's first use, re-derives the forecast and
        basis, and, when `usage_cycles` has reached or passed `max_cycles`, moves the
        item `IN_SERVICE → RETIRED` with `retirement_basis` `CYCLE`, retaining
        `assigned_element_id` for the audit trail."

        PRD 3.4: "`retirement_basis` is decided in a fixed order: `CYCLE` whenever
        `usage_cycles` has reached `max_cycles`, since an exhausted item is finished
        today regardless of how much shelf or service life its dates still allow;
        otherwise `MANUFACTURE` when the service date is null; otherwise
        `MANUFACTURE` when the manufacture date is earlier than or equal to the
        service date; otherwise `SERVICE`."

        Design: Corner/endpoints/log_usage_stamps_first_use_and_increments_usage_cycles
        """
        set_clock(api, CLOCK_TEST_UTC)
        course_id = create_course(api)
        so_id = create_safety_officer(api, course_id)

        rope = validate_success(
            api.create_belay_equipment(
                belay_equipment_payload(course_id, "ROPE"), PROGRAM_DIRECTOR
            ),
            201,
        )
        assert rope["first_use_on"] is None
        assert rope["retirement_basis"] == "MANUFACTURE"
        assert rope["retirement_forecast_date"] == "2032-06-01"

        logged = validate_success(
            api.log_equipment_usage(
                rope["id"], {"cycles": DRILL_CYCLES}, make_safety_officer_headers(so_id)
            )
        )

        assert logged["usage_cycles"] == DRILL_CYCLES
        assert logged["first_use_on"] == CLOCK_TEST_DATE
        assert logged["retirement_basis"] == "SERVICE"
        assert logged["mfg_life_forecast_date"] == "2032-06-01"
        assert logged["service_life_forecast_date"] == "2031-08-10"
        assert logged["retirement_forecast_date"] == "2031-08-10"
        assert logged["status"] == "IN_SERVICE"


class TestBlockAssignmentJunction:
    """The assignment row is readable from the facilitator side as well as the block side."""

    def test_an_assignment_is_listed_under_the_facilitator_who_holds_it(self, api):
        """The junction freezes the rescue snapshot and raises the block's staffing count.

        PRD 3.7: "Staffing a block is a separate `ProgramDirector` operation naming a
        `facilitator_id` and an optional `assignment_role` of `LEAD`, `BELAY` or
        `SPOTTER`, where `BELAY` is meaningful only on a block rigged to a
        `HIGH_ELEMENT`, `CLIMBING_WALL` or `ZIP_LINE` element."

        PRD 3.7: "Each accepted assignment freezes `rescue_current_at_assignment`, a
        boolean snapshot of whether that facilitator's `rescue_drill_last_passed_on`
        was within 180 days of the clock date at the moment of assignment."

        PRD 3.7: "The block's `assigned_facilitator_count` — simply the number of
        assignments on the block — rises by one, and the supervision arithmetic is
        re-derived."

        Design: Corner/endpoints/block_assignment_links_facilitator_and_program_block
        """
        set_clock(api, CLOCK_TEST_UTC)
        course_id = create_course(api)
        f1_id = create_staff_facilitator(api, course_id)
        gc_id = create_funded_client(api, amount_cents=0)
        b_id, _ = create_booking(api, course_id, gc_id, 1)
        block_ids = add_blocks(
            api, b_id, [(1, "ICEBREAKER", "2026-09-15T09:00:00Z", "2026-09-15T09:45:00Z")]
        )

        assignment = validate_success(
            api.create_block_assignment(
                block_ids[0], {"facilitator_id": f1_id, "assignment_role": "LEAD"},
                PROGRAM_DIRECTOR,
            ),
            201,
        )

        assert assignment["program_block_id"] == block_ids[0]
        assert assignment["facilitator_id"] == f1_id
        assert assignment["assignment_role"] == "LEAD"
        assert assignment["rescue_current_at_assignment"] is True

        rows, meta = validate_paginated(
            api.list_facilitator_block_assignments(
                f1_id, PROGRAM_DIRECTOR, params={"limit": 10, "offset": 0}
            )
        )
        assert len(rows) == 1
        assert meta["total_count"] == 1
        assert rows[0]["id"] == assignment["id"]

        block = validate_success(api.get_program_block(block_ids[0], PROGRAM_DIRECTOR))
        assert block["assigned_facilitator_count"] == 1
        assert block["required_facilitator_count"] == 1


class TestRosterFilterOnADerivedStatus:
    """The roster filter reads the freshly derived certification status."""

    def test_the_active_filter_returns_only_the_trained_facilitator(self, api):
        """Two identically configured people differ only in training history.

        PRD 2.3: "Facilitators may be filtered by `course_id`, `staff_type`,
        `cert_status` and `certification_level`; the per-course facilitator roster
        accepts `cert_status`."

        PRD 3.2: "If `cert_expires_on` falls strictly before the clock date, the
        status is `LAPSED`. Otherwise, if `rescue_drill_last_passed_on` is null, or
        more than 180 days have elapsed between the drill date and the clock date,
        or `refresher_hours_24mo` is below eight hours, the status is `PROBATION`.
        Otherwise the status is `ACTIVE`."

        PRD 2.3: "`total_count` counts the records matching the filters before
        pagination is applied and `has_more` states whether records remain beyond
        the current window."

        Design: Corner/endpoints/facilitator_list_filtered_by_computed_cert_status_returns_only_active
        """
        set_clock(api, CLOCK_TEST_UTC)
        course_id = create_course(api)
        f_active_id = create_staff_facilitator(api, course_id)
        f_probation_id = validate_success(
            api.create_facilitator(
                facilitator_payload(
                    course_id, "STAFF_FACILITATOR", full_name=PROBATION_NAME
                ),
                PROGRAM_DIRECTOR,
            ),
            201,
        )["id"]

        rows, meta = validate_paginated(
            api.list_course_facilitators(
                course_id,
                PROGRAM_DIRECTOR,
                params={"cert_status": "ACTIVE", "limit": 10, "offset": 0},
            )
        )

        assert len(rows) == 1
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert rows[0]["id"] == f_active_id
        assert rows[0]["full_name"] == FACILITATOR_NAME
        assert rows[0]["cert_status"] == "ACTIVE"

        probationer = validate_success(api.get_facilitator(f_probation_id, PROGRAM_DIRECTOR))
        assert probationer["cert_status"] == "PROBATION"


class TestRetirementIsConditional:
    """Retirement is not discretionary: a criterion must actually hold."""

    def test_retiring_a_healthy_element_is_refused(self, api):
        """A two-year-old low element with no inspection history meets no criterion.

        PRD 3.1: "At least one retirement criterion must hold:
        `retirement_forecast_date` is on or before the clock date, or
        `consecutive_conditional_count` has reached two, or
        `latest_inspection_outcome` is `FAIL`. If none holds, the request is refused
        with `ERR_RETIREMENT_CRITERIA_NOT_MET`."

        PRD 3.1: "Permanent retirement is an explicit `ProgramDirector` act carrying
        a `reason`, and it drives the element to the terminal `RETIRED` state from
        `SERVICEABLE`, `RESTRICTED` or `OUT_OF_SERVICE` alike."

        Design: Corner/endpoints/retire_rejected_when_no_retirement_criterion_is_met
        """
        set_clock(api, CLOCK_TEST_UTC)
        course_id = create_course(api)
        l_id = create_element(api, course_id, "LOW_ELEMENT", element_name=ELEMENT_NAME_LOW)

        validate_error(
            api.retire_element(l_id, {"reason": RETIREMENT_REASON}, PROGRAM_DIRECTOR),
            ERR_RETIREMENT_CRITERIA_NOT_MET,
            409,
        )

        element = validate_success(api.get_element(l_id, PROGRAM_DIRECTOR))
        assert element["status"] == "SERVICEABLE"
        assert element["retirement_forecast_date"] == "2039-08-10"
        assert element["consecutive_conditional_count"] == 0
        assert element["latest_inspection_outcome"] == "NONE"
