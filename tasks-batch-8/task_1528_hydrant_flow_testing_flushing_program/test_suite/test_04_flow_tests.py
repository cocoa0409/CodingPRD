"""Fire-flow testing: hydraulic formula, classification boundary, dual
provisional/approved reads, window adjacency, temporal gates, and review."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    assert_flow_test,
    api_client,
    TEST_USERS,
    make_supervisor_headers,
    create_program,
    create_zone,
    create_hydrant,
    create_flow_test_payload,
    create_scheduled_flow_test,
    create_submitted_flow_test,
    create_approved_flow_test,
    submit_flow_results,
    review_flow_test,
    set_clock,
    get_hydrant,
    tag_hydrant_out,
    setup_program_zone_hydrant,
)

ADMIN = TEST_USERS["admin_headers"]
OP1 = TEST_USERS["operator_headers"]
SUP1 = TEST_USERS["supervisor_headers"]


class TestFlowFormula:
    def test_flow_at_20psi_three_input_exponent_values(self, api):
        """PRD §3.3: "The pitot flow in gallons per minute is the constant
        29.83 multiplied by the hydrant's `discharge_coefficient`, multiplied
        by the hydrant's `outlet_diameter_in` raised to the second power,
        multiplied by the square root of `pitot_psi`."
        PRD §3.3: "Then `flow_at_20psi_gpm` is the unrounded Q20 rounded half
        up to a whole number of gallons per minute. Rounding happens exactly
        once at the end of this pipeline; an implementation that rounds pitot
        flow first and feeds the rounded value into Q20 is non-conformant."

        Design: Difficulty/combinatorial_formula/flow_at_20psi_three_input_exponent
        """
        program, zone, hydrant = setup_program_zone_hydrant(
            hydrant_overrides={"required_fire_flow_gpm": 1671}
        )
        ft = create_scheduled_flow_test(hydrant["id"])
        set_clock("2026-08-02T10:30:00Z")
        result = submit_flow_results(ft["id"], static_psi=80, residual_psi=40, pitot_psi=64)
        assert_flow_test(result)
        assert result["pitot_flow_gpm"] == pytest.approx(1342.35, abs=0.005), (
            f"pitot_flow_gpm must be 1342.35, got {result['pitot_flow_gpm']}"
        )
        assert result["flow_at_20psi_gpm"] == 1671, (
            f"flow_at_20psi_gpm must be 1671, got {result['flow_at_20psi_gpm']}"
        )

    def test_flow_at_20psi_three_input_exponent_classification(self, api):
        """PRD §3.3: "The test's `classification` is then set to `PASS` when
        `flow_at_20psi_gpm` is at least the hydrant's `required_fire_flow_gpm`,
        and to `FAIL` otherwise."

        Design: Difficulty/combinatorial_formula/flow_at_20psi_three_input_exponent
        """
        program, zone, hydrant = setup_program_zone_hydrant(
            hydrant_overrides={"required_fire_flow_gpm": 1671}
        )
        ft = create_scheduled_flow_test(hydrant["id"])
        set_clock("2026-08-02T10:30:00Z")
        result = submit_flow_results(ft["id"], static_psi=80, residual_psi=40, pitot_psi=64)
        assert result["classification"] == "PASS", (
            f"1671 >= required 1671 must classify PASS, got {result['classification']}"
        )
        assert result["status"] == "RESULTS_SUBMITTED"


class TestProvisionalVsApproved:
    def test_hydrant_fire_flow_provisional_vs_approved_split(self, api):
        """PRD §3.3: "`provisional_fire_flow_gpm` is the field reading that
        operations consult: it considers tests in either `RESULTS_SUBMITTED` or
        `APPROVED` and picks the most recent. `approved_fire_flow_gpm` is the
        regulatory reading that ISO scoring consults: it considers only
        `APPROVED` tests, so identical underlying data yields a different — and
        possibly null — value whenever the latest test has not yet been
        reviewed."

        Design: Difficulty/dual_variant_calc/hydrant_fire_flow_provisional_vs_approved
        """
        program, zone, hydrant = setup_program_zone_hydrant(
            hydrant_overrides={"hydrant_number": "H-100"}
        )
        ft1 = create_approved_flow_test(
            hydrant["id"],
            window_start="2026-08-02T10:00:00Z", window_end="2026-08-02T11:00:00Z",
            static_psi=80, residual_psi=40, pitot_psi=64,
        )
        ft2 = create_submitted_flow_test(
            hydrant["id"],
            clock_inside="2026-08-03T10:30:00Z",
            window_start="2026-08-03T10:00:00Z", window_end="2026-08-03T11:00:00Z",
            static_psi=90, residual_psi=50, pitot_psi=49,
        )
        after = get_hydrant(hydrant["id"])
        assert after["provisional_fire_flow_gpm"] == 1589, (
            f"provisional must be the latest RESULTS_SUBMITTED test's 1589, "
            f"got {after['provisional_fire_flow_gpm']}"
        )
        assert after["approved_fire_flow_gpm"] == 1671, (
            f"approved must be the latest APPROVED test's 1671, "
            f"got {after['approved_fire_flow_gpm']}"
        )

    def test_hydrant_fire_flow_provisional_vs_approved_test_values(self, api):
        """PRD §3.3: "Then compute the unrounded Q20 by multiplying the
        unrounded pitot flow by the quantity: the ratio of `static_psi` minus
        20 to `static_psi` minus `residual_psi`, that ratio raised to the power
        0.54."
        PRD §3.3: "The stored `pitot_flow_gpm` is this value rounded half up to
        2 decimal places."

        Design: Difficulty/dual_variant_calc/hydrant_fire_flow_provisional_vs_approved
        """
        program, zone, hydrant = setup_program_zone_hydrant(
            hydrant_overrides={"hydrant_number": "H-100"}
        )
        create_approved_flow_test(
            hydrant["id"],
            window_start="2026-08-02T10:00:00Z", window_end="2026-08-02T11:00:00Z",
            static_psi=80, residual_psi=40, pitot_psi=64,
        )
        ft2 = create_submitted_flow_test(
            hydrant["id"],
            clock_inside="2026-08-03T10:30:00Z",
            window_start="2026-08-03T10:00:00Z", window_end="2026-08-03T11:00:00Z",
            static_psi=90, residual_psi=50, pitot_psi=49,
        )
        assert ft2["pitot_flow_gpm"] == pytest.approx(1174.56, abs=0.005), (
            f"FT2 pitot_flow_gpm must be 1174.56, got {ft2['pitot_flow_gpm']}"
        )
        assert ft2["flow_at_20psi_gpm"] == 1589, (
            f"FT2 flow_at_20psi_gpm must be 1589, got {ft2['flow_at_20psi_gpm']}"
        )
        assert ft2["status"] == "RESULTS_SUBMITTED"


class TestClassificationBoundary:
    def test_flow_pass_exact_threshold_boundary_passes(self, api):
        """PRD §3.3: "The test's `classification` is then set to `PASS` when
        `flow_at_20psi_gpm` is at least the hydrant's `required_fire_flow_gpm`,
        and to `FAIL` otherwise."

        Design: Difficulty/boundary_precision_check/flow_pass_exact_threshold_boundary
        """
        program, zone, hydrant = setup_program_zone_hydrant(
            hydrant_overrides={"hydrant_number": "H-A", "required_fire_flow_gpm": 1671}
        )
        ft = create_scheduled_flow_test(hydrant["id"])
        set_clock("2026-08-02T10:30:00Z")
        result = submit_flow_results(ft["id"], static_psi=80, residual_psi=40, pitot_psi=64)
        assert result["flow_at_20psi_gpm"] == 1671
        assert result["classification"] == "PASS", (
            f"equality with required_fire_flow_gpm satisfies 'at least' and must PASS, "
            f"got {result['classification']}"
        )

    def test_flow_pass_exact_threshold_boundary_fails_one_above(self, api):
        """PRD §3.3: "The test's `classification` is then set to `PASS` when
        `flow_at_20psi_gpm` is at least the hydrant's `required_fire_flow_gpm`,
        and to `FAIL` otherwise."

        Design: Difficulty/boundary_precision_check/flow_pass_exact_threshold_boundary
        """
        program, zone, hydrant = setup_program_zone_hydrant(
            hydrant_overrides={"hydrant_number": "H-B", "required_fire_flow_gpm": 1672}
        )
        ft = create_scheduled_flow_test(hydrant["id"])
        set_clock("2026-08-02T10:30:00Z")
        result = submit_flow_results(ft["id"], static_psi=80, residual_psi=40, pitot_psi=64)
        assert result["flow_at_20psi_gpm"] == 1671
        assert result["classification"] == "FAIL", (
            f"1671 < required 1672 must classify FAIL, got {result['classification']}"
        )


class TestWindowAdjacency:
    def test_flow_test_half_open_window_adjacency_allowed(self, api):
        """PRD §3.3: "The window is a half-open interval — a test whose
        `window_end` equals another scheduled test's `window_start` does not
        overlap it."

        Design: Difficulty/resource_temporal_overlap/flow_test_half_open_window_adjacency
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        create_scheduled_flow_test(hydrant["id"], "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z")

        resp = api.create_flow_test(
            create_flow_test_payload(
                hydrant["id"],
                window_start="2026-08-02T11:00:00Z", window_end="2026-08-02T12:00:00Z",
            ),
            OP1,
        )
        adjacent = validate_success(resp, expected_status=201)
        assert adjacent["status"] == "SCHEDULED", (
            "a window starting exactly at the existing window's end must be allowed"
        )

    def test_flow_test_half_open_window_overlap_rejected(self, api):
        """PRD §3.3: "The new window must not overlap any other `SCHEDULED`
        flow test on the same hydrant under half-open arithmetic; touching
        endpoints are allowed, and any true overlap is rejected with
        `ERR_FLOW_TEST_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/flow_test_half_open_window_adjacency
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        create_scheduled_flow_test(hydrant["id"], "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z")

        resp = api.create_flow_test(
            create_flow_test_payload(
                hydrant["id"],
                window_start="2026-08-02T10:30:00Z", window_end="2026-08-02T11:30:00Z",
            ),
            OP1,
        )
        validate_error(resp, ApiErrorId.ERR_FLOW_TEST_WINDOW_OVERLAP, 409)


class TestResultsStateGate:
    def test_flowtest_results_from_cancelled_rejected(self, api):
        """PRD §3.3: "The test must be `SCHEDULED` (otherwise
        `ERR_FLOW_TEST_NOT_SCHEDULED`)."
        PRD §3.3: "A test still in `SCHEDULED` can be cancelled outright by a
        `FieldOperator` — any other status yields `ERR_FLOW_TEST_NOT_SCHEDULED`
        — which moves it to `CANCELLED` with `cancel_reason` of
        `OPERATOR_CANCEL`."

        Design: Corner/state_machines/flowtest_results_from_cancelled_rejected
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        ft = create_scheduled_flow_test(hydrant["id"])
        cancelled = validate_success(api.cancel_flow_test(ft["id"], OP1))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancel_reason"] == "OPERATOR_CANCEL"

        set_clock("2026-08-02T10:30:00Z")
        resp = api.submit_flow_test_results(
            ft["id"], {"static_psi": 80, "residual_psi": 40, "pitot_psi": 64}, OP1
        )
        validate_error(resp, ApiErrorId.ERR_FLOW_TEST_NOT_SCHEDULED, 409)

        after = validate_success(api.get_flow_test(ft["id"], OP1))
        assert after["status"] == "CANCELLED"
        assert after.get("flow_at_20psi_gpm") is None, (
            "a rejected submission must compute nothing"
        )


