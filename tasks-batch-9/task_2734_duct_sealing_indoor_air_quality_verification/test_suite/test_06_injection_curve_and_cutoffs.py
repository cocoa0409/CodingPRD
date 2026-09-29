"""The leakage curve: stall detection, the pause/resume cycle, the pressure cutoff
and the compensating abort."""

from test_helpers import (
    ELIGIBILITY_ELIGIBLE,
    ERR_INJECTION_PRESSURE_LIMIT,
    ERR_SAMPLE_SEQUENCE_INVALID,
    ERR_SEAL_JOB_INVALID_STATE,
    JOB_ABORTED_MANUAL,
    JOB_ABORTED_SAFETY,
    JOB_INJECTING,
    JOB_PAUSED,
    MAX_INJECTION_PA,
    PROJECT_SAFETY_HOLD,
    SEAL_STATUS_SEAL_PENDING,
    SEAL_STATUS_SEALING,
    assert_leakage_ledger,
    assert_ledger_identity,
    factories as f,
    fixtures as fx,
    seal_rate_cfm_per_min,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_stalled_run_pauses_itself_and_the_cycle_can_be_traversed_again(api):
    """A stall below half a CFM per minute pauses the run; resume and pause again and
    the loop count stays observable.

    PRD 3.6: "When the computed rate is strictly below half a CFM per minute, the
    sealant has stopped finding holes: the run is driven from `INJECTING` to
    `PAUSED`, `stall_flag` is set true and `pause_count` rises by 1." And: "Resuming
    takes no payload, moves the run from `PAUSED` back to `INJECTING`, clears
    `stall_flag` to false, and bumps `version` by 1".

    Design: Difficulty/non_linear_state_machine/seal_job_injecting_pause_resume_cycle
    """
    sc = fx.scenario_injecting_job(api)
    stored = fx.stream_samples(
        sc, samples=((1, 120.0, 0, 700.0), (2, 119.0, 120, 710.0), (3, 118.4, 240, 720.0))
    )
    assert stored[0]["seal_rate_cfm_per_min"] is None
    assert stored[1]["seal_rate_cfm_per_min"] is None
    assert stored[2]["seal_rate_cfm_per_min"] == seal_rate_cfm_per_min(120.0, 118.4, 0, 240)
    assert stored[2]["seal_rate_cfm_per_min"] == 0.40

    paused = sc.read_seal_job()
    assert paused["status"] == JOB_PAUSED
    assert paused["stall_flag"] is True
    assert paused["pause_count"] == 1
    assert paused["sample_count"] == 3
    assert paused["current_leakage_cfm"] == 118.4
    assert paused["target_reached"] is False

    resumed = validate_success(api.resume_seal_job(sc.seal_job_id, None, sc.tech_headers))
    assert resumed["status"] == JOB_INJECTING
    assert resumed["stall_flag"] is False
    assert resumed["pause_count"] == 1

    manual = validate_success(
        api.pause_seal_job(sc.seal_job_id, f.pause_payload(), sc.tech_headers)
    )
    assert manual["status"] == JOB_PAUSED
    assert manual["pause_count"] == 2

    again = validate_success(api.resume_seal_job(sc.seal_job_id, None, sc.tech_headers))
    assert again["status"] == JOB_INJECTING
    assert again["pause_count"] == 2
    assert again["stall_flag"] is False
    assert again["sample_count"] == 3
    assert again["current_leakage_cfm"] == 118.4
    assert again["target_reached"] is False

    duct_system = sc.read_duct_system()
    assert duct_system["seal_status"] == SEAL_STATUS_SEALING
    assert_leakage_ledger(duct_system, 300.00, 118.4, 181.60)
    assert_ledger_identity(duct_system)


def test_a_manual_pause_keeps_the_stall_flag_as_it_stands_and_clears_any_reason(api):
    """The hand pause is not a stall: it raises the count, leaves the flag alone and
    nulls `abort_reason`.

    PRD 3.6: "A technician may also pause a run by hand, supplying a `pause_reason`
    that is recorded on the run log; the manual pause moves the run from `INJECTING`
    to `PAUSED`, raises `pause_count` by 1, leaves `stall_flag` as it stands, and
    clears `abort_reason` to null."

    Design: Difficulty/non_linear_state_machine/seal_job_injecting_pause_resume_cycle
    """
    sc = fx.scenario_injecting_job(api)
    fx.stream_samples(
        sc, samples=((1, 120.0, 0, 700.0), (2, 119.0, 120, 710.0), (3, 118.4, 240, 720.0))
    )
    assert sc.read_seal_job()["stall_flag"] is True
    validate_success(api.resume_seal_job(sc.seal_job_id, None, sc.tech_headers))

    fourth = fx.stream_samples(sc, samples=((4, 117.0, 300, 730.0),))
    assert fourth[0]["seal_rate_cfm_per_min"] == seal_rate_cfm_per_min(
        119.0, 117.0, 120, 300
    )
    running = sc.read_seal_job()
    assert running["status"] == JOB_INJECTING
    assert running["stall_flag"] is False

    manual = validate_success(
        api.pause_seal_job(sc.seal_job_id, f.pause_payload(), sc.tech_headers)
    )
    assert manual["status"] == JOB_PAUSED
    assert manual["pause_count"] == 2
    assert manual["stall_flag"] is False
    assert manual["abort_reason"] is None

    resumed = validate_success(api.resume_seal_job(sc.seal_job_id, None, sc.tech_headers))
    assert resumed["status"] == JOB_INJECTING
    assert resumed["stall_flag"] is False
    assert resumed["pause_count"] == 2
    assert resumed["sample_count"] == 4
    assert resumed["current_leakage_cfm"] == 117.0


def test_a_seal_rate_of_exactly_half_a_cfm_per_minute_does_not_stall(api):
    """The stall boundary is strict, so exact equality keeps the run injecting.

    PRD 3.6: "That boundary is exact too — a rate of exactly 0.50 does **not**
    stall." And: "For a point whose `sample_seq` is 1 or 2,
    `seal_rate_cfm_per_min` is null."

    Design: Difficulty/boundary_precision_check/stall_rate_exact_half_cfm_per_minute_does_not_pause
    """
    sc = fx.scenario_injecting_job(api)
    stored = fx.stream_samples(
        sc, samples=((1, 120.0, 0, 700.0), (2, 119.0, 120, 710.0), (3, 118.0, 240, 720.0))
    )
    assert stored[0]["seal_rate_cfm_per_min"] is None
    assert stored[1]["seal_rate_cfm_per_min"] is None
    assert stored[2]["seal_rate_cfm_per_min"] == 0.50

    job = sc.read_seal_job()
    assert job["status"] == JOB_INJECTING
    assert job["stall_flag"] is False
    assert job["pause_count"] == 0
    assert job["sample_count"] == 3
    assert job["current_leakage_cfm"] == 118.0

    duct_system = sc.read_duct_system()
    assert duct_system["seal_status"] == SEAL_STATUS_SEALING
    assert_leakage_ledger(duct_system, 300.00, 118.0, 182.00)


def test_a_rate_a_whisker_below_the_boundary_does_stall(api):
    """Rounding half-up to two decimals is what the boundary is compared against.

    PRD 3.6: "dividing that drop by the elapsed time between the two points
    expressed in minutes ... then rounding half-up to two decimals." And: "When
    the computed rate is strictly below half a CFM per minute ... the run is driven from
    `INJECTING` to `PAUSED`, `stall_flag` is set true and `pause_count` rises by 1."

    Design: Difficulty/boundary_precision_check/stall_rate_exact_half_cfm_per_minute_does_not_pause
    """
    sc = fx.scenario_injecting_job(api)
    stored = fx.stream_samples(
        sc, samples=((1, 120.0, 0, 700.0), (2, 119.0, 120, 710.0), (3, 118.1, 240, 720.0))
    )
    assert stored[2]["seal_rate_cfm_per_min"] == seal_rate_cfm_per_min(120.0, 118.1, 0, 240)
    assert stored[2]["seal_rate_cfm_per_min"] == 0.48

    job = sc.read_seal_job()
    assert job["status"] == JOB_PAUSED
    assert job["stall_flag"] is True
    assert job["pause_count"] == 1
    assert job["current_leakage_cfm"] == 118.1


def test_aborting_a_run_by_hand_restores_the_leakage_ledger_exactly(api):
    """The abort compensates the ledger back to baseline with no residual credit.

    PRD 3.6: "The run moves to `ABORTED_MANUAL`, the duct system's `seal_status`
    returns from `SEALING` to `SEAL_PENDING`, `working_leakage_cfm25` is restored to
    `baseline_leakage_cfm25`, `sealed_leakage_reduction_cfm` returns to 0.00 so the
    ledger identity holds exactly, `active_seal_job_id` is cleared, the technician's
    `open_seal_job_count` falls by 1". PRD 2.10: "Compensation restores the identity
    exactly; there is no residual credit for a run that did not finish."

    Design: Difficulty/compensating_invariant/abort_restores_duct_leakage_ledger_identity
    """
    sc = fx.scenario_injecting_job(api)
    fx.stream_samples(
        sc, samples=((1, 300.0, 0, 700.0), (2, 200.0, 240, 710.0), (3, 120.0, 480, 720.0))
    )

    mid_run = sc.read_duct_system()
    assert_leakage_ledger(mid_run, 300.00, 120.00, 180.00)
    assert_ledger_identity(mid_run)
    assert mid_run["working_leakage_cfm25"] + mid_run["sealed_leakage_reduction_cfm"] == (
        mid_run["baseline_leakage_cfm25"]
    )

    aborted = validate_success(
        api.abort_seal_job(sc.seal_job_id, f.abort_payload(), sc.tech_headers)
    )
    assert aborted["status"] == JOB_ABORTED_MANUAL
    assert aborted["abort_reason"] == "homeowner stopped work mid-run"
    assert aborted["current_leakage_cfm"] == 120.0
    assert aborted["sample_count"] == 3

    after = sc.read_duct_system()
    assert_leakage_ledger(after, 300.00, 300.00, 0.00)
    assert_ledger_identity(after)
    assert after["seal_status"] == SEAL_STATUS_SEAL_PENDING
    assert after["active_seal_job_id"] is None
    assert after["eligibility_status"] == ELIGIBILITY_ELIGIBLE
    assert sc.read_technician()["open_seal_job_count"] == 0

    rows, meta = validate_paginated(
        api.list_leakage_samples(sc.seal_job_id, sc.tech_headers)
    )
    assert meta["total_count"] == 3
    assert [row["sample_seq"] for row in rows] == [1, 2, 3]


def test_aborting_from_a_paused_run_compensates_the_same_way(api):
    """The compensation is a property of the abort, not of the state it came from.

    PRD 3.6: "Aborting is available by hand from `SCHEDULED`, `MASKING`, `INJECTING`
    or `PAUSED` ... `working_leakage_cfm25` is restored to `baseline_leakage_cfm25`,
    `sealed_leakage_reduction_cfm` returns to 0.00 so the ledger identity holds
    exactly".

    Design: Difficulty/compensating_invariant/abort_restores_duct_leakage_ledger_identity
    """
    sc = fx.scenario_injecting_job(api)
    fx.stream_samples(
        sc, samples=((1, 300.0, 0, 700.0), (2, 200.0, 240, 710.0), (3, 120.0, 480, 720.0))
    )
    paused = validate_success(
        api.pause_seal_job(sc.seal_job_id, f.pause_payload(), sc.tech_headers)
    )
    assert paused["status"] == JOB_PAUSED
    assert sc.read_technician()["open_seal_job_count"] == 1

    aborted = validate_success(
        api.abort_seal_job(sc.seal_job_id, f.abort_payload(), sc.tech_headers)
    )
    assert aborted["status"] == JOB_ABORTED_MANUAL

    after = sc.read_duct_system()
    assert_leakage_ledger(after, 300.00, 300.00, 0.00)
    assert_ledger_identity(after)
    assert after["active_seal_job_id"] is None
    assert sc.read_technician()["open_seal_job_count"] == 0

    validate_error(
        api.resume_seal_job(sc.seal_job_id, None, sc.tech_headers),
        ERR_SEAL_JOB_INVALID_STATE,
        409,
    )


def test_curve_points_must_arrive_in_strict_sequence(api):
    """Only the next position is accepted — no gaps, no duplicates, no reordering.

    PRD 3.6: "Sequencing is strict: `sample_seq` must equal the run's current
    `sample_count` plus 1, so no out-of-order point and no duplicate point can enter
    the series, and any other value is rejected with `ERR_SAMPLE_SEQUENCE_INVALID`."

    Design: Corner/validations/leakage_sample_seq_must_equal_the_running_count_plus_one
    """
    sc = fx.scenario_injecting_job(api)
    assert sc.read_seal_job()["sample_count"] == 0

    validate_error(
        api.append_leakage_sample(
            sc.seal_job_id, f.leakage_sample_payload(2, 280.0, 60), sc.tech_headers
        ),
        ERR_SAMPLE_SEQUENCE_INVALID,
        422,
    )
    assert sc.read_seal_job()["sample_count"] == 0

    validate_success(
        api.append_leakage_sample(
            sc.seal_job_id, f.leakage_sample_payload(1, 290.0, 0), sc.tech_headers
        ),
        201,
    )
    validate_error(
        api.append_leakage_sample(
            sc.seal_job_id, f.leakage_sample_payload(1, 285.0, 30), sc.tech_headers
        ),
        ERR_SAMPLE_SEQUENCE_INVALID,
        422,
    )
    validate_error(
        api.append_leakage_sample(
            sc.seal_job_id, f.leakage_sample_payload(3, 275.0, 90), sc.tech_headers
        ),
        ERR_SAMPLE_SEQUENCE_INVALID,
        422,
    )
    validate_success(
        api.append_leakage_sample(
            sc.seal_job_id, f.leakage_sample_payload(2, 280.0, 60), sc.tech_headers
        ),
        201,
    )

    rows, meta = validate_paginated(
        api.list_leakage_samples(sc.seal_job_id, sc.tech_headers)
    )
    assert meta["total_count"] == 2
    assert [row["sample_seq"] for row in rows] == [1, 2]
    assert sc.read_seal_job()["sample_count"] == 2


def test_the_pressure_cutoff_is_exact_and_a_cut_off_run_cannot_be_resumed(api):
    """Exactly at the limit is safe; a hair above aborts the run, holds the project,
    and resume reports the cutoff rather than a state error.

    PRD 3.6: "The cutoff fires when `injection_pressure_pa` is strictly above 1000.0
    pascals ... The point itself is still accepted and stored. The boundary is exact:
    a pressure of exactly 1000.0 does **not** cut off." And: "a resume aimed at
    a run in `ABORTED_SAFETY` reports `ERR_INJECTION_PRESSURE_LIMIT` rather than a
    state error". PRD 2.12: "Every other action aimed at such a run — pausing it,
    completing it, appending a further sample to it, registering a warranty on it —
    still reports `ERR_SEAL_JOB_INVALID_STATE` at the state rung."

    Design: Corner/errors/resume_after_the_pressure_cutoff_reports_the_cutoff_not_the_state
    """
    sc = fx.scenario_injecting_job(api)
    at_limit = validate_success(
        api.append_leakage_sample(
            sc.seal_job_id,
            f.leakage_sample_payload(1, 200.0, 0, MAX_INJECTION_PA),
            sc.tech_headers,
        ),
        201,
    )
    assert at_limit["injection_pressure_pa"] == 1000.0
    assert at_limit["cutoff_triggered"] is False
    assert sc.read_seal_job()["status"] == JOB_INJECTING

    over_limit = validate_success(
        api.append_leakage_sample(
            sc.seal_job_id,
            f.leakage_sample_payload(2, 190.0, 60, 1000.1),
            sc.tech_headers,
        ),
        201,
    )
    assert over_limit["cutoff_triggered"] is True

    job = sc.read_seal_job()
    assert job["status"] == JOB_ABORTED_SAFETY
    assert job["abort_reason"] == "injection pressure cutoff"

    duct_system = sc.read_duct_system()
    assert_leakage_ledger(duct_system, 300.00, 300.00, 0.00)
    assert duct_system["seal_status"] == SEAL_STATUS_SEAL_PENDING
    assert duct_system["active_seal_job_id"] is None

    project = sc.read_project()
    assert project["status"] == PROJECT_SAFETY_HOLD
    assert project["safety_hold"] is True
    assert project["safety_hold_reason"] == (
        "injection pressure cutoff on system " + sc.duct_system["system_label"]
    )

    validate_error(
        api.resume_seal_job(sc.seal_job_id, None, sc.tech_headers),
        ERR_INJECTION_PRESSURE_LIMIT,
        422,
    )
    validate_error(
        api.pause_seal_job(sc.seal_job_id, f.pause_payload(), sc.tech_headers),
        ERR_SEAL_JOB_INVALID_STATE,
        409,
    )

    _, meta = validate_paginated(api.list_leakage_samples(sc.seal_job_id, sc.tech_headers))
    assert meta["total_count"] == 2


def test_target_reached_latches_at_equality_while_the_stall_flag_keeps_resetting(api):
    """One flag never clears and the other clears on every resume.

    PRD 3.6: "If that reading is at or below the run's `target_leakage_cfm`,
    `target_reached` latches true and never clears again, even if a later point reads
    higher." And: "Resuming ... clears `stall_flag` to false".

    Design: Corner/cross_cutting_complexity_layers/target_reached_latches_at_exact_equality_and_the_stall_flag_resets
    """
    sc = fx.scenario_injecting_job(api)
    assert sc.seal_job["target_leakage_cfm"] == 60.0
    assert sc.seal_job["target_reached"] is False

    fx.stream_samples(
        sc, samples=((1, 300.0, 0, 700.0), (2, 200.0, 240, 710.0), (3, 60.0, 480, 720.0))
    )
    at_target = sc.read_seal_job()
    assert at_target["current_leakage_cfm"] == 60.0
    assert at_target["target_reached"] is True
    assert at_target["status"] == JOB_INJECTING
    assert at_target["stall_flag"] is False

    fx.stream_samples(sc, samples=((4, 62.0, 540, 730.0),))
    rebounded = sc.read_seal_job()
    assert rebounded["current_leakage_cfm"] == 62.0
    assert rebounded["target_reached"] is True
    assert rebounded["status"] == JOB_INJECTING

    fx.stream_samples(sc, samples=((5, 61.9, 600, 740.0),))
    stalled = sc.read_seal_job()
    assert stalled["status"] == JOB_PAUSED
    assert stalled["stall_flag"] is True
    assert stalled["pause_count"] == 1
    assert stalled["target_reached"] is True

    resumed = validate_success(api.resume_seal_job(sc.seal_job_id, None, sc.tech_headers))
    assert resumed["stall_flag"] is False
    assert resumed["target_reached"] is True
    assert resumed["status"] == JOB_INJECTING
    assert sc.read_duct_system()["working_leakage_cfm25"] == 61.9
