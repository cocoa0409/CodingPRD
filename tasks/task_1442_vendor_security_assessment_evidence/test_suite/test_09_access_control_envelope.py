"""Access control and envelope rules: authentication, authorization, and
pagination bounds (PRD §2.1, §2.3)."""
import pytest

from test_helpers import (
    ANALYST,
    ApiErrorId,
    get_success_data,
    request_risk_acceptance,
    setup_active_policy,
    setup_remediation_cycle,
    setup_risk_acceptance_review_cycle,
    TEST_USERS,
    validate_error,
)

APPROVER = TEST_USERS["security_approver_headers"]
VENDOR_CONTACT = TEST_USERS["vendor_contact_headers"]


class TestAuthentication:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the capacity in
        which they act. The platform recognizes exactly four roles: `PlatformAdmin`,
        `RiskAnalyst`, `SecurityApprover`, and `VendorContact`. A request that is
        missing either header, or that declares a role outside this set, is rejected
        with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
        """
        res = api.list_vendors(headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


class TestAuthorization:
    def test_vendor_contact_cannot_approve_cycle(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted on the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.1: "`SecurityApprover` holds the decision rights that must be
        segregated from the analyst: cycle approval and rejection, risk-acceptance
        decisions, subprocessor decisions, and addendum waivers."

        Design: Corner/rbac/vendor_contact_cannot_approve_cycle
        """
        ctx = setup_risk_acceptance_review_cycle()
        assert ctx["cycle"]["status"] == "RISK_ACCEPTANCE_REVIEW"
        res = api.approve_cycle(ctx["vendor"]["id"], ctx["cycle"]["id"], VENDOR_CONTACT)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_risk_analyst_cannot_approve_risk_acceptance(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted on the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.6: "Approval belongs to a `SecurityApprover` who is not the requester
        (§2.8)".

        Design: Corner/rbac/risk_analyst_cannot_approve_risk_acceptance
        """
        ctx = setup_remediation_cycle(exception_severities=("LOW",))
        acceptance = request_risk_acceptance(ctx, [ctx["exceptions"][0]["id"]])
        fresh = get_success_data(api.get_cycle(ctx["cycle"]["id"], ANALYST))
        res = api.approve_risk_acceptance(
            ctx["vendor"]["id"], ctx["cycle"]["id"], acceptance["id"],
            {"expected_cycle_version": fresh["version"]}, ANALYST,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)


class TestPaginationBounds:
    @pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
    def test_out_of_bounds_pagination_rejected(self, api, params):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter sets how many items to skip and defaults to 0, and may
        never be negative. A `limit` or `offset` outside these bounds is rejected
        with `ERR_PAGINATION_INVALID` (HTTP 422)."

        Design: Corner/errors/error_pagination_invalid
        """
        setup_active_policy()
        res = api.list_vendors(ANALYST, params=params)
        validate_error(res, ApiErrorId.ERR_PAGINATION_INVALID)
