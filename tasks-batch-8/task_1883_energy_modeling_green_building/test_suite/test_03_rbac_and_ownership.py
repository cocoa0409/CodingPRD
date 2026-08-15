"""Role-based access control, header presence, and ownership gates
(PRD §2.1, §2.7 stages 1/3/4)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assign_owner,
    create_attempt,
    create_credit_entry,
    create_cx_task,
    create_members,
    create_project,
    create_project_payload,
    get_attempt,
    get_success_data,
    lock_strategy,
    make_commissioning_agent_headers,
    make_documentation_specialist_headers,
    make_energy_modeler_headers,
    make_project_administrator_headers,
    setup_attempt_under_review,
    submit_phase,
    validate_error,
)

ADMIN = TEST_USERS["program_admin_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
ANY = TEST_USERS["any_headers"]


class TestHeaderPresence:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying an empty value for either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/create_project_missing_auth_header_unauthenticated
        """
        resp = api.create_project(
            create_project_payload(project_name="NoAuth Tower"), headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestExclusiveOperations:
    def test_create_project_as_energy_modeler_unauthorized(self, api):
        """PRD §2.1: "Performing an operation outside one's role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: POST `/certification-projects` is authorized for ProjectAdministrator only.

        Design: Corner/rbac/create_project_as_energy_modeler_unauthorized
        """
        members = create_members()
        resp = api.create_project(
            create_project_payload(project_name="Role Tower"),
            make_energy_modeler_headers(members["modeler"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_reviewer_cannot_lock_strategy(self, api):
        """PRD §2.1: "Performing an operation outside one's role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: POST `/certification-projects/{projectId}/lock-strategy` is authorized for ProjectAdministrator only.

        Design: Corner/rbac/reviewer_cannot_lock_strategy
        """
        members = create_members()
        project = create_project(members["admin"]["id"], project_name="Role2 Tower")
        resp = api.lock_strategy(project["id"], project["version"], REVIEWER)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_program_admin_cannot_award_credit(self, api):
        """PRD §2.1: "Performing an operation outside one's role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: POST `/credit-attempts/{attemptId}/award` is authorized for CertificationReviewer only.

        Design: Corner/rbac/program_admin_award_credit_blocked
        """
        ctx = setup_attempt_under_review(
            [{"code": "WEc1", "points": 2, "category": "WATER",
              "phase_eligibility": "DESIGN"}],
            project_overrides={"project_name": "Role3 Tower"},
        )
        attempt = ctx["attempts"]["WEc1"]
        resp = api.award_attempt(attempt["id"], ADMIN, raw_points_earned=2)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        after = get_attempt(attempt["id"])
        assert after["status"] == "UNDER_REVIEW"


class TestOwnershipGates:
    def test_mark_ready_by_non_owner_blocked(self, api):
        """PRD §3.2: "Marking ready is owner-only: a caller whose `X-User-ID` does not equal the attempt's `documentation_owner_id` is rejected with `ERR_NOT_DOCUMENTATION_OWNER` (HTTP 403)."

        Design: Corner/validations/mark_ready_by_non_owner_blocked
        """
        members = create_members()
        other_spec = get_success_data(
            api.create_team_member(
                {"full_name": "Debra Docs", "email": "debra@x.com",
                 "specialty": "DOCUMENTATION"},
                ADMIN)
        )
        entry = create_credit_entry(
            credit_code="WEc1", category="WATER", points_possible=2,
            phase_eligibility="DESIGN")
        project = create_project(members["admin"]["id"], project_name="Owner Tower")
        attempt = create_attempt(
            project["id"], entry["id"], members["spec"]["id"], members["admin"]["id"])
        assign_owner(attempt["id"], members["spec"]["id"], members["admin"]["id"])

        resp = api.mark_ready(
            attempt["id"],
            make_documentation_specialist_headers(other_spec["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_DOCUMENTATION_OWNER)
        assert get_attempt(attempt["id"])["status"] == "DOCUMENTATION_IN_PROGRESS"

    def test_cx_start_by_non_assigned_agent_rejected(self, api):
        """PRD §3.6: "A caller whose `X-User-ID` is not the task's `agent_id` fails with `ERR_NOT_ASSIGNED_COMMISSIONING_AGENT` (HTTP 403), and starting or completing from the wrong state fails with `ERR_INVALID_TASK_STATE` (HTTP 409)."

        Design: Corner/validations/cx_start_by_non_assigned_agent_rejected
        """
        members = create_members()
        other_cx = get_success_data(
            api.create_team_member(
                {"full_name": "Cora Cx", "email": "cora@x.com",
                 "specialty": "COMMISSIONING", "is_independent": True},
                ADMIN)
        )
        project = create_project(members["admin"]["id"], project_name="Assign Tower")
        task = create_cx_task(
            project["id"], members["cx"]["id"], members["admin"]["id"],
            task_type="CX_PLAN", is_prerequisite_linked=False)

        resp = api.start_commissioning_task(
            task["id"], make_commissioning_agent_headers(other_cx["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_COMMISSIONING_AGENT)
        after = get_success_data(api.get_commissioning_task(task["id"], ANY))
        assert after["status"] == "SCHEDULED"
