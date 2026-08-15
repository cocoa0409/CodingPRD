"""Energy surveys and lockout procedures: draft/approval cycle, revision
numbering, activation gating, and the modification-driven revision cycle."""
from test_helpers import (
    ApiErrorId,
    assert_energy_survey,
    assert_instant_equal,
    assert_lockout_procedure,
    bootstrap_manager,
    create_draft_procedure,
    create_energy_survey_payload,
    create_lockout_procedure_payload,
    create_machine,
    default_energy_sources,
    default_steps,
    get_procedure,
    get_survey,
    make_authorized_employee_headers,
    make_ehs_manager_headers,
    register_employee,
    register_modification,
    setup_machine_with_active_procedure,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSurveyCreation:
    def test_survey_isolation_point_count_is_derived(self, api):
        """PRD §3.2: "The server stamps the survey with the creator's identity as
        `surveyed_by_employee_id`, derives `isolation_point_count` as the number
        of entries in `energy_sources`, and starts the survey in `DRAFT`."

        Design: Corner/entities/survey_computed_field_input_ignored
        """
        mgr = bootstrap_manager("E-MGR-CF", "Mgr CF")
        surveyor = register_employee(mgr, "E-W1-CF", "W1 CF")
        machine = create_machine(mgr, asset_tag="A-CF-1", name="Mill", area="Bay 4")
        payload = create_energy_survey_payload(
            machine["id"], energy_sources=default_energy_sources(2))
        payload["isolation_point_count"] = 99  # client-sent computed field
        survey = validate_success(api.create_energy_survey(
            payload, make_authorized_employee_headers(surveyor["id"])),
            expected_status=201)
        assert_energy_survey(survey)
        assert survey["isolation_point_count"] == 2, \
            "isolation_point_count is derived from energy_sources, not the payload"
        assert survey["status"] == "DRAFT"


class TestSurveyReviewCycle:
    def test_survey_reject_then_resubmit_returns_to_submitted(self, api):
        """PRD §3.2: "Rejection — which may carry an optional `reason` — moves it
        to `REJECTED`, which is not terminal: the original surveyor may resubmit
        the survey, moving `REJECTED` back to `SUBMITTED` under the same
        ownership rule, as many times as needed until it is approved."

        Design: Difficulty/non_linear_state_machine/survey_reject_resubmit_cycle
        """
        mgr = bootstrap_manager("E-MGR-SC", "Mgr SC")
        surveyor = register_employee(mgr, "E-W1-SC", "W1 SC")
        machine = create_machine(mgr, asset_tag="A-SC-100", name="Press M",
                                 area="Line 5")
        survey = validate_success(api.create_energy_survey(
            create_energy_survey_payload(
                machine["id"], energy_sources=default_energy_sources(2)),
            make_authorized_employee_headers(surveyor["id"])), expected_status=201)

        surveyor_headers = make_authorized_employee_headers(surveyor["id"])
        submitted = validate_success(api.submit_energy_survey(
            survey["id"], surveyor_headers))
        assert submitted["status"] == "SUBMITTED"

        rejected = validate_success(api.reject_energy_survey(
            survey["id"], make_ehs_manager_headers(mgr["id"]),
            payload={"reason": "Missing gravity hazard on ram"}))
        assert rejected["status"] == "REJECTED", "rejection moves the survey to REJECTED"

        resubmitted = validate_success(api.submit_energy_survey(
            survey["id"], surveyor_headers))
        assert resubmitted["status"] == "SUBMITTED", \
            "REJECTED is not terminal: the surveyor may resubmit"
        assert resubmitted["id"] == survey["id"], "resubmission retains identity"
        assert resubmitted["surveyed_by_employee_id"] == surveyor["id"]

    def test_survey_resubmit_cycle_terminates_at_approved(self, api):
        """PRD §3.2: "Rejection — which may carry an optional `reason` — moves it
        to `REJECTED`, which is not terminal: the original surveyor may resubmit
        the survey, moving `REJECTED` back to `SUBMITTED` under the same
        ownership rule, as many times as needed until it is approved."
        PRD §3.2: "Approval moves the survey to `APPROVED`, its terminal state."

        Design: Difficulty/non_linear_state_machine/survey_reject_resubmit_cycle
        """
        mgr = bootstrap_manager("E-MGR-SC2", "Mgr SC2")
        surveyor = register_employee(mgr, "E-W1-SC2", "W1 SC2")
        machine = create_machine(mgr, asset_tag="A-SC2-100", name="Press M2",
                                 area="Line 5")
        surveyor_headers = make_authorized_employee_headers(surveyor["id"])
        survey = validate_success(api.create_energy_survey(
            create_energy_survey_payload(
                machine["id"], energy_sources=default_energy_sources(2)),
            surveyor_headers), expected_status=201)

        validate_success(api.submit_energy_survey(survey["id"], surveyor_headers))
        validate_success(api.reject_energy_survey(
            survey["id"], make_ehs_manager_headers(mgr["id"]),
            payload={"reason": "Missing gravity hazard on ram"}))
        validate_success(api.submit_energy_survey(survey["id"], surveyor_headers))
        approved = validate_success(api.approve_energy_survey(
            survey["id"], make_ehs_manager_headers(mgr["id"])))

        assert approved["status"] == "APPROVED", \
            "SUBMITTED -> REJECTED -> SUBMITTED -> APPROVED completes the cycle"
        assert approved["isolation_point_count"] == 2
        assert approved["surveyed_by_employee_id"] == surveyor["id"], \
            "surveyor identity is preserved through the rejection cycle"


class TestSurveyApprovalRules:
    def test_approve_from_draft_returns_invalid_state(self, api):
        """PRD §3.2: "An `EHSManager` approves or rejects a submitted survey, but
        the manager must not be the surveyor; a self-approval or self-rejection
        attempt fails with `ERR_SELF_APPROVAL_FORBIDDEN`."
        PRD §2.8: "State-machine legality — the requested transition must exist
        from the entity's current state — otherwise `ERR_INVALID_STATE`." (listed
        as check 7, ahead of segregation of duties as check 8, in the fixed
        pipeline where "the first failing check determines the error returned")

        Design: Corner/state_machines/survey_approve_from_draft_returns_invalid_state
        """
        mgr = bootstrap_manager("E-MGR-IV3", "Mgr IV3")
        surveyor = register_employee(mgr, "E-W1-IV3", "W1 IV3")
        machine = create_machine(mgr, asset_tag="A-IV3-1", name="Press",
                                 area="Bay 10")
        survey = validate_success(api.create_energy_survey(
            create_energy_survey_payload(machine["id"]),
            make_authorized_employee_headers(surveyor["id"])), expected_status=201)
        assert survey["status"] == "DRAFT"

        resp = api.approve_energy_survey(
            survey["id"], make_ehs_manager_headers(mgr["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_survey(mgr, survey["id"])["status"] == "DRAFT"


class TestProcedureAuthoring:
    def test_revision_no_increments_per_machine(self, api):
        """PRD §3.3: "The server assigns the new row's `revision_no` as one more
        than the count of prior procedure rows for that machine, snapshots
        `isolation_point_count` from the survey at creation time (the snapshot is
        never re-read later), and starts the procedure in `DRAFT`."
        PRD §3.3: "One structural rule guards authoring: a machine may carry at
        most one procedure in `DRAFT` or `ACTIVE` status at a time, with a single
        relaxation — while the machine's current procedure sits in
        `UNDER_REVISION`, one successor `DRAFT` may be created alongside it."

        Design: Corner/entities/procedure_revision_no_increments_per_machine
        """
        mgr = bootstrap_manager("E-MGR-RN", "Mgr RN")
        surveyor = register_employee(mgr, "E-W1-RN", "W1 RN")
        machine, survey, p1 = setup_machine_with_active_procedure(
            mgr, surveyor, asset_tag="A-RN-1", name="Saw", area="Bay 5")
        assert p1["revision_no"] == 1, "first procedure row for the machine"
        assert p1["status"] == "ACTIVE"

        register_modification(mgr, machine["id"], "Added second feed roller")
        p1_after = get_procedure(mgr, p1["id"])
        assert p1_after["status"] == "UNDER_REVISION"

        p2 = validate_success(api.create_lockout_procedure(
            create_lockout_procedure_payload(machine["id"], survey["id"],
                                             steps=default_steps(2)),
            make_ehs_manager_headers(mgr["id"])), expected_status=201)
        assert_lockout_procedure(p2)
        assert p2["revision_no"] == 2, "one more than the count of prior rows"
        assert p2["status"] == "DRAFT"
        assert get_procedure(mgr, p1["id"])["revision_no"] == 1

    def test_second_draft_procedure_while_active_rejected(self, api):
        """PRD §3.3: "One structural rule guards authoring: a machine may carry
        at most one procedure in `DRAFT` or `ACTIVE` status at a time, with a
        single relaxation — while the machine's current procedure sits in
        `UNDER_REVISION`, one successor `DRAFT` may be created alongside it. Any
        other configuration is refused with `ERR_PROCEDURE_CONFLICT`."

        Design: Corner/validations/second_draft_procedure_while_active_rejected
        """
        mgr = bootstrap_manager("E-MGR-PX", "Mgr PX")
        surveyor = register_employee(mgr, "E-W1-PX", "W1 PX")
        machine, survey, p1 = setup_machine_with_active_procedure(
            mgr, surveyor, asset_tag="A-PX-1", name="Press", area="Bay 36")
        assert p1["status"] == "ACTIVE"

        resp = api.create_lockout_procedure(
            create_lockout_procedure_payload(
                machine["id"], survey["id"],
                steps=[{"step_no": 1, "action": "Alt step",
                        "isolation_point": "DP-1"}]),
            make_ehs_manager_headers(mgr["id"]))
        validate_error(resp, ApiErrorId.ERR_PROCEDURE_CONFLICT)
        _procs, meta = validate_paginated(api.list_lockout_procedures(
            make_ehs_manager_headers(mgr["id"]), params={"machine_id": machine["id"]}))
        assert meta["total_count"] == 1, "no second procedure row is persisted"


class TestProcedureActivationGating:
    def test_activation_rejected_while_survey_not_approved(self, api):
        """PRD §3.3: "When an `EHSManager` activates a `DRAFT` procedure, its
        survey must be `APPROVED`, failing which the attempt is rejected with
        `ERR_SURVEY_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/procedure_activation_gated_by_survey_state
        """
        mgr = bootstrap_manager("E-MGR-PG", "Mgr PG")
        surveyor = register_employee(mgr, "E-W1-PG", "W1 PG")
        machine = create_machine(mgr, asset_tag="A-PG-100", name="Press PG",
                                 area="Line 13")
        surveyor_headers = make_authorized_employee_headers(surveyor["id"])
        survey = validate_success(api.create_energy_survey(
            create_energy_survey_payload(machine["id"]), surveyor_headers),
            expected_status=201)
        validate_success(api.submit_energy_survey(survey["id"], surveyor_headers))
        procedure = create_draft_procedure(mgr, machine["id"], survey["id"])

        resp = api.activate_lockout_procedure(
            procedure["id"], {}, make_ehs_manager_headers(mgr["id"]))
        validate_error(resp, ApiErrorId.ERR_SURVEY_NOT_APPROVED)
        assert get_procedure(mgr, procedure["id"])["status"] == "DRAFT", \
            "the procedure stays DRAFT while its survey is merely SUBMITTED"

    def test_activation_succeeds_after_survey_approval(self, api):
        """PRD §3.3: "When an `EHSManager` activates a `DRAFT` procedure, its
        survey must be `APPROVED`, failing which the attempt is rejected with
        `ERR_SURVEY_NOT_APPROVED`."
        PRD §3.3: "On this first activation the server stamps `activated_at` with
        the clock and computes `audit_due_at` 365 days later; any sibling
        procedure of the same machine sitting in `UNDER_REVISION` is
        automatically superseded (moving to `SUPERSEDED`); and every modification
        log entry on the machine still marked `UNREVIEWED` is flipped to
        `REVIEWED`."
        PRD §2.4: "Before the clock has been explicitly set, it reads exactly
        2026-08-01T00:00:00Z; the server must never fall back to wall-clock time."

        Design: Difficulty/cross_entity_state_dependency/procedure_activation_gated_by_survey_state
        """
        mgr = bootstrap_manager("E-MGR-PG2", "Mgr PG2")
        surveyor = register_employee(mgr, "E-W1-PG2", "W1 PG2")
        machine = create_machine(mgr, asset_tag="A-PG2-100", name="Press PG2",
                                 area="Line 13")
        surveyor_headers = make_authorized_employee_headers(surveyor["id"])
        survey = validate_success(api.create_energy_survey(
            create_energy_survey_payload(machine["id"]), surveyor_headers),
            expected_status=201)
        validate_success(api.submit_energy_survey(survey["id"], surveyor_headers))
        procedure = create_draft_procedure(mgr, machine["id"], survey["id"])
        validate_success(api.approve_energy_survey(
            survey["id"], make_ehs_manager_headers(mgr["id"])))

        activated = validate_success(api.activate_lockout_procedure(
            procedure["id"], {}, make_ehs_manager_headers(mgr["id"])))
        assert_lockout_procedure(activated)
        assert activated["status"] == "ACTIVE"
        assert_instant_equal(activated["activated_at"], "2026-08-01T00:00:00Z")
        assert_instant_equal(activated["audit_due_at"], "2027-08-01T00:00:00Z")


class TestProcedureRevisionCycle:
    def _setup_under_revision(self, api, suffix=""):
        """Machine + APPROVED survey + ACTIVE procedure + one modification."""
        mgr = bootstrap_manager(f"E-MGR-RC{suffix}", "Mgr RC")
        surveyor = register_employee(mgr, f"E-W1-RC{suffix}", "W1 RC")
        machine, survey, procedure = setup_machine_with_active_procedure(
            mgr, surveyor, asset_tag=f"A-RC{suffix}-100", name="Saw M",
            area="Line 4")
        return mgr, machine, procedure

    def test_modification_pushes_active_procedure_under_revision(self, api):
        """PRD §3.3: "Second, the modification is logged with `review_status`
        `UNREVIEWED`, and if the machine has an `ACTIVE` procedure, that
        procedure is automatically pushed to `UNDER_REVISION`; that cascade in
        turn cancels every session of the machine still in `SETUP`, voids each
        cancelled session's `ISSUED` locks, and recomputes the machine's
        `open_session_count`."

        Design: Difficulty/non_linear_state_machine/procedure_revision_cycle_reactivation
        """
        mgr, machine, procedure = self._setup_under_revision(api)
        mod = register_modification(mgr, machine["id"],
                                    "Added pneumatic clamp circuit")
        assert mod["review_status"] == "UNREVIEWED"
        after = get_procedure(mgr, procedure["id"])
        assert after["status"] == "UNDER_REVISION", \
            "the ACTIVE procedure is automatically pushed to UNDER_REVISION"
        assert after["revision_no"] == 1

    def test_reactivation_closes_cycle_preserving_anchors(self, api):
        """PRD §3.3: "Re-activation closes the revision loop without creating a
        new revision row."
        PRD §3.3: "Re-activation leaves `activated_at` untouched and does not
        move `audit_due_at`, which remains keyed to the last completed audit or
        first activation; it flips all remaining `UNREVIEWED` modifications of
        the machine to `REVIEWED` and returns the procedure to `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/procedure_revision_cycle_reactivation
        """
        mgr, machine, procedure = self._setup_under_revision(api, suffix="B")
        activated_at = procedure["activated_at"]
        audit_due_at = procedure["audit_due_at"]
        headers = make_ehs_manager_headers(mgr["id"])
        mod = register_modification(mgr, machine["id"],
                                    "Added pneumatic clamp circuit")
        assert get_procedure(mgr, procedure["id"])["status"] == "UNDER_REVISION"

        reactivated = validate_success(api.activate_lockout_procedure(
            procedure["id"],
            {"revalidation_note": "Reviewed: clamp circuit covered by existing step 1"},
            headers))
        assert reactivated["status"] == "ACTIVE", "cycle closes on the same row"
        assert reactivated["revision_no"] == 1, \
            "re-activation creates no new revision row"
        assert_instant_equal(reactivated["activated_at"], activated_at)
        assert_instant_equal(reactivated["audit_due_at"], audit_due_at)
        mods, _meta = validate_paginated(
            api.list_machine_modifications(machine["id"], headers))
        assert mods[0]["id"] == mod["id"]
        assert mods[0]["review_status"] == "REVIEWED", \
            "re-activation flips UNREVIEWED modifications to REVIEWED"


class TestProcedureReactivationValidation:
    def test_reactivation_missing_note_returns_400(self, api):
        """PRD §3.3: "Activating a procedure that sits in `UNDER_REVISION`
        requires the survey to be `APPROVED` (again `ERR_SURVEY_NOT_APPROVED`)
        and additionally requires a `revalidation_note` in the payload, absent
        which the request fails with `ERR_VALIDATION`."

        Design: Corner/validations/procedure_reactivation_missing_note_returns_invalid_request
        """
        mgr = bootstrap_manager("E-MGR-RVN", "Mgr RVN")
        surveyor = register_employee(mgr, "E-W1-RVN", "W1 RVN")
        machine, survey, procedure = setup_machine_with_active_procedure(
            mgr, surveyor, asset_tag="A-RVN-1", name="Press", area="Bay 25")
        register_modification(mgr, machine["id"], "Swapped motor")
        assert get_procedure(mgr, procedure["id"])["status"] == "UNDER_REVISION"

        resp = api.activate_lockout_procedure(
            procedure["id"], {}, make_ehs_manager_headers(mgr["id"]))
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        assert get_procedure(mgr, procedure["id"])["status"] == "UNDER_REVISION"


class TestProcedureRetirement:
    def test_retired_procedure_is_terminal(self, api):
        """PRD §3.3: "Retirement is available from `DRAFT`, from `ACTIVE`, and
        from `UNDER_REVISION`, but only while no session referencing the
        procedure is in `SETUP`, `LOCKED`, or `CLEARED`; otherwise the request
        fails with `ERR_PROCEDURE_IN_USE`. Both `RETIRED` and `SUPERSEDED` are
        terminal."

        Design: Corner/state_machines/procedure_terminal_lockdown_retired
        """
        mgr = bootstrap_manager("E-MGR-TL2", "Mgr TL2")
        surveyor = register_employee(mgr, "E-W1-TL2", "W1 TL2")
        machine, survey, procedure = setup_machine_with_active_procedure(
            mgr, surveyor, asset_tag="A-TL2-1", name="Press", area="Bay 13")
        retired = validate_success(api.retire_lockout_procedure(
            procedure["id"], make_ehs_manager_headers(mgr["id"])))
        assert retired["status"] == "RETIRED"

        resp = api.activate_lockout_procedure(
            procedure["id"], {}, make_ehs_manager_headers(mgr["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_procedure(mgr, procedure["id"])["status"] == "RETIRED"
