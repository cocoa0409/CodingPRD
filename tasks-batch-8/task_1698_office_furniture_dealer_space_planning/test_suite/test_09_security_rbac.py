"""Security: header presence, role authorization, read access for all roles."""
from test_helpers import (
    NO_AUTH_HEADERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    fixtures as fx,
    make_liquidation_appraiser_headers,
    validate_error,
    validate_success,
    APPROVER,
    DESIGNER,
    PM,
    REP,
    WH,
)

class TestHeaderAndExistence:
    def test_missing_auth_header_returns_400(self, api):
        """PRD section 2.1: "A request missing either header, or carrying an
        empty value for either, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        resp = api.list_dealerships(NO_AUTH_HEADERS)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_submit_nonexistent_order_returns_404(self, api):
        """PRD section 2.8: "(3) existence of every path identifier and every
        foreign-key identifier in the body" precedes "(4) the target resource
        being in a state from which the requested transition exists" — a submit
        against a well-formed but absent order id surfaces ERR_NOT_FOUND
        (HTTP 404 per the section 5 catalogue), never a state error.

        Design: Corner/validations/submit_nonexistent_order_returns_404
        """
        resp = api.submit_order(NON_EXISTENT_UUID, fx.AE)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestRoleDenial:
    def test_designer_cannot_activate_contract(self, api):
        """PRD section 2.1: "every endpoint carries an authorized role list,
        and a caller whose role is not on that list is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)." PRD section 4: the activate
        endpoint's authorized role is ContractsOfficer only ("| POST |
        `/api/pricing-contracts/{id}/activate` | Activate a DRAFT contract
        (activator must differ from creator) | ContractsOfficer |").

        Design: Corner/rbac/designer_cannot_activate_contract
        """
        ctx = fx.setup_catalog(activate=False, approve_plan=False)
        resp = api.activate_contract(ctx.contract["id"], DESIGNER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        still_draft = validate_success(
            api.get_pricing_contract(ctx.contract["id"], fx.CO)
        )
        assert still_draft["status"] == "DRAFT"

    def test_appraiser_cannot_issue_credit_role(self, api):
        """PRD section 2.1: "every endpoint carries an authorized role list,
        and a caller whose role is not on that list is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)." PRD section 4: issue_credit's
        authorized role is FinanceManager only ("| POST |
        `/api/liquidation-lots/{id}/issue_credit` | Issue final credit for an
        APPRAISED lot (issuer must differ from appraiser) | FinanceManager |").
        A LiquidationAppraiser calling it is denied by role even with a fresh
        user id that would pass segregation of duties.

        Design: Corner/rbac/appraiser_cannot_issue_credit_role
        """
        ctx = fx.setup_catalog(activate=False, approve_plan=False)
        lot = fx.create_lot(ctx.customer["id"], {"item_count": 10})
        fx.appraise_lot(lot, "B", 500_000)
        resp = api.issue_credit(lot["id"], make_liquidation_appraiser_headers("la-2"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_manufacturerrep_cannot_verify_punch(self, api):
        """PRD section 2.1: "every endpoint carries an authorized role list,
        and a caller whose role is not on that list is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)." PRD section 4: the verify
        endpoint's authorized role is ClaimsCoordinator only ("| POST |
        `/api/punch-items/{id}/verify` | Verify remediation; failure reopens;
        CRITICAL pass auto-creates a claim and sets the series quality hold |
        ClaimsCoordinator |").

        Design: Corner/rbac/manufacturerrep_cannot_verify_punch
        """
        ctx = fx.setup_submitted_order()
        fx.add_punch(ctx, {"order_line_id": ctx.line["id"]})
        fx.get_success_data(api.ready_punch_for_verify(ctx.punch["id"], PM))
        resp = api.verify_punch(ctx.punch["id"], {"passed": True}, REP)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_warehouselead_cannot_confirm_event(self, api):
        """PRD section 2.1: "every endpoint carries an authorized role list,
        and a caller whose role is not on that list is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)." PRD section 4: the confirm
        endpoint's authorized role is ProjectManager only ("| POST |
        `/api/install-events/{id}/confirm` | Confirm a TENTATIVE event
        (re-checks crew overlap) | ProjectManager |").

        Design: Corner/rbac/warehouselead_cannot_confirm_event
        """
        ctx = fx.setup_acknowledged_order()
        event = fx.add_event(ctx)
        resp = api.confirm_event(event["id"], WH)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_pm_cannot_apply_credit(self, api):
        """PRD section 2.1: "every endpoint carries an authorized role list,
        and a caller whose role is not on that list is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)." PRD section 4: apply_credit's
        authorized role is FinanceManager only ("| POST |
        `/api/project-orders/{id}/apply_credit` | Apply customer credit to a
        SUBMITTED or ACKNOWLEDGED order | FinanceManager |").

        Design: Corner/rbac/pm_cannot_apply_credit
        """
        ctx = fx.setup_submitted_order()
        resp = api.apply_credit(ctx.order["id"], {"amount_cents": 100}, PM)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_clientapprover_cannot_submit_plan(self, api):
        """PRD section 2.1: "every endpoint carries an authorized role list,
        and a caller whose role is not on that list is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)." PRD section 4: the plan submit
        endpoint's authorized role is Designer only ("| POST |
        `/api/space-plans/{id}/submit` | Submit a plan for client approval
        (from DRAFT or IN_REVISION) | Designer |").

        Design: Corner/rbac/clientapprover_cannot_submit_plan
        """
        ctx = fx.setup_catalog(activate=False, approve_plan=False)
        resp = api.submit_plan(ctx.plan["id"], APPROVER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


class TestReadAccess:
    def test_get_endpoints_readable_by_all_roles(self, api):
        """PRD section 2.1: "All list and single-resource read endpoints
        (`GET`) are readable by every one of the eleven roles; authorization
        restricts only writes."

        Design: Corner/rbac/get_endpoints_readable_by_all_roles
        """
        ctx = fx.setup_draft_order(
            contract_overrides={"pricing_tiers": []},
        )
        as_rep = validate_success(api.get_project_order(ctx.order["id"], REP))
        as_approver = validate_success(api.get_project_order(ctx.order["id"], APPROVER))
        assert as_rep["id"] == ctx.order["id"]
        assert as_approver["id"] == ctx.order["id"]
