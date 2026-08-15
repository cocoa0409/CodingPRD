"""Role-based access control, identity resolution, and segregation of duties
(PRD §2.1, §3.4, §3.6)."""
from test_helpers import (
    CLERK,
    OPS,
    ApiErrorId,
    create_account,
    create_client_account_payload,
    create_permit,
    create_space,
    issue_permit,
    make_attendant_headers,
    make_entry_supervisor_headers,
    make_personnel,
    make_safety_officer_headers,
    set_clock,
    setup_active_permit,
    setup_issued_permit,
    submit_isolation,
    suspend_permit,
    validate_error,
    validate_success,
    verify_isolation_record,
)

# Headers with well-formed JSON but no auth context fields (PRD §2.1).
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


class TestAuthContext:
    def test_missing_auth_header_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role
        value outside this enumeration, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/rbac/corner_missing_auth_header_rejected
        """
        resp = api.list_personnel(NO_AUTH_HEADERS)
        err = validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
        assert resp.status_code == 400, (
            f"malformed context precedes authorization: got "
            f"{resp.status_code}: {err.get('message')}")

    def test_attendant_cannot_create_client_account(self, api):
        """PRD §2.1: "Beyond header presence, each endpoint permits only a
        declared subset of roles; a request whose role is not authorized for
        that endpoint is rejected with `ERR_FORBIDDEN`."
        PRD §4: POST /rescue-ops/client-accounts is authorized for
        OperationsManager only.

        Design: Corner/rbac/corner_attendant_cannot_create_client_account
        """
        set_clock("2026-08-03T06:00:00Z")
        attendant = make_personnel("Att One", ["ATTENDANT"])
        resp = api.create_client_account(
            create_client_account_payload(name="Forbidden Co",
                                          billing_mode="EVENT"),
            make_attendant_headers(attendant["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert resp.status_code == 403

    def test_identity_qualification_enforced(self, api):
        """PRD §2.1: "An `X-User-ID` that does not resolve to an `ACTIVE`
        `Personnel` row holding the role's required qualification is rejected
        with `ERR_IDENTITY_NOT_QUALIFIED`."

        Design: Corner/rbac/corner_identity_qualification_enforced
        """
        set_clock("2026-08-03T06:00:00Z")
        attendant_only = make_personnel("Att Only", ["ATTENDANT"])
        account = create_account(name="Identity Co")
        space = create_space(account["id"], space_code="TK-IQ")
        payload = {
            "purpose": "Identity job",
            "planned_start_at": "2026-08-03T06:00:00Z",
            "planned_end_at": "2026-08-03T20:00:00Z",
            "expected_space_version": space["version"],
        }
        # An ATTENDANT-only worker acting as EntrySupervisor: the role is
        # permitted on the endpoint but the identity lacks ENTRY_SUPERVISOR.
        resp = api.create_entry_permit(
            space["id"], payload,
            make_entry_supervisor_headers(attendant_only["id"]))
        validate_error(resp, ApiErrorId.ERR_IDENTITY_NOT_QUALIFIED)
        assert resp.status_code == 403


class TestEndpointAuthorization:
    def test_billing_clerk_cannot_activate(self, api):
        """PRD §2.6: "Authentication comes first: header presence and role
        declaration, then role-per-endpoint authorization, then entity-backed
        identity resolution." and "Only after these come optimistic-concurrency
        checks, state-transition legality, and then the domain safety,
        capacity, temporal, qualification, and fiscal gates described
        throughout §3."
        PRD §4: POST /rescue-ops/entry-permits/{id}/activate is authorized for
        EntrySupervisor only.

        Design: Corner/rbac/corner_billing_clerk_cannot_activate
        """
        ctx = setup_issued_permit(at="2026-08-03T06:00:00Z", with_plan=False)
        resp = api.activate_permit(ctx["permit"]["id"], CLERK)
        err = validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert resp.status_code == 403, (
            f"role denial wins over the DRAFT-state failure: {err}")

    def test_supervisor_cannot_post_reading(self, api):
        """PRD §4: POST /rescue-ops/entry-permits/{permitId}/
        atmospheric-readings is authorized for Attendant only.
        PRD §2.1: "a request whose role is not authorized for that endpoint is
        rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/corner_supervisor_cannot_post_reading
        """
        ctx = setup_issued_permit(at="2026-08-03T06:00:00Z", with_plan=False)
        payload = {"reading_kind": "PRE_ENTRY", "o2_pct": 20.9, "lel_pct": 0,
                   "h2s_ppm": 0, "co_ppm": 0}
        resp = api.create_atmospheric_reading(
            ctx["permit"]["id"], payload, ctx["team"]["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert resp.status_code == 403

    def test_ops_manager_cannot_verify(self, api):
        """PRD §4: POST /rescue-ops/isolation-verifications/{id}/verify is
        authorized for SafetyOfficer only.
        PRD §2.1: "a request whose role is not authorized for that endpoint is
        rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/corner_ops_manager_cannot_verify
        """
        ctx = setup_issued_permit(at="2026-08-03T06:00:00Z", with_plan=False)
        iso = submit_isolation(ctx["permit"]["id"],
                               ctx["team"]["officer_headers"],
                               isolation_type="VENTILATION")
        resp = api.verify_isolation(iso["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert resp.status_code == 403
        iso_after = validate_success(
            api.get_isolation_verification(iso["id"], OPS))
        assert iso_after["status"] == "PENDING", "a rejected verify mutates nothing"

    def test_safety_officer_shared_suspend(self, api):
        """PRD §3.5: "Orderly manual suspension from `ACTIVE` — available to
        an `EntrySupervisor` or `SafetyOfficer`, optionally with a `reason` —
        requires the space to be empty of on-duty entrants
        (`ERR_ENTRANTS_STILL_INSIDE`); it increments `suspension_count` and
        stamps `last_suspended_at`."

        Design: Corner/rbac/corner_safety_officer_shared_suspend
        """
        ctx = setup_active_permit(at="2026-08-03T05:30:00Z")
        suspended = suspend_permit(ctx["permit"]["id"],
                                   ctx["team"]["officer_headers"],
                                   reason="weather hold")
        assert suspended["status"] == "SUSPENDED", (
            "suspend is a shared operation: SafetyOfficer may invoke it")
        assert suspended["suspension_count"] == 1
        assert suspended["last_suspended_at"] is not None


class TestSegregationOfDuties:
    def test_sod_verifier_equals_issuer(self, api):
        """PRD §3.4: "Segregation of duties forbids the permit's issuer from
        verifying its isolations — when the verifier's identity equals the
        permit's `issued_by`, the request is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/corner_sod_verifier_equals_issuer
        """
        set_clock("2026-08-03T06:00:00Z")
        # One person holding both qualifications issues the permit, then tries
        # to verify its isolation as SafetyOfficer.
        dual = make_personnel("Dual One", ["ENTRY_SUPERVISOR", "SAFETY_OFFICER"])
        officer = make_personnel("Safe One", ["SAFETY_OFFICER"])
        account = create_account(name="SoD Co")
        space = create_space(account["id"], space_code="TK-SOD",
                             ventilation_required=True)
        permit = create_permit(space["id"], make_entry_supervisor_headers(dual["id"]),
                               planned_start_at="2026-08-03T05:00:00Z",
                               planned_end_at="2026-08-03T20:00:00Z")
        permit = issue_permit(permit["id"],
                              make_entry_supervisor_headers(dual["id"]))
        iso = submit_isolation(permit["id"], make_safety_officer_headers(officer["id"]),
                               isolation_type="VENTILATION")

        resp = api.verify_isolation(
            iso["id"], make_safety_officer_headers(dual["id"]))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert resp.status_code == 403

        verified = verify_isolation_record(
            iso["id"], make_safety_officer_headers(officer["id"]))
        assert verified["status"] == "VERIFIED", (
            "a different SafetyOfficer verifies successfully")

    def test_sod_resolver_equals_reporter(self, api):
        """PRD §3.6: "Resolution moves a `TRIAGED` or `ESCALATED` incident to
        `RESOLVED`, capturing `resolution_notes` and `resolved_by` — but
        segregation of duties forbids the reporter from resolving: when the
        resolver's identity equals `reported_by`, the request is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/corner_sod_resolver_equals_reporter
        """
        ctx = setup_active_permit(at="2026-08-03T05:30:00Z")
        team = ctx["team"]
        suspend_permit(ctx["permit"]["id"], team["supervisor_headers"])

        officer2 = make_personnel("Safe Two", ["SAFETY_OFFICER"])
        officer2_headers = make_safety_officer_headers(officer2["id"])
        incident = validate_success(api.create_incident(
            ctx["permit"]["id"],
            {"severity": "SERIOUS", "kind": "MEDICAL",
             "description": "Heat stress complaint"},
            team["officer_headers"]), expected_status=201)
        validate_success(api.triage_incident(incident["id"], officer2_headers))

        resp = api.resolve_incident(incident["id"], "self-resolution attempt",
                                    team["officer_headers"])
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert resp.status_code == 403

        resolved = validate_success(
            api.resolve_incident(incident["id"], "Independent review complete",
                                 officer2_headers))
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolved_by"] == officer2["id"]
