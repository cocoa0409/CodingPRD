"""Fabrication routing and the final-QA outcomes (PRD §3.7).

The routing branches on the ordered model's door type, and the FAIL and SCRAP
rules at ranks 25 and 26 are exact complements of one another.
"""

import pytest

from test_helpers import *  # noqa: F401,F403


class TestFabricationRouting:
    """PRD §3.7 — an OPEN case never visits door assembly."""

    def test_01_an_open_case_skips_door_assembly_on_the_way_to_final_qa(self, api):
        """Three advances take an open case from QUEUED to FINAL_QA.

        PRD §3.7: "A unit whose model's `door_type` is `OPEN` moves
        `FOAM_INJECTION → FINAL_QA` directly, skipping `DOOR_ASSEMBLY` entirely."

        Design: Corner/state_machines/work_order_open_case_skips_door_assembly_to_final_qa
        """
        ctx = setup_released_plan()
        unit_id = ctx["work_orders"][0]["id"]
        assert ctx["case_model"]["door_type"] == "OPEN"

        first = validate_success(
            api.advance_work_order(unit_id, TEST_USERS["plant_supervisor_headers"])
        )
        assert first["status"] == "SHEET_METAL"

        second = validate_success(
            api.advance_work_order(unit_id, TEST_USERS["plant_supervisor_headers"])
        )
        assert second["status"] == "FOAM_INJECTION"

        third = validate_success(
            api.advance_work_order(unit_id, TEST_USERS["plant_supervisor_headers"])
        )
        assert third["status"] == "FINAL_QA"
        assert third["rework_count"] == 0
        assert_version_is(third, 4, "work order")


class TestFinalQaOutcomes:
    """PRD §3.7 — below the rework limit only FAIL is legal, at it only SCRAP."""

    def test_02_scrap_before_the_rework_allowance_is_exhausted_is_rejected(self, api):
        """A first-pass unit must be reworked, never scrapped.

        PRD §3.7: "Scrapping is permitted only when `rework_count` equals exactly
        2; a `SCRAP` recorded on a unit that still has rework attempts left is
        rejected at rank 26 with `ERR_SCRAP_NOT_PERMITTED` (HTTP 422)."

        Design: Corner/validations/qa_scrap_before_rework_allowance_exhausted_rejected
        """
        ctx = setup_released_plan()
        unit_id = ctx["work_orders"][0]["id"]
        drive_unit_to_final_qa(unit_id)

        response = api.record_qa_result(
            unit_id,
            qa_result_payload("SCRAP", defect_note="Foam void on left endwall"),
            TEST_USERS["plant_supervisor_headers"],
        )
        validate_error(response, ApiErrorId.ERR_SCRAP_NOT_PERMITTED.value)

        unit = validate_success(
            api.get_work_order(unit_id, TEST_USERS["plant_supervisor_headers"])
        )
        assert unit["status"] == "FINAL_QA"
        assert unit["rework_count"] == 0
        assert_version_is(unit, 4, "work order")

    def test_03_a_third_qa_failure_past_the_rework_limit_is_rejected(self, api):
        """Two failures exhaust the allowance; the third must be a scrap.

        PRD §3.7: "A `FAIL` recorded on a unit whose `rework_count` already
        equals 2 is rejected at rank 25 with `ERR_REWORK_LIMIT_EXCEEDED` (HTTP
        422): that unit has exhausted its allowance and must be scrapped
        instead."

        Design: Corner/validations/third_qa_failure_past_rework_limit_rejected
        """
        ctx = setup_released_plan()
        unit_id = ctx["work_orders"][0]["id"]

        drive_unit_to_final_qa(unit_id)
        first_fail = validate_success(
            api.record_qa_result(
                unit_id,
                qa_result_payload("FAIL", defect_note="Gasket seat out of tolerance"),
                TEST_USERS["plant_supervisor_headers"],
            )
        )
        assert first_fail["status"] == "REWORK"
        assert first_fail["rework_count"] == 1

        drive_unit_to_final_qa(unit_id)
        second_fail = validate_success(
            api.record_qa_result(
                unit_id,
                qa_result_payload(
                    "FAIL", defect_note="Gasket seat still out of tolerance"
                ),
                TEST_USERS["plant_supervisor_headers"],
            )
        )
        assert second_fail["status"] == "REWORK"
        assert second_fail["rework_count"] == 2

        drive_unit_to_final_qa(unit_id)
        rejected = api.record_qa_result(
            unit_id,
            qa_result_payload("FAIL", defect_note="Third failure"),
            TEST_USERS["plant_supervisor_headers"],
        )
        validate_error(rejected, ApiErrorId.ERR_REWORK_LIMIT_EXCEEDED.value)

        scrapped = validate_success(
            api.record_qa_result(
                unit_id,
                qa_result_payload("SCRAP", defect_note="Unrecoverable gasket seat"),
                TEST_USERS["plant_supervisor_headers"],
            )
        )
        assert scrapped["status"] == "SCRAPPED"
        assert scrapped["rework_count"] == 2


