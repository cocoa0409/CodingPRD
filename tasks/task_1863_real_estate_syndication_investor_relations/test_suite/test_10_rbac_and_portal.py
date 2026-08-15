"""Authentication, role-based permission denials, and portal access gating."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    contribution_for,
    issue_capital_call,
    make_active_syndication,
    make_investor,
    make_investor_headers,
    make_open_offering,
    make_submitted_subscription,
    receive_escrow_payload,
    setup_offering_with_approved_subscriptions,
    create_syndication_payload,
    make_offering,
    validate_error,
    validate_success,
)

SPONSOR = TEST_USERS["sponsor_operator_headers"]
OFFICER_1 = TEST_USERS["compliance_officer_headers"]
AGENT = TEST_USERS["transfer_agent_headers"]


class TestAuthHeaders:
    def test_missing_user_context_header(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID` and
        `X-User-Role`. If either header is missing or malformed, the request is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/errors/error_missing_user_context_header
        """
        resp = api.list_syndications(headers={})
        validate_error(resp,
                       ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)


class TestRolePermissionDenials:
    def test_investor_cannot_create_syndication(self, api):
        """PRD §2.1: "If the named role is not permitted to invoke the
        endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)." PRD §4 restricts POST /syndications to SponsorOperator.

        Design: Corner/errors/error_insufficient_permissions
        """
        syn = make_active_syndication(syndication_name="Tmp Syn")
        inv = make_investor(full_legal_name="R Inv")
        resp = api.create_syndication(create_syndication_payload(
            syndication_name="Bad Syn"), make_investor_headers(inv["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)

    def test_compliance_officer_cannot_open_offering(
            self, api, compliance_officer_headers):
        """PRD §2.1: "If the named role is not permitted to invoke the
        endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)." PRD §4 restricts POST
        /syndications/{syndicationId}/offerings/{offeringId}/open to
        SponsorOperator.

        Design: Corner/roles/compliance_officer_cannot_open_offering
        """
        syn = make_active_syndication(syndication_name="RBSyn")
        offering = make_offering(syn["id"], offering_name="RB Off")
        resp = api.open_offering(syn["id"], offering["id"],
                                 compliance_officer_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)

    def test_transfer_agent_cannot_verify_accreditation(
            self, api, transfer_agent_headers):
        """PRD §2.1: "If the named role is not permitted to invoke the
        endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)." PRD §4 restricts POST
        /syndications/{syndicationId}/offerings/{offeringId}/subscriptions/{subscriptionId}/verify-accreditation
        to ComplianceOfficer.

        Design: Corner/roles/transfer_agent_cannot_verify_accreditation
        """
        syn = make_active_syndication(syndication_name="TASyn")
        off = make_open_offering(syn["id"], offering_name="TA Off")
        inv = make_investor(full_legal_name="TA Inv")
        sub = make_submitted_subscription(off, inv, 5_000_000, syn["id"])
        assert sub["status"] == "SUBMITTED"
        resp = api.verify_accreditation(syn["id"], off["id"], sub["id"],
                                        transfer_agent_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)

    def test_investor_cannot_release_escrow(self, api):
        """PRD §2.1: "If the named role is not permitted to invoke the
        endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)." PRD §4 restricts POST
        /syndications/{syndicationId}/offerings/{offeringId}/capital-calls/{capitalCallId}/contributions/{contributionId}/release-escrow
        to SponsorOperator.

        Design: Corner/roles/investor_cannot_release_escrow
        """
        ctx = setup_offering_with_approved_subscriptions([5_000_000])
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        sub, inv = ctx["subs"][0], ctx["investors"][0]
        call, contribs = issue_capital_call(syn_id, off_id, 5_000_000)
        contrib = contribution_for(contribs, sub["id"])
        validate_success(api.receive_escrow(
            syn_id, off_id, call["id"], contrib["id"],
            receive_escrow_payload(5_000_000),
            make_investor_headers(inv["id"])))

        resp = api.release_escrow(syn_id, off_id, call["id"], contrib["id"],
                                  make_investor_headers(inv["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)


class TestPortalAccess:
    def test_portal_session_denied_for_invited_investor(self, api):
        """PRD §3.9: "If the investor's portal access is anything other than
        `ACTIVE` — still `INVITED`, or `SUSPENDED` (whether by sponsor action
        or by a defaulted capital call), or `REVOKED` — the session request is
        rejected with `ERR_PORTAL_ACCESS_DENIED`." A freshly registered
        investor is INVITED (PRD §3.1).

        Design: Corner/errors/error_portal_access_denied
        """
        inv = make_investor(full_legal_name="Pd Inv")
        assert inv["portal_access_status"] == "INVITED"
        resp = api.create_portal_session(inv["id"],
                                         make_investor_headers(inv["id"]))
        validate_error(resp, ApiErrorId.ERR_PORTAL_ACCESS_DENIED, 403)
