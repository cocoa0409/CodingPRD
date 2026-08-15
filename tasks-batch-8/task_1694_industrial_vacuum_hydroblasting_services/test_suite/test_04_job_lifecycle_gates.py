"""Job lifecycle referential gates and cross-entity state dependencies."""
from test_helpers import (
    ApiErrorId,
    create_equipment_assignment_payload,
    create_job,
    create_site_with_active_schedule,
    get_success_data,
    validate_error,
    TEST_USERS,
)

PM = TEST_USERS["project_manager_headers"]
AM = TEST_USERS["account_manager_headers"]
PA = TEST_USERS["platform_admin_headers"]


class TestScheduleAndMobilizeGates:
    def test_schedule_without_assignments_rejected(self, api):
        """PRD §3.2: "Scheduling — `QUOTED` → `SCHEDULED` — requires at least one
        assignment still `SCHEDULED` or `CONFIRMED`, failing with
        `ERR_NO_ASSIGNMENTS` otherwise."

        Design: Corner/validations/schedule_requires_any_assignment_and_mobilize_requires_confirmed
        """
        site, _ = create_site_with_active_schedule()
        job = create_job(site["id"], description="job A")
        resp = api.schedule_job(job["id"], PM)
        validate_error(resp, ApiErrorId.ERR_NO_ASSIGNMENTS.value)
        assert resp.status_code == 422

    def test_mobilize_without_confirmed_assignment_rejected(self, api):
        """PRD §3.2: "Mobilizing — `SCHEDULED` → `MOBILIZED` — tightens the
        requirement to at least one `CONFIRMED` assignment, failing with
        `ERR_NO_CONFIRMED_CREW`."

        Design: Corner/validations/schedule_requires_any_assignment_and_mobilize_requires_confirmed
        """
        from test_helpers import create_equipment_unit
        site, _ = create_site_with_active_schedule()
        unit = create_equipment_unit()
        job = create_job(site["id"], description="job B")
        asg = get_success_data(
            api.create_assignment(
                create_equipment_assignment_payload(job["id"], unit["id"]), PM
            )
        )
        assert asg["status"] == "SCHEDULED"
        get_success_data(api.schedule_job(job["id"], PM))
        resp = api.mobilize_job(job["id"], PM)
        validate_error(resp, ApiErrorId.ERR_NO_CONFIRMED_CREW.value)
        assert resp.status_code == 422


class TestStartWorkJhaGate:
    def test_start_work_with_submitted_jha_rejected(self, api):
        """PRD §3.4: "An `APPROVED` hazard analysis revision must exist for the
        job, else `ERR_JHA_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/start_work_requires_approved_jha
        """
        from test_helpers import (
            create_confirmed_equipment_assignment,
            create_equipment_unit,
            create_jha_payload,
            schedule_and_mobilize,
        )
        site, _ = create_site_with_active_schedule()
        unit = create_equipment_unit(unit_type="COMBO", max_pressure_psi=10000)
        job = create_job(site["id"], job_type="COMBINED", description="Cross-entity A")
        create_confirmed_equipment_assignment(job["id"], unit["id"])
        schedule_and_mobilize(job["id"])
        jha = get_success_data(
            api.create_jha(
                create_jha_payload(
                    job["id"],
                    hazards=["HIGH_PRESSURE_WATER"],
                    max_operating_pressure_psi=5000,
                    planned_water_flow_gpm=20.0,
                    water_source="SITE_NONPOTABLE",
                ),
                TEST_USERS["field_supervisor_headers"],
            )
        )
        get_success_data(api.submit_jha(jha["id"], TEST_USERS["field_supervisor_headers"]))
        resp = api.start_work(job["id"], PM)
        validate_error(resp, ApiErrorId.ERR_JHA_NOT_APPROVED.value)
        job_after = get_success_data(api.get_job(job["id"], PM))
        assert job_after["execution_status"] == "MOBILIZED"

    def test_start_work_with_approved_jha_succeeds(self, api):
        """PRD §3.4: "An `APPROVED` hazard analysis revision must exist for the
        job, else `ERR_JHA_NOT_APPROVED`."
        PRD §3.4: "Starting work (`MOBILIZED` → `IN_PROGRESS`, by a
        `ProjectManager`)".

        Design: Difficulty/cross_entity_state_dependency/start_work_requires_approved_jha
        """
        from test_helpers import create_job_in_progress
        ctx = create_job_in_progress()
        assert ctx["job"]["execution_status"] == "IN_PROGRESS"
        assert ctx["job"]["safety_status"] == "CLEAR"


