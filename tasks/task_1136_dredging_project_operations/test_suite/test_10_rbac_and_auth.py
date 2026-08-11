"""Access control: authentication, endpoint role gates (PRD §2.1, §2.9 class 1-2,
§4).
"""
from test_helpers import (
    validate_error,
    ApiErrorId,
    create_project_payload, create_placement_ticket_payload,
    create_project, add_reach, submit_survey, get_reach,
    file_claim,
    setup_dredging_reach, setup_completed_event, setup_species_shutdown,
    open_event, add_site,
)


class TestAuthentication:
    def test_missing_auth_header_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, naming their operational
        capacity."; "A request with either header missing, or carrying a role
        outside these five, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_header_unauthenticated
        """
        res = api.create_project(create_project_payload(name="P-AUTH"),
                                 headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestEndpointRoleGates:
    def test_contractor_cannot_create_project(self, api, contractor_headers):
        """PRD §2.1: "A request whose role is authenticated but not authorized
        for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /projects is authorized for OwnerEngineer only.

        Design: Corner/rbac/contractor_cannot_create_project
        """
        res = api.create_project(create_project_payload(name="P-X"),
                                 contractor_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_surveyor_cannot_accept_survey(self, api, surveyor_headers):
        """PRD §2.1: "A request whose role is authenticated but not authorized
        for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /surveys/{id}/accept is authorized for OwnerEngineer only.
        PRD §2.9: "the role is permitted on the endpoint, else `ERR_FORBIDDEN`
        (HTTP 403)" — the authorization class precedes state and segregation
        checks.

        Design: Corner/rbac/surveyor_cannot_accept_survey
        """
        project = create_project(name="P-RB2")
        reach = add_reach(project["id"])
        survey = submit_survey(reach["id"], "PRE_DREDGE", 40000, 18.5)
        reach_version = get_reach(reach["id"])["version"]
        # SurveyParty role (id deliberately != the submitter's): the role gate
        # fires before any state or segregation consideration.
        res = api.accept_survey(
            survey["id"], {"expected_reach_version": reach_version},
            surveyor_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_monitor_cannot_approve_standby_claim(self, api, monitor_headers):
        """PRD §2.1: "A request whose role is authenticated but not authorized
        for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /standby-claims/{id}/approve is authorized for
        OwnerEngineer only.

        Design: Corner/rbac/monitor_cannot_approve_standby_claim
        """
        ctx = setup_dredging_reach(project_overrides={"name": "P-RB3"})
        event = open_event(ctx["reach"]["id"], ctx["plant"]["id"],
                           "2026-05-10T00:00:00Z")
        ctx["event"] = event
        setup_species_shutdown(ctx, observed_utc="2026-05-10T06:00:00Z",
                               resume_at="2026-05-10T14:00:00Z")
        claim = file_claim(ctx["project"]["id"], ctx["plant"]["id"],
                           "2026-05-10T06:00:00Z", "2026-05-10T14:00:00Z",
                           8.0, "WEATHER")
        res = api.approve_standby_claim(claim["id"], monitor_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_site_operator_cannot_report_ticket(self, api,
                                                site_operator_headers):
        """PRD §2.1: "A request whose role is authenticated but not authorized
        for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /placement-tickets is authorized for ContractorOps only.

        Design: Corner/rbac/site_operator_cannot_report_ticket
        """
        ctx = setup_completed_event(
            project_overrides={"name": "P-RB4"}
        )
        site = add_site(name="SITE-R", bulking_factor=1.3)
        res = api.create_placement_ticket(
            create_placement_ticket_payload(
                ctx["event"]["id"], site["id"],
                placed_utc="2026-05-12T12:00:00Z", declared_volume_cy=500,
            ),
            site_operator_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_contractor_cannot_set_clock(self, api, contractor_headers):
        """PRD §2.1: "A request whose role is authenticated but not authorized
        for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.4: "An `OwnerEngineer` advances it through an admin-only
        test-driving capability".

        Design: Corner/rbac/contractor_cannot_set_clock
        """
        res = api.set_clock({"to_iso8601": "2026-05-10T00:00:00Z"},
                            contractor_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
