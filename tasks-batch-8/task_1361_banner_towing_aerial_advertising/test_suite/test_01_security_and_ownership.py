"""Authentication, role permissions, and entity-backed ownership rules."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_base,
    create_client,
    create_campaign,
    create_pilot,
    create_pending_approval,
    create_route,
    make_client_headers,
    make_pilot_headers,
    validate_error,
)


class TestAuthentication:

    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: "A request whose `X-User-Role` header is missing or names
        a value outside this declared set is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/errors/error_unauthenticated_when_role_header_missing
        """
        headers = {"X-User-ID": "some-user", "Content-Type": "application/json"}
        resp = api.get_base(NON_EXISTENT_UUID, headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

    def test_role_not_permitted_for_endpoint_rejected(self, api):
        """PRD §2.1: "Once authenticated, a request whose role is not permitted
        for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /btaa/bases is authorized for PlatformAdmin only.

        The Pilot identity must resolve to a persisted pilot first (PRD §2.1
        identity-header check), so the request survives authentication and
        fails at the role-permission stage.

        Design: Corner/errors/error_unauthorized_when_role_mismatch
        """
        base = create_base(code="KBCT", name="Base for RBAC")
        pilot = create_pilot(base["id"], full_name="Rookie",
                             certificate_number="CERT-R1",
                             tow_endorsement_level="STANDARD")
        resp = api.create_base({"code": "XXX", "name": "Nope"},
                               make_pilot_headers(pilot["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


class TestRoleExclusiveOperations:

    def test_ground_crew_lead_cannot_grant_airspace_approval(
            self, api, ground_crew_lead_headers):
        """PRD §4: POST /btaa/airspace_approvals/{id}/grant is authorized for
        ComplianceOfficer only. PRD §2.1: "Once authenticated, a request whose
        role is not permitted for the target endpoint is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/ground_crew_lead_cannot_grant_airspace
        """
        base = create_base(code="KCRE", name="RBAC Field")
        route = create_route(base["id"], code="BEACH-RBAC", kind="BEACH")
        approval = create_pending_approval(route["id"])
        resp = api.grant_airspace_approval(approval["id"], ground_crew_lead_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


class TestOwnershipChain:

    def test_client_cannot_cancel_another_clients_campaign(self, api):
        """PRD §3.2: "Only the campaign-owning client may cancel a campaign;
        anyone else is turned away with `ERR_UNAUTHORIZED_OWNER`."
        PRD §2.1: "ownership checks on any resource that references a `Client`
        compare the resource's foreign-key field to `X-User-ID`, and a mismatch
        is rejected with `ERR_UNAUTHORIZED_OWNER` (HTTP 403)."

        Design: Corner/rbac/client_cannot_touch_another_clients_campaign
        """
        create_base(code="KOWN", name="Ownership Field")
        owner = create_client(legal_name="Owner Co", billing_email="o@x.com")
        stranger = create_client(legal_name="Stranger Co", billing_email="s@x.com")
        campaign = create_campaign(owner["id"], name="Owner Campaign")
        resp = api.cancel_campaign(campaign["id"],
                                   make_client_headers(stranger["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_OWNER,
                       expected_status=403)
