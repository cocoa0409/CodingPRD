"""RBAC and role scoping: missing/unknown headers, role gating, FunderViewer
and VendorAnalyst record-level scoping."""
from test_helpers import (
    ApiErrorId,
    NO_AUTH_HEADERS,
    get_success_data,
    make_funder_viewer_headers,
    make_headers,
    make_vendor_analyst_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    create_active_program,
    create_cycle,
    create_engagement,
    create_funder,
    set_clock,
    setup_active_cycle,
    setup_cycle_under_review,
    setup_draft_report,
    setup_program_with_approved_model,
)
from test_helpers.test_users import (
    COLLECTOR, DIRECTOR, LEAD, PRIVACY, STEWARD,
)


class TestAuthentication:
    def test_request_missing_auth_headers_returns_401(self, api):
        """PRD section 2.1: "Every request must carry two HTTP headers:
        `X-User-ID`, identifying the acting user, and `X-User-Role`,
        declaring the capacity in which they act. A request missing either
        header is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401)."

        Design: Corner/validations/request_missing_auth_headers_returns_401
        """
        resp = api.create_program(
            {"name": "NoAuth", "code": "NAU"}, NO_AUTH_HEADERS)
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_HEADERS)

    def test_unknown_role_returns_401(self, api):
        """PRD section 2.1: "If `X-User-Role` is present but does not match
        one of the declared role names, the request is rejected with
        `ERR_UNKNOWN_ROLE` (HTTP 401)."

        Design: Corner/validations/unknown_role_returns_401
        """
        resp = api.create_program(
            {"name": "BadRole", "code": "BRL"},
            make_headers("SuperUser", "someone"),
        )
        validate_error(resp, ApiErrorId.ERR_UNKNOWN_ROLE)


