"""Response envelope, authentication, site onboarding, and sponsor report
workflow: envelope shape, missing auth headers, not-found lookup, site
creation defaults, report generation/period validation and the
submit/acknowledge flow."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_site,
    assert_site_report,
    create_site,
    generate_report,
    setup_open_site,
    validate_error,
    validate_success,
)


class TestResponseEnvelope:
    def test_success_envelope_on_get_site(self, api, sponsor_admin_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`." and "The
        `response_type` is either "object" for a single resource or "array"
        for a list of resources."

        Design: Corner/endpoints/response_envelope_shape
        """
        site = create_site()
        resp = api.get_site(site["id"], sponsor_admin_headers)
        body = resp.json()
        assert resp.status_code == 200
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
        assert body["response_type"] == "object"
        assert body["data"]["name"] == "Library VITA"

    def test_error_envelope_on_not_found(self, api, sponsor_admin_headers):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string
        that identifies the specific error." and "The `message` provides a
        human-readable explanation of what went wrong."
        PRD §2.9: "The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at
        the first identifier that does not correspond to an existing
        resource, and no later identifier is examined."

        Design: Corner/endpoints/response_envelope_shape
        """
        create_site()
        resp = api.get_tax_return(NON_EXISTENT_UUID, sponsor_admin_headers)
        body = resp.json()
        assert body["response_type"] == "error"
        error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert error["message"].strip()


class TestAuthentication:
    def test_missing_auth_header_returns_unauthenticated(self, api):
        """PRD §2.1: "A request that omits either header, presents an
        undeclared role, or — for an entity-backed role — presents an
        `X-User-ID` that does not reference an existing Volunteer is rejected
        with `ERR_MISSING_AUTH_HEADER` (HTTP 401)."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        site = create_site()
        resp = api.get_site(site["id"], None)
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_HEADER)


class TestNotFound:
    def test_get_return_not_found(self, api, sponsor_admin_headers):
        """PRD §2.9: "The request is rejected with `ERR_NOT_FOUND` (HTTP 404)
        at the first identifier that does not correspond to an existing
        resource, and no later identifier is examined."

        Design: Corner/entities/get_return_not_found
        """
        create_site()
        resp = api.get_tax_return(NON_EXISTENT_UUID, sponsor_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestSiteCreationDefaults:
    def test_site_creation_defaults(self, api, sponsor_admin_headers):
        """PRD §3.1: "A newly created site's `status` field begins as
        `SETUP`."
        PRD §3.1: "its `accepted_count` is the number of its tax returns
        currently in `ACCEPTED` or `COMPLETED` status, and its `goal_met`
        flag turns true once `accepted_count` reaches `goal_returns`."

        Design: Corner/entities/site_creation_defaults
        """
        created = create_site()
        assert_site(created)
        assert created["status"] == "SETUP"

        fetched = validate_success(api.get_site(created["id"], sponsor_admin_headers))
        assert_site(fetched)
        assert fetched["status"] == "SETUP"
        assert fetched["accepted_count"] == 0
        assert fetched["goal_met"] is False
        assert fetched["id"] == created["id"]


class TestSiteReports:
    def test_report_period_inverted_rejected(self, api):
        """PRD §3.9: "A `SiteCoordinator` generates a statistics report for
        its site by supplying a `period_start` and a `period_end`; the period
        end must be strictly after the period start
        (`ERR_REPORT_PERIOD_INVALID`)."

        Design: Corner/validations/report_period_inverted_rejected
        """
        ctx = setup_open_site()
        resp = api.create_site_report(
            ctx.site_id,
            {"period_start": "2026-08-31T00:00:00Z",
             "period_end": "2026-08-01T00:00:00Z"},
            ctx.coord_headers,
        )
        validate_error(resp, ApiErrorId.ERR_REPORT_PERIOD_INVALID)

    def test_report_submit_ack_flow(self, api, sponsor_admin_headers):
        """PRD §3.9: "the `SiteCoordinator` submits a `DRAFT` report, moving
        it to `SUBMITTED`, and a `SponsorAdmin` acknowledges a `SUBMITTED`
        report, moving it to `ACKNOWLEDGED`, which is terminal."
        PRD §3.9: "The period values are labels only: every aggregate is
        computed lifetime-to-date at generation time, the snapshot is
        computed once and frozen immutably"

        Design: Corner/state_machines/report_submit_ack_flow
        """
        ctx = setup_open_site()
        report = generate_report(
            ctx.site_id, ctx.coord_headers,
            period_start="2026-08-01T00:00:00Z", period_end="2026-08-07T23:59:59Z",
        )
        assert_site_report(report)
        assert report["status"] == "DRAFT"
        assert report["returns_prepared_count"] == 0
        snapshot = {
            k: report[k]
            for k in (
                "returns_prepared_count", "returns_transmitted_count",
                "returns_accepted_count", "returns_rejected_open_count",
                "returns_referred_count", "returns_withdrawn_count",
                "qr_rework_total", "first_pass_accepted_count",
                "first_pass_acceptance_rate_bp", "final_resolution_rate_bp",
                "financial_referrals_accepted_count", "savings_match_total_cents",
            )
        }

        report = validate_success(
            api.transition_site_report(report["id"], "SUBMITTED", ctx.coord_headers)
        )
        assert report["status"] == "SUBMITTED"

        report = validate_success(
            api.transition_site_report(report["id"], "ACKNOWLEDGED", sponsor_admin_headers)
        )
        assert report["status"] == "ACKNOWLEDGED"
        for key, value in snapshot.items():
            assert report[key] == value, (
                f"Frozen aggregate {key} changed across the report workflow"
            )

    def test_report_rates_null_when_zero_transmitted(self, api):
        """PRD §3.9: "Two acceptance rates, reported in basis points as
        integers rounded half-up, measure e-file quality from different
        angles; both are null when no return of the site has ever been
        transmitted."

        Design: Corner/calculations/report_rates_null_when_zero_transmitted
        """
        ctx = setup_open_site()
        report = generate_report(ctx.site_id, ctx.coord_headers)
        assert_site_report(report)
        assert report["returns_transmitted_count"] == 0
        assert report["first_pass_acceptance_rate_bp"] is None
        assert report["final_resolution_rate_bp"] is None

    def test_coordinator_cannot_ack_report(self, api):
        """PRD §3.9: "the `SiteCoordinator` submits a `DRAFT` report, moving
        it to `SUBMITTED`, and a `SponsorAdmin` acknowledges a `SUBMITTED`
        report, moving it to `ACKNOWLEDGED`, which is terminal."
        PRD §2.1: "Any action attempted outside the caller's role envelope is
        rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/coordinator_cannot_ack_report
        """
        ctx = setup_open_site()
        report = generate_report(ctx.site_id, ctx.coord_headers)
        report = validate_success(
            api.transition_site_report(report["id"], "SUBMITTED", ctx.coord_headers)
        )

        resp = api.transition_site_report(report["id"], "ACKNOWLEDGED", ctx.coord_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        report = validate_success(
            api.list_site_reports(ctx.site_id, ctx.coord_headers)
        )[0]
        assert report["status"] == "SUBMITTED"
