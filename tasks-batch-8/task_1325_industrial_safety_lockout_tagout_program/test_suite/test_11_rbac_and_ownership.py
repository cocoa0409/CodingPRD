"""Authentication, role authorization, ownership, and segregation of duties."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    bootstrap_manager,
    create_energy_survey_payload,
    create_machine,
    create_machine_payload,
    create_procedure_audit_payload,
    get_survey,
    make_authorized_employee_headers,
    make_ehs_auditor_headers,
    make_ehs_manager_headers,
    register_employee,
    register_qualified_employee,
    setup_session_locked,
    validate_error,
    validate_paginated,
    validate_success,
)

NO_HEADERS = {}


class TestAuthentication:
    def test_missing_auth_headers_returns_401(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the capacity in
        which they act. The system recognizes exactly three roles: `EHSManager`,
        `EHSAuditor`, and `AuthorizedEmployee`. A request missing either header,
        or naming a role outside this set, is rejected with
        `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        resp = api.create_machine(
            create_machine_payload(asset_tag="A-UA-1", name="NoAuth", area="Bay 18",
                                   risk_window_policy="ROLLING_12MO"),
            NO_HEADERS)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleAuthorization:
    def test_auditor_cannot_create_machine(self, api):
        """PRD §2.1: "A request whose role is not listed among an endpoint's
        authorized roles, or that fails an ownership check on an ownership-scoped
        action, is rejected with `ERR_FORBIDDEN`."
        PRD §2.1: "An `EHSManager` owns the machine registry and its service
        posture, approves and rejects energy surveys, authors and administers
        lockout procedures, registers employees, assigns and completes training,
        performs emergency lock removal, links or dismisses incident reports,
        approves contractor permits, runs minor-servicing determinations, and
        controls the logical clock."

        Design: Corner/validations/auditor_cannot_create_machine
        """
        mgr = bootstrap_manager("E-MGR-RB1", "Mgr RB1")
        resp = api.create_machine(
            create_machine_payload(asset_tag="A-RB1-1", name="Nope", area="Bay 19",
                                   risk_window_policy="ROLLING_12MO"),
            make_ehs_auditor_headers(mgr["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        _machines, meta = validate_paginated(
            api.list_machines(make_ehs_manager_headers(mgr["id"])))
        assert meta["total_count"] == 0

    def test_ehs_manager_cannot_create_audit(self, api):
        """PRD §2.1: "An `EHSAuditor` is an independent authorized employee who
        schedules and completes the annual procedure audits and must not have
        personally applied locks under the audited procedure during the audit
        period."
        PRD §2.8: "Endpoint role authorization — otherwise `ERR_FORBIDDEN`."
        (check 2, ahead of "Existence and scope — path identifiers and body
        foreign keys exist, and cross-references belong to the same machine scope
        — otherwise `ERR_NOT_FOUND`." as check 4, in the fixed pipeline where
        "the first failing check determines the error returned")

        Design: Corner/rbac/ehs_manager_cannot_create_audit
        """
        mgr = bootstrap_manager("E-MGR-RB2", "Mgr RB2")
        resp = api.create_procedure_audit(
            create_procedure_audit_payload(NON_EXISTENT_UUID),
            make_ehs_manager_headers(mgr["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_authorized_employee_cannot_approve_survey(self, api):
        """PRD §3.2: "An `EHSManager` approves or rejects a submitted survey, but
        the manager must not be the surveyor; a self-approval or self-rejection
        attempt fails with `ERR_SELF_APPROVAL_FORBIDDEN`."
        PRD §2.1: "A request whose role is not listed among an endpoint's
        authorized roles, or that fails an ownership check on an ownership-scoped
        action, is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/authorized_employee_cannot_approve_survey
        """
        mgr = bootstrap_manager("E-MGR-RB3", "Mgr RB3")
        surveyor = register_employee(mgr, "E-W1-RB3", "W1 RB3")
        machine = create_machine(mgr, asset_tag="A-RB3-1", name="Press",
                                 area="Bay 42")
        surveyor_headers = make_authorized_employee_headers(surveyor["id"])
        survey = validate_success(api.create_energy_survey(
            create_energy_survey_payload(machine["id"]), surveyor_headers),
            expected_status=201)
        validate_success(api.submit_energy_survey(survey["id"], surveyor_headers))

        resp = api.approve_energy_survey(survey["id"], surveyor_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_survey(mgr, survey["id"])["status"] == "SUBMITTED"


class TestSegregationOfDuties:
    def test_surveyor_cannot_approve_own_survey(self, api):
        """PRD §3.2: "An `EHSManager` approves or rejects a submitted survey, but
        the manager must not be the surveyor; a self-approval or self-rejection
        attempt fails with `ERR_SELF_APPROVAL_FORBIDDEN`."

        Design: Corner/validations/surveyor_cannot_approve_own_survey
        """
        mgr = bootstrap_manager("E-MGR-SD1", "Mgr SD1")
        surveyor = register_employee(mgr, "E-W1-SD1", "W1 SD1")
        machine = create_machine(mgr, asset_tag="A-SD1-1", name="Press",
                                 area="Bay 21")
        surveyor_headers = make_authorized_employee_headers(surveyor["id"])
        survey = validate_success(api.create_energy_survey(
            create_energy_survey_payload(machine["id"]), surveyor_headers),
            expected_status=201)
        validate_success(api.submit_energy_survey(survey["id"], surveyor_headers))

        # The surveyor wearing the EHSManager hat is still the surveyor.
        resp = api.approve_energy_survey(
            survey["id"], make_ehs_manager_headers(surveyor["id"]))
        validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN)
        assert get_survey(mgr, survey["id"])["status"] == "SUBMITTED"


class TestSessionOwnership:
    def test_non_primary_cannot_release_session(self, api):
        """PRD §3.5: "Each of these four transitions — lock, clear, release,
        cancel — is restricted to the session's primary employee, and any other
        caller is refused with `ERR_FORBIDDEN`."

        Design: Corner/rbac/non_primary_cannot_release_session
        """
        ctx = setup_session_locked(asset_tag="A-RB4-1", lock_no="L-RB4-1",
                                   tag_no="T-RB4-1")
        other = register_qualified_employee(ctx["mgr"], "E-W3-RB4", "W3 RB4")
        primary_headers = make_authorized_employee_headers(ctx["primary"]["id"])
        validate_success(api.remove_employee_lock(ctx["lock"]["id"], primary_headers))
        validate_success(api.clear_lockout_session(
            ctx["session"]["id"], primary_headers))

        resp = api.release_lockout_session(
            ctx["session"]["id"], make_authorized_employee_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        released = validate_success(api.release_lockout_session(
            ctx["session"]["id"], primary_headers))
        assert released["status"] == "RELEASED", "the primary employee succeeds"
