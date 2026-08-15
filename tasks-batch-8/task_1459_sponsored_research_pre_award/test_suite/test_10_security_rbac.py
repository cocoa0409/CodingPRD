"""User-context validation, role permissions, and PI ownership (PRD §2.1, §2.8)."""
from test_helpers import (
    ApiErrorId,
    add_budget_line,
    assert_funding_opportunity,
    assert_proposal,
    build_user_headers,
    create_budget_line_payload,
    create_opportunity_payload,
    create_proposal_payload,
    finalize_budget,
    get_success_data,
    make_analyst_headers,
    make_context,
    make_opportunity,
    make_pi,
    make_pi_headers,
    make_proposal,
    make_routed_proposal,
    reset_clock,
    route_proposal,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]


class TestUserContext:
    def test_missing_headers_rejected(self, api):
        """PRD §2.1: "A request with either header missing, or whose role value
        is not one of these seven, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/get_proposal_missing_auth_rejected
        """
        resp = api.list_proposals(headers={})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value
        )

    def test_unrecognized_role_rejected(self, api):
        """PRD §2.1: "The system recognizes exactly seven roles, spelled
        precisely as follows: `PI`, `PreAwardAnalyst`, `DepartmentChair`,
        `ComplianceOfficer`, `SubrecipientManager`, `OSPDirector`, and
        `OSPSystemAdmin`. A request with either header missing, or whose role
        value is not one of these seven, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/list_proposals_invalid_role_rejected
        """
        resp = api.list_proposals(headers=build_user_headers("user-1", "SuperUser"))
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value
        )


class TestRolePermissions:
    def test_pi_cannot_approve_institutional(self, api):
        """PRD §2.1: "When the role is valid but not permitted to perform the
        requested operation, the request is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)." PRD §4: the
        approve-institutional row lists only `OSPDirector`.

        Design: Corner/rbac/pi_cannot_approve_institutional
        """
        reset_clock()
        env = make_routed_proposal()
        resp = api.approve_institutional(
            env["proposal"]["id"], make_pi_headers(env["ctx"]["pi"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_compliance_officer_cannot_add_budget_line(self, api):
        """PRD §2.1: "When the role is valid but not permitted to perform the
        requested operation, the request is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)." PRD §4: the budget-lines
        creation row lists only `PreAwardAnalyst`.

        Design: Corner/rbac/compliance_officer_cannot_add_budget_line
        """
        ctx = make_context()
        prop = make_proposal(ctx["opp"]["id"], ctx["pi"]["id"], title="RBAC2",
                             pi_effort_pct=10.00)
        resp = api.create_budget_line(
            prop["id"],
            create_budget_line_payload(amount_cents=100),
            TEST_USERS["compliance_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_department_chair_cannot_create_opportunity(self, api):
        """PRD §2.1: "When the role is valid but not permitted to perform the
        requested operation, the request is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)." PRD §4: the
        funding-opportunities creation row lists only `OSPSystemAdmin`.

        Design: Corner/rbac/department_chair_cannot_create_opportunity
        """
        resp = api.create_funding_opportunity(
            create_opportunity_payload(title="Nope"),
            TEST_USERS["chair_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_read_endpoints_allow_all_roles(self, api):
        """PRD §2.1: "All seven roles share read access: every GET endpoint in
        this document is available to any authenticated role."

        Design: Corner/rbac/read_endpoints_allow_all_roles
        """
        ctx = make_context()
        prop = make_proposal(ctx["opp"]["id"], ctx["pi"]["id"], title="Reads",
                             pi_effort_pct=10.00)
        # PI reads its own proposal
        by_pi = validate_success(
            api.get_proposal(prop["id"], make_pi_headers(ctx["pi"]["id"]))
        )
        assert by_pi["id"] == prop["id"]
        # ComplianceOfficer reads the snapshot list; SubrecipientManager reads offers
        validate_success(
            api.list_budget_snapshots(prop["id"], TEST_USERS["compliance_headers"])
        )
        validate_success(
            api.list_negotiation_offers(prop["id"], TEST_USERS["sub_manager_headers"])
        )
        # DepartmentChair reads the opportunity
        by_chair = validate_success(
            api.get_funding_opportunity(ctx["opp"]["id"], TEST_USERS["chair_headers"])
        )
        assert by_chair["id"] == ctx["opp"]["id"]


class TestPiOwnership:
    def test_pi_cannot_edit_others_proposal(self, api):
        """PRD §3.3: "a caller other than the owning PI is rejected with
        `ERR_NOT_RESOURCE_OWNER`." PRD §2.1: "an ownership failure on an existing
        resource is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403) rather than
        the generic permission error."

        Design: Corner/rbac/pi_cannot_edit_others_proposal
        """
        opp = make_opportunity()
        pi1 = make_pi(full_name="Owner")
        pi2 = make_pi(full_name="Other", department_code="CHEM")
        prop = make_proposal(opp["id"], pi1["id"], title="Mine",
                             pi_effort_pct=10.00)
        resp = api.patch_proposal(
            prop["id"], {"title": "Hijacked"}, make_pi_headers(pi2["id"])
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
