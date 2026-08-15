"""Authentication header enforcement and role-based access control."""
import pytest

from test_helpers import (
    ApiErrorId,
    build_user_headers,
    create_client,
    create_deficiency_payload,
    remediate_to_corrected,
    setup_facility_with_system,
    setup_submitted_plan,
    setup_system_with_deficiency,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import CONSULTANT, MANAGER, PLANNER


class TestAuthentication:
    @pytest.mark.parametrize("headers", [
        {},                                                     # neither header
        {"X-User-ID": "test-consultant-1"},                     # role missing
        {"X-User-Role": "Consultant"},                          # id missing
        {"X-User-ID": "test-consultant-1",
         "X-User-Role": "SuperUser"},                           # undeclared role
    ], ids=["no-headers", "missing-role", "missing-id", "unknown-role"])
    def test_missing_auth_headers_rejected(self, api, headers):
        """PRD §2.1: "A request missing either header, or carrying a role
        outside this declared set, is rejected with `ERR_UNAUTHENTICATED`."
        PRD §5: "`ERR_UNAUTHENTICATED` | 401 Unauthorized"

        Design: Corner/rbac/missing_auth_headers_rejected
        """
        resp = api.list_clients(headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleDenials:
    def test_facility_manager_cannot_create_deficiency(self, api):
        """PRD §4: "POST | `/fca/deficiencies` | Record a deficiency finding on
        a system | Consultant"
        PRD §2.1: "A request whose role is valid but not permitted for the
        target endpoint is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/facility_manager_cannot_create_deficiency
        """
        _facility, system = setup_facility_with_system(
            {"system_category": "HVAC", "name": "S", "install_year": 2015,
             "design_life_years": 20, "replacement_cost_cents": 5000000,
             "condition_rating": 3})
        resp = api.create_deficiency(
            create_deficiency_payload(system["id"], description="d",
                                      cost_estimate_cents=1000000, severity=3,
                                      urgency=3, recommended_year=2027),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_consultant_cannot_approve_plan(self, api):
        """PRD §4: "POST | `/fca/capital-plans/{id}/approve` | Approve a
        submitted plan (segregation of duties enforced) | Approver"
        PRD §2.1: "A request whose role is valid but not permitted for the
        target endpoint is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/consultant_cannot_approve_plan
        """
        workspace = setup_submitted_plan(
            submitter_id="planner-z",
            deficiency_specs=[{
                "description": "d", "cost_estimate_cents": 5000000,
                "severity": 3, "urgency": 3, "recommended_year": 2027,
            }],
            plan_overrides={"title": "P", "start_year": 2027,
                            "horizon_years": 1},
            scenario_overrides={"name": "S", "annual_budget_cents": 10000000,
                                "escalation_rate": 0.0},
            system_overrides={"system_category": "HVAC", "name": "S",
                              "install_year": 2010, "design_life_years": 25,
                              "replacement_cost_cents": 50000000,
                              "condition_rating": 3})
        resp = api.approve_plan(workspace["plan"]["id"], CONSULTANT)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        plan = validate_success(
            api.get_capital_plan(workspace["plan"]["id"], CONSULTANT))
        assert plan["status"] == "SUBMITTED", (
            "an unauthorized approval leaves the plan untouched")

    def test_capital_planner_cannot_verify_deficiency(self, api):
        """PRD §4: "POST | `/fca/deficiencies/{id}/verify` | Consultant
        verifies corrected work (`UNVERIFIED` → `VERIFIED`) | Consultant"
        PRD §2.1: "A request whose role is valid but not permitted for the
        target endpoint is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/capital_planner_cannot_verify_deficiency
        """
        _facility, _system, deficiency = setup_system_with_deficiency(
            {"description": "d", "cost_estimate_cents": 1000000,
             "severity": 3, "urgency": 3, "recommended_year": 2027},
            {"system_category": "HVAC", "name": "S", "install_year": 2015,
             "design_life_years": 20, "replacement_cost_cents": 5000000,
             "condition_rating": 3})
        remediate_to_corrected(deficiency["id"])
        resp = api.verify_deficiency(deficiency["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestSharedReads:
    @pytest.mark.parametrize("role", [
        "Consultant", "FacilityManager", "CapitalPlanner", "Approver",
    ])
    def test_all_roles_can_read_lists(self, api, role):
        """PRD §4: "GET | `/fca/clients` | List clients (paginated) |
        Consultant, FacilityManager, CapitalPlanner, Approver"
        PRD §2.1: "The system recognizes exactly four roles: `Consultant`,
        `FacilityManager`, `CapitalPlanner`, and `Approver`."

        Design: Corner/rbac/all_roles_can_read_lists
        """
        create_client(name="F5", contact_email="f5@f5.example")
        resp = api.list_clients(build_user_headers(f"reader-{role}", role))
        validate_success(resp, 200)
        assert resp.json()["response_type"] == "array"
