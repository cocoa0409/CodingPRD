"""Combustion spillage verdicts, the safety hold they raise, and the way out of it."""

from test_helpers import (
    ADMIN_HEADERS,
    APPLIANCE_ATMOSPHERIC_WATER_HEATER,
    APPLIANCE_RANGE,
    ERR_PROJECT_SAFETY_HOLD,
    JOB_ABORTED_SAFETY,
    JOB_INJECTING,
    JOB_PAUSED,
    JOB_SCHEDULED,
    PHASE_POST,
    PHASE_PRE,
    PROJECT_ACTIVE,
    PROJECT_SAFETY_HOLD,
    QA_HEADERS,
    SEAL_STATUS_SEAL_PENDING,
    VERDICT_FAIL,
    VERDICT_MARGINAL,
    VERDICT_PASS,
    expected_verdict,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_the_spillage_and_carbon_monoxide_boundaries_land_on_marginal(api):
    """Exactly at a limit is `MARGINAL`; a hair above it is `FAIL`.

    PRD 3.4: "The boundaries are exact — exactly 60 seconds of spillage is
    `MARGINAL` and not `FAIL`, and a carbon-monoxide reading exactly equal to the
    ceiling is `MARGINAL` and not `FAIL`, since it is not strictly above the ceiling
    but is at or above the warning level."

    Design: Corner/calculations/combustion_verdict_is_marginal_at_the_exact_spillage_and_co_boundaries
    """
    sc = fx.scenario_base(api)

    def verdict_of(label, spillage_seconds, co_ppm_air_free):
        row = fx.add_combustion_test(
            sc,
            appliance_label=label,
            spillage_seconds=spillage_seconds,
            co_ppm_air_free=co_ppm_air_free,
        )
        assert row["verdict"] == expected_verdict(
            APPLIANCE_ATMOSPHERIC_WATER_HEATER, spillage_seconds, co_ppm_air_free, 2.5, 3.0
        )
        return row["verdict"]

    assert verdict_of("WH-1", 59, 49.9) == VERDICT_PASS
    assert verdict_of("WH-2", 60, 18.0) == VERDICT_MARGINAL
    assert verdict_of("WH-3", 12, 50.0) == VERDICT_MARGINAL
    assert verdict_of("WH-4", 12, 100.0) == VERDICT_MARGINAL
    assert verdict_of("WH-5", 61, 18.0) == VERDICT_FAIL
    assert verdict_of("WH-6", 12, 100.1) == VERDICT_FAIL


def test_depressurization_only_fails_when_the_draft_is_weak_at_the_same_time(api):
    """The two readings must be bad together, and both boundaries are strict.

    PRD 3.4: "`worst_case_depressurization_pa` is strictly above the appliance's
    depressurization limit **and**, at the same time, `draft_pressure_pa` is strictly
    below 1.0 ... the depressurization limit only bites when the draft is
    simultaneously weak, so a house with 7 pascals of worst-case depressurization but
    a healthy 3-pascal draft is not failed on that account."

    Design: Corner/calculations/worst_case_depressurization_only_fails_when_the_draft_is_simultaneously_weak
    """
    sc = fx.scenario_base(api)

    def verdict_of(label, draft_pressure_pa, worst_case_depressurization_pa):
        row = fx.add_combustion_test(
            sc,
            appliance_label=label,
            draft_pressure_pa=draft_pressure_pa,
            worst_case_depressurization_pa=worst_case_depressurization_pa,
        )
        assert row["verdict"] == expected_verdict(
            APPLIANCE_ATMOSPHERIC_WATER_HEATER,
            12,
            18.0,
            draft_pressure_pa,
            worst_case_depressurization_pa,
        )
        return row["verdict"]

    assert verdict_of("WH-1", 3.0, 7.0) == VERDICT_PASS
    assert verdict_of("WH-2", 0.5, 5.0) == VERDICT_PASS
    assert verdict_of("WH-3", 1.0, 5.1) == VERDICT_PASS
    assert verdict_of("WH-4", 0.9, 5.1) == VERDICT_FAIL
    assert verdict_of("WH-5", 0.5, 7.0) == VERDICT_FAIL


def test_a_range_is_held_to_its_own_looser_limits(api):
    """The appliance class selects the limits, so 400 ppm is a warning not a failure.

    PRD 3.4: "A `RANGE` is held to looser numbers: an 800 ppm ceiling, a 400 ppm
    warning level, and a depressurization limit of 999.0 pascals that in practice
    never binds."

    Design: Corner/calculations/range_appliance_uses_its_own_carbon_monoxide_ceiling
    """
    sc = fx.scenario_base(api)

    def range_verdict(label, co_ppm_air_free, worst_case=3.0, draft=2.5):
        row = fx.add_combustion_test(
            sc,
            appliance_label=label,
            appliance_type=APPLIANCE_RANGE,
            co_ppm_air_free=co_ppm_air_free,
            draft_pressure_pa=draft,
            worst_case_depressurization_pa=worst_case,
        )
        assert row["appliance_type"] == APPLIANCE_RANGE
        assert row["verdict"] == expected_verdict(
            APPLIANCE_RANGE, 12, co_ppm_air_free, draft, worst_case
        )
        return row["verdict"]

    assert range_verdict("RG-1", 399.9) == VERDICT_PASS
    assert range_verdict("RG-2", 400.0) == VERDICT_MARGINAL
    assert range_verdict("RG-3", 800.0) == VERDICT_MARGINAL
    assert range_verdict("RG-4", 800.1) == VERDICT_FAIL
    assert range_verdict("RG-5", 18.0, worst_case=900.0, draft=0.5) == VERDICT_PASS

    # The same 150 ppm reading that a water heater fails on is only a warning here.
    hot = fx.add_combustion_test(
        sc, appliance_label="RG-6", appliance_type=APPLIANCE_RANGE, co_ppm_air_free=150.0
    )
    assert hot["verdict"] == VERDICT_PASS
    vented = fx.add_combustion_test(sc, appliance_label="WH-9", co_ppm_air_free=150.0)
    assert vented["verdict"] == VERDICT_FAIL


def test_a_post_phase_failure_reaches_the_project_the_runs_and_the_ledgers(api):
    """One failing post test holds the project, aborts every live run under it and
    compensates each duct system.

    PRD 3.4: "It drives the project from `ACTIVE` to `SAFETY_HOLD`, sets
    `safety_hold` true and stamps `safety_hold_reason` as `combustion spillage
    failure on ` followed by the offending `appliance_label`. When the failing test
    is a `POST`-phase test, every sealing run under the project whose status is
    `MASKING`, `INJECTING` or `PAUSED` is driven to `ABORTED_SAFETY` with
    `abort_reason` recorded as `combustion spillage failure`, and each affected duct
    system's ledger is compensated exactly as described in §2.10".

    Design: Corner/cross_cutting_complexity_layers/post_phase_combustion_failure_cascades_across_three_entities
    """
    sc = fx.scenario_ready_to_inject(api)
    second = fx.add_duct_system(sc, system_label="AHU-2", lab_reference="LAB-1002")
    third = fx.add_duct_system(sc, system_label="AHU-3", lab_reference="LAB-1003")
    fx.add_accepted_leakage_test(sc, duct_system=second)
    fx.add_accepted_leakage_test(sc, duct_system=third)

    injecting = fx.schedule_seal_job(
        sc,
        scheduled_start_at=f.utc(2026, 8, 2, 13, 0),
        scheduled_end_at=f.utc(2026, 8, 2, 18, 0),
    )
    fx.mask_all_registers(sc, seal_job=injecting)
    fx.begin_injection(sc, seal_job=injecting)
    fx.stream_samples(
        sc,
        samples=((1, 300.0, 0, 700.0), (2, 200.0, 240, 710.0), (3, 120.0, 480, 720.0)),
        seal_job=injecting,
    )
    masking = fx.schedule_seal_job(
        sc,
        duct_system=second,
        scheduled_start_at=f.utc(2026, 8, 2, 18, 0),
        scheduled_end_at=f.utc(2026, 8, 2, 21, 0),
    )
    fx.mask_all_registers(sc, seal_job=masking, duct_system=second)
    scheduled = fx.schedule_seal_job(
        sc,
        duct_system=third,
        scheduled_start_at=f.utc(2026, 8, 3, 9, 0),
        scheduled_end_at=f.utc(2026, 8, 3, 12, 0),
    )
    assert sc.read_technician()["open_seal_job_count"] == 3

    failing = fx.add_combustion_test(
        sc, phase=PHASE_POST, appliance_label="WH-2", co_ppm_air_free=150.0
    )
    assert failing["verdict"] == VERDICT_FAIL
    assert failing["phase"] == PHASE_POST

    project = sc.read_project()
    assert project["status"] == PROJECT_SAFETY_HOLD
    assert project["safety_hold"] is True
    assert project["safety_hold_reason"] == "combustion spillage failure on WH-2"

    for job_id in (injecting["id"], masking["id"]):
        job = sc.read_seal_job(job_id)
        assert job["status"] == JOB_ABORTED_SAFETY
        assert job["abort_reason"] == "combustion spillage failure"

    assert sc.read_seal_job(scheduled["id"])["status"] == JOB_SCHEDULED

    for duct_system_id in (sc.duct_system_id, second["id"]):
        view = sc.read_duct_system(duct_system_id)
        assert view["seal_status"] == SEAL_STATUS_SEAL_PENDING
        assert view["working_leakage_cfm25"] == view["baseline_leakage_cfm25"] == 300.00
        assert view["sealed_leakage_reduction_cfm"] == 0.00
        assert view["active_seal_job_id"] is None

    assert sc.read_technician()["open_seal_job_count"] == 1


def test_releasing_the_hold_leaves_the_paused_run_paused(api):
    """A hold pauses the live run, blocks resume while it stands, and clearing it does
    not restart anything by itself.

    PRD 3.4: "An administrator or a verifier may also raise the hold by hand ...
    drives every run under the project that is `INJECTING` to `PAUSED`", and "There
    are two ways out of a hold, and both leave paused runs paused ... In neither case
    is any paused run resumed automatically — each one still requires an explicit
    resume by its technician." PRD 3.6: "a paused run under a held project stays
    paused with `ERR_PROJECT_SAFETY_HOLD` until the hold clears."

    Design: Corner/state_machines/safety_hold_release_does_not_auto_resume_a_paused_job
    """
    sc = fx.scenario_injecting_job(api)
    fx.stream_samples(sc, samples=((1, 300.0, 0, 700.0), (2, 200.0, 240, 710.0)))

    held = validate_success(
        api.raise_safety_hold(sc.project_id, f.safety_hold_payload(), QA_HEADERS)
    )
    assert held["status"] == PROJECT_SAFETY_HOLD
    assert held["safety_hold"] is True
    assert held["safety_hold_reason"] == "homeowner reported flue odor"
    assert sc.read_seal_job()["status"] == JOB_PAUSED

    validate_error(
        api.resume_seal_job(sc.seal_job_id, None, sc.tech_headers),
        ERR_PROJECT_SAFETY_HOLD,
        422,
    )

    released = validate_success(
        api.release_safety_hold(
            sc.project_id, f.release_safety_hold_payload(), ADMIN_HEADERS
        )
    )
    assert released["status"] == PROJECT_ACTIVE
    assert released["safety_hold"] is False
    assert released["safety_hold_reason"] is None
    assert sc.read_seal_job()["status"] == JOB_PAUSED

    resumed = validate_success(api.resume_seal_job(sc.seal_job_id, None, sc.tech_headers))
    assert resumed["status"] == JOB_INJECTING
    assert resumed["stall_flag"] is False


def test_combustion_tests_can_be_listed_by_phase_and_by_computed_verdict(api):
    """The verdict the server computed is itself a filter key.

    PRD 2.5: "A project's combustion tests are listed under the project and can be
    narrowed by `phase` and by `verdict`."

    Design: Corner/endpoints/combustion_test_list_filters_on_the_computed_verdict
    """
    sc = fx.scenario_base(api)
    passing = fx.add_combustion_test(sc, appliance_label="WH-1")
    marginal = fx.add_combustion_test(sc, appliance_label="WH-2", spillage_seconds=60)
    failing = fx.add_combustion_test(
        sc, phase=PHASE_POST, appliance_label="WH-3", co_ppm_air_free=150.0
    )
    assert (passing["verdict"], marginal["verdict"], failing["verdict"]) == (
        VERDICT_PASS,
        VERDICT_MARGINAL,
        VERDICT_FAIL,
    )

    rows, meta = validate_paginated(
        api.list_combustion_tests(sc.project_id, ADMIN_HEADERS)
    )
    assert meta["total_count"] == 3
    assert [row["id"] for row in rows] == [passing["id"], marginal["id"], failing["id"]]

    rows, meta = validate_paginated(
        api.list_combustion_tests(sc.project_id, ADMIN_HEADERS, phase=PHASE_PRE)
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {passing["id"], marginal["id"]}

    rows, meta = validate_paginated(
        api.list_combustion_tests(sc.project_id, ADMIN_HEADERS, verdict=VERDICT_MARGINAL)
    )
    assert meta["total_count"] == 1 and rows[0]["id"] == marginal["id"]

    rows, meta = validate_paginated(
        api.list_combustion_tests(
            sc.project_id, ADMIN_HEADERS, phase=PHASE_POST, verdict=VERDICT_FAIL
        )
    )
    assert meta["total_count"] == 1 and rows[0]["id"] == failing["id"]

    _, meta = validate_paginated(
        api.list_combustion_tests(
            sc.project_id, ADMIN_HEADERS, phase=PHASE_PRE, verdict=VERDICT_FAIL
        )
    )
    assert meta["total_count"] == 0