class TestQaRulePriority:
    """PRD §2.5 — state admissibility at rank 7 precedes every domain rule."""

    def test_04_state_check_outranks_the_rework_limit_on_a_completed_unit(self, api):
        """A late FAIL on a COMPLETE unit is a state error, not a limit error.

        PRD §3.7: "All three outcomes are admissible only from `FINAL_QA` and
        each increments the unit's `version` by 1."

        Design: Difficulty/priority_pair_validation_conflict/state_check_outranks_rework_limit_on_completed_unit
        """
        ctx = setup_released_plan()
        unit_id = ctx["work_orders"][0]["id"]

        drive_unit_to_final_qa(unit_id)
        validate_success(
            api.record_qa_result(
                unit_id,
                qa_result_payload("FAIL", defect_note="Foam void at the left mullion"),
                TEST_USERS["plant_supervisor_headers"],
            )
        )
        drive_unit_to_final_qa(unit_id)
        validate_success(
            api.record_qa_result(
                unit_id,
                qa_result_payload(
                    "FAIL", defect_note="Second foam void after repour"
                ),
                TEST_USERS["plant_supervisor_headers"],
            )
        )
        drive_unit_to_final_qa(unit_id)
        passed = validate_success(
            api.record_qa_result(
                unit_id, qa_result_payload("PASS"), TEST_USERS["plant_supervisor_headers"]
            )
        )
        assert passed["status"] == "COMPLETE"
        assert passed["rework_count"] == 2

        late = api.record_qa_result(
            unit_id,
            qa_result_payload("FAIL", defect_note="Late defect reported after completion"),
            TEST_USERS["plant_supervisor_headers"],
        )
        validate_error(late, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)

        unit = validate_success(
            api.get_work_order(unit_id, TEST_USERS["plant_supervisor_headers"])
        )
        assert unit["status"] == "COMPLETE"
        assert unit["rework_count"] == 2
        assert refresh_store_plan(ctx)["units_completed_count"] == 1

    def test_05_state_check_also_outranks_the_scrap_permission_rule(self, api):
        """SCRAP is domain-legal at two reworks, yet a COMPLETE unit still refuses.

        PRD §2.5: "The target row's current state admits the requested
        transition, else `ERR_INVALID_STATE_TRANSITION` (HTTP 409). This check
        guards every state-driving operation in the service"

        Design: Difficulty/priority_pair_validation_conflict/state_check_outranks_rework_limit_on_completed_unit
        """
        ctx = setup_released_plan()
        unit_id = ctx["work_orders"][0]["id"]

        for note in ("First foam void", "Second foam void"):
            drive_unit_to_final_qa(unit_id)
            validate_success(
                api.record_qa_result(
                    unit_id,
                    qa_result_payload("FAIL", defect_note=note),
                    TEST_USERS["plant_supervisor_headers"],
                )
            )
        drive_unit_to_final_qa(unit_id)
        completed = validate_success(
            api.record_qa_result(
                unit_id, qa_result_payload("PASS"), TEST_USERS["plant_supervisor_headers"]
            )
        )
        assert completed["status"] == "COMPLETE"
        assert completed["rework_count"] == 2

        response = api.record_qa_result(
            unit_id,
            qa_result_payload("SCRAP", defect_note="Retired after completion"),
            TEST_USERS["plant_supervisor_headers"],
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)

        unit = validate_success(
            api.get_work_order(unit_id, TEST_USERS["plant_supervisor_headers"])
        )
        assert unit["status"] == "COMPLETE"
        assert refresh_store_plan(ctx)["units_completed_count"] == 1
