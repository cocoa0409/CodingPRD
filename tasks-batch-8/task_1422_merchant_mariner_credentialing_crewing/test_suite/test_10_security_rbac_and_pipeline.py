"""Auth headers, role authorization, resource scoping, segregation of duties,
validation-pipeline precedence, and the mariner-profile OCC guard."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_enrollment,
    budget_rows,
    create_activated_mariner,
    create_course,
    create_credential_payload,
    create_mariner,
    create_mariner_payload,
    create_union_hall,
    create_union_registration_payload,
    create_vessel_payload,
    make_crewing_headers,
    make_fleet_admin_headers,
    make_mariner_headers,
    make_union_dispatcher_headers,
    propose_assignment,
    request_enrollment,
    schedule_drug_test,
    setup_crewing_scenario,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
OFFICER = TEST_USERS["officer_headers"]
CREWING = TEST_USERS["crewing_headers"]


class TestAuthPipeline:

    def test_missing_auth_header_rejected(self):
        """PRD section 2.1: "A request missing either header, or carrying an
        empty value, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_rejected
        """
        resp = api_client.create_mariner(
            create_mariner_payload(full_name="No Auth"), headers={})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_role_denied_before_resource_existence(self):
        """PRD section 2.5: "Every request is evaluated against an ordered
        validation pipeline. The first check that fails determines the error
        returned, and later checks are not evaluated — error precedence is
        therefore deterministic across the whole API."
        PRD section 2.5: "Role authorization. The role must appear in the
        endpoint's authorized roles, else `ERR_UNAUTHORIZED_ROLE`."

        Design: Corner/validations/role_denied_before_resource_existence
        """
        # Mariner is not among POST /vessels' roles; the 403 precedes any
        # existence or schema evaluation.
        resp = api_client.create_vessel(
            create_vessel_payload(vessel_name="SS Nope"),
            make_mariner_headers(NON_EXISTENT_UUID))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_existence_beats_state_on_missing_assignment(self):
        """PRD section 2.5: "Path existence. Identifiers in the URL are
        resolved strictly left to right; the first identifier that does not
        correspond to an existing resource yields that resource's dedicated
        404"
        PRD section 2.5: "Every request is evaluated against an ordered
        validation pipeline. The first check that fails determines the error
        returned, and later checks are not evaluated"

        Design: Corner/validations/existence_beats_state_on_missing_assignment
        """
        resp = api_client.confirm_assignment(NON_EXISTENT_UUID, CREWING)
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND)


class TestRoleExclusivity:

    def test_rbac_officer_cannot_confirm_assignment(self):
        """PRD section 2.1: "When the supplied role is not among the roles
        authorized for the target endpoint, the request is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD section 4: POST `/assignments/{id}/confirm` is authorized for
        CrewingManager and UnionDispatcher only.

        Design: Corner/rbac/rbac_officer_cannot_confirm_assignment
        """
        # Build a PROPOSED assignment (confirmable in every other respect).
        env = setup_crewing_scenario()
        assignment = propose_assignment(env["mariner"]["id"], env["slot"]["id"])

        resp = api_client.confirm_assignment(assignment["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        still = validate_success(api_client.get_assignment(assignment["id"],
                                                           CREWING))
        assert still["assignment_status"] == "PROPOSED", \
            "the rejected call must not mutate the assignment"

    def test_rbac_crewing_manager_cannot_issue_credential(self):
        """PRD section 2.1: "When the supplied role is not among the roles
        authorized for the target endpoint, the request is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD section 4: POST `/mariners/{id}/credentials` is authorized for
        CredentialingOfficer only.

        Design: Corner/rbac/rbac_crewing_manager_cannot_issue_credential
        """
        mariner = create_mariner()
        resp = api_client.create_credential(
            mariner["id"], create_credential_payload(), CREWING)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_rbac_mariner_cannot_record_drug_result(self):
        """PRD section 2.1: "When the supplied role is not among the roles
        authorized for the target endpoint, the request is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD section 4: POST `/mariners/{id}/drug-tests/{testId}/record-result`
        is authorized for CredentialingOfficer only.

        Design: Corner/rbac/rbac_mariner_cannot_record_drug_result
        """
        mariner = create_mariner()
        test = schedule_drug_test(mariner["id"], test_type="PERIODIC",
                                  scheduled_date="2026-05-01T00:00:00Z")
        resp = api_client.record_drug_test_result(
            mariner["id"], test["id"],
            {"result": "NEGATIVE", "collected_date": "2026-05-01T00:00:00Z"},
            make_mariner_headers(mariner["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestResourceScoping:

    def test_mariner_reading_other_mariner_forbidden(self):
        """PRD section 2.1: "A caller with role `Mariner` may only address
        their own mariner id — their own `/mariners/{id}` subtree and
        resources linked to it — and a caller with role `UnionDispatcher` may
        only mutate registrations of their own hall (the hall id in the path
        must equal `X-User-ID`) and may only act on union-dispatch assignments
        whose union registration belongs to their own hall. Either violation
        is rejected with `ERR_FORBIDDEN_RESOURCE_ACCESS` (HTTP 403)."

        Design: Corner/errors/mariner_reading_other_mariner_forbidden
        """
        m1 = create_mariner()
        m2 = create_mariner()
        resp = api_client.get_mariner(m2["id"], make_mariner_headers(m1["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_RESOURCE_ACCESS)

    def test_union_dispatcher_wrong_hall_forbidden(self):
        """PRD section 2.1: "a caller with role `UnionDispatcher` may only
        mutate registrations of their own hall (the hall id in the path must
        equal `X-User-ID`) and may only act on union-dispatch assignments
        whose union registration belongs to their own hall. Either violation
        is rejected with `ERR_FORBIDDEN_RESOURCE_ACCESS` (HTTP 403)."

        Design: Corner/errors/union_dispatcher_wrong_hall_forbidden
        """
        hall_a = create_union_hall()
        hall_b = create_union_hall()
        mariner = create_mariner(hire_channel="UNION_HALL")
        resp = api_client.create_union_registration(
            hall_a["id"],
            create_union_registration_payload(mariner["id"]),
            make_union_dispatcher_headers(hall_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_RESOURCE_ACCESS)


class TestValidationPriorityPairs:

    def _setup_cancelled_assignment_and_suspended_mariner(self):
        """A PROPOSED-then-CANCELLED assignment whose mariner is then
        SUSPENDED (posture BLOCKED): the confirm request violates both the
        state precondition and the readiness gate."""
        env = setup_crewing_scenario()
        assignment = propose_assignment(env["mariner"]["id"], env["slot"]["id"])
        validate_success(api_client.cancel_assignment(assignment["id"], CREWING))
        suspended = validate_success(
            api_client.suspend_mariner(env["mariner"]["id"], ADMIN))
        assert suspended["readiness_posture"] == "BLOCKED", \
            "safety gate would also fail for this request"
        return assignment["id"]

    def test_confirm_state_error_beats_safety_error(self):
        """PRD section 2.5: "Every request is evaluated against an ordered
        validation pipeline. The first check that fails determines the error
        returned, and later checks are not evaluated — error precedence is
        therefore deterministic across the whole API."
        PRD section 2.5: "9. **State preconditions.** The target entity must
        be in the state the transition requires, else `ERR_INVALID_STATE` or
        the transition-specific error" precedes "10. **Readiness gates.**
        Mariner posture gates reject with `ERR_MARINER_NOT_CLEAR` or
        `ERR_RESTRICTED_WINDOW_EXCEEDED` (section 3.2)."

        Design: Difficulty/priority_pair_validation_conflict/confirm_state_error_beats_safety_error
        """
        assignment_id = \
            self._setup_cancelled_assignment_and_suspended_mariner()
        resp = api_client.confirm_assignment(assignment_id, CREWING)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_confirm_state_error_leaves_assignment_untouched(self):
        """PRD section 3.7: "Cancellation moves an assignment from `PROPOSED`,
        `CONFIRMED`, or `SUSPENDED` to the terminal `CANCELLED` — any other
        source state is `ERR_INVALID_STATE`"
        PRD section 2.5: "Every request is evaluated against an ordered
        validation pipeline. The first check that fails determines the error
        returned, and later checks are not evaluated"

        Design: Difficulty/priority_pair_validation_conflict/confirm_state_error_beats_safety_error
        """
        assignment_id = \
            self._setup_cancelled_assignment_and_suspended_mariner()
        resp = api_client.confirm_assignment(assignment_id, CREWING)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api_client.get_assignment(assignment_id,
                                                           CREWING))
        assert after["assignment_status"] == "CANCELLED", \
            "a rejected confirm mutates nothing"

    def test_enroll_safety_error_beats_fiscal_error(self):
        """PRD section 2.5: "Every request is evaluated against an ordered
        validation pipeline. The first check that fails determines the error
        returned, and later checks are not evaluated"
        PRD section 2.5: "10. **Readiness gates.** Mariner posture gates
        reject with `ERR_MARINER_NOT_CLEAR` or
        `ERR_RESTRICTED_WINDOW_EXCEEDED` (section 3.2)." precedes "15.
        **Fiscal gate.** The training-budget availability check at enrollment
        rejects with `ERR_TRAINING_BUDGET_EXCEEDED` (section 3.9)."

        Design: Difficulty/priority_pair_validation_conflict/enroll_safety_error_beats_fiscal_error
        """
        # Cap 1000 makes the fiscal check fail too (provisional 160000), but
        # the mariner is suspended first, so only the safety error may fire.
        mariner = create_activated_mariner(annual_training_cap_cents=1000)
        course = create_course(cost_cents=250_000)
        enrollment = request_enrollment(course["id"], mariner["id"])
        approve_enrollment(enrollment["id"], approver_id="cm-500")
        validate_success(api_client.suspend_mariner(mariner["id"], ADMIN))

        resp = api_client.enroll_enrollment(enrollment["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_MARINER_NOT_CLEAR)

    def test_enroll_safety_rejection_persists_no_budget_row(self):
        """PRD section 3.9: "The budget row is persisted only on a successful
        enroll"
        PRD section 2.5: "The first check that fails determines the error
        returned, and later checks are not evaluated"

        Design: Difficulty/priority_pair_validation_conflict/enroll_safety_error_beats_fiscal_error
        """
        mariner = create_activated_mariner(annual_training_cap_cents=1000)
        course = create_course(cost_cents=250_000)
        enrollment = request_enrollment(course["id"], mariner["id"])
        approve_enrollment(enrollment["id"], approver_id="cm-500")
        validate_success(api_client.suspend_mariner(mariner["id"], ADMIN))

        resp = api_client.enroll_enrollment(enrollment["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_MARINER_NOT_CLEAR)
        assert budget_rows(mariner["id"]) == [], \
            "the fiscal gate never runs; no budget row may be persisted"
        assert validate_success(
            api_client.get_enrollment(enrollment["id"], ADMIN)
        )["status"] == "APPROVED"

    def _setup_approved_enrollment(self, approver_id="cm-777"):
        mariner = create_activated_mariner()
        course = create_course()
        enrollment = request_enrollment(course["id"], mariner["id"])
        approve_enrollment(enrollment["id"], approver_id=approver_id)
        return enrollment

    def test_reimburse_sod_error_beats_state_error(self):
        """PRD section 2.5: "8. **Segregation of duties.** The sea-service
        verifier must differ from the recorder, and the reimburser must differ
        from the approver (section 3.4 and section 3.9), else
        `ERR_SOD_VERIFY_SAME_RECORDER` or `ERR_SOD_REIMBURSE_SAME_APPROVER`."
        precedes "9. **State preconditions.** The target entity must be in the
        state the transition requires, else `ERR_INVALID_STATE`"
        PRD section 3.9: "the reimburser's `X-User-ID` must differ from the
        enrollment's `approved_by_user_id`, else
        `ERR_SOD_REIMBURSE_SAME_APPROVER` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/reimburse_sod_error_beats_state_error
        """
        enrollment = self._setup_approved_enrollment(approver_id="cm-777")
        # The reimburser IS the approver (SoD violation) AND the enrollment is
        # APPROVED, not COMPLETED (state violation): SoD fires first.
        resp = api_client.reimburse_enrollment(
            enrollment["id"], {"receipt_amount_cents": 50000},
            make_fleet_admin_headers("cm-777"))
        validate_error(resp, ApiErrorId.ERR_SOD_REIMBURSE_SAME_APPROVER)

    def test_reimburse_state_error_when_sod_passes(self):
        """PRD section 3.9: "Reimbursement — a `FleetAdmin` action moving
        `COMPLETED` to the terminal `REIMBURSED` (else `ERR_INVALID_STATE`)"

        Design: Difficulty/priority_pair_validation_conflict/reimburse_sod_error_beats_state_error
        """
        enrollment = self._setup_approved_enrollment(approver_id="cm-777")
        # A different reimburser passes SoD; the state gate then fires alone.
        resp = api_client.reimburse_enrollment(
            enrollment["id"], {"receipt_amount_cents": 50000},
            make_fleet_admin_headers("fa-999"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestMarinerProfileOcc:

    def test_occ_mariner_profile_update_stale_version(self):
        """PRD section 2.8: "Editing a mariner profile requires
        `expected_mariner_version`, carrying the client's last observed
        `version` of that Mariner. A mismatch — the version advanced by
        cascading side effects such as credential sweeps, posture recomputes,
        or assignment suspensions, or by another writer's edit — is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_mariner_profile_update_stale_version
        """
        mariner = create_activated_mariner()
        observed = validate_success(api_client.get_mariner(mariner["id"], ADMIN))
        observed_version = observed["version"]

        first = validate_success(
            api_client.update_mariner(
                mariner["id"],
                {"home_port_code": "OAK",
                 "expected_mariner_version": observed_version},
                ADMIN))
        assert first["version"] == observed_version + 1
        assert first["home_port_code"] == "OAK"

        resp = api_client.update_mariner(
            mariner["id"],
            {"home_port_code": "SEA",
             "expected_mariner_version": observed_version},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        final = validate_success(api_client.get_mariner(mariner["id"], ADMIN))
        assert final["home_port_code"] == "OAK", "the stale write is dropped"
        assert final["version"] == observed_version + 1
