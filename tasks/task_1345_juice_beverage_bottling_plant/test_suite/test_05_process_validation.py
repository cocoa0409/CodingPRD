"""Process validation (pasteurization/HPP), disposition, abort, and condemn."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, factories,
    create_customer, create_formula, create_tank, plan_batch, blend_and_record,
    qa_verdict, create_qa_passed_batch,
    make_qa_inspector_headers, OP_USER,
)

# Module-level alias of the session-scoped `api` fixture (conftest returns
# the same object) so module/class helpers can call the client without
# declaring the fixture parameter.
api = api_client


PM = TEST_USERS["plant_manager_headers"]
OP = TEST_USERS["blend_operator_headers"]
QA = TEST_USERS["qa_inspector_headers"]


def _qa_passed_batch(process_type="PASTEURIZATION", measured=None):
    customer = create_customer()
    overrides = {}
    if process_type == "HPP":
        overrides = {"process_type": "HPP", "target_brix": 8.0,
                     "concentrate_brix": 60.0, "claims": ["COLD_PRESSED"]}
    formula = create_formula(customer["id"], approve=False, **overrides)
    tank = create_tank()
    if measured is None:
        measured = formula["target_brix"] + 0.1
    batch = create_qa_passed_batch(formula, tank, quantity_liters=1000,
                                   measured_brix=measured)
    return formula, tank, batch


class TestConditionalSetpoints:
    def test_pasteurization_requires_temp_setpoints(self, api):
        """PRD §3.5: "a pasteurization run requires `setpoint_temp_c` and
        `setpoint_hold_seconds`, while an HPP run requires
        `setpoint_pressure_mpa` and `setpoint_pressure_hold_seconds`."

        Design: Corner/entities/conditional_setpoint_requirement_per_process_type
        """
        formula, tank, batch = _qa_passed_batch("PASTEURIZATION")
        resp = api.create_process_run({"batch_id": batch["id"]}, OP)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400
        prun = get_success_data(api.create_process_run(
            {"batch_id": batch["id"], "setpoint_temp_c": 88.0,
             "setpoint_hold_seconds": 30}, OP))
        assert prun["process_type"] == "PASTEURIZATION"

    def test_hpp_requires_pressure_setpoints(self, api):
        """PRD §3.5: "a pasteurization run requires `setpoint_temp_c` and
        `setpoint_hold_seconds`, while an HPP run requires
        `setpoint_pressure_mpa` and `setpoint_pressure_hold_seconds`."

        Design: Corner/entities/conditional_setpoint_requirement_per_process_type
        """
        formula, tank, batch = _qa_passed_batch("HPP")
        # temp setpoints on an HPP run leave the required pressure pair missing
        resp = api.create_process_run(
            {"batch_id": batch["id"], "setpoint_temp_c": 88.0,
             "setpoint_hold_seconds": 30}, OP)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400
        prun = get_success_data(api.create_process_run(
            {"batch_id": batch["id"], "setpoint_pressure_mpa": 600.0,
             "setpoint_pressure_hold_seconds": 180}, OP))
        assert prun["process_type"] == "HPP"


class TestProcessRunLifecycle:
    def test_one_active_run_per_batch(self, api):
        """PRD §3.5: "A batch carries at most one live process run — creating
        another while a sibling stands in `SCHEDULED` or `RUNNING` is refused
        with `ERR_PROCESS_RUN_ACTIVE_EXISTS`"

        Design: Corner/state_machines/process_run_active_sibling_and_terminal_guards
        """
        formula, tank, batch = _qa_passed_batch()
        prun = get_success_data(api.create_process_run(
            factories.create_process_run_payload(batch["id"], "PASTEURIZATION"), OP))
        assert prun["status"] == "SCHEDULED"
        resp = api.create_process_run(
            factories.create_process_run_payload(batch["id"], "PASTEURIZATION"), OP)
        validate_error(resp, ApiErrorId.ERR_PROCESS_RUN_ACTIVE_EXISTS)

    def test_state_guards_and_abort_cycle(self, api):
        """PRD §3.5: "A `BlendOperator` may also abort a run standing in
        `SCHEDULED` or `RUNNING` (any other state draws
        `ERR_PROCESS_RUN_STATE_INVALID`); aborting a run whose batch had entered
        `PROCESSING` returns the batch to `QA_PASSED`, so a replacement run can be
        scheduled against it"

        Design: Corner/state_machines/process_run_active_sibling_and_terminal_guards
        """
        formula, tank, batch = _qa_passed_batch()
        prun = get_success_data(api.create_process_run(
            factories.create_process_run_payload(batch["id"], "PASTEURIZATION"), OP))
        # complete before start
        validate_error(api.complete_process_run(
            prun["id"], {"min_temp_c": 88.0, "time_below_setpoint_seconds": 0}, OP),
            ApiErrorId.ERR_PROCESS_RUN_STATE_INVALID)
        running = get_success_data(api.start_process_run(prun["id"], OP))
        assert running["status"] == "RUNNING"
        # no idempotent replay of start
        validate_error(api.start_process_run(prun["id"], OP),
                       ApiErrorId.ERR_PROCESS_RUN_STATE_INVALID)
        aborted = get_success_data(api.abort_process_run(prun["id"], OP))
        assert aborted["status"] == "ABORTED"
        assert get_success_data(api.get_batch(batch["id"], PM))["status"] == "QA_PASSED"
        # ABORTED is terminal
        validate_error(api.start_process_run(prun["id"], OP),
                       ApiErrorId.ERR_PROCESS_RUN_STATE_INVALID)
        # a replacement run can be scheduled after the abort
        prun2 = get_success_data(api.create_process_run(
            factories.create_process_run_payload(batch["id"], "PASTEURIZATION"), OP))
        assert prun2["status"] == "SCHEDULED"


class TestPasteurizationDeviationBoundaries:
    def _three_running_paste_runs(self):
        formula, tank, batch1 = _qa_passed_batch()
        tank2 = create_tank()
        batch2 = create_qa_passed_batch(formula, tank2, quantity_liters=1000)
        tank3 = create_tank()
        batch3 = create_qa_passed_batch(formula, tank3, quantity_liters=1000)
        runs = []
        for batch in (batch1, batch2, batch3):
            prun = get_success_data(api.create_process_run(
                factories.create_process_run_payload(batch["id"], "PASTEURIZATION"), OP))
            get_success_data(api.start_process_run(prun["id"], OP))
            runs.append((batch["id"], prun["id"]))
        return runs

    def test_minor_at_inclusive_boundaries(self, api):
        """PRD §3.5: "otherwise, when `min_temp_c` is no more than two degrees
        Celsius below the setpoint and `time_below_setpoint_seconds` is no more
        than sixty seconds, the run is `DEVIATED` with `deviation_class` `MINOR`"

        Design: Corner/calculations/pasteurization_deviation_class_boundaries
        """
        (b1, p1), _, (b3, p3) = self._three_running_paste_runs()
        # exactly setpoint - 2.0 and exactly 60 s below -> MINOR (inclusive)
        done1 = get_success_data(api.complete_process_run(
            p1, {"min_temp_c": 86.0, "time_below_setpoint_seconds": 60}, OP))
        assert done1["status"] == "DEVIATED"
        assert done1["deviation_class"] == "MINOR"
        # at setpoint temp but 30 s below -> VALIDATED requires exactly zero below
        done3 = get_success_data(api.complete_process_run(
            p3, {"min_temp_c": 88.0, "time_below_setpoint_seconds": 30}, OP))
        assert done3["status"] == "DEVIATED"
        assert done3["deviation_class"] == "MINOR"
        # a DEVIATED run leaves its batch in PROCESSING pending disposition
        assert get_success_data(api.get_batch(b1, PM))["status"] == "PROCESSING"

    def test_major_below_minor_floor(self, api):
        """PRD §3.5: "anything worse is `DEVIATED` with `deviation_class`
        `MAJOR`."

        Design: Corner/calculations/pasteurization_deviation_class_boundaries
        """
        runs = self._three_running_paste_runs()
        _, (b2, p2), _ = runs
        # 85.9 < 88.0 - 2.0: misses the MINOR floor
        done2 = get_success_data(api.complete_process_run(
            p2, {"min_temp_c": 85.9, "time_below_setpoint_seconds": 60}, OP))
        assert done2["status"] == "DEVIATED"
        assert done2["deviation_class"] == "MAJOR"


class TestHppDeviationBoundaries:
    def _three_running_hpp_runs(self):
        formula, tank, batch1 = _qa_passed_batch("HPP")
        tank2 = create_tank()
        batch2 = create_qa_passed_batch(formula, tank2, quantity_liters=1000)
        tank3 = create_tank()
        batch3 = create_qa_passed_batch(formula, tank3, quantity_liters=1000)
        runs = []
        for batch in (batch1, batch2, batch3):
            prun = get_success_data(api.create_process_run(
                factories.create_process_run_payload(batch["id"], "HPP"), OP))
            get_success_data(api.start_process_run(prun["id"], OP))
            runs.append((batch["id"], prun["id"]))
        return runs

    def test_hpp_minor_at_inclusive_boundaries(self, api):
        """PRD §3.5: "pressure no more than twenty megapascals below setpoint with
        a shortfall of no more than thirty seconds yields `DEVIATED` and `MINOR`"

        Design: Corner/calculations/hpp_deviation_class_boundaries
        """
        (b1, p1), _, _ = self._three_running_hpp_runs()
        done1 = get_success_data(api.complete_process_run(
            p1, {"min_pressure_mpa": 580.0, "pressure_hold_shortfall_seconds": 30}, OP))
        assert done1["status"] == "DEVIATED"
        assert done1["deviation_class"] == "MINOR"

    def test_hpp_major_beyond_either_axis(self, api):
        """PRD §3.5: "anything worse yields `DEVIATED` and `MAJOR`." and
        "`min_pressure_mpa` at least `setpoint_pressure_mpa` with
        `pressure_hold_shortfall_seconds` exactly zero yields `VALIDATED` and
        `NONE`"

        Design: Corner/calculations/hpp_deviation_class_boundaries
        """
        _, (b2, p2), (b3, p3) = self._three_running_hpp_runs()
        # shortfall 31 > 30 even at full pressure -> MAJOR
        done2 = get_success_data(api.complete_process_run(
            p2, {"min_pressure_mpa": 600.0, "pressure_hold_shortfall_seconds": 31}, OP))
        assert done2["status"] == "DEVIATED"
        assert done2["deviation_class"] == "MAJOR"
        # pressure 579.9 < 580.0 misses the MINOR floor even with zero shortfall
        done3 = get_success_data(api.complete_process_run(
            p3, {"min_pressure_mpa": 579.9, "pressure_hold_shortfall_seconds": 0}, OP))
        assert done3["status"] == "DEVIATED"
        assert done3["deviation_class"] == "MAJOR"


class TestQaSegregationOfDuties:
    def test_blender_cannot_pass_own_batch(self, api):
        """PRD §3.4: "Quality judgment is rendered by a `QAInspector` who must not
        be the operator who blended the batch: a caller whose `X-User-ID` equals
        the batch's `blended_by_user_id` is refused with
        `ERR_SOD_QA_SELF_APPROVAL`."

        Design: Corner/rbac/sod_qa_verdict_and_disposition
        """
        customer = create_customer()
        formula = create_formula(customer["id"], approve=False)
        tank = create_tank()
        batch = plan_batch(formula["id"], tank["id"], quantity_liters=1000)
        recorded = blend_and_record(batch["id"], 12.1)
        assert recorded["blended_by_user_id"] == OP_USER
        resp = api.qa_verdict(batch["id"], {"verdict": "PASS"},
                              make_qa_inspector_headers(OP_USER))
        validate_error(resp, ApiErrorId.ERR_SOD_QA_SELF_APPROVAL)
        assert resp.status_code == 403
        passed = qa_verdict(batch["id"], "PASS")  # a different QA user passes
        assert passed["status"] == "QA_PASSED"

    def test_blender_cannot_disposition_own_deviated_run(self, api):
        """PRD §3.5: "Disposition of a deviated run belongs to a `QAInspector`
        under the same self-approval bar as §3.4 — the caller must differ from the
        batch's `blended_by_user_id`, else `ERR_SOD_QA_SELF_APPROVAL` — and the
        run must stand in `DEVIATED`, else `ERR_PROCESS_RUN_STATE_INVALID`."

        Design: Corner/rbac/sod_qa_verdict_and_disposition
        """
        formula, tank, batch = _qa_passed_batch()
        prun = get_success_data(api.create_process_run(
            factories.create_process_run_payload(batch["id"], "PASTEURIZATION"), OP))
        get_success_data(api.start_process_run(prun["id"], OP))
        deviated = get_success_data(api.complete_process_run(
            prun["id"], {"min_temp_c": 86.5, "time_below_setpoint_seconds": 30}, OP))
        assert deviated["status"] == "DEVIATED"
        assert deviated["deviation_class"] == "MINOR"
        resp = api.qa_disposition(prun["id"], {"disposition": "RELEASE"},
                                  make_qa_inspector_headers(OP_USER))
        validate_error(resp, ApiErrorId.ERR_SOD_QA_SELF_APPROVAL)
        resolved = get_success_data(api.qa_disposition(
            prun["id"], {"disposition": "RELEASE"}, QA))
        assert resolved["status"] == "DISPOSITION_RELEASED"
        assert get_success_data(api.get_batch(batch["id"], PM))["status"] == "PROCESSED"


class TestReleaseProcessGate:
    def _deviated_processing_batch(self):
        formula, tank, batch = _qa_passed_batch()
        prun = get_success_data(api.create_process_run(
            factories.create_process_run_payload(batch["id"], "PASTEURIZATION"), OP))
        get_success_data(api.start_process_run(prun["id"], OP))
        get_success_data(api.complete_process_run(
            prun["id"], {"min_temp_c": 86.5, "time_below_setpoint_seconds": 30}, OP))
        return batch["id"], prun["id"]

    def test_release_blocked_while_governing_run_deviated(self, api):
        """PRD §3.4: "Releasing straight out of `PROCESSING` is the fast path: the
        governing process run — the batch's latest process run that is not
        `ABORTED` — must stand in `VALIDATED` or `DISPOSITION_RELEASED`, else the
        release is refused with `ERR_PROCESS_NOT_VALIDATED`"

        Design: Difficulty/cross_entity_state_dependency/release_requires_validated_process_run
        """
        batch_id, prun_id = self._deviated_processing_batch()
        resp = api.release_batch(batch_id, QA)
        validate_error(resp, ApiErrorId.ERR_PROCESS_NOT_VALIDATED)
        assert resp.status_code == 409

    def test_release_succeeds_after_disposition_release(self, api):
        """PRD §3.5: "A `disposition` of `RELEASE` moves the run to
        `DISPOSITION_RELEASED` and completes the batch's processing exactly as a
        validation would have: the batch moves to `PROCESSED` and the loss figures
        are booked."

        Design: Difficulty/cross_entity_state_dependency/release_requires_validated_process_run
        """
        batch_id, prun_id = self._deviated_processing_batch()
        validate_error(api.release_batch(batch_id, QA),
                       ApiErrorId.ERR_PROCESS_NOT_VALIDATED)
        get_success_data(api.qa_disposition(prun_id, {"disposition": "RELEASE"}, QA))
        assert get_success_data(api.get_batch(batch_id, PM))["status"] == "PROCESSED"
        released = get_success_data(api.release_batch(batch_id, QA))
        assert released["status"] == "RELEASED"


class TestCondemnFromQaFailed:
    def test_condemn_fires_only_applicable_branches(self, api):
        """PRD §3.4: "The cascade runs four hops deep (§2.10): any of the batch's
        process runs still standing in `SCHEDULED`, `RUNNING`, or `DEVIATED` is
        aborted; the production run currently reserving the batch through its
        `linked_run_id`, if that run sits in `SCHEDULED`, is demoted to
        `BLOCKED_SUPPLY`; that run's container reservations are released back to
        their lots; and its bottling-line window is freed. If the tank was still
        `OCCUPIED` by the condemned batch, its posture drops to `AWAITING_CIP` at
        the same moment."

        Design: Corner/state_machines/condemn_from_qa_failed_conditional_cascade
        """
        customer = create_customer()
        formula = create_formula(customer["id"], approve=False)
        tank = create_tank()
        batch = plan_batch(formula["id"], tank["id"], quantity_liters=1000)
        blend_and_record(batch["id"], 13.0)  # 1.0 over target, outside 0.3 band
        qa_verdict(batch["id"], "FAIL")
        condemned = get_success_data(api.condemn_batch(batch["id"], QA))
        assert condemned["status"] == "CONDEMNED"
        tank_after = get_success_data(api.get_tank(tank["id"], PM))
        assert tank_after["posture"] == "AWAITING_CIP"
        assert tank_after.get("occupying_batch_id") is None
        # no process run ever existed: the abort branch has nothing to do
        pruns = get_success_data(api.list_batch_process_runs(batch["id"], PM))
        assert pruns == []

    def test_condemned_is_terminal(self, api):
        """PRD §3.4: "A `QAInspector` may condemn a batch standing in `QA_FAILED`,
        `PROCESSED`, or `RELEASED` — any other state draws
        `ERR_BATCH_STATE_INVALID`"

        Design: Corner/state_machines/condemn_from_qa_failed_conditional_cascade
        """
        customer = create_customer()
        formula = create_formula(customer["id"], approve=False)
        tank = create_tank()
        batch = plan_batch(formula["id"], tank["id"], quantity_liters=1000)
        blend_and_record(batch["id"], 13.0)
        qa_verdict(batch["id"], "FAIL")
        get_success_data(api.condemn_batch(batch["id"], QA))
        validate_error(api.condemn_batch(batch["id"], QA),
                       ApiErrorId.ERR_BATCH_STATE_INVALID)
        validate_error(api.release_batch(batch["id"], QA),
                       ApiErrorId.ERR_BATCH_STATE_INVALID)
