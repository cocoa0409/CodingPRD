"""Resource existence: every identifier named in a request must resolve, each
resource type answering its own not-found code (PRD §2.8)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    create_members,
    create_project,
    make_documentation_specialist_headers,
    make_project_administrator_headers,
    validate_error,
)

ADMIN = TEST_USERS["program_admin_headers"]
ANY = TEST_USERS["any_headers"]


class TestNotFoundFamily:
    def test_get_project_not_found(self, api):
        """PRD §2.8: "Every identifier named in a request — path parameters first, left to right, then foreign keys in the body — must resolve to an existing resource."
        PRD §2.8: "Each resource type carries its own not-found code: `ERR_PROJECT_NOT_FOUND`, `ERR_TEAM_MEMBER_NOT_FOUND`, `ERR_CREDIT_ENTRY_NOT_FOUND`, `ERR_ENERGY_MODEL_NOT_FOUND`, `ERR_CREDIT_ATTEMPT_NOT_FOUND`, `ERR_REVIEW_COMMENT_NOT_FOUND`, `ERR_COMMISSIONING_TASK_NOT_FOUND`, `ERR_INCENTIVE_PROGRAM_NOT_FOUND`, `ERR_PROJECT_INCENTIVE_NOT_FOUND`, `ERR_ANALYSIS_NOT_FOUND`, and `ERR_PERFORMANCE_REPORT_NOT_FOUND`, all HTTP 404."

        Design: Corner/entities/get_project_not_found_returns_404
        """
        resp = api.get_project(NON_EXISTENT_UUID, ANY)
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_FOUND)

    def test_get_team_member_not_found(self, api):
        """PRD §2.8: "Every identifier named in a request — path parameters first, left to right, then foreign keys in the body — must resolve to an existing resource."
        PRD §2.8: "Each resource type carries its own not-found code: `ERR_PROJECT_NOT_FOUND`, `ERR_TEAM_MEMBER_NOT_FOUND`, `ERR_CREDIT_ENTRY_NOT_FOUND`, `ERR_ENERGY_MODEL_NOT_FOUND`, `ERR_CREDIT_ATTEMPT_NOT_FOUND`, `ERR_REVIEW_COMMENT_NOT_FOUND`, `ERR_COMMISSIONING_TASK_NOT_FOUND`, `ERR_INCENTIVE_PROGRAM_NOT_FOUND`, `ERR_PROJECT_INCENTIVE_NOT_FOUND`, `ERR_ANALYSIS_NOT_FOUND`, and `ERR_PERFORMANCE_REPORT_NOT_FOUND`, all HTTP 404."

        Design: Corner/entities/get_team_member_not_found_returns_404
        """
        resp = api.get_team_member(NON_EXISTENT_UUID, ANY)
        validate_error(resp, ApiErrorId.ERR_TEAM_MEMBER_NOT_FOUND)

    def test_get_credit_entry_not_found(self, api):
        """PRD §2.8: "Every identifier named in a request — path parameters first, left to right, then foreign keys in the body — must resolve to an existing resource."
        PRD §2.8: "Each resource type carries its own not-found code: `ERR_PROJECT_NOT_FOUND`, `ERR_TEAM_MEMBER_NOT_FOUND`, `ERR_CREDIT_ENTRY_NOT_FOUND`, `ERR_ENERGY_MODEL_NOT_FOUND`, `ERR_CREDIT_ATTEMPT_NOT_FOUND`, `ERR_REVIEW_COMMENT_NOT_FOUND`, `ERR_COMMISSIONING_TASK_NOT_FOUND`, `ERR_INCENTIVE_PROGRAM_NOT_FOUND`, `ERR_PROJECT_INCENTIVE_NOT_FOUND`, `ERR_ANALYSIS_NOT_FOUND`, and `ERR_PERFORMANCE_REPORT_NOT_FOUND`, all HTTP 404."

        Design: Corner/entities/get_credit_entry_not_found_returns_404
        """
        resp = api.get_credit_library_entry(NON_EXISTENT_UUID, ANY)
        validate_error(resp, ApiErrorId.ERR_CREDIT_ENTRY_NOT_FOUND)

    def test_get_energy_model_not_found(self, api):
        """PRD §2.8: "Every identifier named in a request — path parameters first, left to right, then foreign keys in the body — must resolve to an existing resource."
        PRD §2.8: "Each resource type carries its own not-found code: `ERR_PROJECT_NOT_FOUND`, `ERR_TEAM_MEMBER_NOT_FOUND`, `ERR_CREDIT_ENTRY_NOT_FOUND`, `ERR_ENERGY_MODEL_NOT_FOUND`, `ERR_CREDIT_ATTEMPT_NOT_FOUND`, `ERR_REVIEW_COMMENT_NOT_FOUND`, `ERR_COMMISSIONING_TASK_NOT_FOUND`, `ERR_INCENTIVE_PROGRAM_NOT_FOUND`, `ERR_PROJECT_INCENTIVE_NOT_FOUND`, `ERR_ANALYSIS_NOT_FOUND`, and `ERR_PERFORMANCE_REPORT_NOT_FOUND`, all HTTP 404."

        Design: Corner/entities/get_energy_model_not_found_returns_404
        """
        resp = api.get_energy_model(NON_EXISTENT_UUID, ANY)
        validate_error(resp, ApiErrorId.ERR_ENERGY_MODEL_NOT_FOUND)

    def test_get_credit_attempt_not_found(self, api):
        """PRD §2.8: "Every identifier named in a request — path parameters first, left to right, then foreign keys in the body — must resolve to an existing resource."
        PRD §2.8: "Each resource type carries its own not-found code: `ERR_PROJECT_NOT_FOUND`, `ERR_TEAM_MEMBER_NOT_FOUND`, `ERR_CREDIT_ENTRY_NOT_FOUND`, `ERR_ENERGY_MODEL_NOT_FOUND`, `ERR_CREDIT_ATTEMPT_NOT_FOUND`, `ERR_REVIEW_COMMENT_NOT_FOUND`, `ERR_COMMISSIONING_TASK_NOT_FOUND`, `ERR_INCENTIVE_PROGRAM_NOT_FOUND`, `ERR_PROJECT_INCENTIVE_NOT_FOUND`, `ERR_ANALYSIS_NOT_FOUND`, and `ERR_PERFORMANCE_REPORT_NOT_FOUND`, all HTTP 404."

        Design: Corner/entities/get_credit_attempt_not_found_returns_404
        """
        resp = api.get_credit_attempt(NON_EXISTENT_UUID, ANY)
        validate_error(resp, ApiErrorId.ERR_CREDIT_ATTEMPT_NOT_FOUND)

    def test_get_commissioning_task_not_found(self, api):
        """PRD §2.8: "Every identifier named in a request — path parameters first, left to right, then foreign keys in the body — must resolve to an existing resource."
        PRD §2.8: "Each resource type carries its own not-found code: `ERR_PROJECT_NOT_FOUND`, `ERR_TEAM_MEMBER_NOT_FOUND`, `ERR_CREDIT_ENTRY_NOT_FOUND`, `ERR_ENERGY_MODEL_NOT_FOUND`, `ERR_CREDIT_ATTEMPT_NOT_FOUND`, `ERR_REVIEW_COMMENT_NOT_FOUND`, `ERR_COMMISSIONING_TASK_NOT_FOUND`, `ERR_INCENTIVE_PROGRAM_NOT_FOUND`, `ERR_PROJECT_INCENTIVE_NOT_FOUND`, `ERR_ANALYSIS_NOT_FOUND`, and `ERR_PERFORMANCE_REPORT_NOT_FOUND`, all HTTP 404."

        Design: Corner/entities/get_commissioning_task_not_found_returns_404
        """
        resp = api.get_commissioning_task(NON_EXISTENT_UUID, ANY)
        validate_error(resp, ApiErrorId.ERR_COMMISSIONING_TASK_NOT_FOUND)

    def test_get_incentive_program_not_found(self, api):
        """PRD §2.8: "Every identifier named in a request — path parameters first, left to right, then foreign keys in the body — must resolve to an existing resource."
        PRD §2.8: "Each resource type carries its own not-found code: `ERR_PROJECT_NOT_FOUND`, `ERR_TEAM_MEMBER_NOT_FOUND`, `ERR_CREDIT_ENTRY_NOT_FOUND`, `ERR_ENERGY_MODEL_NOT_FOUND`, `ERR_CREDIT_ATTEMPT_NOT_FOUND`, `ERR_REVIEW_COMMENT_NOT_FOUND`, `ERR_COMMISSIONING_TASK_NOT_FOUND`, `ERR_INCENTIVE_PROGRAM_NOT_FOUND`, `ERR_PROJECT_INCENTIVE_NOT_FOUND`, `ERR_ANALYSIS_NOT_FOUND`, and `ERR_PERFORMANCE_REPORT_NOT_FOUND`, all HTTP 404."

        Design: Corner/entities/get_incentive_program_not_found_returns_404
        """
        resp = api.get_incentive_program(NON_EXISTENT_UUID, ANY)
        validate_error(resp, ApiErrorId.ERR_INCENTIVE_PROGRAM_NOT_FOUND)

    def test_get_project_incentive_not_found(self, api):
        """PRD §2.8: "Every identifier named in a request — path parameters first, left to right, then foreign keys in the body — must resolve to an existing resource."
        PRD §2.8: "Each resource type carries its own not-found code: `ERR_PROJECT_NOT_FOUND`, `ERR_TEAM_MEMBER_NOT_FOUND`, `ERR_CREDIT_ENTRY_NOT_FOUND`, `ERR_ENERGY_MODEL_NOT_FOUND`, `ERR_CREDIT_ATTEMPT_NOT_FOUND`, `ERR_REVIEW_COMMENT_NOT_FOUND`, `ERR_COMMISSIONING_TASK_NOT_FOUND`, `ERR_INCENTIVE_PROGRAM_NOT_FOUND`, `ERR_PROJECT_INCENTIVE_NOT_FOUND`, `ERR_ANALYSIS_NOT_FOUND`, and `ERR_PERFORMANCE_REPORT_NOT_FOUND`, all HTTP 404."

        Design: Corner/entities/get_project_incentive_not_found_returns_404
        """
        resp = api.get_project_incentive(NON_EXISTENT_UUID, ANY)
        validate_error(resp, ApiErrorId.ERR_PROJECT_INCENTIVE_NOT_FOUND)

    def test_get_analysis_not_found(self, api):
        """PRD §2.8: "Every identifier named in a request — path parameters first, left to right, then foreign keys in the body — must resolve to an existing resource."
        PRD §2.8: "Each resource type carries its own not-found code: `ERR_PROJECT_NOT_FOUND`, `ERR_TEAM_MEMBER_NOT_FOUND`, `ERR_CREDIT_ENTRY_NOT_FOUND`, `ERR_ENERGY_MODEL_NOT_FOUND`, `ERR_CREDIT_ATTEMPT_NOT_FOUND`, `ERR_REVIEW_COMMENT_NOT_FOUND`, `ERR_COMMISSIONING_TASK_NOT_FOUND`, `ERR_INCENTIVE_PROGRAM_NOT_FOUND`, `ERR_PROJECT_INCENTIVE_NOT_FOUND`, `ERR_ANALYSIS_NOT_FOUND`, and `ERR_PERFORMANCE_REPORT_NOT_FOUND`, all HTTP 404."

        Design: Corner/entities/get_analysis_not_found_returns_404
        """
        resp = api.get_cost_premium_analysis(NON_EXISTENT_UUID, ANY)
        validate_error(resp, ApiErrorId.ERR_ANALYSIS_NOT_FOUND)

    def test_performance_report_action_not_found(self, api):
        """PRD §2.8: "Every identifier named in a request — path parameters first, left to right, then foreign keys in the body — must resolve to an existing resource."
        PRD §2.8: "Each resource type carries its own not-found code: `ERR_PROJECT_NOT_FOUND`, `ERR_TEAM_MEMBER_NOT_FOUND`, `ERR_CREDIT_ENTRY_NOT_FOUND`, `ERR_ENERGY_MODEL_NOT_FOUND`, `ERR_CREDIT_ATTEMPT_NOT_FOUND`, `ERR_REVIEW_COMMENT_NOT_FOUND`, `ERR_COMMISSIONING_TASK_NOT_FOUND`, `ERR_INCENTIVE_PROGRAM_NOT_FOUND`, `ERR_PROJECT_INCENTIVE_NOT_FOUND`, `ERR_ANALYSIS_NOT_FOUND`, and `ERR_PERFORMANCE_REPORT_NOT_FOUND`, all HTTP 404."

        Design: Corner/entities/performance_report_not_found_returns_404
        """
        members = create_members()
        resp = api.submit_performance_report(
            NON_EXISTENT_UUID,
            make_project_administrator_headers(members["admin"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PERFORMANCE_REPORT_NOT_FOUND)

    def test_review_comment_action_not_found(self, api):
        """PRD §2.8: "Every identifier named in a request — path parameters first, left to right, then foreign keys in the body — must resolve to an existing resource."
        PRD §2.8: "Each resource type carries its own not-found code: `ERR_PROJECT_NOT_FOUND`, `ERR_TEAM_MEMBER_NOT_FOUND`, `ERR_CREDIT_ENTRY_NOT_FOUND`, `ERR_ENERGY_MODEL_NOT_FOUND`, `ERR_CREDIT_ATTEMPT_NOT_FOUND`, `ERR_REVIEW_COMMENT_NOT_FOUND`, `ERR_COMMISSIONING_TASK_NOT_FOUND`, `ERR_INCENTIVE_PROGRAM_NOT_FOUND`, `ERR_PROJECT_INCENTIVE_NOT_FOUND`, `ERR_ANALYSIS_NOT_FOUND`, and `ERR_PERFORMANCE_REPORT_NOT_FOUND`, all HTTP 404."

        Design: Corner/entities/review_comment_not_found_returns_404
        """
        members = create_members()
        resp = api.respond_to_comment(
            NON_EXISTENT_UUID, "x",
            make_documentation_specialist_headers(members["spec"]["id"]))
        validate_error(resp, ApiErrorId.ERR_REVIEW_COMMENT_NOT_FOUND)


class TestForeignKeyResolution:
    def test_create_credit_attempt_with_unknown_entry_rejected(self, api):
        """PRD §2.8: "Every identifier named in a request — path parameters first, left to right, then foreign keys in the body — must resolve to an existing resource."
        PRD §2.8: "Each resource type carries its own not-found code: `ERR_PROJECT_NOT_FOUND`, `ERR_TEAM_MEMBER_NOT_FOUND`, `ERR_CREDIT_ENTRY_NOT_FOUND`, `ERR_ENERGY_MODEL_NOT_FOUND`, `ERR_CREDIT_ATTEMPT_NOT_FOUND`, `ERR_REVIEW_COMMENT_NOT_FOUND`, `ERR_COMMISSIONING_TASK_NOT_FOUND`, `ERR_INCENTIVE_PROGRAM_NOT_FOUND`, `ERR_PROJECT_INCENTIVE_NOT_FOUND`, `ERR_ANALYSIS_NOT_FOUND`, and `ERR_PERFORMANCE_REPORT_NOT_FOUND`, all HTTP 404."

        Design: Corner/entities/create_credit_attempt_with_unknown_entry_rejected
        """
        members = create_members()
        project = create_project(members["admin"]["id"], project_name="FK Tower")
        resp = api.create_credit_attempt(
            {"project_id": project["id"],
             "credit_library_entry_id": NON_EXISTENT_UUID,
             "phase": "DESIGN",
             "documentation_owner_id": members["spec"]["id"]},
            make_project_administrator_headers(members["admin"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_ENTRY_NOT_FOUND)