class TestMissedAndReschedule:
    def test_flowtest_missed_on_sweep_then_reschedule(self, api):
        """PRD §3.9: "Second, the sweep expires stale flow tests: every
        `SCHEDULED` flow test on a hydrant of the swept program whose
        `window_end` is before the current logical clock moves to `MISSED`."
        PRD §3.3: "A test in `REJECTED` or `MISSED` can be rescheduled by a
        `FieldOperator` supplying a new `window_start` and `window_end`;
        anything other than `REJECTED` or `MISSED` is rejected with
        `ERR_FLOW_TEST_NOT_RESCHEDULABLE`, and the new window must not overlap
        the hydrant's other `SCHEDULED` tests under the same half-open rule
        (`ERR_FLOW_TEST_WINDOW_OVERLAP`). A successful reschedule moves the
        test back to `SCHEDULED` with the new window."
        PRD §3.9: "The sweep response reports `missed_flow_tests`,
        `escalated_outages`, and `tier_recomputed_hydrants` — the three counts
        an operations lead reviews after each run."

        Design: Corner/state_machines/flowtest_missed_on_sweep_then_reschedule
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        ft = create_scheduled_flow_test(hydrant["id"], "2026-08-02T10:00:00Z",
                                        "2026-08-02T11:00:00Z")
        set_clock("2026-08-05T00:00:00Z")
        sweep = validate_success(api.sweep_program(program["id"], ADMIN))
        assert sweep["missed_flow_tests"] == 1, (
            f"sweep must report exactly 1 missed flow test, got {sweep['missed_flow_tests']}"
        )
        missed = validate_success(api.get_flow_test(ft["id"], OP1))
        assert missed["status"] == "MISSED"

        rescheduled = validate_success(api.reschedule_flow_test(
            ft["id"],
            {"window_start": "2026-08-06T10:00:00Z", "window_end": "2026-08-06T11:00:00Z"},
            OP1,
        ))
        assert rescheduled["status"] == "SCHEDULED"
        assert rescheduled["window_start"].startswith("2026-08-06T10:00"), (
            f"reschedule must install the new window, got {rescheduled['window_start']}"
        )


class TestRejectRecomputesProvisional:
    def test_rejected_flowtest_recomputes_provisional(self, api):
        """PRD §3.3: "On `REJECT`, the test moves to `REJECTED`,
        `reviewed_by_user_id` is recorded, and the hydrant's
        `provisional_fire_flow_gpm` is recomputed from the hydrant's remaining
        `RESULTS_SUBMITTED` or `APPROVED` tests — taking the most recent by
        results submission time, with ties broken by `created_at` ascending —
        and set to null when no qualifying test remains, again incrementing the
        hydrant's version."

        Design: Corner/state_machines/rejected_flowtest_recomputes_provisional
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        ft1 = create_submitted_flow_test(
            hydrant["id"],
            clock_inside="2026-08-02T10:30:00Z",
            window_start="2026-08-02T10:00:00Z", window_end="2026-08-02T11:00:00Z",
            static_psi=80, residual_psi=40, pitot_psi=64,
        )
        ft2 = create_submitted_flow_test(
            hydrant["id"],
            clock_inside="2026-08-03T10:30:00Z",
            window_start="2026-08-03T10:00:00Z", window_end="2026-08-03T11:00:00Z",
            static_psi=90, residual_psi=50, pitot_psi=49,
        )
        assert get_hydrant(hydrant["id"])["provisional_fire_flow_gpm"] == 1589

        rejected = review_flow_test(ft2["id"], decision="REJECT", headers=SUP1)
        assert rejected["status"] == "REJECTED"

        after = get_hydrant(hydrant["id"])
        assert after["provisional_fire_flow_gpm"] == 1671, (
            f"provisional must fall back to FT1's 1671, got {after['provisional_fire_flow_gpm']}"
        )
        assert after.get("approved_fire_flow_gpm") is None, (
            "nothing has been APPROVED, so approved_fire_flow_gpm must be null"
        )


