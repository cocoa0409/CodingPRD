"""Authentication, role authorization, and entity-backed ownership (PRD §2.1)."""
from test_helpers import (
    ApiErrorId,
    create_trust_payload,
    get_success_data,
    make_beneficiary_headers,
    make_tax_headers,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    EXEC,
    MANAGER,
    OFFICER,
    add_beneficiary,
    create_active_trust,
    create_approved_document,
    create_request,
    create_trust,
)


class TestAuthentication:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, naming the capacity in
        which they act. A request missing either header, or naming a role the
        system does not recognize, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/missing_auth_headers_unauthenticated
        """
        resp = api.create_trust(
            create_trust_payload(trust_name="NoAuth", distribution_standard="HEMS"),
            headers={},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_unrecognized_role_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or naming a role the
        system does not recognize, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/missing_auth_headers_unauthenticated
        """
        resp = api.create_trust(
            create_trust_payload(),
            headers={"X-User-ID": "someone", "X-User-Role": "SuperUser"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleAuthorization:
    def test_beneficiary_role_forbidden_from_trust_create(self, api):
        """PRD §2.1: "A request whose role is recognized but not authorized
        for the target operation is rejected with `ERR_FORBIDDEN`.""
        PRD §4: "POST /trusts | Create a trust account in DRAFT | TrustOfficer".

        Design: Corner/rbac/beneficiary_role_forbidden_from_staff_endpoints
        """
        resp = api.create_trust(
            create_trust_payload(trust_name="Nope", distribution_standard="HEMS"),
            make_beneficiary_headers("ben_outsider"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_beneficiary_role_forbidden_from_committee_create(self, api):
        """PRD §2.1: "A request whose role is recognized but not authorized
        for the target operation is rejected with `ERR_FORBIDDEN`."
        PRD §3.2: "A `TrustExecutive` creates a CommitteeMember with a
        `full_name` and a service window from `term_start` to `term_end`;
        members start ACTIVE."

        Design: Corner/rbac/beneficiary_role_forbidden_from_staff_endpoints
        """
        resp = api.create_committee_member(
            {"full_name": "Nope", "term_start": "2026-01-01", "term_end": "2028-12-31"},
            make_beneficiary_headers("ben_outsider"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_officer_cannot_approve_document(self, api):
        """PRD §3.1: "A `TrustExecutive` then either approves the
        interpretation, moving INTERPRETED → APPROVED and stamping
        `approved_at`, or rejects it, moving INTERPRETED → REJECTED with a
        recorded `rejected_reason`."
        PRD §2.1: "A request whose role is recognized but not authorized for
        the target operation is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/officer_cannot_approve_document
        """
        trust = create_trust(trust_name="RBAC Doc")
        resp = api.create_document(
            {"trust_id": trust["id"], "version_number": 1, "summary": "v1"}, OFFICER
        )
        doc = get_success_data(resp)
        assert api.submit_document(doc["id"], OFFICER).status_code == 200
        assert api.interpret_document(
            doc["id"], {"per_stirpes": False, "interpretation_notes": "ok"}, OFFICER
        ).status_code == 200

        denied = api.approve_document(doc["id"], OFFICER)
        validate_error(denied, ApiErrorId.ERR_FORBIDDEN)

        approved = api.approve_document(doc["id"], EXEC)
        data = validate_success(approved)
        assert data["status"] == "APPROVED"

    def test_tax_specialist_cannot_activate_ips(self, api):
        """PRD §3.4: "Activation moves DRAFT → ACTIVE and enforces window
        hygiene" and PRD §4: "POST |
        `/trusts/investment-policy-statements/{id}/activate` | Move DRAFT to
        ACTIVE; supersedes the prior policy and runs a drift check |
        InvestmentManager".
        PRD §2.1: "A request whose role is recognized but not authorized for
        the target operation is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/tax_specialist_cannot_activate_ips
        """
        trust = create_active_trust(trust_name="RBAC IPS")
        resp = api.create_ips(
            {
                "trust_id": trust["id"],
                "effective_from": "2026-08-01",
                "effective_to": "2027-08-01",
                "equity_target_pct": 60.00,
                "equity_band_pct": 5.00,
                "fixed_income_target_pct": 30.00,
                "fixed_income_band_pct": 5.00,
                "alternatives_allowed": False,
            },
            MANAGER,
        )
        ips = get_success_data(resp)
        denied = api.activate_ips(ips["id"], make_tax_headers("tax_outsider"))
        validate_error(denied, ApiErrorId.ERR_FORBIDDEN)
        current = validate_success(api.get_ips(ips["id"], MANAGER))
        assert current["status"] == "DRAFT"


class TestBeneficiaryOwnership:
    def test_beneficiary_cannot_withdraw_others_request(self, api):
        """PRD §2.1: "When `X-User-Role` is `Beneficiary`, `X-User-ID` is the
        `id` of the acting Beneficiary; ownership checks on any resource that
        references a Beneficiary compare the resource's beneficiary reference
        to `X-User-ID`, and a mismatch is rejected with
        `ERR_NOT_OWN_RESOURCE`."

        Design: Corner/rbac/beneficiary_cannot_withdraw_others_request
        """
        trust = create_trust(trust_name="Ownership")
        create_approved_document(trust["id"])
        ben_a = add_beneficiary(trust["id"], full_name="A Aaa", share_bps=6000,
                                date_of_birth="1950-01-01")
        ben_b = add_beneficiary(trust["id"], full_name="B Bbb", share_bps=4000,
                                date_of_birth="1951-01-01")
        assert api.submit_for_acceptance(trust["id"], OFFICER).status_code == 200
        assert api.accept_trust(trust["id"], EXEC).status_code == 200

        req = create_request(trust["id"], ben_a["id"], amount_cents=50000,
                             as_beneficiary=True)
        denied = api.withdraw_request(req["id"], make_beneficiary_headers(ben_b["id"]))
        validate_error(denied, ApiErrorId.ERR_NOT_OWN_RESOURCE)

    def test_owning_beneficiary_withdraw_succeeds(self, api):
        """PRD §3.3: "The beneficiary may also abandon the request: withdrawal
        moves SUBMITTED, UNDER_REVIEW, or INFORMATION_REQUESTED → WITHDRAWN,
        is restricted to the owning beneficiary in the same way, decrements
        `pending_distribution_count` by one, and increments the trust's
        `version`."

        Design: Corner/rbac/beneficiary_cannot_withdraw_others_request
        """
        trust = create_trust(trust_name="Ownership Own")
        create_approved_document(trust["id"])
        ben_a = add_beneficiary(trust["id"], full_name="A Aaa", share_bps=6000,
                                date_of_birth="1950-01-01")
        add_beneficiary(trust["id"], full_name="B Bbb", share_bps=4000,
                        date_of_birth="1951-01-01")
        assert api.submit_for_acceptance(trust["id"], OFFICER).status_code == 200
        assert api.accept_trust(trust["id"], EXEC).status_code == 200

        req = create_request(trust["id"], ben_a["id"], amount_cents=50000,
                             as_beneficiary=True)
        data = validate_success(
            api.withdraw_request(req["id"], make_beneficiary_headers(ben_a["id"]))
        )
        assert data["status"] == "WITHDRAWN"
        trust_after = validate_success(api.get_trust(trust["id"], OFFICER))
        assert trust_after["pending_distribution_count"] == 0
