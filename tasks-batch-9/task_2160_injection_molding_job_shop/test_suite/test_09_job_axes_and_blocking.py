"""The job's two independent axes, the blocking cascade and the material gates."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_job,
    create_job,
    disposition_lot,
    post_report,
    read_job,
    read_lot,
    read_mold,
    read_press,
    setup_approved_tool,
    setup_running_job,
    setup_staged_job,
    validate_error,
    validate_success,
)

PE = TEST_USERS["process_engineer_headers"]
QE = TEST_USERS["quality_engineer_headers"]


def test_quarantining_the_tool_blocks_de_stages_and_releases_the_press_minutes(api):
    """PRD §3.4: "Quarantining an approved tool, by contrast, is a cascade origin:
    every job on that tool whose `run_status` is `SCHEDULED` is driven to `BLOCKED`
    with its `block_reason` set to `MOLD_QUARANTINED`, and each of those jobs then
    fires its own blocking side effects — de-staging its material and releasing its
    press minutes — as §3.6 describes."
    PRD §3.6: "Arriving at `BLOCKED` fires the job's own two side effects in turn:
    its `material_status` moves `STAGED → UNSTAGED` with `staged_resin_lot_id`
    cleared, and its whole-minute duration is subtracted from the press's
    `committed_minutes_scheduled` with the press's `version` incremented by 1."

    Design: Difficulty/non_linear_state_machine/production_job_parallel_axes_with_blocked_cycle
    """
    shop = setup_staged_job()
    assert read_press(shop["press"]["id"])["committed_minutes_scheduled"] == 480

    validate_success(
        api.mold_quality_hold(
            shop["mold"]["id"],
            {"action": "QUARANTINE", "reason": "dimensional drift found on cavity 3"},
            QE,
        )
    )

    job = read_job(shop["job"]["id"])
    assert job["run_status"] == "BLOCKED"
    assert job["material_status"] == "UNSTAGED"
    assert job["block_reason"] == "MOLD_QUARANTINED"
    assert job.get("staged_resin_lot_id") is None
    assert read_press(shop["press"]["id"])["committed_minutes_scheduled"] == 0


def test_a_blocked_job_returns_to_schedule_and_restages_on_its_own_axis(api):
    """PRD §3.4: "In neither case are blocked jobs restored automatically; each must
    be returned to the schedule explicitly, one at a time."
    PRD §3.6: "On success `block_reason` is cleared, the job's duration is added
    back to the press's `committed_minutes_scheduled`, and the press's `version` is
    incremented by 1. The material axis is **not** restored: `material_status` stays
    `UNSTAGED` and the lot must be staged again from scratch."
    PRD §3.5: "Binding a lot to a job is a `ProcessEngineer` action that moves the
    job's **material axis only**, `UNSTAGED → STAGED`, and leaves the run axis
    exactly where it was — the clearest demonstration in the system that the two
    axes are genuinely independent."

    Design: Difficulty/non_linear_state_machine/production_job_parallel_axes_with_blocked_cycle
    """
    shop = setup_staged_job()
    validate_success(
        api.mold_quality_hold(
            shop["mold"]["id"],
            {"action": "QUARANTINE", "reason": "dimensional drift found on cavity 3"},
            QE,
        )
    )

    released = validate_success(
        api.mold_quality_hold(
            shop["mold"]["id"],
            {"action": "RELEASE", "reason": "cavity 3 re-cut and verified"},
            QE,
        )
    )
    assert released["status"] == "PPAP_APPROVED"
    assert read_job(shop["job"]["id"])["run_status"] == "BLOCKED", (
        "a release does not restore blocked jobs by itself"
    )

    unblocked = validate_success(
        api.unblock_job(
            shop["job"]["id"],
            {"expected_press_version": read_press(shop["press"]["id"])["version"]},
            PE,
        )
    )
    assert unblocked["run_status"] == "SCHEDULED"
    assert unblocked["material_status"] == "UNSTAGED"
    assert unblocked.get("block_reason") is None
    assert read_press(shop["press"]["id"])["committed_minutes_scheduled"] == 480

    restaged = validate_success(
        api.stage_material(shop["job"]["id"], {"resin_lot_id": shop["lot"]["id"]}, PE)
    )
    assert restaged["material_status"] == "STAGED"
    assert restaged["run_status"] == "SCHEDULED", "the run axis never moved"


def test_a_report_crossing_the_pm_interval_takes_the_tool_out_of_service(api):
    """PRD §3.8: "**The preventive-maintenance gate is evaluated first**: if
    `shots_since_pm` has reached or passed `pm_interval_shots` and the tool's
    `service_state` is `SERVICEABLE`, the tool moves `SERVICEABLE → PM_DUE`, which
    is a cascade origin that blocks that tool's scheduled jobs with `block_reason`
    `MOLD_PM_DUE`."
    PRD §3.8: "`total_shot_count` is the summed `shots` of every non-reversed report
    whose job names that tool — a lifetime figure that nothing resets."

    Design: Difficulty/transitive_cascade/report_pm_threshold_blocks_sibling_job_and_releases_press_minutes
    """
    shop = setup_running_job(
        mold_overrides={"pm_interval_shots": 1000}, job_overrides={"planned_qty": 4000}
    )

    post_report(
        shop["job"]["id"],
        shots=1000,
        short_shot_shots=5,
        good_parts=3960,
        scrap_parts=40,
        virgin_grams=36000,
        regrind_grams=4000,
        run_minutes=600,
    )

    mold = read_mold(shop["mold"]["id"])
    assert mold["shots_since_pm"] == 1000
    assert mold["total_shot_count"] == 1000
    assert mold["service_state"] == "PM_DUE"


def test_the_pm_cascade_blocks_the_sibling_job_and_frees_its_press_minutes(api):
    """PRD §3.6: "The system blocks a job on its own initiative. Whenever a tool's
    `service_state` reaches `PM_DUE`, or its lifecycle status reaches `QUARANTINED`
    by either route, every job on that tool whose `run_status` is `SCHEDULED` is
    driven `SCHEDULED → BLOCKED`, with `block_reason` set to `MOLD_PM_DUE`,
    `MOLD_QUARANTINED` or `INTERIM_PPAP_EXPIRED` according to which condition
    fired."
    PRD §3.6: "Note that only `SCHEDULED` jobs are blocked — a job already `RUNNING`
    on the tool that posted the tripping report keeps running."
    PRD §3.6: "Arriving at `BLOCKED` fires the job's own two side effects in turn:
    its `material_status` moves `STAGED → UNSTAGED` with `staged_resin_lot_id`
    cleared, and its whole-minute duration is subtracted from the press's
    `committed_minutes_scheduled` with the press's `version` incremented by 1."

    Design: Difficulty/transitive_cascade/report_pm_threshold_blocks_sibling_job_and_releases_press_minutes
    """
    shop = setup_running_job(
        mold_overrides={"pm_interval_shots": 1000}, job_overrides={"planned_qty": 4000}
    )
    sibling = add_job(
        shop,
        "2026-09-12T08:00:00Z",
        "2026-09-12T16:00:00Z",
        schedule=True,
        stage=True,
        planned_qty=4000,
    )
    assert read_press(shop["press"]["id"])["committed_minutes_scheduled"] == 960

    post_report(
        shop["job"]["id"],
        shots=1000,
        short_shot_shots=5,
        good_parts=3960,
        scrap_parts=40,
        virgin_grams=36000,
        regrind_grams=4000,
        run_minutes=600,
    )

    blocked = read_job(sibling["id"])
    assert blocked["run_status"] == "BLOCKED"
    assert blocked["block_reason"] == "MOLD_PM_DUE"
    assert blocked["material_status"] == "UNSTAGED"
    assert blocked.get("staged_resin_lot_id") is None
    assert read_press(shop["press"]["id"])["committed_minutes_scheduled"] == 480

    running = read_job(shop["job"]["id"])
    assert running["run_status"] == "RUNNING"
    assert running["material_status"] == "STAGED"
    assert read_lot(shop["lot"]["id"])["qty_grams_remaining"] == 464000


def test_a_held_lot_blocks_the_start_of_an_otherwise_ready_job(api):
    """PRD §3.6: "Starting a job carries no request body at all. It advances
    `SCHEDULED → RUNNING` and requires that the job's `material_status` is `STAGED`
    — otherwise `ERR_JOB_MATERIAL_NOT_STAGED` — that the staged lot's `status` is
    still `RELEASED`, otherwise `ERR_RESIN_LOT_NOT_RELEASED`, and that the tool is
    still `PPAP_APPROVED` or `INTERIM_APPROVED` with `service_state` `SERVICEABLE`."
    PRD §3.5: "A `HOLD` decision is accepted only from `RELEASED` and moves the lot
    to `HOLD`; jobs that have already staged that lot keep their `material_status`
    at `STAGED` but can no longer be started."

    Design: Difficulty/cross_entity_state_dependency/job_start_gated_on_resin_lot_status
    """
    shop = setup_staged_job()
    disposition_lot(shop["lot"]["id"], "HOLD", reason="moisture retest pending")

    response = api.start_job(shop["job"]["id"], PE)

    assert response.status_code == 422, f"Expected 422, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_RESIN_LOT_NOT_RELEASED.value)
    job = read_job(shop["job"]["id"])
    assert job["run_status"] == "SCHEDULED"
    assert job["material_status"] == "STAGED"


def test_releasing_the_lot_again_lets_the_identical_start_call_succeed(api):
    """PRD §3.5: "Releasing out of `QUARANTINE` initialises `qty_grams_remaining` to
    the received kilograms multiplied by 1,000 if it is somehow still unset;
    releasing out of `HOLD` makes already-staged jobs startable again."
    PRD §3.6: "Starting a job carries no request body at all. It advances
    `SCHEDULED → RUNNING` and requires that the job's `material_status` is `STAGED`
    — otherwise `ERR_JOB_MATERIAL_NOT_STAGED` — that the staged lot's `status` is
    still `RELEASED`, otherwise `ERR_RESIN_LOT_NOT_RELEASED`, and that the tool is
    still `PPAP_APPROVED` or `INTERIM_APPROVED` with `service_state` `SERVICEABLE`."

    Design: Difficulty/cross_entity_state_dependency/job_start_gated_on_resin_lot_status
    """
    shop = setup_staged_job()
    disposition_lot(shop["lot"]["id"], "HOLD", reason="moisture retest pending")
    blocked = api.start_job(shop["job"]["id"], PE)
    assert blocked.status_code == 422

    released = validate_success(
        api.resin_lot_disposition(shop["lot"]["id"], {"decision": "RELEASE"}, QE)
    )
    assert released["status"] == "RELEASED"

    started = validate_success(api.start_job(shop["job"]["id"], PE))
    assert started["run_status"] == "RUNNING"


def test_a_second_start_reports_the_run_status_rather_than_the_held_lot(api):
    """PRD §2.7: "Requests are screened in a fixed order, and the **first** check
    that fails determines the response. This ordering is normative: a request that
    would fail two different checks always reports the earlier one."
    PRD §2.7: "**Transition legality.** The target resource is in a state from which
    the requested transition is declared, or a 409 state error — the specific one
    where the system defines it, and `ERR_INVALID_STATE` otherwise."
    PRD §2.7: "**Material and first-article gates.** Resin release status, resin
    grade match, first-article verdict and incoming moisture, answered with
    `ERR_RESIN_LOT_NOT_RELEASED`, `ERR_RESIN_GRADE_MISMATCH`, `ERR_FAI_NOT_PASSED`
    or `ERR_RESIN_MOISTURE_TOO_HIGH` (422)."
    PRD §3.6: "Starting a job that is not `SCHEDULED` is rejected with
    `ERR_JOB_NOT_SCHEDULED`."

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_material_safety_gate_on_second_start
    """
    shop = setup_running_job()
    disposition_lot(shop["lot"]["id"], "HOLD", reason="moisture retest pending")

    response = api.start_job(shop["job"]["id"], PE)

    assert response.status_code == 409, f"Expected 409, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_JOB_NOT_SCHEDULED.value)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_RESIN_LOT_NOT_RELEASED.value


def test_the_rejected_second_start_leaves_the_job_running_and_the_lot_on_hold(api):
    """PRD §3.6: "Starting a job that is not `SCHEDULED` is rejected with
    `ERR_JOB_NOT_SCHEDULED`."
    PRD §3.5: "A `HOLD` decision is accepted only from `RELEASED` and moves the lot
    to `HOLD`; jobs that have already staged that lot keep their `material_status`
    at `STAGED` but can no longer be started."

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_material_safety_gate_on_second_start
    """
    shop = setup_running_job()
    disposition_lot(shop["lot"]["id"], "HOLD", reason="moisture retest pending")

    response = api.start_job(shop["job"]["id"], PE)
    assert response.status_code == 409

    job = read_job(shop["job"]["id"])
    assert job["run_status"] == "RUNNING"
    assert job["material_status"] == "STAGED"
    assert read_lot(shop["lot"]["id"])["status"] == "HOLD"


def test_starting_a_draft_job_is_refused_because_it_never_reserved_anything(api):
    """PRD §3.6: "Starting a job that is not `SCHEDULED` is rejected with
    `ERR_JOB_NOT_SCHEDULED`."
    PRD §3.6: "Opening a job reserves **no** press minutes — a `DRAFT` job is a
    plan, not a booking."

    Design: Corner/state_machines/job_start_from_draft_returns_job_not_scheduled
    """
    shop = setup_approved_tool(with_lot=False)
    job = create_job(shop["quote"]["id"], press_id=shop["press"]["id"])
    assert job["run_status"] == "DRAFT"

    response = api.start_job(job["id"], PE)

    assert response.status_code == 409, f"Expected 409, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_JOB_NOT_SCHEDULED.value)
    current = read_job(job["id"])
    assert current["run_status"] == "DRAFT"
    assert current["material_status"] == "UNSTAGED"
    assert read_press(shop["press"]["id"])["committed_minutes_scheduled"] == 0
