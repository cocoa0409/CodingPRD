"""Authentication context, role-based denial, validation priority of auth over
existence, and applicant identity segregation on lease signing."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    add_issued_lease,
    add_leasable_application,
    create_agent,
    create_floorplan,
    create_pricing_offer,
    create_property,
    get_pricing_offer,
    make_applicant_headers,
    make_leasing_agent_headers,
    setup_site,
    validate_error,
    validate_success,
)

PM = TEST_USERS["property_manager_headers"]


class TestAuthContext:
    def test_missing_auth_headers_returns_invalid_context(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, naming the caller's
        operational capacity. The system recognizes exactly three roles:
        `PropertyManager`, `LeasingAgent`, and `Applicant`. A request missing either
        header, or carrying a role outside this set, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/errors/missing_auth_headers_returns_invalid_context
        """
        resp = api.create_property({"name": "NoAuth", "code": "NA1"}, headers=None)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)


class TestRoleDenial:
    def test_decide_as_agent_returns_unauthorized(self, api):
        """PRD §2.10: "Every request is validated in a fixed order, and the first
        failing check determines the response."
        PRD §2.10: "Second, authorization and ownership: the role must be permitted
        on the endpoint (`ERR_UNAUTHORIZED_ROLE`), the respond and mark-lost
        ownership check (`ERR_NOT_ASSIGNED_AGENT`), and the lease-signature identity
        check (`ERR_APPLICANT_MISMATCH`). Third, existence and request shape: path
        identifiers are resolved and each body reference must point at an existing
        resource"
        PRD §4: "POST /leasing/applications/{applicationId}/decide —
        PropertyManager"

        Design: Corner/validations/decide_as_agent_returns_unauthorized
        """
        prop = create_property(name="Prio Place", code="PR1")
        agent = create_agent(prop["id"], full_name="PrA", email="pra@x.com")

        # The role check (second) outranks existence (third): a LeasingAgent
        # deciding a nonexistent application gets 403, not 404.
        resp = api.decide_application(NON_EXISTENT_UUID, "APPROVED",
                                      make_leasing_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

    def test_agent_cannot_publish_offer_returns_unauthorized(self, api):
        """PRD §2.1: "Once authenticated, each endpoint permits only the roles
        listed in §4; a caller whose role is not permitted is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: "POST /leasing/pricing-offers/{pricingOfferId}/publish — Publish a
        DRAFT offer; at most one PUBLISHED per floorplan — PropertyManager"

        Design: Corner/rbac/agent_cannot_publish_offer_returns_unauthorized
        """
        prop = create_property(name="RBAC Row", code="RB1")
        agent = create_agent(prop["id"], full_name="RbA", email="rba@x.com")
        floorplan = create_floorplan(prop["id"])
        offer = create_pricing_offer(prop["id"], floorplan["id"])

        resp = api.publish_pricing_offer(offer["id"],
                                         make_leasing_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)
        assert get_pricing_offer(offer["id"])["status"] == "DRAFT", \
            "a rejected publish leaves the offer untouched"

    def test_applicant_cannot_create_property_returns_unauthorized(self, api):
        """PRD §2.1: "Once authenticated, each endpoint permits only the roles
        listed in §4; a caller whose role is not permitted is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §2.1: "When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the
        `Application` the portal session is scoped to: the applicant may read
        property, floorplan, and pricing-offer display data, read their own
        application and lease, and e-sign their lease, with the signature check
        comparing the lease's application reference to `X-User-ID`."
        PRD §4: "POST /leasing/properties — Create a property with its leasing
        configuration — PropertyManager"

        Design: Corner/rbac/applicant_cannot_create_property_returns_unauthorized
        """
        resp = api.create_property({"name": "Nope", "code": "NP1"},
                                   make_applicant_headers(NON_EXISTENT_UUID))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)


class TestApplicantSigningIdentity:
    def test_applicant_signing_other_application_lease_returns_forbidden(self, api):
        """PRD §2.1: "Signing a lease requires the caller's `X-User-ID` to equal the
        lease's application reference; a mismatch is rejected with
        `ERR_APPLICANT_MISMATCH` (HTTP 403)."
        PRD §3.6: "A successful signature stamps `signed_at` and moves the lease to
        `SIGNED_BY_APPLICANT`."
        PRD §4: "POST /leasing/leases/{leaseId}/sign — Applicant e-signature —
        Applicant"
        PRD §2.1: "Once authenticated, each endpoint permits only the roles listed
        in §4; a caller whose role is not permitted is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/applicant_signing_other_application_lease_returns_forbidden
        """
        from test_helpers import assert_same_instant
        site = setup_site()
        agent_id = site["agent"]["id"]
        bundle1 = add_issued_lease(site, inquiry_overrides={
            "contact_name": "S1", "contact_email": "s1@x.com"})
        bundle2 = add_leasable_application(site, decision=None, inquiry_overrides={
            "contact_name": "S2", "contact_email": "s2@x.com", "source": "PHONE"})
        lease1 = bundle1["lease"]

        # The Applicant role may sign, but only its own application's lease.
        wrong = api.sign_lease(lease1["id"],
                               make_applicant_headers(bundle2["application"]["id"]))
        validate_error(wrong, ApiErrorId.ERR_APPLICANT_MISMATCH, 403)

        # A LeasingAgent may not e-sign at all: the endpoint is Applicant-only.
        as_agent = api.sign_lease(lease1["id"], make_leasing_agent_headers(agent_id))
        validate_error(as_agent, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

        # The correct applicant signs at the default logical clock.
        signed = validate_success(api.sign_lease(
            lease1["id"], make_applicant_headers(bundle1["application"]["id"])))
        assert signed["status"] == "SIGNED_BY_APPLICANT"
        assert_same_instant(signed["signed_at"], "2026-08-01T00:00:00Z",
                            label="signed_at")
