"""Fault records: pinpoint dual velocity variants, corridor geometry, and the
warranty reopen cycle (PRD §3.7)."""
import pytest

from test_helpers import (
    TEST_USERS,
    validate_success,
    setup_job_in_progress,
    setup_fault_closed_verified,
    setup_retest_accepted,
    create_fail_series_with_fault,
    pinpoint_fault,
    get_fault,
    get_circuit,
    accept_splice,
)

SUPERVISOR = TEST_USERS["test_supervisor_headers"]


def _suspected_fault(circuit_ref, calibrated_velocity_factor=None):
    ctx = setup_job_in_progress(
        circuit_ref=circuit_ref, length_m=2000, approved_budget_cents=900000,
        calibrated_velocity_factor=calibrated_velocity_factor,
    )
    series, fault_id = create_fail_series_with_fault(ctx["job"]["id"])
    ctx["series"] = series
    ctx["fault_id"] = fault_id
    return ctx


class TestPinpointDualVariants:
    def test_standard_variant_distances(self, api):
        """PRD §3.7: "the two genuinely differ, so on a `KV_15` circuit a
        twenty-microsecond trace yields 1,560.0 metres at the standard factor
        against 1,500.0 metres at a calibrated factor of 0.50."

        Design: Difficulty/dual_variant_calc/fault_distance_standard_vs_calibrated_velocity
        """
        ctx = _suspected_fault("CKT-DV2", calibrated_velocity_factor=0.50)
        fault = pinpoint_fault(ctx["fault_id"], trace_time_us=20.0,
                               pinpoint_method="PULSE_ECHO",
                               use_calibrated_velocity=False)
        assert fault["pinpointed_distance_m"] == 1560.0
        assert fault["alternate_distance_m"] == 1500.0
        assert fault["velocity_factor_used"] == 0.52

    def test_corridor_built_symmetrically_around_selected_distance(self, api):
        """PRD §3.7: "The dig corridor is then built symmetrically: its
        half-width is the larger of 5.0 metres and ten percent of the
        pinpointed distance rounded half-up to one-tenth of a metre, and
        `corridor_start_m` and `corridor_end_m` are the pinpointed distance
        minus and plus that half-width respectively". Pinpointing "moves the
        fault to `PINPOINTED`."

        Design: Difficulty/dual_variant_calc/fault_distance_standard_vs_calibrated_velocity
        """
        ctx = _suspected_fault("CKT-DV2", calibrated_velocity_factor=0.50)
        fault = pinpoint_fault(ctx["fault_id"], trace_time_us=20.0,
                               pinpoint_method="PULSE_ECHO",
                               use_calibrated_velocity=False)
        # half-width = max(5.0, 0.10 * 1560.0 = 156.0) = 156.0
        assert fault["corridor_start_m"] == 1404.0
        assert fault["corridor_end_m"] == 1716.0
        assert fault["status"] == "PINPOINTED"

    def test_calibrated_variant_selected_when_flag_true(self, api):
        """PRD §3.7: "The selected factor is the calibrated one when
        `use_calibrated_velocity` is true and the standard one otherwise;
        `velocity_factor_used` records which factor was actually applied,
        `pinpointed_distance_m` holds the selected-variant distance, and
        `alternate_distance_m` holds the distance under the other variant".

        Design: Difficulty/dual_variant_calc/fault_distance_standard_vs_calibrated_velocity
        """
        ctx = _suspected_fault("CKT-DV2", calibrated_velocity_factor=0.50)
        fault = pinpoint_fault(ctx["fault_id"], trace_time_us=20.0,
                               pinpoint_method="PULSE_ECHO",
                               use_calibrated_velocity=True)
        assert fault["pinpointed_distance_m"] == 1500.0
        assert fault["alternate_distance_m"] == 1560.0
        assert fault["velocity_factor_used"] == 0.50
        # half-width = max(5.0, 150.0) = 150.0
        assert fault["corridor_start_m"] == 1350.0
        assert fault["corridor_end_m"] == 1650.0

    def test_corridor_minimum_half_width_clamps(self, api):
        """PRD §3.7: "its half-width is the larger of 5.0 metres and ten
        percent of the pinpointed distance rounded half-up to one-tenth of a
        metre". A 0.5 us trace pinpoints at 0.52 x 300 x 0.5 / 2 = 39.0 m;
        ten percent (3.9 m) is below the 5.0 m floor.

        Design: Corner/calculations/corridor_min_half_width_applies
        """
        ctx = setup_job_in_progress(circuit_ref="CKT-C6")
        _, fault_id = create_fail_series_with_fault(ctx["job"]["id"])
        fault = pinpoint_fault(fault_id, trace_time_us=0.5,
                               pinpoint_method="PULSE_ECHO")
        assert fault["pinpointed_distance_m"] == 39.0
        assert fault["corridor_start_m"] == 34.0
        assert fault["corridor_end_m"] == 44.0


