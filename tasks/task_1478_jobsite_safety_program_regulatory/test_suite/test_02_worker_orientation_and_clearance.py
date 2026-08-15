"""Workforce gating: conditional employer fields, orientation prerequisites,
training-based clearance, standing and posture gates, and the terminal REMOVED
lockdown (PRD §3.2, §3.7)."""
from test_helpers import (
    ApiErrorId, api_client,
    validate_error, validate_success,
    create_project, create_plan, create_project_with_active_plan,
    create_subcontractor, create_worker, create_oriented_worker,
    create_cleared_worker, create_verified_certificate, create_certificate,
    complete_orientation, clear_worker, get_worker, probation_review,
    create_completed_inspection, create_deficiency, create_incident,
    set_clock,
    make_safety_manager_headers, make_site_superintendent_headers,
)

SM = make_safety_manager_headers()
SS = make_site_superintendent_headers()


def _drive_sub_to_probation(project_id: str, sub_id: str, inspector_id: str = "insp-1"):
    """Two OPEN MAJOR deficiencies -> realtime 70 (< 80) -> DEMOTE to PROBATION."""
    inspection = create_completed_inspection(project_id, inspector_id=inspector_id)
    create_deficiency(inspection["id"], "guardrail A", "MAJOR",
                      assigned_subcontractor_id=sub_id, creator_id=inspector_id)
    create_deficiency(inspection["id"], "guardrail B", "MAJOR",
                      assigned_subcontractor_id=sub_id, creator_id=inspector_id)
    return probation_review(sub_id, "DEMOTE")


class TestWorkerConditionalFields:

    def test_employer_type_conditional_subcontractor_field(self, api):
        """PRD §3.2: "When the employer type is `SUBCONTRACTOR`, the payload must
        also carry `subcontractor_id` identifying the engaging firm; when the type
        is `DIRECT`, `subcontractor_id` must be null. Violating either conditional
        rule is an `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §2.9: "Fourth (priority 4): request shape — all required fields present"

        Design: Corner/entities/worker_conditional_subcontractor_field_rejected
        """
        project = create_project(name="Hill", location="Renton",
                                 annual_hours_worked=30000)
        sub = create_subcontractor(project["id"], company_name="Amp",
                                   trade="electrical")

        # DIRECT worker carrying a subcontractor_id violates the conditional rule.
        resp1 = api.create_worker(
            {"project_id": project["id"], "full_name": "Bad Direct",
             "employer_type": "DIRECT", "subcontractor_id": sub["id"]}, SS,
        )
        validate_error(resp1, ApiErrorId.ERR_INVALID_REQUEST)

        # SUBCONTRACTOR worker without subcontractor_id violates it symmetrically.
        resp2 = api.create_worker(
            {"project_id": project["id"], "full_name": "Bad Sub",
             "employer_type": "SUBCONTRACTOR"}, SS,
        )
        validate_error(resp2, ApiErrorId.ERR_INVALID_REQUEST)

        # Missing employer_type entirely is a required-field shape failure.
        resp3 = api.create_worker(
            {"project_id": project["id"], "full_name": "No Type"}, SS,
        )
        validate_error(resp3, ApiErrorId.ERR_INVALID_REQUEST)


class TestOrientation:

    def test_orientation_requires_active_plan(self, api):
        """PRD §3.2: "it requires the worker's project to have a plan in `ACTIVE`
        status, failing with `ERR_NO_ACTIVE_SAFETY_PLAN` when none exists"

        Design: Corner/validations/orientation_requires_active_plan
        """
        project = create_project(name="Wedgwood", location="Seattle",
                                 annual_hours_worked=8000)
        # A DRAFT plan that was never activated does not satisfy the gate.
        create_plan(project["id"], effective_date="2026-08-01")
        worker = create_worker(project["id"], full_name="B Coe")
        resp = api.complete_orientation(worker["id"], {}, SS)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_SAFETY_PLAN)


