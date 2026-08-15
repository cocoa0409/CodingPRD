"""Safety stop-work dimension, incident cascades, job cancellation cascades,
and terminal-state lockdown."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_confirmed_equipment_assignment,
    create_equipment_assignment_payload,
    create_equipment_unit,
    create_incident_payload,
    create_job,
    create_job_in_progress,
    create_permit_payload,
    create_site_with_active_schedule,
    get_success_data,
    schedule_and_mobilize,
    validate_error,
    verify_containment,
)

PM = TEST_USERS["project_manager_headers"]
FS = TEST_USERS["field_supervisor_headers"]
SM = TEST_USERS["safety_manager_headers"]


class TestParallelDimensionsStopWorkGate:
    def _setup_in_progress_with_permit(self, api):
        ctx = create_job_in_progress(
            job_overrides={"job_type": "COMBINED", "description": "Tank T-101 confined entry"},
            jha_overrides={
                "confined_space": True,
                "hazards": ["CONFINED_SPACE", "HIGH_PRESSURE_WATER"],
                "water_source": "TRUCKED_IN",
            },
            pressure_plan=True,
            confined_space_permit=True,
        )
        ctx["containment"] = verify_containment(ctx["job"]["id"], used=1000, captured=1000)
        return ctx

    def test_serious_incident_stops_work_and_gates_completion(self, api):
        """PRD §3.4: "Reporting a `SERIOUS` or `MAJOR` incident while the job's
        safety dimension is `CLEAR` immediately moves the job to `STOP_WORK` and
        suspends every `ACTIVE` permit on the job — the same cascade as an
        explicit stop."
        PRD §3.4: "the safety dimension must be `CLEAR` (`ERR_JOB_STOPPED`)".

        Design: Difficulty/non_linear_state_machine/job_parallel_dims_stop_work_gate
        """
        ctx = self._setup_in_progress_with_permit(api)
        job_id = ctx["job"]["id"]
        incident = get_success_data(
            api.create_incident(
                create_incident_payload(
                    job_id,
                    severity="SERIOUS",
                    title="Hose whip near-miss with injury potential",
                    description="Hydroblast hose coupling separated under pressure",
                ),
                FS,
            )
        )
        job_mid = get_success_data(api.get_job(job_id, PM))
        assert job_mid["safety_status"] == "STOP_WORK"
        assert job_mid["execution_status"] == "IN_PROGRESS"
        permit_mid = get_success_data(api.get_permit(ctx["permit"]["id"], PM))
        assert permit_mid["status"] == "SUSPENDED"

        resp = api.complete_field_work(
            job_id, {"gallons_removed": 500, "feet_cleaned": 40}, PM
        )
        validate_error(resp, ApiErrorId.ERR_JOB_STOPPED.value)
        assert resp.status_code == 409

    def test_resume_after_incident_closure_then_completion_succeeds(self, api):
        """PRD §3.4: "Resuming (`STOP_WORK` → `CLEAR`) requires that every
        incident report on the job is `CLOSED` (`ERR_INVALID_STATE` otherwise)
        and that an `APPROVED` hazard analysis still exists
        (`ERR_JHA_NOT_APPROVED`). Suspended permits stay suspended after the
        resume; each is re-activated explicitly under §3.3's four checks."

        Design: Difficulty/non_linear_state_machine/job_parallel_dims_stop_work_gate
        """
        ctx = self._setup_in_progress_with_permit(api)
        job_id = ctx["job"]["id"]
        incident = get_success_data(
            api.create_incident(
                create_incident_payload(job_id, severity="SERIOUS",
                                        title="Hose whip", description="coupling"),
                FS,
            )
        )
        get_success_data(api.start_incident_review(incident["id"], SM))
        get_success_data(
            api.close_incident(
                incident["id"],
                {"osha_recordable": False,
                 "corrective_action": "Retrain crew on coupling inspection"},
                SM,
            )
        )
        resumed = get_success_data(api.resume_work(job_id, SM))
        assert resumed["safety_status"] == "CLEAR"
        permit_after = get_success_data(api.get_permit(ctx["permit"]["id"], PM))
        assert permit_after["status"] == "SUSPENDED"
        completed = get_success_data(
            api.complete_field_work(
                job_id, {"gallons_removed": 500, "feet_cleaned": 40}, PM
            )
        )
        assert completed["execution_status"] == "FIELD_COMPLETE"


class TestInitialStates:
    def test_job_and_incident_initial_states(self, api):
        """PRD §3.2: "New jobs open with `execution_status` `QUOTED`,
        `safety_status` `CLEAR`, and `standby_accrued_cents` at zero."
        PRD §3.4: "the report enters as `REPORTED`."

        Design: Corner/state_machines/job_and_downtime_and_incident_initial_states
        """
        site, _ = create_site_with_active_schedule()
        job = create_job(site["id"], description="initial states")
        assert job["execution_status"] == "QUOTED"
        assert job["safety_status"] == "CLEAR"

        unit = create_equipment_unit()
        create_confirmed_equipment_assignment(job["id"], unit["id"])
        schedule_and_mobilize(job["id"])
        incident = get_success_data(
            api.create_incident(create_incident_payload(job["id"]), FS)
        )
        assert incident["status"] == "REPORTED"

    def test_near_miss_does_not_move_safety_status(self, api):
        """PRD §3.4: "Reporting a `SERIOUS` or `MAJOR` incident while the job's
        safety dimension is `CLEAR` immediately moves the job to `STOP_WORK`".

        Design: Corner/state_machines/job_and_downtime_and_incident_initial_states
        """
        site, _ = create_site_with_active_schedule()
        unit = create_equipment_unit()
        job = create_job(site["id"])
        create_confirmed_equipment_assignment(job["id"], unit["id"])
        schedule_and_mobilize(job["id"])
        get_success_data(api.create_incident(create_incident_payload(job["id"]), FS))
        job_after = get_success_data(api.get_job(job["id"], PM))
        assert job_after["safety_status"] == "CLEAR"


class TestJobCancelCascade:
    def test_cancel_from_terminal_state_rejected(self, api):
        """PRD §3.7: "Cancelling is available from `QUOTED`, `SCHEDULED`,
        `MOBILIZED`, `IN_PROGRESS` and `FIELD_COMPLETE` — never from `INVOICED`,
        `CLOSED` or `CANCELLED`".
        PRD §2.8: "terminal states accept no further transitions, else
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/job_cancel_from_terminal_state_rejected
        """
        site, _ = create_site_with_active_schedule()
        job = create_job(site["id"], description="cancel twice")
        get_success_data(api.cancel_job(job["id"], PM))
        resp = api.cancel_job(job["id"], PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_cancel_cascade_skips_terminal_children(self, api):
        """PRD §3.7: "A cancellation cascades: assignments in `SCHEDULED` or
        `CONFIRMED` move to `CANCELLED`; permits in `ISSUED`, `ACTIVE` or
        `SUSPENDED` move to `REVOKED`".

        Design: Corner/state_machines/job_cancel_conditional_cascade_skips_terminal_children
        """
        site, _ = create_site_with_active_schedule()
        unit_a = create_equipment_unit(unit_code="VAC-01")
        unit_b = create_equipment_unit(unit_code="VAC-02")
        job = create_job(site["id"], description="conditional cascade")
        asg_a = get_success_data(
            api.create_assignment(
                create_equipment_assignment_payload(job["id"], unit_a["id"]), PM
            )
        )
        asg_b = get_success_data(
            api.create_assignment(
                create_equipment_assignment_payload(job["id"], unit_b["id"]), PM
            )
        )
        get_success_data(api.confirm_assignment(asg_a["id"], PM))
        get_success_data(api.confirm_assignment(asg_b["id"], PM))
        get_success_data(api.release_assignment(asg_b["id"], PM))
        schedule_and_mobilize(job["id"])
        permit = get_success_data(
            api.create_permit(create_permit_payload(job["id"]), FS)
        )

        cancelled = get_success_data(api.cancel_job(job["id"], PM))
        assert cancelled["execution_status"] == "CANCELLED"

        a_after = get_success_data(api.get_assignment(asg_a["id"], PM))
        assert a_after["status"] == "CANCELLED"
        b_after = get_success_data(api.get_assignment(asg_b["id"], PM))
        assert b_after["status"] == "RELEASED"
        permit_after = get_success_data(api.get_permit(permit["id"], PM))
        assert permit_after["status"] == "REVOKED"
