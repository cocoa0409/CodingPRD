"""Authentication and role-based authorization denials (PRD 2.1, 2.6, 4)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_client,
    find_rework_auth,
    make_client_headers,
    make_field_rep_headers,
    make_scenario,
    reject_visit,
    schedule_assignment,
    set_clock,
    validate_error,
    visit_store,
)

PM = TEST_USERS["pm_headers"]
PA = TEST_USERS["payroll_admin_headers"]


class TestAuthentication:
    def test_missing_auth_headers_unauthenticated(self, api, anonymous_headers):
        """PRD 2.1: "The placeholder role `Anonymous` is reserved for negative
        authentication testing: it is not a declared working role, and any
        request that omits the headers or carries an unrecognized role is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_missing_headers
        """
        resp = api.list_projects(anonymous_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestFieldRepAuthorization:
    def test_field_rep_cannot_verify_visit(self, api):
        """PRD 2.1: "A request whose role is declared but not permitted for the
        target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD 4: "POST /retail-reset/store-visits/{id}/verify | Verify a
        submitted visit ... | ProjectManager".

        Design: Corner/rbac/fieldrep_cannot_verify_visit
        """
        scn = make_scenario()
        asg, visit = visit_store(scn)
        resp = api.verify_store_visit(
            visit["id"], make_field_rep_headers(scn["reps"][0]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_rep_cannot_check_in_another_reps_assignment(self, api):
        """PRD 3.3: "Checking in moves the assignment from either `SCHEDULED`
        or `EN_ROUTE` to `ON_SITE`, and is likewise restricted to the assigned
        rep."
        PRD 2.1: "ownership checks on any resource that references a field rep
        — an assignment's `rep_id`, a mileage log's `rep_id` — compare that
        foreign-key field to `X-User-ID`, and a rep acting on another rep's
        assignment is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/rep_cannot_checkin_another_reps_assignment
        """
        scn = make_scenario(num_reps=2)
        rep_a, rep_b = scn["reps"]
        asg = schedule_assignment(
            scn["project"]["id"], scn["ps_rows"][0]["id"], rep_a["id"]
        )
        set_clock("2026-08-05T09:30:00Z")
        resp = api.check_in_assignment(asg["id"], make_field_rep_headers(rep_b["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestClientAuthorization:
    def test_client_cannot_approve_other_clients_rework(self, api):
        """PRD 3.5: "The acting client must own the project (its `id` must
        equal the project's `client_id`)."
        PRD 2.1: "ownership checks compare a project's `client_id` to
        `X-User-ID`, and a client acting on another client's project is
        rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/client_cannot_approve_other_clients_rework
        """
        scn = make_scenario()
        asg, visit = visit_store(scn, outcome="reject")
        auth = find_rework_auth(scn["ps_rows"][0]["id"], status="REQUESTED")
        other_client = create_client(name="Other Client")
        resp = api.approve_rework_authorization(
            auth["id"], make_client_headers(other_client["id"])
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestPayrollAdminAuthorization:
    def test_payroll_admin_cannot_create_project(self, api):
        """PRD 2.1: "A request whose role is declared but not permitted for the
        target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD 4: "POST /retail-reset/projects | Create a project under a client |
        ProjectManager".

        Design: Corner/rbac/payroll_admin_cannot_create_project
        """
        client = create_client(name="PA Client")
        resp = api.create_project(
            {"client_id": client["id"], "title": "PA Proj", "scope_type": "AUDIT"},
            PA,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
