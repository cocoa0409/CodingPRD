"""Cross-cutting envelope checks: user-context header, 404s, pagination,
RBAC denials, and report finalization gates (PRD §2.1, §2.3, §2.6, §3.8)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_active_strategy,
    bootstrap_org,
    create_composite_payload,
    create_draft_report,
    create_draft_strategy,
    create_job,
    create_org,
    get_success_data,
    make_reviewer_headers,
    mgr_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

VENDOR_ADMIN = TEST_USERS["vendor_admin_headers"]


class TestUserContextHeader:
    def test_missing_user_context_header_rejected(self, api):
        """PRD §2.1: "All interactions with the API must be authenticated
        through two mandatory HTTP headers: `X-User-ID`, identifying the
        acting user, and `X-User-Role`, specifying their operational capacity.
        A request in which either header is missing or malformed is rejected
        with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/errors/error_missing_user_context_header
        """
        org = create_org()
        resp = api.get_org(org["id"], {"X-User-Role": "VendorAdmin"})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestNotFound:
    def test_get_nonexistent_job_returns_not_found(self, api):
        """PRD §2.6: "the server validates path parameters from left to right,
        confirming each resource exists within the enclosing scope before
        examining the next. The first identifier that fails to resolve
        produces an `ERR_NOT_FOUND` (HTTP 404)".

        Design: Corner/endpoints/get_nonexistent_job_returns_not_found
        """
        create_org()
        resp = api.get_job(NON_EXISTENT_UUID, VENDOR_ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestPaginationEnvelope:
    def test_list_jobs_pagination_defaults_applied(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; it defaults to 10, with a minimum of 1 and a maximum of 100."
        PRD §2.3: "The `offset` parameter sets the number of items skipped and
        defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/pagination_defaults_applied
        """
        org = create_org()
        create_job(org["id"], job_code="ENG.IC3", title="Sr Eng")
        create_job(org["id"], job_code="ENG.M1", title="Eng Mgr",
                   career_level="M1")
        data, meta = validate_paginated(api.list_jobs(VENDOR_ADMIN))
        assert meta["limit"] == 10, f"Default limit must be 10, got {meta['limit']}"
        assert meta["offset"] == 0
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert isinstance(data, list) and len(data) == 2


class TestReportRbacAndGates:
    def test_committee_reviewer_cannot_present_report(self, api):
        """PRD §2.1: "A `CompCommitteeReviewer` is read-only."
        PRD §3.8: "Presentation closes the loop: an `HRDirector` moves a
        `FINALIZED` report to `PRESENTED`, stamping `presented_at` — null
        until then — with the current logical time and emitting a
        `REPORT_PRESENT` audit event."
        PRD §2.1: "a caller whose role is valid but not permitted for the
        requested endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE`
        (HTTP 403)."

        Design: Corner/endpoints/committee_reviewer_cannot_present_report
        """
        bundle = bootstrap_org()
        strategy = add_active_strategy(bundle)
        reviewer = get_success_data(api.create_employee(
            bundle["org"]["id"],
            {"full_name": "Reviewer", "email": "reviewer@x.com",
             "job_id": bundle["job"]["id"], "geo_code": "US-SF",
             "base_salary_annual_cents": 12000000, "hire_date": "2023-01-01"},
            mgr_headers(bundle)))
        report = create_draft_report(bundle, strategy)
        finalized = validate_success(api.finalize_report(
            report["id"], {}, mgr_headers(bundle)))
        assert finalized["status"] == "FINALIZED"
        resp = api.present_report(report["id"],
                                  make_reviewer_headers(reviewer["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_finalize_with_draft_strategy_rejected(self, api):
        """PRD §3.8: "Two guards apply in ladder order: the pinned strategy
        must be `ACTIVE` at finalize time (`ERR_STRATEGY_NOT_ACTIVE`)".

        Design: Corner/errors/error_strategy_not_active_on_report_finalize
        """
        bundle = bootstrap_org()
        strategy = create_draft_strategy(bundle)  # never activated
        report = create_draft_report(bundle, strategy)
        resp = api.finalize_report(report["id"], {}, mgr_headers(bundle))
        validate_error(resp, ApiErrorId.ERR_STRATEGY_NOT_ACTIVE)


class TestCustomGeoIndexCoverage:
    def test_custom_geo_index_missing_entry_rejected(self, api):
        """PRD §3.6: "If that pinned strategy uses the `CUSTOM_GEO_INDEX`
        policy and the pinned `job_geo_code` has no entry in the custom index
        table, creation fails immediately with `ERR_GEO_INDEX_MISSING`
        (HTTP 422)."

        The custom index covers US-SF, US-NYC, US-CHI, and US-REMOTE only;
        US-AUS has no entry.

        Design: Corner/errors/error_geo_index_missing
        """
        bundle = bootstrap_org()
        strategy = add_active_strategy(
            bundle, geo_differential_policy="CUSTOM_GEO_INDEX")
        resp = api.create_composite(
            bundle["job"]["id"],
            create_composite_payload(strategy["id"], job_geo_code="US-AUS"),
            mgr_headers(bundle))
        validate_error(resp, ApiErrorId.ERR_GEO_INDEX_MISSING)
