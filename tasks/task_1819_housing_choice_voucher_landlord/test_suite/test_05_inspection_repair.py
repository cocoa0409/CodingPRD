"""Inspection, repair, and verification-cycle tests (PRD §3.4)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, ADMIN, INSPECTOR,
    setup_active_scenario,
    schedule_contract_inspection, attach_repair_item, fail_inspection,
    setup_failed_inspection, setup_repair_verification,
    mark_item_repaired, request_reinspection, verify_item,
    make_landlord_headers,
)


class TestFailRequiresItemsBoundary:
    def test_fail_with_zero_repair_items_rejected(self, api):
        """PRD §3.4: "Recording a `FAIL` is more involved: the inspector must
        have attached at least one `RepairItem` to the inspection before or with
        the failure result, otherwise the record-result call is rejected with
        `ERR_FAIL_REQUIRES_ITEMS`."

        Design: Difficulty/boundary_precision_check/fail_result_requires_nonempty_repair_items_boundary
        """
        landlord, prop, unit, family, contract = setup_active_scenario(
            zip_code="90013", family_code="FC",
        )
        inspection = schedule_contract_inspection(contract["id"], "ANNUAL", "2026-08-05")
        resp = api.record_inspection_result(
            inspection["id"], {"outcome": "FAIL"}, INSPECTOR
        )
        validate_error(resp, ApiErrorId.ERR_FAIL_REQUIRES_ITEMS)

    def test_fail_with_one_repair_item_succeeds(self, api):
        """PRD §3.4: "When the result is recorded as `FAIL`, the inspection
        moves from `SCHEDULED` to `FAILED`, `result_recorded_date` is set, and
        every attached repair item begins life in `OPEN` status."

        Design: Difficulty/boundary_precision_check/fail_result_requires_nonempty_repair_items_boundary
        """
        landlord, prop, unit, family, contract = setup_active_scenario(
            zip_code="90013", family_code="FC2",
        )
        inspection = schedule_contract_inspection(contract["id"], "ANNUAL", "2026-08-05")
        item = attach_repair_item(inspection["id"], description="leak")
        data = validate_success(
            api.record_inspection_result(inspection["id"], {"outcome": "FAIL"}, INSPECTOR)
        )
        assert data["status"] == "FAILED"
        assert data["result_recorded_date"] is not None, (
            "FAIL must set result_recorded_date to the current logical date"
        )


class TestInspectionRepairVerificationCycle:
    def test_failed_verify_loops_inspection_back_to_failed(self, api):
        """PRD §3.4: "a `FAIL` outcome moves the item from `REPAIRED` to
        `FAILED_VERIFICATION`, drops the inspection from `REPAIR_VERIFICATION`
        back to `FAILED`, and restarts the repair-deadline clock from the new
        verification date."

        Design: Difficulty/non_linear_state_machine/inspection_repair_verification_cycle
        """
        landlord, prop, unit, family, contract = setup_active_scenario(
            zip_code="90005", family_code="F5",
        )
        inspection, item = setup_repair_verification(contract, landlord)
        verify_item(item["id"], "FAIL")
        insp = get_success_data(api.get_inspection(inspection["id"], ADMIN))
        assert insp["status"] == "FAILED", (
            f"a failed verification must drop the inspection back to FAILED, got "
            f"{insp['status']}"
        )
        itm = get_success_data(
            api.list_inspection_repair_items(inspection["id"], ADMIN)
        )
        statuses = [i["status"] for i in itm]
        assert "FAILED_VERIFICATION" in statuses, (
            f"the refuted item must be FAILED_VERIFICATION, got {statuses}"
        )

    def test_full_cycle_fail_rerepair_verify_pass_closes(self, api):
        """PRD §3.4: "When the final non-`VERIFIED` item on the inspection is
        verified `PASS`, three things happen in one cascade: the inspection
        moves from `REPAIR_VERIFICATION` to `CLOSED`; the contract, if it was
        `ABATED`, moves back to `ACTIVE`; and the unit moves from
        `SUSPENDED_ABATEMENT` back to `UNDER_CONTRACT`."

        Design: Difficulty/non_linear_state_machine/inspection_repair_verification_cycle
        """
        landlord, prop, unit, family, contract = setup_active_scenario(
            zip_code="90005", family_code="F5b",
        )
        inspection, item = setup_repair_verification(contract, landlord)
        # First verification fails -> cycle back to FAILED.
        verify_item(item["id"], "FAIL")
        insp = get_success_data(api.get_inspection(inspection["id"], ADMIN))
        assert insp["status"] == "FAILED"
        # Re-repair, re-request reinspection, verify PASS -> CLOSED.
        mark_item_repaired(item["id"], landlord)
        request_reinspection(inspection["id"], landlord)
        verify_item(item["id"], "PASS")
        insp = get_success_data(api.get_inspection(inspection["id"], ADMIN))
        assert insp["status"] == "CLOSED", (
            f"final PASS verification must close the inspection, got {insp['status']}"
        )


class TestReinspectionWithOpenItemsRejected:
    def test_request_reinspection_with_open_item_rejected(self, api):
        """PRD §3.4: "Once every item on the inspection is in `REPAIRED`, the
        landlord requests a reinspection, moving the inspection from `FAILED` to
        `REPAIR_VERIFICATION`; if even one item is not yet `REPAIRED`, the
        request is rejected with `ERR_OPEN_REPAIR_ITEMS`."

        Design: Corner/validations/reinspection_with_open_items_rejected
        """
        landlord, prop, unit, family, contract = setup_active_scenario(
            zip_code="90308", family_code="CF11",
        )
        inspection, item = setup_failed_inspection(contract, landlord)
        # Item is still OPEN (not yet marked repaired).
        resp = api.request_reinspection(
            inspection["id"], make_landlord_headers(landlord["id"])
        )
        validate_error(resp, ApiErrorId.ERR_OPEN_REPAIR_ITEMS)


class TestScheduleInspectionInPast:
    def test_back_dated_schedule_rejected(self, api):
        """PRD §3.4: "The scheduled date must not precede the current logical
        date — a back-dated schedule is rejected with `ERR_SCHEDULE_IN_PAST`."

        Design: Corner/validations/schedule_inspection_in_past_rejected
        """
        landlord, prop, unit, family, contract = setup_active_scenario(
            zip_code="90307", family_code="CF10",
        )
        # Clock default is 2026-08-01 (PRD §2.7); 2026-07-01 precedes it.
        resp = api.schedule_inspection(
            contract["id"],
            {"inspection_type": "ANNUAL", "scheduled_date": "2026-07-01"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_IN_PAST)
