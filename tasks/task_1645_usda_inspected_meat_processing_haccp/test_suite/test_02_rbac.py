"""Role-based access control: exclusive operations, shared reads, auth headers."""
from test_helpers import (
    MISSING_UUID,
    TEST_USERS,
    ApiErrorId,
    build_user_headers,
    create_plant_payload,
    receive_lot_payload,
    report_result_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures

ADMIN = TEST_USERS["plant_admin_headers"]
QA = TEST_USERS["qa_manager_headers"]
TECH = TEST_USERS["qa_tech_headers"]
LAB = TEST_USERS["lab_analyst_headers"]
INSP = TEST_USERS["inspector_headers"]
PROD = TEST_USERS["production_manager_headers"]


class TestExclusiveRoleDenied:
    def test_qa_tech_cannot_approve_plan(self, api):
        """PRD §2.1: "A request whose role is recognized but is not on the target endpoint's authorized-role list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/haccp-plans/{id}/approve` | Inspector approves a SUBMITTED plan | Inspector |"

        Design: Corner/rbac/qa_tech_cannot_approve_plan_returns_forbidden
        """
        plant = fixtures.create_plant(establishment_number="EST-1645-40")
        plan = fixtures.create_draft_plan(plant["id"])
        fixtures.add_ccp(plan["id"])
        fixtures.submit_plan(plan["id"])

        resp = api.approve_haccp_plan(plan["id"], TECH)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        after = validate_success(api.get_haccp_plan(plan["id"], QA), 200)
        assert after["status"] == "SUBMITTED", (
            "a role-denied approve must not move the plan out of SUBMITTED"
        )

    def test_production_manager_cannot_report_sample_result(self, api):
        """PRD §2.7: "Every request is evaluated against a fixed sequence of rule families, and a failure in an earlier family masks all later families"
        PRD §2.7: "**Role authorization** — the acting role appears in the endpoint's authorized list (`ERR_FORBIDDEN_ROLE`)."
        PRD §2.7: "**Path existence** — left-to-right resolution per §2.6 (`ERR_NOT_FOUND`)."

        Design: Corner/rbac/production_manager_cannot_report_sample_result_returns_forbidden
        """
        resp = api.report_sample_result(
            MISSING_UUID, report_result_payload(result="NEGATIVE"), PROD
        )
        # Role denial (family 2) precedes path existence (family 5):
        # a ProductionManager gets 403 even for a nonexistent sample id.
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert resp.status_code == 403

    def test_inspector_cannot_create_lots(self, api):
        """PRD §2.1: "A request whose role is recognized but is not on the target endpoint's authorized-role list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/production-days/{id}/lots` | Receive a livestock lot on an OPEN day | ProductionManager |"

        Design: Corner/rbac/inspector_cannot_create_lots_returns_forbidden
        """
        resp = api.receive_lot(MISSING_UUID, receive_lot_payload(), INSP)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert resp.status_code == 403


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
        """
        payload = create_plant_payload(establishment_number="EST-1645-41")
        # Neither X-User-ID nor X-User-Role present.
        resp = api.create_plant(payload, {"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        assert resp.status_code == 401
        # A role outside the declared set is likewise unauthenticated.
        resp2 = api.create_plant(
            payload, build_user_headers("anon-1", "Anonymous")
        )
        validate_error(resp2, ApiErrorId.ERR_UNAUTHENTICATED)
        assert resp2.status_code == 401


class TestSharedReadAccess:
    def test_get_endpoints_are_shared_across_all_roles(self, api):
        """PRD §4: "| GET | `/plants/{id}` | Plant detail including posture and compliance scores | PlantAdmin, QAManager, QATech, LabAnalyst, Inspector, ProductionManager |"

        Design: Corner/rbac/get_endpoints_are_shared_across_all_roles
        """
        plant = fixtures.create_plant(establishment_number="EST-1645-42")

        data = validate_success(api.get_plant(plant["id"], LAB), 200)
        assert data["establishment_number"] == "EST-1645-42"

        plans, meta = validate_paginated(
            api.list_haccp_plans(TECH, params={"plant_id": plant["id"]})
        )
        assert plans == []
        assert meta["total_count"] == 0

        records, _ = validate_paginated(
            api.list_noncompliance_records(INSP, params={"plant_id": plant["id"]})
        )
        assert records == []
