"""Response envelope shape and role-based access control (PRD §2.1, §2.2, §2.3, §4)."""
import re

from test_helpers import (
    ApiErrorId,
    build_user_headers,
    create_jurisdiction,
    create_jurisdiction_rule_payload,
    create_posting,
    setup_analyzed_study,
    submit_legal_review,
    two_eng_member_specs,
    validate_error,
    validate_success,
)


class TestResponseEnvelope:
    def test_response_envelope_success_and_error_shape(
        self, api, people_ops_admin_headers
    ):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
        PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits."
        PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
        PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints."
        PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."

        Design: Corner/endpoints/response_envelope_success_and_error_shape
        """
        # --- Success envelope (single object) ---
        res = api.create_jurisdiction_rule(
            create_jurisdiction_rule_payload(jurisdiction_code="ENV"),
            people_ops_admin_headers,
        )
        assert res.status_code == 201
        body = res.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert re.match(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$",
            body["meta"]["api_request_timestamp"],
        ), "api_request_timestamp must be ISO 8601 UTC with three fractional digits"
        assert isinstance(body["data"]["id"], str) and body["data"]["id"]

        # --- Success envelope (list with pagination fields and defaults) ---
        list_res = api.list_jurisdiction_rules(people_ops_admin_headers)
        assert list_res.status_code == 200
        list_body = list_res.json()
        assert list_body["response_type"] == "array"
        meta = list_body["meta"]
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in meta, f"meta missing pagination field {field}"
        # Defaults: limit 10, offset 0.
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 1

        # --- Error envelope ---
        err_res = api.get_jurisdiction_rule(
            "11111111-2222-4333-8444-555555555555", people_ops_admin_headers
        )
        assert err_res.status_code == 404
        err_body = err_res.json()
        assert err_body["response_type"] == "error"
        assert set(err_body["meta"].keys()) == {
            "api_request_id",
            "api_request_timestamp",
        }
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str)
        assert err_body["data"]["message"].strip() != ""


class TestRoleDenials:
    def test_rbac_analyst_cannot_legal_decision(self, api, comp_analyst_headers):
        """PRD §2.1: "Access to specific operations is further restricted by role; an attempt to perform an action outside the caller's designated role is rejected with an `ERR_INSUFFICIENT_PERMISSIONS` error."
        PRD §4: "| POST | `/api/pay-equity-studies/{studyId}/legal-decision` | Render the legal decision on a study under review | LegalCounsel |"

        Design: Corner/rbac/rbac_analyst_cannot_legal_decision
        """
        ctx = setup_analyzed_study(
            name="RB", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31", member_specs=two_eng_member_specs(),
            group_name="GRB", min_group_size=2,
        )
        submit_legal_review(ctx["study"]["id"])
        # CompAnalyst is outside the legal-decision role even on a valid call.
        res = api.legal_decision(
            ctx["study"]["id"], {"decision": "APPROVE"}, comp_analyst_headers
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        study = validate_success(api.get_study(ctx["study"]["id"], comp_analyst_headers))
        assert study["status"] == "UNDER_LEGAL_REVIEW"

    def test_rbac_reporter_cannot_create_study(self, api, compliance_reporter_headers):
        """PRD §2.1: "Access to specific operations is further restricted by role; an attempt to perform an action outside the caller's designated role is rejected with an `ERR_INSUFFICIENT_PERMISSIONS` error."
        PRD §4: "| POST | `/api/pay-equity-studies` | Create a pay equity study in `DRAFT` | CompAnalyst |"

        Design: Corner/rbac/rbac_reporter_cannot_create_study
        """
        res = api.create_study(
            {
                "name": "Nope",
                "analysis_period_start": "2025-01-01",
                "analysis_period_end": "2025-12-31",
                "protected_classes": ["GENDER"],
            },
            compliance_reporter_headers,
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_rbac_peopleops_cannot_publish_posting(
        self, api, people_ops_admin_headers, compliance_reporter_headers
    ):
        """PRD §2.1: "Access to specific operations is further restricted by role; an attempt to perform an action outside the caller's designated role is rejected with an `ERR_INSUFFICIENT_PERMISSIONS` error."
        PRD §4: "| POST | `/api/transparency-postings/{postingId}/publish` | Publish a `DRAFT` posting under jurisdiction rules | ComplianceReporter |"

        Design: Corner/rbac/rbac_peopleops_cannot_publish_posting
        """
        jurisdiction = create_jurisdiction("JRB")
        posting = create_posting(
            jurisdiction["id"], job_posting_ref="P-RB", title="Analyst",
            min_salary_cents=10000000, max_salary_cents=12000000,
        )
        # PeopleOpsAdmin configures jurisdictions but cannot publish postings.
        res = api.publish_posting(posting["id"], people_ops_admin_headers)
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        # Control: the authorized role publishes the same posting.
        published = validate_success(
            api.publish_posting(posting["id"], compliance_reporter_headers)
        )
        assert published["status"] == "PUBLISHED"

    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity."
        PRD §2.1: "A request missing either header, or carrying a role value outside this declared set, is rejected with an `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` error."

        Design: Corner/rbac/missing_auth_headers_rejected
        """
        # An undeclared role value is rejected before any endpoint logic.
        res = api.list_studies(build_user_headers("user-x-1", "UnknownRole"))
        validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
        # Headers absent entirely are rejected the same way.
        res2 = api.list_studies({})
        validate_error(res2, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
