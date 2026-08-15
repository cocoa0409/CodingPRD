"""Auth-header enforcement, validation priority order, and role denials."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_property,
    add_verified_lease,
    create_approved_tenant,
    create_deal,
    create_model,
    create_tenant_payload,
    submit_model,
    validate_error,
)


class TestAuthHeaders:
    def test_missing_auth_header_returns_400(self, api):
        """PRD §2.1: "A request missing either header, or presenting a
        malformed value, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        resp = api.list_deals({})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_auth_beats_existence_priority(self, api):
        """PRD §2.8: "validation across all endpoints proceeds in a fixed
        priority order: authentication-header checks first
        (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role
        authorization (`ERR_INSUFFICIENT_PERMISSIONS`), then path existence"
        PRD §2.8: "an authorization failure surfaces before any 404"

        Design: Corner/validations/auth_beats_existence_priority
        """
        resp = api.get_deal(NON_EXISTENT_UUID, {})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_existence_beats_state_priority(self, api, escrow_headers):
        """PRD §2.8: "then path existence, then body foreign-key existence
        (`ERR_REFERENCED_RESOURCE_NOT_FOUND`, 422), then from-state validity
        for the requested transition (the entity-specific 409 state errors)"

        Design: Corner/validations/existence_beats_state_priority
        """
        # close is a state-gated transition; the missing deal must surface
        # its existence error before any state evaluation.
        resp = api.close_deal(NON_EXISTENT_UUID, escrow_headers)
        validate_error(resp, ApiErrorId.ERR_DEAL_NOT_FOUND)


class TestRoleDenials:
    def test_analyst_cannot_approve_own_model_role_denied(
            self, api, analyst_headers):
        """PRD §2.1: "A request whose role is not authorized for the target
        endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: "| POST | `/acquisition-deals/deals/{id}/underwriting-models/{modelId}/approve` | Approve model (SoD vs submitter) | UnderwritingCommittee |"

        Design: Corner/rbac/analyst_cannot_approve_own_model_role_denied
        """
        deal = create_deal(deal_name="RBACDeal1")
        prop = add_property(deal["id"])
        tenant = create_approved_tenant(legal_name="RT1")
        add_verified_lease(deal["id"], prop["id"], tenant["id"])
        model = create_model(deal["id"])
        submit_model(deal["id"], model["id"])

        resp = api.approve_underwriting_model(deal["id"], model["id"],
                                              analyst_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_dd_officer_cannot_close_deal_role_denied(self, api,
                                                      dd_officer_headers):
        """PRD §2.1: "A request whose role is not authorized for the target
        endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: "| POST | `/acquisition-deals/deals/{id}/close` | Close the deal | EscrowOfficer |"

        Design: Corner/rbac/dd_officer_cannot_close_deal_role_denied
        """
        deal = create_deal(deal_name="RBACDeal2")
        resp = api.close_deal(deal["id"], dd_officer_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_capital_markets_officer_cannot_create_tenant(
            self, api, capital_markets_headers):
        """PRD §2.1: "A request whose role is not authorized for the target
        endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: "| POST | `/tenants` | Create a tenant | AcquisitionsAnalyst |"

        Design: Corner/rbac/capital_markets_officer_cannot_create_tenant
        """
        resp = api.create_tenant(create_tenant_payload(legal_name="Nope"),
                                 capital_markets_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
