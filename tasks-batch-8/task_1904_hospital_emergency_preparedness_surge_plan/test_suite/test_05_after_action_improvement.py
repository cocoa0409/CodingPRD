"""After-action reports and improvement tasks: subject-state gate, one-AAR-per-
subject, task workflow legality, clock-driven overdue sweep, and SoD on approval."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_improvement_task,
    create_after_action_report_payload,
    create_and_demobilize_incident,
    create_incident,
    create_open_task,
    create_staff_member,
    make_hospital_administrator_headers,
    make_incident_commander_headers,
    set_clock,
    validate_error,
    validate_success,
)

EM = TEST_USERS["emergency_manager_headers"]
IC = TEST_USERS["incident_commander_headers"]
HA = TEST_USERS["hospital_administrator_headers"]


class TestAfterActionSubjectGate:
    def test_aar_create_requires_subject_terminal_state(self, api):
        """PRD §3.3: "An `AfterActionReport` names its subject polymorphically:
        `subject_type` is `EXERCISE` or `INCIDENT`, and `subject_id` references a
        `COMPLETED` exercise or a `DEACTIVATED` incident accordingly; a create
        whose subject is not in the required state fails the generic state guard
        with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/aar_create_requires_subject_terminal_state
        """
        incident = create_incident(incident_name="MCI-aar-early")
        resp = api.create_after_action_report(
            create_after_action_report_payload("INCIDENT", incident["id"],
                                               summary="too early"),
            IC,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_aar_duplicate_subject_rejected(self, api):
        """PRD §3.3: "At most one report may exist per subject; a duplicate create
        against the same `subject_type` and `subject_id` is rejected with
        `ERR_AAR_ALREADY_EXISTS`."

        Design: Corner/validations/aar_duplicate_subject_rejected
        """
        incident = create_and_demobilize_incident(incident_name="MCI-dup-aar")
        first = api.create_after_action_report(
            create_after_action_report_payload("INCIDENT", incident["id"],
                                               summary="first"),
            IC,
        )
        validate_success(first, expected_status=201)
        resp = api.create_after_action_report(
            create_after_action_report_payload("INCIDENT", incident["id"],
                                               summary="second"),
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_AAR_ALREADY_EXISTS)


class TestImprovementTaskWorkflow:
    def test_improvement_task_skip_in_progress_rejected(self, api):
        """PRD §3.3: "Progression is driven by patching `target_status`: `OPEN` →
        `IN_PROGRESS`, then `IN_PROGRESS` → `VERIFIED_COMPLETE`, which is terminal,
        each patch advancing the task's `version`."
        PRD §2.11: "8. State-transition legality on the target resource — the
        generic guard that rejects any action whose target's current state does
        not permit it: `ERR_INVALID_STATE`."

        Design: Corner/state_machines/improvement_task_skip_in_progress_rejected
        """
        task, _aar, _inc = create_open_task(description="Fix cache signage",
                                            priority="LOW")
        assert task["status"] == "OPEN"
        resp = api.patch_improvement_task(task["id"], {"target_status": "VERIFIED_COMPLETE"}, EM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        reread = validate_success(api.get_improvement_task(task["id"], EM))
        assert reread["status"] == "OPEN", "OPEN may not jump to VERIFIED_COMPLETE"

    def test_improvement_task_clock_sweep_marks_overdue(self, api):
        """PRD §2.5: "Setting the clock triggers two sweeps. Every call-back
        request still in `PENDING` whose `expires_at` lies strictly before the new
        clock time transitions to `EXPIRED`, and every improvement task in `OPEN`
        or `IN_PROGRESS` whose `due_date` lies strictly before the new clock time
        transitions to `OVERDUE`."
        PRD §2.5: "The capability's response reports the new `current_utc` along
        with the counts `swept_callbacks` and `swept_tasks`."

        Design: Corner/state_machines/improvement_task_clock_sweep_marks_overdue
        """
        task, _aar, _inc = create_open_task(description="Restock trailer",
                                            priority="HIGH",
                                            due_date="2026-08-02T00:00:00Z")
        report = set_clock("2026-08-03T00:00:00Z")
        assert report["swept_tasks"] == 1
        reread = validate_success(api.get_improvement_task(task["id"], EM))
        assert_improvement_task(reread)
        assert reread["status"] == "OVERDUE"


class TestComplianceRoles:
    def test_rbac_hospital_admin_cannot_patch_improvement_task(self, api):
        """PRD §2.1: "A request that is authenticated but whose role is not
        authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."
        PRD §4: "PATCH | `/emergency/improvement-tasks/{id}` | Advance task status
        per the task state machine | EmergencyManager".

        Design: Corner/rbac/rbac_hospital_admin_cannot_patch_improvement_task
        """
        task, _aar, _inc = create_open_task(description="Task", priority="MEDIUM",
                                            assigned_department="NURSING")
        resp = api.patch_improvement_task(task["id"], {"target_status": "IN_PROGRESS"}, HA)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        reread = validate_success(api.get_improvement_task(task["id"], EM))
        assert reread["status"] == "OPEN"

    def test_aar_approve_by_creator_rejected_segregation(self, api):
        """PRD §2.7: "An after-action report likewise records `created_by_id`, and
        its approval is rejected the same way."

        Design: Corner/rbac/aar_approve_by_creator_rejected_segregation
        """
        commander = create_staff_member(full_name="Ic", department="ADMINISTRATION",
                                        role_qualifications=["INCIDENT_COMMANDER"])
        admin = create_staff_member(full_name="Ha", department="ADMINISTRATION")
        ic_as_commander = make_incident_commander_headers(commander["id"])

        incident = validate_success(
            api.create_incident(
                {"incident_name": "MCI-aar-sod", "incident_type": "NATURAL",
                 "declared_at": "2026-08-01T00:00:00Z"},
                ic_as_commander,
            ),
            expected_status=201,
        )
        validate_success(api.demobilize_incident(incident["id"], ic_as_commander))
        aar = validate_success(
            api.create_after_action_report(
                create_after_action_report_payload("INCIDENT", incident["id"],
                                                   summary="AAR"),
                ic_as_commander,
            ),
            expected_status=201,
        )
        validate_success(api.submit_after_action_report(aar["id"], ic_as_commander))

        resp = api.approve_after_action_report(
            aar["id"], make_hospital_administrator_headers(commander["id"])
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        approved = validate_success(
            api.approve_after_action_report(
                aar["id"], make_hospital_administrator_headers(admin["id"])
            )
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_id"] == admin["id"]
