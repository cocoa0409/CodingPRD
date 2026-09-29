"""Who may act, and on whose records.

Three of the five roles are opaque and act for anyone; two are entity-backed and
act only for themselves. On top of that sits a rule that no single officer may
both prepare and certify the same packet.
"""

from test_helpers import (
    ADMIN,
    COMPLIANCE,
    REGULATOR,
    ApiErrorId,
    api_client,
    attach_document,
    create_fundraiser,
    create_officer,
    create_organization,
    make_certifying_officer_headers,
    make_fundraiser_agent_headers,
    read_organization,
    read_registration,
    seed_california_profile,
    seed_state_profile,
    setup_draft_filing,
    setup_submitted_filing,
    state_profile_payload,
    validate_error,
    validate_success,
)


class TestAdjudicationIsExclusiveToTheRegulator:
    """The charity's own preparer cannot approve the charity's own packet."""

    def test_a_compliance_officer_reviewing_a_submitted_filing_is_refused(self):
        """PRD §2.1: "A well-authenticated request whose role does not appear in the
        authorized-role list of the endpoint it targets (see §4) is rejected with
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403)." PRD §2.1 on the opaque roles: "A
        compliance officer therefore acts on behalf of any organization in the roster, a
        state regulator adjudicates any filing, and a platform administrator seeds
        configuration and drives the clock, all without an ownership relationship."

        Design: Corner/rbac/compliance_officer_cannot_review_its_own_filing
        """
        ctx = setup_submitted_filing()

        response = api_client.review_state_registration(
            ctx["registration"]["id"], {"decision": "APPROVE"}, COMPLIANCE
        )

        validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)
        filing = read_registration(ctx["registration"]["id"])
        assert filing["status"] == "SUBMITTED", (
            f"The packet still awaits adjudication, got {filing['status']}"
        )
        assert filing["registered_at"] is None, (
            f"Nothing was registered, got {filing['registered_at']}"
        )
        assert read_organization(ctx["organization"]["id"])[
            "registered_state_count"
        ] == 0, "And the charity is registered nowhere"


class TestConfigurationIsExclusiveToTheAdministrator:
    """A fundraiser may read a rule set it may not write."""

    def test_a_fundraiser_agent_may_read_a_profile_but_not_seed_one(self):
        """PRD §2.1: "A request missing either header, carrying an empty value, or naming
        a role outside that set of five is rejected with `ERR_UNAUTHENTICATED` (HTTP
        401). A well-authenticated request whose role does not appear in the
        authorized-role list of the endpoint it targets (see §4) is rejected with
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403)." PRD §4 authorizes `POST /state-profiles`
        for "SystemAdmin" alone and `GET /state-profiles/{state_code}` for "All roles".

        Design: Corner/rbac/fundraiser_agent_cannot_seed_a_state_rule_set
        """
        seed_california_profile(
            fundraiser_contract_filing_days=10, fundraiser_bond_minimum_cents=2_500_000
        )
        firm = create_fundraiser(
            legal_name="Northline Donor Services",
            bond_amount_cents=2_500_000,
            bond_expires_at="2028-12-31T00:00:00Z",
        )
        agent = make_fundraiser_agent_headers(firm["id"])

        profile = validate_success(api_client.get_state_profile("CA", agent))
        response = api_client.create_state_profile(
            state_profile_payload(
                "NV",
                registration_required=False,
                renewal_due_rule="FYE_PLUS_6M",
                assurance_basis="GROSS_REVENUE",
            ),
            agent,
        )

        assert profile["fundraiser_contract_filing_days"] == 10, (
            "The firm can read the window it must file inside, got "
            f"{profile['fundraiser_contract_filing_days']}"
        )
        validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)
        validate_error(
            api_client.get_state_profile("NV", ADMIN),
            ApiErrorId.ERR_STATE_PROFILE_NOT_FOUND.value,
        )


