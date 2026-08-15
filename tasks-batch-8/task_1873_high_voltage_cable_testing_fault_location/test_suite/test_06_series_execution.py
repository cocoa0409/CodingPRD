"""Test series execution: creation gates, energize gates, reading discipline,
and evaluation preconditions (PRD §3.6, §2.5)."""
import pytest

from test_helpers import (
    api_client,
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    assert_test_reading,
    setup_planned_job,
    setup_job_in_progress,
    create_permit,
    issue_permit,
    verify_grounding,
    create_unit,
    create_assignment,
    confirm_assignment,
    activate_window,
    set_clock,
    create_series,
    energize_series,
    add_reading,
    log_vlf_steps,
    evaluate_series,
    create_fail_series_with_fault,
    pinpoint_fault,
    get_circuit,
    get_success_data,
    create_job,
)

SUPERVISOR = TEST_USERS["test_supervisor_headers"]
TECHNICIAN = TEST_USERS["field_technician_headers"]
PLANNER = TEST_USERS["network_planner_headers"]


def _setup_issued_not_verified(circuit_ref):
    """Job IN_PROGRESS with the permit only ISSUED (not grounding-verified)."""
    ctx = setup_planned_job(circuit_ref=circuit_ref)
    permit = issue_permit(create_permit(ctx["job"]["id"])["id"])
    unit = create_unit()
    assignment = confirm_assignment(create_assignment(unit["id"], ctx["job"]["id"])["id"])
    set_clock("2026-08-10T09:00:00Z")
    activate_window(ctx["window"]["id"])
    get_success_data(api_client.start_job(ctx["job"]["id"], SUPERVISOR))
    ctx.update({"permit": permit, "unit": unit, "assignment": assignment})
    return ctx


class TestReadingLog:
    def test_reading_is_append_only_without_version(self, api):
        """PRD §2.5: "a test reading is an append-only log entry and carries
        only `id` and `created_at`. Both `updated_at` and `version` are absent
        from test readings; a reading, once appended, is never modified."
        PRD §3.6: "The appending operator is recorded as
        `recorded_by_user_id`."

        Design: Corner/entities/reading_log_has_no_version_field
        """
        ctx = setup_job_in_progress(circuit_ref="CKT-E5")
        series = energize_series(create_series(ctx["job"]["id"])["id"])
        reading = add_reading(series["id"], 0, 4.35, tan_delta_e3=4.0)
        assert_test_reading(reading)
        assert reading["recorded_by_user_id"] == "ft-1"

        readings = validate_success(api.list_readings(series["id"], TECHNICIAN))
        assert len(readings) == 1
        assert_test_reading(readings[0])
        assert readings[0]["id"] == reading["id"]


