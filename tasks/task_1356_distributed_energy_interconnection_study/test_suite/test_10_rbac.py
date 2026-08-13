"""Role-based access control: exclusive operations, read access, and ownership."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_agreement_payload,
    create_cluster_group_payload,
    create_project,
    create_queued_project,
    create_transparency_report,
    get_project,
    issue_agreement,
    list_project_agreements,
    make_developer_headers,
    make_study_engineer_headers,
    setup_developer_and_cluster,
    setup_project_agreement_pending,
    setup_study_scenario,
    submit_milestone,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["queue_admin_headers"]
ENGINEER = TEST_USERS["study_engineer_headers"]
REGULATOR = TEST_USERS["regulator_headers"]


class TestExclusiveOperationDenial:
    def test_regulator_cannot_create_cluster(self, api):
        """PRD §2.1: "The `Regulator` role is read-only across the entire API."
        PRD §2.1: "Once the caller is authenticated, the role must also be
        authorized for the specific endpoint; a caller whose role is not permitted
        is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/regulator_cannot_create_cluster
        """
        resp = api.create_cluster_group(
            create_cluster_group_payload(name="RegCluster", capacity_mw=100),
            REGULATOR)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_developer_cannot_review_milestone(self, api):
        """PRD §4 endpoint table: "| POST | `/interconnection/milestone-submissions/{id}/review` | Accept or reject a pending milestone submission | QueueAdministrator |"
        PRD §2.1: "a caller whose role is not permitted is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/developer_cannot_review_milestone
        """
        developer, cluster = setup_developer_and_cluster()
        project = create_queued_project(developer["id"], cluster["id"])
        submission = submit_milestone(project["id"], developer["id"], "SITE_CONTROL")

        # The owning developer calls review on their OWN project's submission:
        # ownership holds, but the role is not in the endpoint's role list.
        resp = api.review_milestone_submission(
            submission["id"], {"decision": "ACCEPTED"},
            make_developer_headers(developer["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

        submissions, _meta = _list_submissions(api, project["id"])
        assert submissions[0]["status"] == "PENDING_REVIEW"

    def test_developer_cannot_scope_study(self, api):
        """PRD §4 endpoint table: "| POST | `/interconnection/cluster-groups/{id}/studies` | Scope the cluster impact study; enforces readiness and creates PROVISIONAL cost shares | StudyEngineer |"
        PRD §2.8: "Second, the role's permission for the endpoint is checked
        (`ERR_INSUFFICIENT_PERMISSIONS`)."

        Design: Corner/rbac/developer_cannot_scope_study
        """
        developer, cluster = setup_developer_and_cluster()

        resp = api.create_study(cluster["id"], {"total_cost_cents": 1000000},
                                make_developer_headers(developer["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_study_engineer_cannot_issue_agreement(self, api):
        """PRD §4 endpoint table: "| POST | `/interconnection/projects/{id}/agreements` | Issue (or re-issue after expiry) an interconnection agreement; OCC-guarded | QueueAdministrator |"
        PRD §2.1: "a caller whose role is not permitted is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/study_engineer_cannot_issue_agreement
        """
        scenario = setup_study_scenario([{"capacity_mw": 10}], publish=True)
        project = scenario["projects"][0]
        fresh = get_project(project["id"])

        resp = api.issue_agreement(
            project["id"],
            create_agreement_payload(fresh["version"], max_injection_mw=10),
            make_study_engineer_headers())
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

        agreements = list_project_agreements(project["id"])
        assert agreements == [], "no agreement persisted on the rejected call"

    def test_queue_admin_cannot_execute_agreement(self, api):
        """PRD §4 endpoint table: "| POST | `/interconnection/agreements/{id}/execute` | Developer executes an issued agreement before its deadline | Developer |"
        PRD §2.1: "a caller whose role is not permitted is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/queue_admin_cannot_execute_agreement
        """
        scenario = setup_project_agreement_pending(finalize=True)
        agreement = scenario["agreement"]

        resp = api.execute_agreement(agreement["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

        agreements = list_project_agreements(scenario["project"]["id"])
        assert agreements[0]["status"] == "ISSUED", "no state change on denied execute"


class TestSharedReadAccess:
    def test_regulator_and_developer_read_access(self, api):
        """PRD §4 endpoint table: "| GET | `/interconnection/transparency-reports/{id}` | Get a transparency report | Developer, QueueAdministrator, StudyEngineer, Regulator |"
        PRD §4 endpoint table: "| GET | `/interconnection/projects/{id}` | Get a project | Developer, QueueAdministrator, StudyEngineer, Regulator |"
        PRD §2.1: "The `Regulator` role is read-only across the entire API."

        Design: Corner/rbac/regulator_and_developer_read_access
        """
        developer, cluster = setup_developer_and_cluster()
        project = create_project(developer["id"], cluster["id"])
        report = _create_report(api)

        resp = api.get_transparency_report(report["id"], REGULATOR)
        data = validate_success(resp, expected_status=200)
        assert data["queued_project_count"] == 1

        resp = api.get_project(project["id"], make_developer_headers(developer["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "SUBMITTED"


def _create_report(api):
    return create_transparency_report("2026-Q3")


def _list_submissions(api, project_id):
    return validate_paginated(api.list_milestone_submissions(project_id, ADMIN))
