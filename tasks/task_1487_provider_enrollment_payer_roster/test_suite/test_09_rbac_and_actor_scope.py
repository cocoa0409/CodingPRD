"""Role-based access control and actor-scope rules (PRD §2.1, §2.8 tiers 1/2/5,
§3.5 segregation of duties)."""
from test_helpers import (
    ApiErrorId,
    confirm_line,
    create_active_agreement,
    create_payer_config,
    create_practice_group,
    create_provider,
    create_submitted_application,
    get_agreement,
    get_roster_line,
    make_compliance_officer_headers,
    make_provider_headers,
    roster_add_line,
    setup_group_provider_payer,
    submit_roster_file,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

SPECIALIST = TEST_USERS["enrollment_specialist_headers"]
PAYER_REP = TEST_USERS["payer_representative_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


class TestMissingContextHeaders:
    def test_request_without_user_headers_returns_400(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, naming the capacity in
        which they act. The declared roles are `ComplianceOfficer`,
        `EnrollmentSpecialist`, `PayerRepresentative`, and `Provider`. A request
        missing either header, or carrying a role name that is not one of these
        four, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/rbac/missing_auth_headers_returns_400
        """
        res = api.create_payer(
            {
                "payer_code": "PX",
                "name": "Payer X",
                "is_medicare": False,
                "effective_date_policy": "APPROVAL_DATE",
                "claims_hold_enabled": True,
                "revalidation_interval_days": 200,
            },
            headers={},
        )
        validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRoleAuthorization:
    def test_specialist_cannot_approve_application(self, api):
        """PRD §2.1: "A request whose role is not listed among the roles
        authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: POST /api/enrollment-applications/{id}/approve —
        "PayerRepresentative".

        Design: Corner/rbac/specialist_cannot_approve_application
        """
        _, provider, _, payer = setup_group_provider_payer()
        app = create_submitted_application(provider["id"], payer["id"])

        res = api.approve_application(app["id"], SPECIALIST)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

        after = validate_success(api.get_enrollment_application(app["id"], SPECIALIST), 200)
        assert after["status"] == "SUBMITTED"

    def test_payer_representative_cannot_submit_roster(self, api):
        """PRD §2.1: "A request whose role is not listed among the roles
        authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: POST /api/roster-files — "EnrollmentSpecialist".

        Design: Corner/rbac/payer_rep_cannot_submit_roster
        """
        group = create_practice_group()
        provider = create_provider(group["id"])
        payer = create_payer_config()
        agreement = create_active_agreement(group["id"], payer["id"])
        version_before = agreement["version"]

        res = api.create_roster_file(
            {
                "agreement_id": agreement["id"],
                "expected_agreement_version": agreement["version"],
                "lines": [roster_add_line(provider["id"])],
            },
            PAYER_REP,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        assert get_agreement(agreement["id"])["version"] == version_before, (
            "the write never happened, so the agreement version is unchanged"
        )

    def test_provider_role_cannot_create_payer(self, api):
        """PRD §2.1: "A request whose role is not listed among the roles
        authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: POST /api/payers — "ComplianceOfficer".

        Design: Corner/rbac/provider_cannot_create_payer
        """
        group = create_practice_group()
        provider = create_provider(group["id"])

        res = api.create_payer(
            {
                "payer_code": "PX",
                "name": "Payer X",
                "is_medicare": False,
                "effective_date_policy": "APPROVAL_DATE",
                "claims_hold_enabled": True,
                "revalidation_interval_days": 200,
            },
            make_provider_headers(provider["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


class TestRosterReconcileSegregationOfDuties:
    def test_submitter_cannot_reconcile_own_roster(self, api):
        """PRD §3.5: "A `ComplianceOfficer` reconciles a file that has reached
        `CONFIRMED` or `PARTIALLY_CONFIRMED`, moving it to `RECONCILED` — but
        never the file they submitted themselves: if the reconciler's
        `X-User-ID` equals the file's `submitted_by_user_id`, the attempt is
        rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/roster_reconcile_segregation_of_duties
        """
        group = create_practice_group()
        provider = create_provider(group["id"])
        payer = create_payer_config()
        agreement = create_active_agreement(group["id"], payer["id"])

        roster = submit_roster_file(
            agreement["id"], agreement["version"],
            [roster_add_line(provider["id"], expected_effective_date="2026-08-01")],
            submitter_user_id="spec-1",
        )
        assert roster["submitted_by_user_id"] == "spec-1"
        line = get_roster_line(roster["id"], 0)
        confirm_line(roster["id"], line["id"], "2026-08-01")
        assert validate_success(api.get_roster_file(roster["id"], SPECIALIST), 200)[
            "status"
        ] == "CONFIRMED"

        # The same operator id that submitted the roster may not reconcile it.
        res = api.reconcile_roster_file(
            roster["id"], make_compliance_officer_headers("spec-1")
        )
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        reconciled = validate_success(
            api.reconcile_roster_file(
                roster["id"], make_compliance_officer_headers("officer-7")
            ),
            200,
        )
        assert reconciled["status"] == "RECONCILED"