class TestRoleDenials:
    def test_field_collector_cannot_open_audit(self, api):
        """PRD section 2.1: "Each endpoint declares the roles permitted to
        call it. A recognized role that is not on an endpoint's list is
        rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD section 4: the open-audit endpoint lists `DataSteward` only.

        Design: Corner/rbac/field_collector_cannot_open_audit
        """
        resp = api.open_audit(
            "11111111-2222-3333-4444-555555555555", COLLECTOR)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_privacy_officer_cannot_read_observations(self, api):
        """PRD section 3.5: "Consent is managed exclusively by the
        `PrivacyOfficer`, who is deliberately barred from reading observation
        data - the role sees programs, cycles, participants, consents,
        funders, logic models, and indicators, but never field measurements."
        PRD section 2.1: "A recognized role that is not on an endpoint's list
        is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/privacy_officer_cannot_read_observations
        """
        resp = api.get_observation(
            "11111111-2222-3333-4444-555555555555", PRIVACY)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_evaluation_lead_cannot_revoke_consent(self, api):
        """PRD section 3.5: "Consent is managed exclusively by the
        `PrivacyOfficer`".
        PRD section 2.1: "A recognized role that is not on an endpoint's list
        is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/evaluation_lead_cannot_revoke_consent
        """
        resp = api.revoke_consent(
            "11111111-2222-3333-4444-555555555555", LEAD)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_data_steward_cannot_create_logic_model(self, api):
        """PRD section 3.2: "An `EvaluationLead` drafts a program's
        measurement framework as a **LogicModel**".
        PRD section 2.1: "A recognized role that is not on an endpoint's list
        is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/data_steward_cannot_create_logic_model
        """
        resp = api.create_logic_model(
            "11111111-2222-3333-4444-555555555555",
            {"title": "Nope"},
            make_headers("DataSteward", "steward-1"),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestFunderViewerScoping:
    def test_funder_viewer_scoped_to_own_reports(self, api):
        """PRD section 3.8: "The same scoping governs reads - a
        `FunderViewer` fetching a single report sees it only if it belongs to
        their funder, and the report list is forcibly restricted to reports
        whose `funder_id` equals the caller's `X-User-ID`."
        PRD section 2.1: "a `FunderViewer` may only touch reports belonging
        to their own funder, and a `VendorAnalyst` may only touch resources
        inside an active engagement's window and scope" - "a scope violation
        is rejected with `ERR_SCOPE_DENIED` (HTTP 403)".
        PRD section 2.1: "A recognized role that is not on an endpoint's
        list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/funder_viewer_scoped_to_own_reports
        """
        base = setup_program_with_approved_model(program_name="Scope",
                                                 program_code="SCP")
        cycle = setup_active_cycle(base["program"])
        get_success_data(api.close_data(cycle["id"], DIRECTOR))
        get_success_data(api.begin_review(cycle["id"], DIRECTOR))

        funder_a = create_funder(name="Foundation A", code="FND-A")
        funder_b = create_funder(name="Foundation B", code="FND-B")

        cycle_now = get_success_data(api.get_cycle(cycle["id"], LEAD))
        report_a = validate_success(api.create_report(
            cycle["id"],
            {"funder_id": funder_a["id"], "report_type": "FUNDER_STANDARD",
             "expected_program_cycle_version": cycle_now["version"]},
            LEAD,
        ), expected_status=201)

        cycle_now2 = get_success_data(api.get_cycle(cycle["id"], LEAD))
        report_b = validate_success(api.create_report(
            cycle["id"],
            {"funder_id": funder_b["id"], "report_type": "FUNDER_STANDARD",
             "expected_program_cycle_version": cycle_now2["version"]},
            LEAD,
        ), expected_status=201)

        # Funder A reading funder B's report: scope denied.
        denied = api.get_report(report_b["id"],
                                make_funder_viewer_headers(funder_a["id"]))
        validate_error(denied, ApiErrorId.ERR_SCOPE_DENIED)

        # Funder A reading own report: OK.
        own = validate_success(api.get_report(
            report_a["id"], make_funder_viewer_headers(funder_a["id"])))
        assert own["id"] == report_a["id"]

        # List as funder A: only own report is visible.
        page, meta = validate_paginated(
            api.list_reports(make_funder_viewer_headers(funder_a["id"])))
        assert meta["total_count"] == 1
        assert page[0]["id"] == report_a["id"]

        # Funder A cannot generate (not a FunderViewer operation).
        forbidden = api.generate_report(
            report_a["id"], make_funder_viewer_headers(funder_a["id"]))
        validate_error(forbidden, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestVendorAnalystScoping:
    def test_vendor_analyst_window_scope_status_gating(self, api):
        """PRD section 3.9: "Once active, the vendor's analyst users -
        `VendorAnalyst` callers whose `X-User-ID` is the engagement's `id` -
        may read their own engagement and, only while the engagement remains
        `ACTIVE` and the current logical time lies within the access window
        from `access_start` up to but not including `access_end`, may read
        the in-scope cycles and those cycles' observations. Any vendor read
        or write outside the engagement, its window, its `ACTIVE` status, or
        its scope is rejected with `ERR_SCOPE_DENIED`."

        Design: Corner/rbac/vendor_analyst_window_scope_status_gating
        """
        program = create_active_program(name="Vendor", code="VND")
        cycle1 = create_cycle(program["id"], label="C1")
        cycle2 = create_cycle(
            program["id"], label="C2",
            enrollment_start="2026-08-01T00:00:00Z",
            enrollment_end="2026-08-31T23:59:59Z",
            cycle_start="2026-10-01T00:00:00Z",
            cycle_end="2026-10-31T23:59:59Z",
            reporting_due_date="2026-11-15T00:00:00Z")

        eng_active = create_engagement(
            program["id"], [cycle1["id"]], vendor_name="EvalCo",
            access_start="2026-08-01T00:00:00Z",
            access_end="2026-09-01T00:00:00Z",
            deliverable_due="2026-09-10T00:00:00Z")
        get_success_data(api.activate_engagement(eng_active["id"], DIRECTOR))

        eng_proposed = create_engagement(
            program["id"], [cycle1["id"]], vendor_name="ProposedCo",
            access_start="2026-09-02T00:00:00Z",
            access_end="2026-10-01T00:00:00Z",
            deliverable_due="2026-10-10T00:00:00Z")

        # ACTIVE engagement inside window, in-scope cycle: 200.
        ok = validate_success(api.get_cycle(
            cycle1["id"], make_vendor_analyst_headers(eng_active["id"])))
        assert ok["id"] == cycle1["id"]

        # Out-of-scope cycle: scope denied.
        out_of_scope = api.get_cycle(
            cycle2["id"], make_vendor_analyst_headers(eng_active["id"]))
        validate_error(out_of_scope, ApiErrorId.ERR_SCOPE_DENIED)

        # Clock moved past access_end: window closed.
        set_clock("2026-09-02T00:00:00Z")
        out_of_window = api.get_cycle(
            cycle1["id"], make_vendor_analyst_headers(eng_active["id"]))
        validate_error(out_of_window, ApiErrorId.ERR_SCOPE_DENIED)

        # PROPOSED engagement inside its window: still not ACTIVE.
        set_clock("2026-09-05T00:00:00Z")
        not_active = api.get_cycle(
            cycle1["id"], make_vendor_analyst_headers(eng_proposed["id"]))
        validate_error(not_active, ApiErrorId.ERR_SCOPE_DENIED)
