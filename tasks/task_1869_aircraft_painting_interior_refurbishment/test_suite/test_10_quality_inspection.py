"""Quality inspections: FAIL revert loop and major-defect trigger (PRD §3.11)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_program,
    create_and_certify_lot,
    get_program,
    pass_inspection,
    prepare_weight_record,
    setup_in_inspection_program,
    sign_off_weight_record,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    create_quality_inspection_payload,
    record_inspection_result_payload,
)

_QI = TEST_USERS["quality_inspector_headers"]
_PM = TEST_USERS["program_manager_headers"]


def _schedule(api, program_id: str, inspection_type: str) -> dict:
    return validate_success(
        api.create_quality_inspection(
            create_quality_inspection_payload(
                program_id=program_id, inspection_type=inspection_type
            ),
            _QI,
        ),
        201,
    )


def _record(api, inspection_id: str, **overrides):
    return api.record_inspection_result(
        inspection_id, record_inspection_result_payload(**overrides), _QI
    )


class TestFailRevertLoop:
    def test_failed_inspection_reverts_program_and_counts_rework(self, api):
        """PRD §3.5: "When a quality inspection records a `FAIL` result while
        the program is `IN_INSPECTION`, the program automatically reverts from
        `IN_INSPECTION` to `IN_WORK`, its `rework_cycles` increments by one,
        and the program must earn its way back through the inspection gate
        after rework."

        Design: Difficulty/non_linear_state_machine/program_inspection_rework_revert_loop
        """
        ctx = setup_in_inspection_program()
        inspection = _schedule(api, ctx["program"]["id"], "PAINT")
        failed = validate_success(_record(api, inspection["id"], result="FAIL",
                                          major_defects=2, minor_defects=1))
        assert failed["status"] == "FAILED"

        program = get_program(ctx["program"]["id"])
        assert program["status"] == "IN_WORK", "FAIL forces the revert"
        assert program["rework_cycles"] == 1

    def test_major_defect_fail_spawns_safety_discovery_and_blocks_reentry(self, api,
                                                                          program_manager_headers):
        """PRD §3.6: "a failed inspection with two or more major defects causes
        the system to create an item with `source` of `INSPECTION_AUTO`,
        `safety_linked` forced to `true`, and status `OPEN`." PRD §3.5:
        "From `IN_WORK` to `IN_INSPECTION`: every discovery item of the program
        must be in a terminal state — `COMPLETED`, `REJECTED`, or `DEFERRED`
        (`ERR_DISCOVERY_ITEMS_OPEN`)".

        Design: Difficulty/non_linear_state_machine/program_inspection_rework_revert_loop
        """
        ctx = setup_in_inspection_program()
        inspection = _schedule(api, ctx["program"]["id"], "PAINT")
        validate_success(_record(api, inspection["id"], result="FAIL",
                                 major_defects=2, minor_defects=1))

        items, meta = validate_paginated(api.list_discovery_items(_PM))
        assert meta["total_count"] == 1
        auto = items[0]
        assert auto["source"] == "INSPECTION_AUTO"
        assert auto["safety_linked"] is True
        assert auto["status"] == "OPEN"
        assert auto["program_id"] == ctx["program"]["id"]

        blocked = api.advance_program(
            ctx["program"]["id"], {"to_phase": "IN_INSPECTION"}, program_manager_headers
        )
        validate_error(blocked, ApiErrorId.ERR_DISCOVERY_ITEMS_OPEN)


class TestMajorDefectThreshold:
    def test_single_major_defect_reverts_but_spawns_nothing(self, api):
        """PRD §3.11: "when the recorded `major_defects` reaches two or more
        the system creates a safety-linked discovery item as described in §3.6
        — at exactly one major defect no item is created; at two, one is."
        PRD §3.5: the FAIL still reverts the program "from `IN_INSPECTION` to
        `IN_WORK`, its `rework_cycles` increments by one".

        Design: Corner/cross_cutting_complexity_layers/major_defect_threshold_below_boundary_spawns_nothing
        """
        ctx = setup_in_inspection_program()
        inspection = _schedule(api, ctx["program"]["id"], "PAINT")
        validate_success(_record(api, inspection["id"], result="FAIL",
                                 major_defects=1, minor_defects=3))

        program = get_program(ctx["program"]["id"])
        assert program["status"] == "IN_WORK"
        assert program["rework_cycles"] == 1, "revert fires below the threshold too"

        items, meta = validate_paginated(api.list_discovery_items(_PM))
        assert meta["total_count"] == 0, "major_defects 1 < 2 spawns no item"


class TestFinalInspectionPrerequisite:
    def test_final_result_requires_prior_paint_and_interior_passes(self, api):
        """PRD §3.11: "The `FINAL` type carries a prerequisite on both
        outcomes: at least one `PASSED` `PAINT` inspection and at least one
        `PASSED` `INTERIOR` inspection must already exist for the program, else
        the result recording is rejected with
        `ERR_FINAL_INSPECTION_PREREQUISITE`."

        Design: Corner/errors/final_inspection_requires_prior_passes
        """
        ctx = setup_in_inspection_program()
        _schedule(api, ctx["program"]["id"], "PAINT")  # SCHEDULED, never recorded
        final = _schedule(api, ctx["program"]["id"], "FINAL")
        resp = _record(api, final["id"], result="PASS", major_defects=0, minor_defects=0)
        validate_error(resp, ApiErrorId.ERR_FINAL_INSPECTION_PREREQUISITE)


class TestReadyGateInspectionStep:
    def test_ready_blocked_without_passed_final_inspection(self, api, program_manager_headers):
        """PRD §3.5: "Step one: no `FAILED` quality inspection may lack a later
        `PASSED` inspection of the same `inspection_type`, and a `FINAL`
        inspection must have passed (`ERR_INSPECTION_OUTSTANDING`)." — the
        pinned three-step gate is "evaluated in order — inspection first, then
        certification, then weight".

        Design: Corner/errors/ready_blocked_with_unresolved_or_missing_final_inspection
        """
        ctx = setup_in_inspection_program()
        pass_inspection(ctx["program"]["id"], "PAINT")
        pass_inspection(ctx["program"]["id"], "INTERIOR")
        # No FINAL inspection at all; no lots; no weight record — step 1 fires
        # before cert/weight are consulted.
        resp = api.advance_program(
            ctx["program"]["id"], {"to_phase": "READY_FOR_DELIVERY"},
            program_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INSPECTION_OUTSTANDING)
