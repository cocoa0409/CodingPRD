"""Series verdict computation: thresholds, dual verdict bases, temperature
correction, and fault creation (PRD §3.6, §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    setup_job_in_progress,
    create_energized_series,
    create_evaluated_vlf_series,
    log_vlf_steps,
    log_vlf_pd_steps,
    evaluate_series,
    create_series,
    energize_series,
    add_reading,
    get_circuit,
)

SUPERVISOR = TEST_USERS["test_supervisor_headers"]


class TestThresholds:
    def test_tip_up_exactly_twelve_fails(self, api):
        """PRD §3.6: "otherwise `FAIL` when the difference between the step-2
        and step-0 rounded values reaches or exceeds 12.0 (the tip-up check)".

        Design: Corner/calculations/tip_up_exactly_twelve_fails
        """
        ctx = setup_job_in_progress(circuit_ref="CKT-C1")
        series = create_evaluated_vlf_series(ctx["job"]["id"], (10.0, 10.0, 22.0))
        assert series["verdict"] == "FAIL", (
            "tip-up 22.0 - 10.0 == 12.0 reaches the >= 12.0 threshold even "
            "though max 22.0 is far below 80.0"
        )
        faults = validate_success(api.list_series_faults(series["id"], SUPERVISOR))
        assert len(faults) == 1
        assert faults[0]["status"] == "SUSPECTED"

    def test_pd_at_2000_fails_despite_tan_delta_pass(self, api):
        """PRD §3.6: "The partial-discharge part, which applies to
        `VLF_WITH_PD` and `PD_MAPPING`: `FAIL` when the maximum `pd_level_pc`
        reaches or exceeds 2,000 picocoulombs; otherwise `MONITOR` when it
        reaches or exceeds 500; otherwise `PASS`."

        Design: Corner/calculations/pd_threshold_2000_boundary
        """
        ctx = setup_job_in_progress(
            circuit_ref="CKT-C2", requested_methods=["VLF_WITH_PD"],
            approved_budget_cents=900000,
        )
        series = create_energized_series(ctx["job"]["id"], "VLF_WITH_PD")
        log_vlf_pd_steps(series["id"], td=3.0, pd=2000)
        evaluated = evaluate_series(series["id"])
        assert evaluated["max_pd_pc"] == 2000
        assert evaluated["verdict"] == "FAIL", (
            "the PD part reaches 2,000 pC and dominates the tan-delta PASS"
        )

    def test_pd_just_below_2000_monitors(self, api):
        """PRD §3.6: "otherwise `MONITOR` when it reaches or exceeds 500".

        Design: Corner/calculations/pd_threshold_2000_boundary
        """
        ctx = setup_job_in_progress(
            circuit_ref="CKT-C2", requested_methods=["VLF_WITH_PD"],
            approved_budget_cents=900000,
        )
        series = create_energized_series(ctx["job"]["id"], "VLF_WITH_PD")
        log_vlf_pd_steps(series["id"], td=3.0, pd=1999.9)
        evaluated = evaluate_series(series["id"])
        assert evaluated["verdict"] == "MONITOR", "1999.9 pC lies in [500, 2000)"


class TestDualVerdictBases:
    def test_identical_readings_flip_between_bases(self, api):
        """PRD §3.6: "identical raw data can therefore flip outcomes between
        the two bases, as when a reading of 88.0 taken at 35 degrees Celsius
        corrects to 79.2."
        PRD §3.6: "The official `verdict` of the series is the
        temperature-corrected basis when the job's
        `use_temperature_correction` is true and the as-tested basis
        otherwise".

        Design: Difficulty/dual_variant_calc/verdict_temperature_correction_flips_official_verdict
        """
        ctx = setup_job_in_progress(
            circuit_ref="CKT-DV1", length_m=2000, approved_budget_cents=900000,
            use_temperature_correction=False,
        )
        series = create_evaluated_vlf_series(
            ctx["job"]["id"], (88.0, 88.0, 88.0), ambient_temp_c=35.0,
        )
        assert series["verdict_as_tested"] == "FAIL", (
            "raw rounded max 88.0 reaches the 80.0 FAIL threshold"
        )
        assert series["verdict_temperature_corrected"] == "MONITOR", (
            "k(35C) clamps to 0.9, so 88.0 corrects to 79.2, in [5.0, 80.0)"
        )
        assert series["verdict"] == "FAIL", (
            "flag false selects the as-tested basis as official"
        )

    def test_fail_official_verdict_auto_creates_fault(self, api):
        """PRD §3.6: "When the official verdict is `FAIL`, the system
        immediately creates a fault record in `SUSPECTED` for the series and
        increments the circuit's `unresolved_fault_count` by one."

        Design: Difficulty/dual_variant_calc/verdict_temperature_correction_flips_official_verdict
        """
        ctx = setup_job_in_progress(
            circuit_ref="CKT-DV1", length_m=2000, approved_budget_cents=900000,
            use_temperature_correction=False,
        )
        series = create_evaluated_vlf_series(
            ctx["job"]["id"], (88.0, 88.0, 88.0), ambient_temp_c=35.0,
        )
        assert series["verdict"] == "FAIL"
        faults = validate_success(api.list_series_faults(series["id"], SUPERVISOR))
        assert len(faults) == 1
        assert faults[0]["status"] == "SUSPECTED"
        assert get_circuit(ctx["circuit"]["id"])["unresolved_fault_count"] == 1

    def test_flag_on_selects_corrected_official_and_no_fault(self, api):
        """PRD §3.6: "The official `verdict` of the series is the
        temperature-corrected basis when the job's
        `use_temperature_correction` is true and the as-tested basis
        otherwise, and `verdict_as_tested` and
        `verdict_temperature_corrected` remain available for inspection
        regardless."

        Design: Corner/cross_cutting_layers/conditional_flag_selects_corrected_official
        """
        ctx = setup_job_in_progress(
            circuit_ref="CKT-X3", length_m=2000, approved_budget_cents=900000,
            use_temperature_correction=True,
        )
        series = create_evaluated_vlf_series(
            ctx["job"]["id"], (88.0, 88.0, 88.0), ambient_temp_c=35.0,
        )
        assert series["verdict_as_tested"] == "FAIL"
        assert series["verdict"] == "MONITOR", (
            "flag true makes the corrected basis official; MONITOR creates no fault"
        )
        faults = validate_success(api.list_series_faults(series["id"], SUPERVISOR))
        assert faults == []
        assert get_circuit(ctx["circuit"]["id"])["unresolved_fault_count"] == 0


class TestRoundingBoundary:
    def test_tan_delta_rounds_up_to_exact_fail_threshold(self, api):
        """PRD §3.6: "For the as-tested basis, each reading's `tan_delta_e3`
        is first rounded half-up to one decimal place and the rounded raw
        values are compared." and "the part verdict is `FAIL` when the maximum
        rounded tan-delta across the series' readings reaches or exceeds
        80.0". Raw 79.95 rounds half-up to exactly 80.0.

        Design: Difficulty/boundary_precision_check/tan_delta_rounds_to_exact_fail_threshold
        """
        ctx = setup_job_in_progress(circuit_ref="CKT-BP1", length_m=2000,
                                    approved_budget_cents=900000)
        series = create_evaluated_vlf_series(ctx["job"]["id"], (79.9, 79.9, 79.95))
        assert series["max_tan_delta_e3"] == 80.0
        assert series["verdict"] == "FAIL", "rounded 80.0 >= 80.0 triggers FAIL"
        faults = validate_success(api.list_series_faults(series["id"], SUPERVISOR))
        assert len(faults) == 1

    def test_tan_delta_rounds_down_and_stays_monitor(self, api):
        """PRD §3.6: "each reading's `tan_delta_e3` is first rounded half-up
        to one decimal place" — raw 79.94 rounds to 79.9, below the 80.0 FAIL
        threshold and not below the 5.0 PASS threshold, so the part verdict is
        `MONITOR`.

        Design: Difficulty/boundary_precision_check/tan_delta_rounds_to_exact_fail_threshold
        """
        ctx = setup_job_in_progress(circuit_ref="CKT-BP1", length_m=2000,
                                    approved_budget_cents=900000)
        series = create_evaluated_vlf_series(ctx["job"]["id"], (79.9, 79.9, 79.94))
        assert series["max_tan_delta_e3"] == 79.9
        assert series["verdict"] == "MONITOR"
        faults = validate_success(api.list_series_faults(series["id"], SUPERVISOR))
        assert faults == []
        assert get_circuit(ctx["circuit"]["id"])["unresolved_fault_count"] == 0


class TestManualFaultCreation:
    def test_manual_fault_on_pass_series_rejected(self, api):
        """PRD §3.7: "an engineering-judgement escalation permitted only when
        the series' verdict is `MONITOR`: a `PASS` series cannot raise a fault
        (`ERR_VERDICT_NOT_FAIL`), and a `FAIL` series already produced its
        fault automatically."

        Design: Corner/validations/verdict_not_fail_rejected
        """
        ctx = setup_job_in_progress(circuit_ref="CKT-V7")
        series = create_evaluated_vlf_series(ctx["job"]["id"], (3.0, 3.0, 3.0))
        assert series["verdict"] == "PASS"
        resp = api.create_fault({"test_series_id": series["id"]}, SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_VERDICT_NOT_FAIL)

    def test_second_fault_on_same_series_rejected(self, api):
        """PRD §3.7: "Only one fault may ever exist for a given series (else
        `ERR_FAULT_ALREADY_RECORDED`), and the verdict precondition is checked
        before the uniqueness check."

        Design: Corner/validations/fault_already_recorded_rejected
        """
        ctx = setup_job_in_progress(circuit_ref="CKT-V8")
        series = create_evaluated_vlf_series(ctx["job"]["id"], (50.0, 50.0, 50.0))
        assert series["verdict"] == "MONITOR"
        first = validate_success(
            api.create_fault({"test_series_id": series["id"]}, SUPERVISOR), 201
        )
        assert first["status"] == "SUSPECTED"
        second = api.create_fault({"test_series_id": series["id"]}, SUPERVISOR)
        validate_error(second, ApiErrorId.ERR_FAULT_ALREADY_RECORDED)
