"""Request discipline: response envelope, authentication, RBAC, and
not-found handling (PRD §2.1, §2.2, §2.6)."""
from test_helpers import (
    NON_EXISTENT_UUID, ApiErrorId, assert_fiscal_year, create_fiscal_year,
    create_fiscal_year_payload, get_success_data, validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_budget_version_payload
from test_helpers.fixtures import add_projection, create_open_fiscal_year
from test_helpers.test_users import TEST_USERS

BA = TEST_USERS["budget_analyst_headers"]
BM = TEST_USERS["business_manager_headers"]
BC = TEST_USERS["board_clerk_headers"]
DT = TEST_USERS["district_treasurer_headers"]
AU = TEST_USERS["auditor_headers"]


class TestResponseEnvelope:
    def test_success_envelope_shape(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body" and
        "The `api_request_id` is a server-generated unique identifier for the
        request that starts with `req_`."

        Design: Corner/endpoints/response_envelope_shape_for_success_and_error
        """
        resp = api.create_fiscal_year(create_fiscal_year_payload(), BM)
        data = validate_success(resp, 201)
        assert_fiscal_year(data)
        body = resp.json()
        assert body["response_type"] == "object"
        meta = body["meta"]
        assert meta["api_request_id"].startswith("req_")
        assert isinstance(meta["api_request_timestamp"], str)

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" and "The `meta` object for error responses
        contains only `api_request_id` and `api_request_timestamp`."

        Design: Corner/endpoints/response_envelope_shape_for_success_and_error
        """
        resp = api.get_fiscal_year(NON_EXISTENT_UUID, AU)
        err = validate_error(resp, ApiErrorId.ERR_FISCAL_YEAR_NOT_FOUND)
        assert err["message"].strip(), "error message must be human-readable"
        body = resp.json()
        assert body["response_type"] == "error"
        assert set(body["meta"].keys()) == {"api_request_id",
                                            "api_request_timestamp"}
        assert body["meta"]["api_request_id"].startswith("req_")


class TestAuthentication:
    def test_missing_role_header_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        outside these six, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_role_header_returns_unauthenticated
        """
        resp = api.create_fiscal_year(
            create_fiscal_year_payload(),
            {"Content-Type": "application/json"})  # no X-User-ID / X-User-Role
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestRbac:
    def test_auditor_cannot_create_fiscal_year(self, api):
        """PRD §2.1: "An authenticated role attempting an operation its role
        is not authorized for is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)." — `Auditor` is external read-only access; the fiscal-year
        create endpoint is authorized for BusinessManager only (§4).

        Design: Corner/rbac/auditor_cannot_create_fiscal_year
        """
        resp = api.create_fiscal_year(create_fiscal_year_payload(), AU)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    def test_budget_analyst_cannot_certify_projection(self, api):
        """PRD §2.1: "An authenticated role attempting an operation its role
        is not authorized for is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)." PRD §3.1: "Certification belongs to the
        `BusinessManager`, who supplies the certified `actual_pupils` count".

        Design: Corner/rbac/budget_analyst_cannot_certify_projection
        """
        fy = create_open_fiscal_year()
        ep = add_projection(fy["id"], "ELEMENTARY", 1200)
        resp = api.certify_enrollment_projection(
            ep["id"], {"actual_pupils": 1250}, BA)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    def test_treasurer_cannot_adopt_budget_authz_before_state(self, api):
        """PRD §2.9: "Every mutation request passes a fixed validation
        pipeline, and the earliest failing stage determines the error returned
        — a request that would fail several checks surfaces the error from the
        earliest of them:" — stage 2 is "**Role authorization** — the acting
        role appears in the endpoint's authorized role list
        (`ERR_FORBIDDEN_ROLE`, HTTP 403).", ahead of stage 8 state admission.
        Adoption is a BoardClerk operation (§4).

        Design: Corner/rbac/treasurer_cannot_adopt_budget_authz_before_state
        """
        fy = create_open_fiscal_year()
        fy_now = get_success_data(api.get_fiscal_year(fy["id"], AU))
        bv = get_success_data(api.create_budget_version(
            fy["id"],
            create_budget_version_payload(fy_now["version"]), BA), 201)
        # Version is DRAFT: BOTH the role gate and the state gate would fail.
        resp = api.adopt_budget_version(bv["id"], DT)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    def test_auditor_can_read_all_resources(self, api):
        """PRD §2.1: "All six roles may call every retrieval endpoint and the
        test-driving clock capability; mutation rights are enumerated per
        endpoint in §4."

        Design: Corner/rbac/auditor_can_read_all_resources
        """
        fy = create_open_fiscal_year()
        fy_now = get_success_data(api.get_fiscal_year(fy["id"], AU))
        bv = get_success_data(api.create_budget_version(
            fy["id"],
            create_budget_version_payload(fy_now["version"]), BA), 201)
        listing = validate_success(api.list_fiscal_years(AU), 200)
        assert any(row["id"] == fy["id"] for row in listing)
        one = validate_success(api.get_fiscal_year(fy["id"], AU), 200)
        assert one["id"] == fy["id"]
        versions = validate_success(api.list_budget_versions(fy["id"], AU), 200)
        assert [row["id"] for row in versions] == [bv["id"]]


class TestNotFound:
    def test_get_fiscal_year_not_found_returns_404(self, api):
        """PRD §2.6: "The request is rejected immediately with the 404 that
        corresponds to the first path identifier that does not resolve:
        `ERR_FISCAL_YEAR_NOT_FOUND`, `ERR_ENROLLMENT_PROJECTION_NOT_FOUND`,
        `ERR_BUDGET_VERSION_NOT_FOUND`, `ERR_STAFFING_ALLOCATION_NOT_FOUND`,
        `ERR_POSITION_NOT_FOUND`, `ERR_REVENUE_ESTIMATE_NOT_FOUND`,
        `ERR_PUBLIC_HEARING_NOT_FOUND`, `ERR_ELECTION_NOT_FOUND`,
        `ERR_BOND_PROPOSAL_NOT_FOUND`, `ERR_BOND_PROJECT_NOT_FOUND`,
        `ERR_BALLOT_MEASURE_NOT_FOUND`, `ERR_BOND_SALE_NOT_FOUND`,
        `ERR_PROJECT_EXPENDITURE_NOT_FOUND`, or
        `ERR_CAPITAL_PLAN_AMENDMENT_NOT_FOUND`."

        Design: Corner/entities/get_fiscal_year_not_found_returns_404
        """
        resp = api.get_fiscal_year(NON_EXISTENT_UUID, AU)
        validate_error(resp, ApiErrorId.ERR_FISCAL_YEAR_NOT_FOUND, 404)

    def test_get_bond_project_not_found_returns_404(self, api):
        """PRD §2.6: "The request is rejected immediately with the 404 that
        corresponds to the first path identifier that does not resolve:
        `ERR_FISCAL_YEAR_NOT_FOUND`, `ERR_ENROLLMENT_PROJECTION_NOT_FOUND`,
        `ERR_BUDGET_VERSION_NOT_FOUND`, `ERR_STAFFING_ALLOCATION_NOT_FOUND`,
        `ERR_POSITION_NOT_FOUND`, `ERR_REVENUE_ESTIMATE_NOT_FOUND`,
        `ERR_PUBLIC_HEARING_NOT_FOUND`, `ERR_ELECTION_NOT_FOUND`,
        `ERR_BOND_PROPOSAL_NOT_FOUND`, `ERR_BOND_PROJECT_NOT_FOUND`,
        `ERR_BALLOT_MEASURE_NOT_FOUND`, `ERR_BOND_SALE_NOT_FOUND`,
        `ERR_PROJECT_EXPENDITURE_NOT_FOUND`, or
        `ERR_CAPITAL_PLAN_AMENDMENT_NOT_FOUND`."

        Design: Corner/entities/get_bond_project_not_found_returns_404
        """
        resp = api.get_bond_project(NON_EXISTENT_UUID, AU)
        validate_error(resp, ApiErrorId.ERR_BOND_PROJECT_NOT_FOUND, 404)
