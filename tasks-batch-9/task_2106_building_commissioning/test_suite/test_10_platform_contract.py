"""Platform-wide contract: authentication, screening order, envelopes and pagination."""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    build_user_headers,
    create_project,
    is_iso8601_timestamp,
    validate_error,
    validate_success,
)
from test_helpers import CONTRACTOR, CXA


class TestAuthentication:
    def test_missing_or_unknown_role_headers_answer_unauthenticated(self, api):
        """PRD §2.1: "A request that omits either header, or supplies either as an empty
        string, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.1: "A request whose `X-User-Role` is not one of the five recognised roles is
        rejected with the same `ERR_UNAUTHENTICATED` (HTTP 401) — an unknown role is treated
        as a failure to authenticate, not as a permission problem."

        Design: Corner/errors/missing_auth_headers_return_unauthenticated
        """
        anonymous = api.get_cx_project(
            NON_EXISTENT_UUID, {"Content-Type": "application/json"}
        )
        validate_error(anonymous, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

        unknown_role = api.get_cx_project(
            NON_EXISTENT_UUID, build_user_headers("u-someone-1", "NotARole")
        )
        validate_error(unknown_role, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


class TestScreeningOrder:
    def test_the_role_check_runs_before_the_path_existence_check(self, api):
        """PRD §2.5: "The named role appears in the endpoint's authorised-role list —
        otherwise `ERR_ROLE_NOT_PERMITTED` (403). Applies to every endpoint."
        PRD §2.5: "The server evaluates the checks below strictly in the order listed, and
        the **first** failing check decides the response."

        Design: Corner/validations/role_check_precedes_existence_check_on_unknown_issue
        """
        response = api.void_issue(
            NON_EXISTENT_UUID, {"reason": "not mine to void"}, CONTRACTOR
        )
        validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    def test_the_existence_check_runs_before_the_state_check(self, api):
        """PRD §2.5: "This ordering is a contract: a request that is both unauthenticated
        and semantically nonsensical answers `ERR_UNAUTHENTICATED`, never `ERR_VALIDATION`;
        a request naming a non-existent project on a frozen engagement answers the not-found
        error, never `ERR_PROJECT_FROZEN`."
        PRD §2.5: "The target resource is in a status from which the requested transition is
        declared — otherwise `ERR_INVALID_STATE` (409). This applies to every state-changing
        action endpoint in the system."

        Design: Corner/validations/existence_check_precedes_state_check_on_unknown_checklist
        """
        response = api.verify_checklist(NON_EXISTENT_UUID, CXA)
        validate_error(response, ApiErrorId.ERR_CHECKLIST_NOT_FOUND.value, 404)


class TestNotFoundCatalogue:
    @pytest.mark.parametrize(
        "reader,expected_error",
        [
            ("get_owner_requirement", ApiErrorId.ERR_REQUIREMENT_NOT_FOUND.value),
            ("get_cx_plan", ApiErrorId.ERR_PLAN_NOT_FOUND.value),
            ("get_submittal", ApiErrorId.ERR_SUBMITTAL_NOT_FOUND.value),
            ("get_functional_test", ApiErrorId.ERR_TEST_NOT_FOUND.value),
            ("get_deferred_test", ApiErrorId.ERR_DEFERRED_TEST_NOT_FOUND.value),
            ("get_closeout_deliverable", ApiErrorId.ERR_DELIVERABLE_NOT_FOUND.value),
            ("get_energy_baseline", ApiErrorId.ERR_BASELINE_NOT_FOUND.value),
            ("get_issue", ApiErrorId.ERR_ISSUE_NOT_FOUND.value),
        ],
    )
    def test_each_collection_answers_its_own_not_found_code(
        self, api, reader, expected_error
    ):
        """PRD §2.5: "Every identifier embedded in the request path resolves to a stored
        row, checked from left to right, answering with the not-found code of the first
        identifier that fails: `ERR_PROJECT_NOT_FOUND`, `ERR_REQUIREMENT_NOT_FOUND`,
        `ERR_PLAN_NOT_FOUND`, `ERR_SUBMITTAL_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`,
        `ERR_CHECKLIST_NOT_FOUND`, `ERR_TEST_NOT_FOUND`, `ERR_ISSUE_NOT_FOUND`,
        `ERR_DEFERRED_TEST_NOT_FOUND`, `ERR_DELIVERABLE_NOT_FOUND`, `ERR_CREDIT_NOT_FOUND`
        or `ERR_BASELINE_NOT_FOUND` (all 404)."

        Design: Corner/errors/remaining_resource_ids_return_their_own_not_found_error
        """
        response = getattr(api, reader)(NON_EXISTENT_UUID, CXA)
        validate_error(response, expected_error, 404)


class TestPaginationBounds:
    def test_a_limit_above_the_maximum_is_a_validation_failure(self, api):
        """PRD §2.3: "`limit` sets the maximum number of rows returned; it defaults to 10,
        has a minimum of 1 and a maximum of 100."
        PRD §2.3: "A `limit` below 1 or above 100, or a negative `offset`, is a request-shape
        failure and is rejected with `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/validations/pagination_limit_above_maximum_returns_validation
        """
        project = create_project(
            name="Page Cx", building_name="Page Block", contract_value_cents=50_000_000
        )

        response = api.list_issues(
            CXA, params={"project_id": project["id"], "limit": 101}
        )
        validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)


class TestResponseEnvelopes:
    def test_success_and_error_envelopes_carry_meta_and_response_type(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
        request that starts with `req_`."
        PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp
        with three fractional digits."
        PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and
        `api_request_timestamp`."

        Design: Corner/endpoints/success_and_error_envelopes_carry_meta_and_response_type
        """
        project = create_project(
            name="Envelope Cx",
            building_name="Envelope Block",
            contract_value_cents=50_000_000,
        )

        ok = api.get_cx_project(project["id"], CXA)
        data = validate_success(ok, 200)
        body = ok.json()
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert data["id"] == project["id"]

        missing = api.get_cx_project(NON_EXISTENT_UUID, CXA)
        error_data = validate_error(
            missing, ApiErrorId.ERR_PROJECT_NOT_FOUND.value, 404
        )
        error_body = missing.json()
        assert error_body["response_type"] == "error"
        assert error_body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(error_body["meta"]["api_request_timestamp"])
        assert isinstance(error_data["message"], str) and error_data["message"].strip()
