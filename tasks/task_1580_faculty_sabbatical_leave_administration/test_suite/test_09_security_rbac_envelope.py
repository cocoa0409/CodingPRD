"""Auth context, RBAC, ownership, and response envelope shape."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_application,
    create_cycle,
    create_department,
    create_faculty,
    decide_application,
    get_success_data,
    grant_for_application,
    make_committee_member_headers,
    make_department_chair_headers,
    make_faculty_headers,
    open_cycle,
    run_accruals,
    set_department_chair,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
PROVOST = TEST_USERS["provost_headers"]


class TestAuthContext:
    def test_submit_missing_auth_header_rejected(self, api):
        """PRD 2.1: "Every request must carry two headers: `X-User-ID` and
        `X-User-Role`. If either header is missing, or the role value is not
        one of the declared roles, the request is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400)."
        PRD 2.9: "the server evaluates checks in a fixed order and surfaces
        the error from the earliest failing tier."

        Design: Corner/validations/submit_missing_auth_header_rejected
        """
        # No auth headers at all; the target cycle does not even exist, and
        # the authentication tier still short-circuits the request.
        resp = api.open_leave_cycle(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT)


class TestRoleBeforeExistence:
    def test_role_check_precedes_existence(self, api):
        """PRD 2.9: "3. **Role membership.** The caller's role is authorized
        for the endpoint, else `ERR_FORBIDDEN_ROLE`. 4. **Existence.** Path
        identifiers and body foreign-key references are resolved left to right"
        PRD 2.1: "If the role is declared but not listed among the roles
        authorized for the target endpoint, the request is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/validations/role_check_precedes_existence
        """
        dept = create_department()
        faculty = create_faculty(dept["id"])
        # POST /leave-cycles/{id}/open is ProvostOffice-only; the id does not
        # exist, and the role tier is evaluated before existence.
        resp = api.open_leave_cycle(NON_EXISTENT_UUID, make_faculty_headers(faculty["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestOwnership:
    def test_submit_other_faculty_application_forbidden(self, api):
        """PRD 2.1: "A `Faculty` caller acting on another faculty member's
        resource is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
        PRD 3.3: "Only the owning faculty member may submit
        (`ERR_NOT_RESOURCE_OWNER`)"

        Design: Corner/validations/submit_other_faculty_application_forbidden
        """
        dept = create_department()
        fa = create_faculty(dept["id"])
        fb = create_faculty(
            dept["id"], academic_rank="ASSISTANT_PROFESSOR",
            hire_date="2021-08-01T00:00:00Z", annual_base_salary=100000.00,
        )
        run_accruals()
        cycle = open_cycle(create_cycle()["id"])
        app = create_application(fa["id"], leave_type="SABBATICAL", cycle_id=cycle["id"])

        resp = api.submit_leave_application(app["id"], make_faculty_headers(fb["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


class TestExclusiveOperations:
    def test_rbac_exclusive_operations_forbidden(self, api):
        """PRD 2.1: "If the role is declared but not listed among the roles
        authorized for the target endpoint, the request is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD 4 routing table: `/leave-cycles/{id}/close` lists ProvostOffice;
        `/accrual-runs` and `/leave-grants/{id}/activate` list
        LeaveAdministrator; `POST /leave-applications` lists Faculty.

        Design: Corner/rbac/rbac_exclusive_operations_forbidden
        """
        dept = create_department()
        chair = create_faculty(
            dept["id"], academic_rank="FULL_PROFESSOR",
            hire_date="2010-01-01T00:00:00Z", annual_base_salary=150000.00,
        )
        set_department_chair(dept["id"], chair["id"])
        faculty = create_faculty(dept["id"])
        committee_member = create_faculty(
            dept["id"], academic_rank="FULL_PROFESSOR",
            hire_date="2015-08-01T00:00:00Z", annual_base_salary=130000.00,
        )
        cycle = open_cycle(create_cycle()["id"])

        pro = create_application(
            faculty["id"], leave_type="PROFESSIONAL",
            requested_duration_semesters=1, requested_salary_pct=100,
            proposed_start_date="2027-01-01T00:00:00Z",
            proposed_end_date="2027-07-01T00:00:00Z",
        )
        submit_application(pro["id"], faculty["id"])
        decide_application(pro["id"], "APPROVED")
        grant = grant_for_application(pro["id"])

        close_by_committee = api.close_leave_cycle(
            cycle["id"], make_committee_member_headers(committee_member["id"])
        )
        validate_error(close_by_committee, ApiErrorId.ERR_FORBIDDEN_ROLE)

        accrual_by_faculty = api.run_accruals({}, make_faculty_headers(faculty["id"]))
        validate_error(accrual_by_faculty, ApiErrorId.ERR_FORBIDDEN_ROLE)

        activate_by_chair = api.activate_leave_grant(
            grant["id"], make_department_chair_headers(chair["id"])
        )
        validate_error(activate_by_chair, ApiErrorId.ERR_FORBIDDEN_ROLE)

        create_by_admin = api.create_leave_application(
            {
                "leave_type": "PERSONAL",
                "requested_duration_semesters": 1,
                "requested_salary_pct": 0,
                "proposed_start_date": "2027-01-01T00:00:00Z",
                "proposed_end_date": "2027-07-01T00:00:00Z",
            },
            ADMIN,
        )
        validate_error(create_by_admin, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestResponseEnvelopeShape:
    def test_response_envelope_shape(self, api):
        """PRD 2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD 2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."
        PRD 2.2: "Pagination-related fields in `meta` (`limit`, `offset`,
        `total_count`, `has_more`) are included for list endpoints."
        PRD 2.2: error responses carry "response_type": "error" and a data
        object with `error_id` and `message`.

        Design: Corner/endpoints/response_envelope_shape
        """
        dept = create_department()

        obj_resp = api.get_department(dept["id"], ADMIN)
        obj_body = obj_resp.json()
        assert obj_resp.status_code == 200
        assert obj_body["meta"]["api_request_id"].startswith("req_")
        assert obj_body["response_type"] == "object"
        assert obj_body["data"]["id"] == dept["id"]

        list_resp = api.list_departments(ADMIN)
        list_body = list_resp.json()
        assert list_resp.status_code == 200
        assert list_body["response_type"] == "array"
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in list_body["meta"], f"missing pagination meta field {field}"

        err_resp = api.get_department(NON_EXISTENT_UUID, ADMIN)
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_DEPARTMENT_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str)
