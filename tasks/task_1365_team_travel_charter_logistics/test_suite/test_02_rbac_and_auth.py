"""Header validation, role authorization, and segregation of duties (PRD §2.1, §3.10)."""
import pytest

from test_helpers import (
    TEST_USERS, build_user_headers,
    create_team_payload, create_trip_payload, create_credential_payload,
    create_contract, create_credential_request,
    setup_team_season, setup_team_season_trip, add_member,
    make_security_officer_headers,
    validate_error, validate_success,
)

MGR = TEST_USERS["manager_headers"]
FIN = TEST_USERS["finance_headers"]
EQ = TEST_USERS["equipment_headers"]
VENDOR = TEST_USERS["vendor_headers"]


class TestHeaderValidation:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying a malformed
        value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/validations/missing_auth_header_rejected
        """
        res = api.create_team(
            create_team_payload(team_code="XXX", display_name="No Auth"), headers={})
        validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                       expected_status=400)


class TestRoleAuthorization:
    def test_team_member_cannot_create_trip(self, api):
        """PRD §2.1: "A request whose role is not permitted to perform the
        attempted operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)." PRD §4: "Create a trip in DRAFT | TravelManager".

        Design: Corner/validations/role_not_permitted
        """
        team, season = setup_team_season()
        member_headers = build_user_headers("arbitrary-member-id", "TeamMember")
        res = api.create_trip(team["id"], create_trip_payload(season["id"]),
                              member_headers)
        validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)

    def test_vendor_rep_cannot_execute_contract(self, api):
        """PRD §2.1: "A request whose role is not permitted to perform the
        attempted operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)." PRD §4: "Team executes contract | TravelFinanceLead".

        Design: Corner/rbac/vendor_rep_cannot_execute_contract
        """
        team, season, trip = setup_team_season_trip(
            budget_cents=1000000000,
            trip_overrides={"game_tipoff_utc": "2027-06-10T00:00:00Z"})
        contract = create_contract(team["id"], trip["id"])
        validate_success(
            api.submit_contract(team["id"], trip["id"], contract["id"], MGR), 200)
        countersigned = validate_success(
            api.countersign_contract(team["id"], trip["id"], contract["id"], VENDOR), 200)
        res = api.execute_contract(
            team["id"], trip["id"], contract["id"], countersigned["version"], VENDOR)
        validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)

    def test_equipment_manager_cannot_security_review(self, api):
        """PRD §2.1: "A request whose role is not permitted to perform the
        attempted operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)." PRD §4: "Move credential to security review | SecurityOfficer".

        Design: Corner/rbac/equipment_manager_cannot_manage_credentials
        """
        team, season, trip = setup_team_season_trip()
        member = add_member(team["id"], trip["id"], member_ref="C02")
        cred = create_credential_request(team["id"], trip["id"], member["id"],
                                         venue_code="MKE")
        res = api.security_review_credential(
            team["id"], trip["id"], cred["id"],
            build_user_headers("eq-manager-1", "EquipmentManager"))
        validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)


class TestSegregationOfDuties:
    def test_submitter_cannot_security_review_own_request(self, api):
        """PRD §3.10: "A `SecurityOfficer` moves the request from `SUBMITTED` to
        `SECURITY_REVIEW`, but only if the officer's `X-User-ID` differs from the
        `submitted_by_user_id` — a submitter may not review their own request,
        and the attempt fails with `ERR_SOD_VIOLATION` (HTTP 403)".

        Design: Corner/validations/sod_reviewer_equals_submitter_rejected
        """
        team, season, trip = setup_team_season_trip()
        member = add_member(team["id"], trip["id"], member_ref="L01")
        cred = create_credential_request(team["id"], trip["id"], member["id"],
                                         venue_code="PHX")
        # Same X-User-ID as the submitter, but acting in the SecurityOfficer role.
        res = api.security_review_credential(
            team["id"], trip["id"], cred["id"],
            make_security_officer_headers(member["id"]))
        validate_error(res, "ERR_SOD_VIOLATION", expected_status=403)