class TestResultsTemporalGate:
    def test_flowtest_results_before_window_rejected(self, api):
        """PRD §3.3: "The logical clock must fall within the scheduled window —
        before `window_start` yields `ERR_FLOW_TEST_WINDOW_NOT_STARTED`, after
        `window_end` yields `ERR_FLOW_TEST_WINDOW_EXPIRED`."

        Design: Corner/validations/flowtest_results_before_window_rejected
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        ft = create_scheduled_flow_test(hydrant["id"], "2026-08-02T10:00:00Z",
                                        "2026-08-02T11:00:00Z")
        # Clock left at the default 2026-08-01T00:00:00Z, before window_start.
        resp = api.submit_flow_test_results(
            ft["id"], {"static_psi": 80, "residual_psi": 40, "pitot_psi": 64}, OP1
        )
        validate_error(resp, ApiErrorId.ERR_FLOW_TEST_WINDOW_NOT_STARTED, 409)

    def test_flowtest_results_after_window_rejected(self, api):
        """PRD §3.3: "The logical clock must fall within the scheduled window —
        before `window_start` yields `ERR_FLOW_TEST_WINDOW_NOT_STARTED`, after
        `window_end` yields `ERR_FLOW_TEST_WINDOW_EXPIRED`."

        Design: Corner/validations/flowtest_results_after_window_rejected
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        ft = create_scheduled_flow_test(hydrant["id"], "2026-08-02T10:00:00Z",
                                        "2026-08-02T11:00:00Z")
        set_clock("2026-08-02T12:00:00Z")
        resp = api.submit_flow_test_results(
            ft["id"], {"static_psi": 80, "residual_psi": 40, "pitot_psi": 64}, OP1
        )
        validate_error(resp, ApiErrorId.ERR_FLOW_TEST_WINDOW_EXPIRED, 409)