class TestClearanceTrainingGate:

    def test_clear_rejected_until_certificate_verified(self, api):
        """PRD §3.2: "a non-supervisor must hold a `VERIFIED`, non-expired
        certificate of either type `OSHA_10` or `OSHA_30`, where non-expired means
        the current time is at or before the end of the certificate's
        `expires_date`. Failing the training bar is rejected with
        `ERR_TRAINING_REQUIREMENT_NOT_MET` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/worker_clear_requires_verified_cert
        """
        set_clock("2026-08-01T08:00:00Z")
        project, _plan = create_project_with_active_plan(
            name="Alley 24", annual_hours_worked=50000
        )
        worker = create_worker(project["id"], full_name="J Kim")
        cert = create_certificate(worker["id"], cert_type="OSHA_10")
        complete_orientation(worker["id"])

        # The only certificate is UNVERIFIED: clearance is rejected 422.
        resp_blocked = api.clear_worker(worker["id"], {}, SS)
        validate_error(resp_blocked, ApiErrorId.ERR_TRAINING_REQUIREMENT_NOT_MET)
        assert get_worker(worker["id"])["status"] == "ORIENTED"

        # Once the certificate reaches VERIFIED, the same clearance succeeds.
        from test_helpers import verify_certificate
        verify_certificate(cert["id"], "insp-1")
        data = validate_success(api.clear_worker(worker["id"], {}, SS), 200)
        assert data["status"] == "CLEARED"

    def test_supervisor_clearance_requires_osha30(self, api):
        """PRD §3.2: "a supervisor must hold a `VERIFIED`, non-expired certificate
        of type `OSHA_30`; a non-supervisor must hold a `VERIFIED`, non-expired
        certificate of either type `OSHA_10` or `OSHA_30`, where non-expired means
        the current time is at or before the end of the certificate's
        `expires_date`. Failing the training bar is rejected with
        `ERR_TRAINING_REQUIREMENT_NOT_MET` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/worker_clear_requires_verified_cert
        """
        set_clock("2026-08-01T08:00:00Z")
        project, _plan = create_project_with_active_plan(
            name="Alley 24 Annex", annual_hours_worked=51000
        )
        worker = create_worker(project["id"], full_name="J Kim Sr",
                               is_supervisor=True)
        # A VERIFIED OSHA_10 does not satisfy the supervisor bar.
        create_verified_certificate(worker["id"], cert_type="OSHA_10",
                                    issued_date="2026-07-01",
                                    expires_date="2027-07-01")
        complete_orientation(worker["id"])
        resp_blocked = api.clear_worker(worker["id"], {}, SS)
        validate_error(resp_blocked, ApiErrorId.ERR_TRAINING_REQUIREMENT_NOT_MET)

        # Adding a VERIFIED OSHA_30 satisfies the supervisor training bar.
        create_verified_certificate(worker["id"], cert_type="OSHA_30",
                                    issued_date="2026-07-02",
                                    expires_date="2027-07-02")
        data = validate_success(api.clear_worker(worker["id"], {}, SS), 200)
        assert data["status"] == "CLEARED"


