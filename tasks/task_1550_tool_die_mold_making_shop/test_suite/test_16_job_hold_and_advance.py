"""BuildJob hold/resume branching and the constrained advance set
(PRD §3.4)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    get_success_data,
    schedule_tryout_round,
    setup_booked_job,
    start_build,
    validate_error,
    validate_success,
)

PM = TEST_USERS["project_manager_headers"]


def test_job_hold_blocks_ops_and_resume_returns_prior_state(api):
    """PRD §3.4: "A job in `BOOKED`, `IN_BUILD`, `TRYOUT_PHASE`,
    `BUYOFF_PASSED`, or `READY_TO_SHIP` may be put on hold. Holding captures
    the current state into `hold_return_state` and moves the job to `ON_HOLD`;
    resuming returns the job to `hold_return_state` and clears that field to
    null. Both actions increment the job's `version`. While a job is
    `ON_HOLD`, operational actions on it — completing milestones, filing
    engineering changes, initiating sample rework — are rejected with
    `ERR_JOB_ON_HOLD`."

    Design: Corner/state_machines/job_hold_blocks_ops_and_resume_returns_prior_state
    """
    ctx = setup_booked_job(company_name="Hold Co", part_number="PN-HD1")
    job_id = ctx["job"]["id"]
    start_build(job_id)
    schedule_tryout_round(job_id)  # first sample moves IN_BUILD -> TRYOUT_PHASE
    job = get_success_data(api_client.get_build_job(job_id, PM))
    assert job["status"] == "TRYOUT_PHASE"

    held = validate_success(api_client.hold_build_job(job_id, PM), 200)
    assert held["status"] == "ON_HOLD"
    assert held["hold_return_state"] == "TRYOUT_PHASE"

    milestone_id = ctx["milestones"][0]["id"]
    res = api_client.complete_milestone(milestone_id, {}, PM)
    error = validate_error(res, ApiErrorId.ERR_JOB_ON_HOLD)
    assert error["error_id"] == "ERR_JOB_ON_HOLD"
    assert res.status_code == 409

    milestone = get_success_data(api_client.get_build_milestone(milestone_id, PM))
    assert milestone["status"] == "PENDING", "a rejected completion must not earn"

    resumed = validate_success(api_client.resume_build_job(job_id, PM), 200)
    assert resumed["status"] == "TRYOUT_PHASE", (
        f"resume must return to hold_return_state, got {resumed['status']}"
    )
    assert resumed["hold_return_state"] is None


def test_job_advance_illegal_target_rejected(api):
    """PRD §3.4: "Moving the job forward is a `ProjectManager` action with an
    explicit `target_state`, and only two advances are legal: `BOOKED` to
    `IN_BUILD`, which requires at least one `RESERVED` machine reservation on
    the job (`ERR_NO_CAPACITY_RESERVED`), and `BUYOFF_PASSED` to
    `READY_TO_SHIP`, which requires milestones with `seq` 1 through 5 all in
    `EARNED`, `INVOICED`, or `PAID` (`ERR_MILESTONE_SEQUENCE_BLOCKED`). Any
    other advance target is rejected with `ERR_INVALID_STATE` (an
    out-of-domain value is a shape failure under §2.7 tier 3)."

    Design: Corner/state_machines/job_advance_illegal_target_rejected
    """
    ctx = setup_booked_job(company_name="Adv Co", part_number="PN-AV1")
    job_id = ctx["job"]["id"]
    start_build(job_id)

    # BUYOFF_PASSED is a system-driven state, not a legal advance target.
    res = api_client.advance_build_job(job_id, {"target_state": "BUYOFF_PASSED"}, PM)
    error = validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert error["error_id"] == "ERR_INVALID_STATE"
    assert res.status_code == 409

    job = get_success_data(api_client.get_build_job(job_id, PM))
    assert job["status"] == "IN_BUILD"


def test_advance_without_machine_capacity_rejected(api):
    """PRD §3.4: "Moving the job forward is a `ProjectManager` action with an
    explicit `target_state`, and only two advances are legal: `BOOKED` to
    `IN_BUILD`, which requires at least one `RESERVED` machine reservation on
    the job (`ERR_NO_CAPACITY_RESERVED`), and `BUYOFF_PASSED` to
    `READY_TO_SHIP`, which requires milestones with `seq` 1 through 5 all in
    `EARNED`, `INVOICED`, or `PAID` (`ERR_MILESTONE_SEQUENCE_BLOCKED`)."

    Design: Corner/state_machines/advance_without_machine_capacity_rejected
    """
    ctx = setup_booked_job(company_name="NoCap Co", part_number="PN-NC1")
    job_id = ctx["job"]["id"]

    # No machine reservation exists for this job.
    res = api_client.advance_build_job(job_id, {"target_state": "IN_BUILD"}, PM)
    error = validate_error(res, ApiErrorId.ERR_NO_CAPACITY_RESERVED)
    assert error["error_id"] == "ERR_NO_CAPACITY_RESERVED"
    assert res.status_code == 409

    job = get_success_data(api_client.get_build_job(job_id, PM))
    assert job["status"] == "BOOKED"
