"""Drying sessions: moisture projection, curve hours, redry loop, lab
confirmation boundary, crack-risk gate, and the packaging hand-off gate."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_run,
    drying_session_for_run,
    get_drying_session,
    get_run,
    packaging_job_for_run,
    set_clock,
    setup_run_in_drying,
    setup_scheduled_run,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

TECH = TEST_USERS["qa_technician_headers"]
OP = TEST_USERS["production_operator_headers"]


def test_drying_finish_before_required_hours(api):
    """PRD: "Finishing a session — again a `ProductionOperator` action —
    requires elapsed hours of at least `required_hours`, failing with
    `ERR_DRYING_INCOMPLETE` otherwise"
    PRD: "The `STANDARD` curve runs stages of 6, 8, and 4 hours removing 0.30,
    0.50, and 0.20 of the gap respectively — 18 hours in total."

    Design: Corner/state_machines/drying_finish_before_required_hours
    """
    sc = setup_run_in_drying(contract_code="C-DF")
    session = sc["session"]
    assert session["required_hours"] == 18

    set_clock("2026-08-10T06:00:00Z")
    resp = api.finish_drying_session(session["id"], OP)
    validate_error(resp, ApiErrorId.ERR_DRYING_INCOMPLETE)

    after = get_drying_session(session["id"])
    assert after["status"] == "IN_PROGRESS", "unchanged"


def test_inline_projection_piecewise_stage_values(api):
    """PRD: "the projected moisture is the initial moisture minus the
    initial-minus-target gap multiplied by the sum of the fraction removed by
    all completed stages plus the current stage's fraction prorated by how far
    elapsed time has advanced through the current stage"
    PRD: "Elapsed time exactly equal to a stage boundary counts as that stage
    complete."
    PRD: "Once elapsed time reaches `required_hours`, the projection floors at
    the target, and in all cases the projection never reads below the target."

    Design: Corner/calculations/inline_projection_piecewise_stage_values
    """
    sc = setup_run_in_drying(contract_code="C-INL")  # STANDARD, 28.0 -> 12.5
    session = sc["session"]

    set_clock("2026-08-10T06:00:00Z")
    r6 = validate_success(api.record_inline_reading(session["id"], OP))
    assert r6["latest_inline_moisture_pct"] == pytest.approx(23.35), (
        "stage-1 boundary: 28.0 - 15.5*0.30"
    )

    set_clock("2026-08-10T14:00:00Z")
    r14 = validate_success(api.record_inline_reading(session["id"], OP))
    assert r14["latest_inline_moisture_pct"] == pytest.approx(15.6), (
        "stage-2 boundary: 28.0 - 15.5*0.80"
    )

    set_clock("2026-08-10T18:00:00Z")
    r18 = validate_success(api.record_inline_reading(session["id"], OP))
    assert r18["latest_inline_moisture_pct"] == pytest.approx(12.5), (
        "projection floors at target at total required hours"
    )


def test_low_temp_curve_requires_36_hours(api):
    """PRD: "`LOW_TEMP` runs 9, 18, and 9 hours removing 0.25, 0.45, and 0.30
    — 36 hours total."
    PRD: "requires elapsed hours of at least `required_hours`, failing with
    `ERR_DRYING_INCOMPLETE` otherwise"

    Design: Corner/calculations/low_temp_curve_requires_36_hours
    """
    sc = setup_run_in_drying(
        contract_code="C-LT",
        recipe_overrides={"recipe_name": "Penne LT", "drying_curve": "LOW_TEMP"},
        scheduled_end="2026-08-13T00:00:00Z",
    )
    session = sc["session"]
    assert session["required_hours"] == 36

    set_clock("2026-08-10T18:00:00Z")
    resp = api.finish_drying_session(session["id"], OP)
    validate_error(resp, ApiErrorId.ERR_DRYING_INCOMPLETE)

    set_clock("2026-08-11T12:00:00Z")
    finished = validate_success(api.finish_drying_session(session["id"], OP))
    assert finished["status"] == "AWAITING_LAB"
    assert finished["required_hours"] == 36


def test_crack_risk_high_temp_conditional_gate(api):
    """PRD: "If the recipe's `drying_curve` is `HIGH_TEMP` and the supplied
    initial moisture exceeds 32.0, the hop is rejected with `ERR_CRACK_RISK`"
    PRD: "`HIGH_TEMP` runs 3, 4, and 2 hours removing 0.50, 0.35, and 0.15 — 9
    hours total."

    Design: Corner/calculations/crack_risk_high_temp_conditional_gate
    """
    sc = setup_scheduled_run(
        contract_code="C-CRK",
        recipe_overrides={"recipe_name": "Penne CRK", "drying_curve": "HIGH_TEMP"},
    )
    set_clock("2026-08-10T00:00:00Z")
    advance_run(sc["run"]["id"])
    advance_run(sc["run"]["id"])  # EXTRUDING

    resp = api.advance_run(sc["run"]["id"], {"initial_moisture_pct": 33.0}, OP)
    validate_error(resp, ApiErrorId.ERR_CRACK_RISK)
    assert get_run(sc["run"]["id"])["production_status"] == "EXTRUDING"

    advance_run(sc["run"]["id"], {"initial_moisture_pct": 31.0})
    run = get_run(sc["run"]["id"])
    assert run["production_status"] == "DRYING"
    session = drying_session_for_run(sc["run"]["id"])
    assert session["required_hours"] == 9, "HIGH_TEMP curve total"


class TestRedryLoopExtendsRequiredHours:
    def test_redry_grows_required_hours_and_guards_finish(self, api):
        """PRD: "a `ProductionOperator` may send it back to `IN_PROGRESS` via
        redry, which increments `redry_count`, adds 4 remedial hours to
        `required_hours`, and leaves the original `drying_started_at` untouched
        so elapsed time keeps accruing from the session's first start."
        PRD: "a value above target moves it to `FAILED`"

        Design: Difficulty/non_linear_state_machine/drying_session_redry_loop_extends_required_hours
        """
        sc = setup_run_in_drying(contract_code="C-RDR")
        session = sc["session"]

        set_clock("2026-08-10T18:00:00Z")
        finished = validate_success(api.finish_drying_session(session["id"], OP))
        assert finished["status"] == "AWAITING_LAB", "elapsed 18h == required 18h inclusive"

        failed = validate_success(api.submit_drying_lab_results(
            session["id"], {"lab_moisture_pct": 13.0}, TECH))
        assert failed["status"] == "FAILED", "13.0 > 12.5"

        redried = validate_success(api.redry_session(session["id"], OP))
        assert redried["status"] == "IN_PROGRESS"
        assert redried["redry_count"] == 1
        assert redried["required_hours"] == 22, "18 + 4 remedial hours"

        set_clock("2026-08-10T20:00:00Z")
        resp = api.finish_drying_session(session["id"], OP)
        validate_error(resp, ApiErrorId.ERR_DRYING_INCOMPLETE)

    def test_finish_at_extended_hours_then_confirm(self, api):
        """PRD: "so `required_hours` is the curve total plus 4 times the redry
        count"
        PRD: "a value at or below the target (the inclusive boundary passes)
        moves the session to `CONFIRMED`, its terminal state"

        Design: Difficulty/non_linear_state_machine/drying_session_redry_loop_extends_required_hours
        """
        sc = setup_run_in_drying(contract_code="C-RDR2")
        session = sc["session"]

        set_clock("2026-08-10T18:00:00Z")
        validate_success(api.finish_drying_session(session["id"], OP))
        validate_success(api.submit_drying_lab_results(
            session["id"], {"lab_moisture_pct": 13.0}, TECH))
        validate_success(api.redry_session(session["id"], OP))

        set_clock("2026-08-10T22:00:00Z")
        finished = validate_success(api.finish_drying_session(session["id"], OP))
        assert finished["status"] == "AWAITING_LAB", "elapsed 22h == extended 22h"

        confirmed = validate_success(api.submit_drying_lab_results(
            session["id"], {"lab_moisture_pct": 12.5}, TECH))
        assert confirmed["status"] == "CONFIRMED"


class TestDryingLabMoistureExactTarget:
    def _session_awaiting_lab(self, api, code):
        sc = setup_run_in_drying(contract_code=code)
        set_clock("2026-08-10T18:00:00Z")
        validate_success(api.finish_drying_session(sc["session"]["id"], OP))
        return sc

    def test_lab_exactly_at_target_confirms(self, api):
        """PRD: "a value at or below the target (the inclusive boundary passes)
        moves the session to `CONFIRMED`, its terminal state"
        PRD: "Either way `latest_lab_moisture_pct` is recorded."

        Design: Difficulty/boundary_precision_check/drying_lab_moisture_exact_target_passes
        """
        sc = self._session_awaiting_lab(api, "C-BM")
        confirmed = validate_success(api.submit_drying_lab_results(
            sc["session"]["id"], {"lab_moisture_pct": 12.5}, TECH))
        assert confirmed["status"] == "CONFIRMED", "12.5 <= 12.5 inclusive boundary"
        assert confirmed["latest_lab_moisture_pct"] == 12.5

    def test_lab_one_tick_above_target_fails(self, api):
        """PRD: "a value above target moves it to `FAILED`"
        PRD: "Either way `latest_lab_moisture_pct` is recorded."

        Design: Difficulty/boundary_precision_check/drying_lab_moisture_exact_target_passes
        """
        sc = self._session_awaiting_lab(api, "C-BM2")
        failed = validate_success(api.submit_drying_lab_results(
            sc["session"]["id"], {"lab_moisture_pct": 12.6}, TECH))
        assert failed["status"] == "FAILED"
        assert failed["latest_lab_moisture_pct"] == 12.6


class TestPackagingGateRequiresDryingConfirmed:
    def test_awaiting_lab_blocks_then_confirmed_unlocks(self, api):
        """PRD: "The hop from `DRYING` to `PACKAGING` requires the run's drying
        session to have reached `CONFIRMED` (`ERR_INVALID_STATE`)"
        PRD: "The run records the yield and a `PackagingJob` is created in
        `CREATED`"

        Design: Difficulty/cross_entity_state_dependency/run_packaging_gate_requires_drying_confirmed
        """
        sc = setup_run_in_drying(contract_code="C-XD")
        set_clock("2026-08-10T18:00:00Z")
        validate_success(api.finish_drying_session(sc["session"]["id"], OP))

        resp = api.advance_run(sc["run"]["id"], {"actual_yield_kg": 400.0}, OP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        validate_success(api.submit_drying_lab_results(
            sc["session"]["id"], {"lab_moisture_pct": 12.0}, TECH))
        run = advance_run(sc["run"]["id"], {"actual_yield_kg": 400.0})
        assert run["production_status"] == "PACKAGING"

        job = packaging_job_for_run(sc["run"]["id"])
        assert job["status"] == "CREATED"

    def test_in_progress_session_also_blocks(self, api):
        """PRD: "The hop from `DRYING` to `PACKAGING` requires the run's drying
        session to have reached `CONFIRMED` (`ERR_INVALID_STATE`)"

        Design: Difficulty/cross_entity_state_dependency/run_packaging_gate_requires_drying_confirmed
        """
        sc = setup_run_in_drying(contract_code="C-XD2")
        assert sc["session"]["status"] == "IN_PROGRESS"

        resp = api.advance_run(sc["run"]["id"], {"actual_yield_kg": 400.0}, OP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_run(sc["run"]["id"])["production_status"] == "DRYING"