class TestValidationPriority:
    def test_state_error_beats_safety_error_on_start_work(self, api):
        """PRD §2.8: "Every request passes through a fixed validation pipeline,
        and the first failing check determines the error returned: ... 6. **State
        legality** — the target entity is in a from-state that permits the
        requested transition ... else `ERR_INVALID_STATE`. 7. **Business gates**
        ... (`ERR_JHA_NOT_APPROVED`) ...".

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_safety_error_on_start_work
        """
        from test_helpers import create_jha_payload
        site, _ = create_site_with_active_schedule()
        job = create_job(site["id"], description="Priority test A")
        # JHA exists only in DRAFT; job is QUOTED (not MOBILIZED).
        get_success_data(
            api.create_jha(
                create_jha_payload(job["id"]),
                TEST_USERS["field_supervisor_headers"],
            )
        )
        resp = api.start_work(job["id"], PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        assert resp.status_code == 409

    def test_start_work_on_quoted_job_rejected_invalid_state(self, api):
        """PRD §3.4: "Starting work (`MOBILIZED` → `IN_PROGRESS`, by a
        `ProjectManager`) evaluates six gates in order".
        PRD §2.8: "State legality — the target entity is in a from-state that
        permits the requested transition, and terminal states accept no further
        transitions, else `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_safety_error_on_start_work
        """
        site, _ = create_site_with_active_schedule()
        job = create_job(site["id"])
        resp = api.start_work(job["id"], PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        job_after = get_success_data(api.get_job(job["id"], PM))
        assert job_after["execution_status"] == "QUOTED"


class TestSafetyVsFiscalPriority:
    def test_permit_not_active_beats_credit_hold(self, api, account_manager_headers):
        """PRD §2.8: "7. **Business gates**, evaluated in a fixed relative order:
        ... before confined-space permit presence (`ERR_PERMIT_NOT_ACTIVE`) ...
        before the referential gates ..., and finally the fiscal gates
        (`ERR_SITE_CREDIT_HOLD`, then `ERR_FACILITY_CAPACITY_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/safety_error_beats_fiscal_error_on_start_work
        """
        from test_helpers import (
            create_confirmed_equipment_assignment,
            create_equipment_unit,
            create_pressure_plan_jha_payload,
            create_site_payload,
            create_rate_schedule_payload,
            schedule_and_mobilize,
        )
        site = get_success_data(
            api.create_site(create_site_payload(), account_manager_headers)
        )
        sched = get_success_data(
            api.create_rate_schedule(
                create_rate_schedule_payload(site["id"]), account_manager_headers
            )
        )
        get_success_data(
            api.activate_rate_schedule(
                sched["id"], {"expected_site_version": site["version"]},
                account_manager_headers,
            )
        )
        unit = create_equipment_unit(unit_type="COMBO", max_pressure_psi=10000)
        job = create_job(site["id"], job_type="COMBINED", description="Priority test B")
        create_confirmed_equipment_assignment(job["id"], unit["id"])
        schedule_and_mobilize(job["id"])

        FS = TEST_USERS["field_supervisor_headers"]
        SM = TEST_USERS["safety_manager_headers"]
        jha = get_success_data(
            api.create_jha(
                create_pressure_plan_jha_payload(
                    job["id"], confined_space=True, hazards=["CONFINED_SPACE"],
                    water_source="TRUCKED_IN",
                ),
                FS,
            )
        )
        get_success_data(api.submit_jha(jha["id"], FS))
        job_now = get_success_data(api.get_job(job["id"], PM))
        get_success_data(
            api.approve_jha(jha["id"], {"expected_job_version": job_now["version"]}, SM)
        )
        # No CONFINED_SPACE permit created; site placed on CREDIT_HOLD.
        get_success_data(
            api.update_site(site["id"], {"credit_status": "CREDIT_HOLD"}, account_manager_headers)
        )
        resp = api.start_work(job["id"], PM)
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ACTIVE.value)
        assert resp.status_code == 422

    def test_permit_not_active_raised_when_confined_jha_but_no_permit(self, api):
        """PRD §3.4: "When that approved analysis declares `confined_space` true,
        an `ACTIVE` permit of type `CONFINED_SPACE` must exist for the job, else
        `ERR_PERMIT_NOT_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/safety_error_beats_fiscal_error_on_start_work
        """
        from test_helpers import (
            create_confirmed_equipment_assignment,
            create_equipment_unit,
            create_pressure_plan_jha_payload,
            create_submit_approve_jha,
            schedule_and_mobilize,
        )
        site, _ = create_site_with_active_schedule()
        unit = create_equipment_unit(unit_type="COMBO", max_pressure_psi=10000)
        job = create_job(site["id"], job_type="COMBINED")
        create_confirmed_equipment_assignment(job["id"], unit["id"])
        schedule_and_mobilize(job["id"])
        create_submit_approve_jha(
            job["id"],
            jha_overrides={"confined_space": True, "hazards": ["CONFINED_SPACE"]},
            pressure_plan=True,
        )
        resp = api.start_work(job["id"], PM)
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ACTIVE.value)
        job_after = get_success_data(api.get_job(job["id"], PM))
        assert job_after["execution_status"] == "MOBILIZED"