class TestClearanceStandingAndPostureGates:

    def test_probation_standing_blocks_worker_clear(self, api):
        """PRD §3.2: "for a worker whose employer type is `SUBCONTRACTOR`, the
        linked subcontractor's `standing` must be `GOOD_STANDING`, failing with
        `ERR_SUBCONTRACTOR_NOT_IN_GOOD_STANDING`."

        Design: Corner/validations/subcontractor_probation_blocks_worker_clear
        """
        set_clock("2026-08-01T08:00:00Z")
        project, _plan = create_project_with_active_plan(
            name="Sand Point", annual_hours_worked=58000
        )
        sub = create_subcontractor(project["id"], company_name="Amp Electric",
                                   trade="electrical")
        worker = create_worker(project["id"], full_name="C Dow",
                               employer_type="SUBCONTRACTOR",
                               subcontractor_id=sub["id"])
        create_verified_certificate(worker["id"], cert_type="OSHA_10")
        complete_orientation(worker["id"])
        _drive_sub_to_probation(project["id"], sub["id"])

        resp = api.clear_worker(worker["id"], {}, SS)
        validate_error(resp, ApiErrorId.ERR_SUBCONTRACTOR_NOT_IN_GOOD_STANDING)
        assert get_worker(worker["id"])["status"] == "ORIENTED"

    def test_frozen_posture_blocks_worker_clear(self, api):
        """PRD §3.2: "the project's `safety_posture` must not be `FROZEN`, failing
        with `ERR_PROJECT_POSTURE_BLOCKED`."
        PRD §2.6: "the posture is `FROZEN` if the project has any deficiency of
        severity `IMMINENT_DANGER` in status `OPEN` or `OVERDUE`, or any incident
        of severity `CRITICAL` or `FATALITY` in status `REPORTED`,
        `UNDER_INVESTIGATION`, or `DETERMINATION_MADE`."

        Design: Corner/validations/posture_frozen_blocks_worker_clear
        """
        set_clock("2026-08-01T08:00:00Z")
        project, _plan = create_project_with_active_plan(
            name="Roxhill", annual_hours_worked=33000
        )
        worker = create_worker(project["id"], full_name="X Yang")
        create_verified_certificate(worker["id"], cert_type="OSHA_10")
        complete_orientation(worker["id"])
        # An open CRITICAL incident freezes the project.
        create_incident(project["id"], incident_type="INJURY", severity="CRITICAL",
                        occurred_at="2026-08-02T08:00:00Z", work_related=True,
                        description="structural collapse, no worker identified")

        resp = api.clear_worker(worker["id"], {}, SS)
        validate_error(resp, ApiErrorId.ERR_PROJECT_POSTURE_BLOCKED)
        assert get_worker(worker["id"])["status"] == "ORIENTED"


class TestWorkerTerminalAndInvalidStates:

    def test_removed_worker_rejects_suspend(self, api):
        """PRD §3.2: "A clearance attempted from any state other than `ORIENTED` —
        including the terminal `REMOVED` state, which is a lockdown — fails with
        `ERR_WORKER_INVALID_STATE`."
        PRD §3.7: "every worker of that subcontractor in status `ORIENTED` or
        `CLEARED` is removed"

        Design: Corner/state_machines/removed_worker_terminal_lockdown
        """
        set_clock("2026-08-01T08:00:00Z")
        project, _plan = create_project_with_active_plan(
            name="Eastgate", location="Bellevue", annual_hours_worked=55000
        )
        sub = create_subcontractor(project["id"], company_name="Rusty Nails GC",
                                   trade="carpentry")
        worker = create_worker(project["id"], full_name="R Sousa",
                               employer_type="SUBCONTRACTOR",
                               subcontractor_id=sub["id"])
        complete_orientation(worker["id"])
        _drive_sub_to_probation(project["id"], sub["id"])
        resp_remove = api.remove_subcontractor(sub["id"],
                                               {"reason": "repeated deficiencies"}, SM)
        validate_success(resp_remove, 200)

        # The removal cascade drove the ORIENTED worker to terminal REMOVED.
        worker_after = get_worker(worker["id"])
        assert worker_after["status"] == "REMOVED", (
            f"sub-worker must cascade to REMOVED, got {worker_after['status']}"
        )

        # REMOVED is a lockdown: a further worker action is rejected.
        resp = api.suspend_worker(worker["id"], {"reason": "too late"}, SM)
        validate_error(resp, ApiErrorId.ERR_WORKER_INVALID_STATE)

    def test_suspend_from_pending_orientation_rejected(self, api):
        """PRD §3.2: "Suspension is a manual safety action available to a
        `SafetyManager` against a worker in `ORIENTED` or `CLEARED`"

        Design: Corner/errors/worker_suspend_from_pending_orientation_rejected
        """
        project = create_project(name="Dunlap", location="Seattle",
                                 annual_hours_worked=7000)
        worker = create_worker(project["id"], full_name="I Jung")
        resp = api.suspend_worker(worker["id"], {"reason": "too early"}, SM)
        validate_error(resp, ApiErrorId.ERR_WORKER_INVALID_STATE)