class TestReopenCycle:
    def test_reopen_clears_closure_and_restores_counters(self, api):
        """PRD §3.7: "reopening clears `closed_at` to null, increments
        `unresolved_fault_count` by one, recomputes
        `resolved_fault_count_24m`, and lands the fault in `REOPENED`, from
        which the pinpoint-excavate-repair-retest loop runs again."

        Design: Difficulty/non_linear_state_machine/fault_reopen_cycle_returns_through_pinpoint
        """
        ctx = setup_fault_closed_verified(circuit_ref="CKT-NL1")
        fault = validate_success(api.reopen_fault(ctx["fault_id"], SUPERVISOR))
        assert fault["status"] == "REOPENED"
        assert fault["closed_at"] is None
        circuit = get_circuit(ctx["circuit"]["id"])
        assert circuit["unresolved_fault_count"] == 1
        assert circuit["resolved_fault_count_24m"] == 0

    def test_reopened_fault_repinpointed_with_recomputed_corridor(self, api):
        """PRD §3.7: "Pinpointing is the `FaultCrewLead`'s craft and is
        available from `SUSPECTED` — and, for warranty work, from `REOPENED`,
        where it recomputes everything." A 10.0 us trace on `KV_15`
        pinpoints at 0.52 x 300 x 10.0 / 2 = 780.0 m with a 78.0 m half-width.

        Design: Difficulty/non_linear_state_machine/fault_reopen_cycle_returns_through_pinpoint
        """
        ctx = setup_fault_closed_verified(circuit_ref="CKT-NL1")
        validate_success(api.reopen_fault(ctx["fault_id"], SUPERVISOR))
        fault = pinpoint_fault(ctx["fault_id"], trace_time_us=10.0,
                               pinpoint_method="ARC_REFLECTION")
        assert fault["status"] == "PINPOINTED"
        assert fault["pinpointed_distance_m"] == 780.0
        assert fault["corridor_start_m"] == 702.0
        assert fault["corridor_end_m"] == 858.0


class TestCloseReopenConservation:
    def test_close_then_reopen_conserves_unresolved_count(self, api):
        """PRD §3.7: "Closure is a rich event: `closed_at` is set to the
        logical clock, the circuit's `unresolved_fault_count` is decremented
        by one, `resolved_fault_count_24m` is recomputed, the circuit's
        `splice_count` is incremented by one" — and reopening "increments
        `unresolved_fault_count` by one, recomputes
        `resolved_fault_count_24m`", restoring the pre-close count.

        Design: Difficulty/compensating_invariant/fault_close_reopen_conserves_unresolved_count
        """
        ctx = setup_retest_accepted(circuit_ref="CKT-CI2")
        before = get_circuit(ctx["circuit"]["id"])
        assert before["unresolved_fault_count"] == 1
        assert before["resolved_fault_count_24m"] == 0

        accept_splice(ctx["splice"]["id"])
        closed = get_circuit(ctx["circuit"]["id"])
        assert closed["unresolved_fault_count"] == 0
        assert closed["resolved_fault_count_24m"] == 1

        validate_success(api.reopen_fault(ctx["fault_id"], SUPERVISOR))
        after = get_circuit(ctx["circuit"]["id"])
        assert after["unresolved_fault_count"] == 1, (
            "the close/reopen pair conserves the pre-close count"
        )
        assert after["resolved_fault_count_24m"] == 0

    def test_close_sets_closed_at_and_reopen_clears_it(self, api):
        """PRD §3.7: "`closed_at` is set to the logical clock" at closure,
        and "reopening clears `closed_at` to null, increments
        `unresolved_fault_count` by one, recomputes
        `resolved_fault_count_24m`, and lands the fault in `REOPENED`, from
        which the pinpoint-excavate-repair-retest loop runs again."

        Design: Difficulty/compensating_invariant/fault_close_reopen_conserves_unresolved_count
        """
        ctx = setup_retest_accepted(circuit_ref="CKT-CI2")
        accept_splice(ctx["splice"]["id"])
        closed_fault = get_fault(ctx["fault_id"])
        assert closed_fault["status"] == "CLOSED_VERIFIED"
        assert closed_fault["closed_at"] is not None

        reopened = validate_success(api.reopen_fault(ctx["fault_id"], SUPERVISOR))
        assert reopened["status"] == "REOPENED"
        assert reopened["closed_at"] is None
