"""Authentication, role authorization, and the fiscal checkpoint batch
(PRD §2.1, §2.4, §4)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    create_sponsor_payload, create_application_payload,
    create_sponsor, create_draft_program, add_project, create_application,
    list_assurances, create_contractor,
    set_clock, run_checkpoint,
    make_contractor_headers, build_user_headers,
    TEST_USERS, ApiErrorId,
)

FAA = TEST_USERS["faa_manager_headers"]
SPONSOR = TEST_USERS["sponsor_staff_headers"]


class TestAuthentication:
    def test_missing_auth_header_returns_unauthenticated(self):
        """PRD §2.1: "A request that omits either header, or presents a role outside this
        declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Authentication is
        always evaluated before anything else".

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        res = api_client.create_sponsor(create_sponsor_payload(
            sponsor_name="Sponsor A", airport_size_tier="SMALL_HUB",
            npe_entitlement_total=5_000_000), headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestRoleAuthorization:
    def test_role_mismatch_returns_forbidden(self):
        """PRD §2.1: "only after the caller is authenticated does the system check whether
        the role is permitted to invoke the requested endpoint, rejecting impermissible
        combinations with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4 lists POST /aip/capital-programs under SponsorStaff; a FinanceOfficer calling
        it is impermissible even with a valid payload.

        Design: Corner/validations/role_mismatch_returns_forbidden
        """
        sponsor = create_sponsor()
        finance = build_user_headers("user-fin-1", "FinanceOfficer")
        res = api_client.create_program(
            {"sponsor_id": sponsor["id"], "fiscal_year": 2027}, finance)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_contractor_cannot_certify_assurance(self):
        """PRD §4 lists POST /aip/sponsor-assurances/{assuranceId}/certify under
        "Compliance officer certifies an assurance (cannot certify own application)" with
        authorized role ComplianceOfficer.
        PRD §2.1: "rejecting impermissible combinations with `ERR_FORBIDDEN` (HTTP 403)".

        Design: Corner/rbac/contractor_cannot_certify_assurance
        """
        sponsor = create_sponsor()
        program = create_draft_program(sponsor["id"])
        project = add_project(program["id"], title="Apron", project_type="CAPACITY",
                              estimated_cost=250_000, safety_score=5, capacity_score=5,
                              preservation_score=5, security_score=5, environmental_score=5)
        app = create_application(sponsor["id"], program["id"], [project["id"]])
        row = list_assurances(app["id"])[0]
        contractor = create_contractor(sponsor["id"])
        res = api_client.certify_assurance(
            row["id"], make_contractor_headers(contractor["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


class TestFiscalCheckpoint:
    def test_checkpoint_expires_applications_and_programs(self):
        """PRD §2.4: "an application still in `DRAFT`, `UNDER_REVIEW`, or `RETURNED` once the
        clock passes that instant is moved to `EXPIRED`."
        PRD §2.4: "A capital program still in `DRAFT`, `SUBMITTED`, or `AMENDMENT_DRAFT` once
        the clock passes December 31 at 23:59:59 UTC of the year preceding its `fiscal_year`
        is likewise moved to `EXPIRED`, and every child project still in `PROPOSED`,
        `SELECTED`, or `DEFERRED` is dropped with it."
        PRD §2.4: "both are executed by a checkpoint batch capability, invoked by a
        `FAAManager`, which also recomputes the service credits of in-service grant assets
        against the current clock and reports the counts `applications_expired`,
        `programs_expired`, and `assets_recomputed`."

        Design: Corner/cross_cutting_layers/checkpoint_expires_applications_and_programs
        """
        set_clock("2026-05-01T00:00:00Z")
        sponsor = create_sponsor()
        program = create_draft_program(sponsor["id"], fiscal_year=2027)
        project = add_project(program["id"], title="Apron", project_type="CAPACITY",
                              estimated_cost=250_000, safety_score=5, capacity_score=5,
                              preservation_score=5, security_score=5, environmental_score=5)
        app = validate_success(api_client.create_application(
            create_application_payload(sponsor["id"], program["id"], [project["id"]]),
            SPONSOR), 201)

        # Past the FY2027 application deadline (2026-05-15) and the program's
        # 2026-12-31 boundary.
        set_clock("2027-01-01T00:00:00Z")
        counts = validate_success(api_client.run_checkpoint(FAA), 200)
        assert counts["applications_expired"] == 1
        assert counts["programs_expired"] == 1

        app_after = validate_success(api_client.get_application(app["id"], SPONSOR), 200)
        assert app_after["status"] == "EXPIRED"
        program_after = validate_success(api_client.get_program(program["id"], SPONSOR),
                                         200)
        assert program_after["status"] == "EXPIRED"
        project_after = validate_success(api_client.get_project(project["id"], SPONSOR),
                                         200)
        assert project_after["status"] == "DROPPED"