class TestEvaluatePreconditions:
    def test_evaluate_energizing_without_readings_rejected(self, api):
        """PRD §3.6: "Evaluation by the `TestSupervisor` — invocable from
        `ENERGIZING` or `LOGGING` — requires at least one reading (else
        `ERR_NO_READINGS` — which always fires for a series still in
        `ENERGIZING`, since the first reading would already have moved it to
        `LOGGING`)".

        Design: Corner/state_machines/evaluate_energizing_without_readings_rejected
        """
        ctx = setup_job_in_progress(circuit_ref="CKT-S6")
        series = energize_series(create_series(ctx["job"]["id"])["id"])
        resp = api.evaluate_series(series["id"], SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_NO_READINGS)
        assert validate_success(api.get_test_series(series["id"], SUPERVISOR))["status"] == "ENERGIZING"

    def test_evaluate_with_missing_step_rejected_then_succeeds(self, api):
        """PRD §3.6: "and then requires every step from 0 through `step_count`
        minus one to have a reading (else `ERR_STEP_INCOMPLETE`), in that
        order."

        Design: Corner/state_machines/evaluate_with_missing_step_rejected
        """
        ctx = setup_job_in_progress(circuit_ref="CKT-S7")
        series = energize_series(create_series(ctx["job"]["id"])["id"])
        add_reading(series["id"], 0, 4.35, tan_delta_e3=4.0)
        add_reading(series["id"], 1, 8.7, tan_delta_e3=4.1)

        resp = api.evaluate_series(series["id"], SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_STEP_INCOMPLETE)

        add_reading(series["id"], 2, 13.05, tan_delta_e3=4.2)
        evaluated = evaluate_series(series["id"])
        assert evaluated["verdict"] == "PASS", (
            "max rounded tan-delta 4.2 is strictly below 5.0 (PRD §3.6)"
        )

    def test_evaluate_twice_rejected(self, api):
        """PRD §3.6: "Evaluation by the `TestSupervisor` — invocable from
        `ENERGIZING` or `LOGGING`" — `EVALUATED` is not a from-state.
        PRD §2.7: "6. **State legality** — the target entity must be in an
        allowed from-state for the requested transition, else
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/series_evaluate_twice_rejected
        """
        ctx = setup_job_in_progress(circuit_ref="CKT-S2")
        series, fault_id = create_fail_series_with_fault(ctx["job"]["id"])

        resp = api.evaluate_series(series["id"], SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        faults = validate_success(api.list_series_faults(series["id"], SUPERVISOR))
        assert len(faults) == 1, "the rejected retry must not create a second fault"


class TestReadingDiscipline:
    def test_duplicate_step_rejected(self, api):
        """PRD §3.6: "The `step_index` is zero-based, must be below the
        series' `step_count` (else `ERR_STEP_OUT_OF_RANGE`, HTTP 422), and
        must not repeat a step already recorded for the series (else
        `ERR_DUPLICATE_STEP`)".

        Design: Corner/validations/duplicate_step_rejected
        """
        ctx = setup_job_in_progress(circuit_ref="CKT-V4")
        series = energize_series(create_series(ctx["job"]["id"])["id"])
        add_reading(series["id"], 0, 4.35, tan_delta_e3=4.0)

        resp = api.add_reading(
            series["id"],
            {"step_index": 0, "applied_voltage_kv": 4.35,
             "tan_delta_e3": 4.5, "ambient_temp_c": 20.0},
            TECHNICIAN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_STEP)
        readings = validate_success(api.list_readings(series["id"], TECHNICIAN))
        assert len(readings) == 1
        assert readings[0]["tan_delta_e3"] == 4.0, "the original step-0 reading is unchanged"

    def test_step_out_of_range_on_single_step_method(self, api):
        """PRD §3.6: "its `step_count` is derived from the method: three steps
        for `VLF_TAN_DELTA` and `VLF_WITH_PD`, where steps 0, 1, and 2
        correspond to applied levels of one-half, one times, and
        one-and-a-half times U0, and a single step for `PD_MAPPING`." A
        reading at step_index 1 is "below the series' `step_count` (else
        `ERR_STEP_OUT_OF_RANGE`, HTTP 422)".

        Design: Corner/validations/step_out_of_range_rejected
        """
        ctx = setup_job_in_progress(
            circuit_ref="CKT-V5", requested_methods=["PD_MAPPING"],
        )
        series = create_series(ctx["job"]["id"], "PD_MAPPING", 5.0)
        assert series["step_count"] == 1
        energize_series(series["id"])
        resp = api.add_reading(
            series["id"],
            {"step_index": 1, "applied_voltage_kv": 5.0, "pd_level_pc": 300,
             "pd_location_m": 420.0, "ambient_temp_c": 20.0},
            TECHNICIAN,
        )
        validate_error(resp, ApiErrorId.ERR_STEP_OUT_OF_RANGE)

    def test_method_conditional_reading_fields(self, api):
        """PRD §3.6: "`tan_delta_e3` is required for the VLF methods and
        forbidden for `PD_MAPPING`; `pd_level_pc` is required for
        `VLF_WITH_PD` and `PD_MAPPING` and forbidden for `VLF_TAN_DELTA`;
        `pd_location_m` is optional and meaningful for `PD_MAPPING` only."
        PRD §2.7: "Any violation yields `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/validations/reading_field_method_discipline
        """
        ctx = setup_job_in_progress(
            circuit_ref="CKT-V6",
            requested_methods=["VLF_TAN_DELTA", "PD_MAPPING"],
            approved_budget_cents=900000,
        )
        vlf = energize_series(create_series(ctx["job"]["id"], "VLF_TAN_DELTA", 13.05)["id"])
        pd_series = energize_series(create_series(ctx["job"]["id"], "PD_MAPPING", 5.0)["id"])

        vlf_with_pd_field = api.add_reading(
            vlf["id"],
            {"step_index": 0, "applied_voltage_kv": 4.35, "tan_delta_e3": 4.0,
             "pd_level_pc": 100, "ambient_temp_c": 20.0},
            TECHNICIAN,
        )
        validate_error(vlf_with_pd_field, ApiErrorId.ERR_INVALID_REQUEST)

        pd_missing_field = api.add_reading(
            pd_series["id"],
            {"step_index": 0, "applied_voltage_kv": 5.0, "ambient_temp_c": 20.0},
            TECHNICIAN,
        )
        validate_error(pd_missing_field, ApiErrorId.ERR_INVALID_REQUEST)


class TestSeriesCreationGates:
    def test_voltage_tolerance_boundary(self, api):
        """PRD §3.6: "for the two VLF methods the `test_voltage_kv` must lie
        within five percent — in either direction, boundaries included — of
        one and a half times the U0 of the circuit's voltage class, with
        violations rejected as `ERR_VOLTAGE_MISMATCH` (HTTP 422)."
        PRD §2.8: "8.7 kV for `KV_15`" (1.5 x 8.7 = 13.05; +5% = 13.7025).

        Design: Corner/validations/voltage_tolerance_boundary
        """
        ctx = setup_job_in_progress(
            circuit_ref="CKT-V3", with_permit=False, with_equipment=False,
        )
        at_boundary = validate_success(api.create_test_series(
            {"test_job_id": ctx["job"]["id"], "method": "VLF_TAN_DELTA",
             "test_voltage_kv": 13.7025},
            SUPERVISOR,
        ), 201)
        assert at_boundary["step_count"] == 3

        over_boundary = api.create_test_series(
            {"test_job_id": ctx["job"]["id"], "method": "VLF_TAN_DELTA",
             "test_voltage_kv": 13.7026},
            SUPERVISOR,
        )
        validate_error(over_boundary, ApiErrorId.ERR_VOLTAGE_MISMATCH)

    def test_method_not_requested_rejected(self, api):
        """PRD §3.6: "the `method` must be a member of the job's
        `requested_methods` (else `ERR_METHOD_NOT_REQUESTED`)".

        Design: Corner/validations/method_not_requested_rejected
        """
        ctx = setup_job_in_progress(
            circuit_ref="CKT-V17", with_permit=False, with_equipment=False,
        )
        resp = api.create_test_series(
            {"test_job_id": ctx["job"]["id"], "method": "PD_MAPPING",
             "test_voltage_kv": 5.0},
            SUPERVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_METHOD_NOT_REQUESTED)

    def test_retest_series_requires_repaired_fault(self, api):
        """PRD §3.6: "a re-test may only be created while its linked fault is
        `REPAIRED` (a violation is likewise `ERR_INVALID_STATE`)".

        Design: Corner/validations/retest_requires_repaired_fault
        """
        ctx = setup_job_in_progress(circuit_ref="CKT-V16")
        _, fault_id = create_fail_series_with_fault(ctx["job"]["id"])
        pinpoint_fault(fault_id)
        resp = api.create_test_series(
            {"test_job_id": ctx["job"]["id"], "method": "VLF_TAN_DELTA",
             "test_voltage_kv": 13.05, "is_retest": True,
             "retest_of_fault_id": fault_id},
            SUPERVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestEnergizeGates:
    def test_energize_without_equipment_rejected(self, api):
        """PRD §3.6: "there must exist an equipment assignment for the job in
        `CONFIRMED` or `ACTIVE` whose interval brackets the logical clock —
        `mobilize_at` at or before now and `demobilize_at` at or after now
        (else `ERR_NO_EQUIPMENT_ON_SITE`)".

        Design: Corner/validations/no_equipment_on_site_rejected
        """
        ctx = setup_job_in_progress(circuit_ref="CKT-V11", with_equipment=False)
        series = create_series(ctx["job"]["id"])
        resp = api.energize_series(series["id"], SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_NO_EQUIPMENT_ON_SITE)
        assert validate_success(api.get_test_series(series["id"], SUPERVISOR))["status"] == "SETUP"

    def test_energize_blocked_until_grounding_verified(self, api):
        """PRD §3.6: "the job's isolation permit must have reached
        `GROUNDING_VERIFIED` (else `ERR_GROUNDING_NOT_VERIFIED`)".

        Design: Difficulty/cross_entity_state_dependency/energize_blocked_until_grounding_verified
        """
        ctx = _setup_issued_not_verified("CKT-CE1")
        series = create_series(ctx["job"]["id"])
        resp = api.energize_series(series["id"], SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_GROUNDING_NOT_VERIFIED)
        assert validate_success(api.get_test_series(series["id"], SUPERVISOR))["status"] == "SETUP"

    def test_energize_after_independent_verification_succeeds(self, api):
        """PRD §3.6: "Energizing moves the series `SETUP` → `ENERGIZING` and
        the circuit `GROUNDED` → `UNDER_TEST`."

        Design: Difficulty/cross_entity_state_dependency/energize_blocked_until_grounding_verified
        """
        ctx = _setup_issued_not_verified("CKT-CE1")
        series = create_series(ctx["job"]["id"])
        verify_grounding(ctx["permit"]["id"])
        energized = energize_series(series["id"])
        assert energized["status"] == "ENERGIZING"
        assert get_circuit(ctx["circuit"]["id"])["status"] == "UNDER_TEST"


class TestEvaluationRole:
    def test_technician_cannot_evaluate(self, api):
        """PRD §2.1: "`FieldTechnician` — operates the test set under
        supervision; appends test readings and nothing else."
        PRD §2.1: "Once authenticated, the role must be among the roles
        allowed for the specific endpoint; otherwise the request is rejected
        with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/technician_cannot_evaluate
        """
        ctx = setup_job_in_progress(circuit_ref="CKT-R2")
        series = energize_series(create_series(ctx["job"]["id"])["id"])
        log_vlf_steps(series["id"], (4.0, 4.0, 4.0))
        resp = api.evaluate_series(series["id"], TECHNICIAN)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert validate_success(api.get_test_series(series["id"], SUPERVISOR))["status"] == "LOGGING", (
            "the first reading moved the series ENERGIZING → LOGGING (PRD §3.6)"
        )