class TestPressureValidityGate:
    def test_pressure_residual_must_exceed_twenty(self, api):
        """PRD §3.3: "The pressure readings themselves must satisfy a physical
        validity gate evaluated before any arithmetic: `static_psi` must be
        strictly greater than `residual_psi`, and `residual_psi` must be
        strictly greater than 20; a violation is rejected with
        `ERR_PRESSURE_READING_INVALID` (HTTP 422)."

        Design: Corner/calculations/pressure_residual_must_exceed_twenty
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        ft = create_scheduled_flow_test(hydrant["id"])
        set_clock("2026-08-02T10:30:00Z")
        resp = api.submit_flow_test_results(
            ft["id"], {"static_psi": 80, "residual_psi": 20, "pitot_psi": 64}, OP1
        )
        validate_error(resp, ApiErrorId.ERR_PRESSURE_READING_INVALID, 422)

        after = validate_success(api.get_flow_test(ft["id"], OP1))
        assert after["status"] == "SCHEDULED", "rejected submission must not move the test"
        assert after.get("flow_at_20psi_gpm") is None

    def test_pressure_static_must_exceed_residual(self, api):
        """PRD §3.3: "The pressure readings themselves must satisfy a physical
        validity gate evaluated before any arithmetic: `static_psi` must be
        strictly greater than `residual_psi`, and `residual_psi` must be
        strictly greater than 20; a violation is rejected with
        `ERR_PRESSURE_READING_INVALID` (HTTP 422)."

        Design: Corner/calculations/pressure_static_must_exceed_residual
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        ft = create_scheduled_flow_test(hydrant["id"])
        set_clock("2026-08-02T10:30:00Z")
        resp = api.submit_flow_test_results(
            ft["id"], {"static_psi": 40, "residual_psi": 40, "pitot_psi": 64}, OP1
        )
        validate_error(resp, ApiErrorId.ERR_PRESSURE_READING_INVALID, 422)


class TestReviewSegregationOfDuties:
    def test_sod_review_own_flowtest_rejected(self, api):
        """PRD §3.3: "Review is a `UtilitySupervisor` action gated by
        segregation of duties: the reviewer's `X-User-ID` must differ from
        `recorded_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/sod_review_own_flowtest_rejected
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        ft = create_submitted_flow_test(hydrant["id"])  # recorded by op_1

        resp = api.review_flow_test(ft["id"], {"decision": "APPROVE"},
                                    make_supervisor_headers("op_1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

        after = validate_success(api.get_flow_test(ft["id"], OP1))
        assert after["status"] == "RESULTS_SUBMITTED", (
            "rejected review must leave the test RESULTS_SUBMITTED"
        )