class TestOrganizationReadIsSharedByEveryRole:
    """One endpoint, five capacities, one body."""

    def test_all_five_roles_read_the_same_charity(self):
        """PRD §2.1: "Five roles exist, spelled exactly as follows:
        `ComplianceOfficer`, `CertifyingOfficer`, `StateRegulator`, `FundraiserAgent`,
        and `SystemAdmin`." PRD §4 authorizes `GET /organizations/{id}` — "Read one
        organization including its derived postures, counters and penalty ledger" — for
        "All roles".

        Design: Corner/rbac/organization_read_is_shared_by_all_five_roles
        """
        seed_state_profile("CA", assurance_basis="GROSS_REVENUE")
        organization = create_organization()
        certifier = create_officer(
            organization["id"], "Dana Reyes", "PRESIDENT", is_certifying_officer=True
        )
        firm = create_fundraiser(
            legal_name="Northline Donor Services",
            bond_amount_cents=2_500_000,
            bond_expires_at="2028-12-31T00:00:00Z",
        )

        bodies = {
            "ComplianceOfficer": validate_success(
                api_client.get_organization(organization["id"], COMPLIANCE)
            ),
            "CertifyingOfficer": validate_success(
                api_client.get_organization(
                    organization["id"], make_certifying_officer_headers(certifier["id"])
                )
            ),
            "StateRegulator": validate_success(
                api_client.get_organization(organization["id"], REGULATOR)
            ),
            "SystemAdmin": validate_success(
                api_client.get_organization(organization["id"], ADMIN)
            ),
            "FundraiserAgent": validate_success(
                api_client.get_organization(
                    organization["id"], make_fundraiser_agent_headers(firm["id"])
                )
            ),
        }

        for role, body in bodies.items():
            assert body["legal_name"] == "Harbor Light Foundation", (
                f"{role} reads the same charity, got {body['legal_name']}"
            )
            assert body["id"] == organization["id"], (
                f"{role} reads the same row, got {body['id']}"
            )
        assert bodies["FundraiserAgent"]["filing_posture"] == "CURRENT", (
            "An outside firm sees the derived posture too, got "
            f"{bodies['FundraiserAgent']['filing_posture']}"
        )


class TestOwnershipIsCheckedAgainstTheOfficersOwnCharity:
    """Holding the role is not holding the roster seat."""

    def test_an_officer_of_a_peer_charity_cannot_certify_this_packet(self):
        """PRD §2.1: "Where an entity-backed role acts on a resource it does not own,
        the rejection is `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This covers a
        `FundraiserAgent` registering a firm other than its own or filing a contract
        whose `fundraiser_id` is not its own identifier, and a `CertifyingOfficer`
        acting on a filing or promotion whose `organization_id` differs from the
        organization of the disclosure named by `X-User-ID`."

        Design: Corner/rbac/certifying_officer_of_another_charity_cannot_submit_this_packet
        """
        ctx = setup_draft_filing()
        peer = create_organization(
            legal_name="Cedar Ridge Alliance",
            ein="223456789",
            domicile_state_code="CA",
            fiscal_year_end_month=6,
        )
        peer_certifier = create_officer(
            peer["id"], "Lee Vasquez", "PRESIDENT", is_certifying_officer=True
        )

        response = api_client.submit_state_registration(
            ctx["registration"]["id"],
            {"certification_note": "Certified under penalty of perjury."},
            make_certifying_officer_headers(peer_certifier["id"]),
        )

        validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
        filing = read_registration(ctx["registration"]["id"])
        assert filing["status"] == "DRAFT", (
            f"The packet was never submitted, got {filing['status']}"
        )
        assert filing["certified_by_officer_id"] is None, (
            f"No officer was stamped, got {filing['certified_by_officer_id']}"
        )
        assert filing["submitted_at"] is None, (
            f"And no instant was stamped, got {filing['submitted_at']}"
        )


class TestSegregationOfDutiesIsPerDocument:
    """The one officer who prepared a page cannot be the one who swears to it."""

    def test_the_certifier_who_prepared_the_review_report_cannot_submit(self):
        """PRD §2.1: "Segregation of duties is a first-class rule rather than an
        afterthought: the officer who certifies a filing may not have prepared any
        document inside it, and the officer who settles a co-venture promotion may not
        be the officer who certified that promotion's client filing for the same state.
        Both violations report `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/officer_who_prepared_the_packet_cannot_certify_it
        """
        ctx = setup_draft_filing(attach_documents=False)
        registration_id = ctx["registration"]["id"]
        certifier_id = ctx["certifier"]["id"]
        attach_document(registration_id, ctx["preparer"]["id"], "GOVERNING_DOCUMENT")
        attach_document(registration_id, ctx["preparer"]["id"], "FINANCIAL_STATEMENT")
        tainted = attach_document(registration_id, certifier_id, "REVIEW_REPORT")

        response = api_client.submit_state_registration(
            registration_id,
            {"certification_note": "Certified under penalty of perjury."},
            make_certifying_officer_headers(certifier_id),
        )

        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
        assert tainted["prepared_by_officer_id"] == certifier_id, (
            "The offending document names the certifying officer as its preparer, got "
            f"{tainted['prepared_by_officer_id']}"
        )
        filing = read_registration(registration_id)
        assert filing["status"] == "DRAFT", (
            f"The packet is still a draft, got {filing['status']}"
        )
        assert filing["certified_by_officer_id"] is None, (
            f"No officer was stamped, got {filing['certified_by_officer_id']}"
        )
