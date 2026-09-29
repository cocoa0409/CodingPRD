"""Every refusal in the catalog, triggered where the ladder says it lives.

The ladder is ascending and the first failure wins, so each of these scenarios
is built so that exactly one rung can answer — and the code it names is the code
the catalog assigns to that resource family.
"""

from test_helpers import (
    COMPLIANCE,
    NON_EXISTENT_UUID,
    REGULATOR,
    ApiErrorId,
    api_client,
    create_financial_statement,
    create_fundraiser,
    create_officer,
    create_organization,
    extension_request_payload,
    decide_extension,
    fundraiser_registration_payload,
    list_financial_statements,
    issue_enforcement_action,
    make_fundraiser_agent_headers,
    move_clock_to,
    open_filing,
    read_enforcement_action,
    read_organization,
    read_promotion,
    read_registration,
    register_fundraiser_in_state,
    registration_document_payload,
    remediate_action,
    run_sweep,
    seed_california_profile,
    seed_state_profile,
    settle_promotion,
    setup_draft_filing,
    setup_filed_promotion,
    setup_granted_extension,
    setup_two_state_charity,
    state_registration_payload,
    submit_filing,
    vacate_action,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthenticationRungRunsFirst:
    """No headers at all is 401, not 403 and not 404."""

    def test_a_read_of_a_real_charity_without_headers_is_unauthenticated(self):
        """PRD §2.11 rung 1: "Authentication — both headers present and
        `X-User-Role` one of the five declared roles → `ERR_UNAUTHENTICATED` (401).
        Applies to every endpoint."

        Design: Corner/errors/request_missing_auth_headers_returns_unauthenticated
        """
        seed_state_profile("CA", assurance_basis="GROSS_REVENUE")
        organization = create_organization()

        response = api_client.get_organization(organization["id"])

        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
        assert read_organization(organization["id"])["id"] == organization["id"], (
            "The very same read succeeds once the headers are present"
        )


class TestUnseededStateCode:
    """A state whose rule set was never written is a 404 on every surface."""

    def test_an_unseeded_state_is_not_found_both_as_a_path_and_as_a_body_key(self):
        """PRD §2.7: "A referenced `state_code` that matches no profile — whether it
        arrives as a path parameter, as a payload field, or as one element of a
        `state_codes` array — is rejected with `ERR_STATE_PROFILE_NOT_FOUND` (HTTP
        404)."

        Design: Corner/errors/unseeded_state_code_returns_state_profile_not_found
        """
        seed_state_profile("CA", assurance_basis="GROSS_REVENUE")
        organization = create_organization()
        statement = create_financial_statement(organization)

        read_response = api_client.get_state_profile("OR", COMPLIANCE)
        create_response = api_client.create_state_registration(
            state_registration_payload(organization["id"], statement["id"], "OR"),
            COMPLIANCE,
        )

        validate_error(read_response, ApiErrorId.ERR_STATE_PROFILE_NOT_FOUND.value)
        validate_error(create_response, ApiErrorId.ERR_STATE_PROFILE_NOT_FOUND.value)
        assert read_organization(organization["id"])["registered_state_count"] == 0, (
            "The refused create opened no filing"
        )


class TestUnknownPreparerOnADocument:
    """With the filing real, the officer is what fails."""

    def test_a_document_naming_no_existing_officer_reports_officer_not_found(self):
        """PRD §2.9: "A dangling `organization_id` reports
        `ERR_ORGANIZATION_NOT_FOUND`; a dangling `financial_statement_id` reports
        `ERR_FINANCIAL_STATEMENT_NOT_FOUND`; a dangling `prepared_by_officer_id`
        reports `ERR_OFFICER_NOT_FOUND`; a dangling `fundraiser_id` or `coventurer_id`
        reports `ERR_FUNDRAISER_NOT_FOUND`; a dangling `registration_id` or
        `supersedes_registration_id` reports `ERR_REGISTRATION_NOT_FOUND`."

        Design: Corner/errors/document_naming_an_unknown_preparer_returns_officer_not_found
        """
        seed_state_profile("CA", assurance_basis="GROSS_REVENUE")
        organization = create_organization()
        statement = create_financial_statement(organization)
        filing = open_filing(organization["id"], statement["id"], "CA")

        response = api_client.create_registration_document(
            registration_document_payload(filing["id"], NON_EXISTENT_UUID),
            COMPLIANCE,
        )

        validate_error(response, ApiErrorId.ERR_OFFICER_NOT_FOUND.value)
        documents, meta = validate_paginated(
            api_client.list_registration_documents(
                COMPLIANCE, params={"registration_id": filing["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"No document row was created, got {meta['total_count']}"
        )
        assert documents == [], f"And none is listed, got {documents}"


class TestEachResourceFamilyOwnsItsNotFoundCode:
    """Six unknown path identifiers, six different codes."""

    def test_unknown_path_identifiers_report_their_own_not_found_codes(self):
        """PRD §2.9: "The first identifier in the path that names no existing row
        determines the error, and the server stops there rather than continuing to
        evaluate deeper segments or the request body: a document read reports
        `ERR_REGISTRATION_DOCUMENT_NOT_FOUND`, an extension-request decision reports
        `ERR_EXTENSION_REQUEST_NOT_FOUND`, an enforcement decision reports
        `ERR_ENFORCEMENT_ACTION_NOT_FOUND`, a contract operation reports
        `ERR_CONTRACT_NOT_FOUND`, a promotion operation reports
        `ERR_PROMOTION_NOT_FOUND`, a filing operation reports
        `ERR_REGISTRATION_NOT_FOUND`, an organization read or amendment reports
        `ERR_ORGANIZATION_NOT_FOUND`, a fundraiser read reports
        `ERR_FUNDRAISER_NOT_FOUND`, and a profile read keyed on `state_code` reports
        `ERR_STATE_PROFILE_NOT_FOUND`. All nine carry HTTP 404."

        Design: Corner/errors/unknown_path_ids_return_their_own_not_found_codes
        """
        seed_california_profile()
        firm = create_fundraiser(
            legal_name="Northline Donor Services",
            bond_amount_cents=2_500_000,
            bond_expires_at="2028-12-31T00:00:00Z",
        )
        agent = make_fundraiser_agent_headers(firm["id"])
        missing = "00000000-0000-0000-0000-00000000000{}"

        cases = [
            (
                api_client.remediate_enforcement_action(
                    missing.format(1),
                    {"remediation_note": "Answering a notice that does not exist."},
                    COMPLIANCE,
                ),
                ApiErrorId.ERR_ENFORCEMENT_ACTION_NOT_FOUND.value,
            ),
            (
                api_client.file_fundraising_contract(missing.format(2), {}, agent),
                ApiErrorId.ERR_CONTRACT_NOT_FOUND.value,
            ),
            (
                api_client.activate_coventure_promotion(
                    missing.format(3), {}, COMPLIANCE
                ),
                ApiErrorId.ERR_PROMOTION_NOT_FOUND.value,
            ),
            (
                api_client.decide_extension_request(
                    missing.format(4), {"decision": "GRANT"}, REGULATOR
                ),
                ApiErrorId.ERR_EXTENSION_REQUEST_NOT_FOUND.value,
            ),
            (
                api_client.get_registration_document(missing.format(5), COMPLIANCE),
                ApiErrorId.ERR_REGISTRATION_DOCUMENT_NOT_FOUND.value,
            ),
            (
                api_client.get_professional_fundraiser(missing.format(6), COMPLIANCE),
                ApiErrorId.ERR_FUNDRAISER_NOT_FOUND.value,
            ),
        ]

        for response, expected_error_id in cases:
            assert response.status_code == 404, (
                f"{expected_error_id} carries HTTP 404, got {response.status_code}"
            )
            validate_error(response, expected_error_id)


class TestFundraiserRegistrationUniqueness:
    """A better bond does not buy a second live registration in one state."""

    def test_a_second_active_registration_in_the_same_state_is_refused(self):
        """PRD §2.11 rung 33: "No other active fundraiser registration exists for the
        same firm and state → `ERR_DUPLICATE_FUNDRAISER_REGISTRATION` (409). Applies to
        fundraiser-registration creation."

        Design: Corner/errors/second_active_registration_for_the_same_state_rejected
        """
        seed_california_profile()
        firm = create_fundraiser(
            legal_name="Northline Donor Services",
            bond_amount_cents=5_000_000,
            bond_expires_at="2028-12-31T00:00:00Z",
        )
        agent = make_fundraiser_agent_headers(firm["id"])
        incumbent = register_fundraiser_in_state(
            firm["id"], "CA", bond_on_file_cents=2_500_000,
            expires_at="2027-12-31T00:00:00Z",
        )

        response = api_client.create_fundraiser_registration(
            fundraiser_registration_payload(
                firm["id"], "CA", 4_000_000, "2028-06-30T00:00:00Z"
            ),
            agent,
        )

        validate_error(
            response, ApiErrorId.ERR_DUPLICATE_FUNDRAISER_REGISTRATION.value
        )
        rows, meta = validate_paginated(
            api_client.list_fundraiser_registrations(firm["id"], agent)
        )
        assert meta["total_count"] == 1, (
            f"The refused create added no row, got {meta['total_count']}"
        )
        assert rows[0]["id"] == incumbent["id"], (
            "The surviving row is the first registration"
        )
        assert rows[0]["status"] == "ACTIVE", (
            f"It is still active, got {rows[0]['status']}"
        )
        assert rows[0]["bond_on_file_cents"] == 2_500_000, (
            "And still carries the original bond, got "
            f"{rows[0]['bond_on_file_cents']}"
        )


class TestVacaturIsTerminal:
    """A vacated assessment cannot be answered, and its penalty is gone."""

    def test_remediating_a_vacated_assessment_is_refused_on_the_state_rung(self):
        """PRD §2.11 rung 10: "The enforcement action's `status` is in the requested
        transition's from-set → `ERR_INVALID_ENFORCEMENT_STATE` (409). Applies to
        remediation, decision, and vacatur of an enforcement action." PRD §3.9: a
        remediation "deliberately leaves `penalty_outstanding_cents` alone, because a
        submitted remediation is still an outstanding matter: the penalty leaves the
        ledger only when the action is cured or vacated."

        Design: Corner/errors/remediating_a_vacated_action_rejected
        """
        seed_california_profile()
        organization = create_organization()
        statement = create_financial_statement(organization)
        filing = open_filing(organization["id"], statement["id"], "CA")
        action = issue_enforcement_action(
            organization["id"],
            filing["id"],
            "PENALTY_ASSESSMENT",
            penalty_cents_override=25_000,
        )
        validate_success(
            vacate_action(action["id"], "Issued against the wrong fiscal year.")
        )

        response = remediate_action(action["id"], "Packet submitted anyway.")

        validate_error(response, ApiErrorId.ERR_INVALID_ENFORCEMENT_STATE.value)
        reread = read_enforcement_action(action["id"])
        assert reread["status"] == "VACATED", (
            f"Vacatur is terminal, got {reread['status']}"
        )
        assert reread["settlement_total_cents"] == 0, (
            f"No settlement was ever stamped, got {reread['settlement_total_cents']}"
        )
        assert read_organization(organization["id"])["penalty_outstanding_cents"] == 0, (
            "The vacated penalty left the ledger and the refusal did not bring it back"
        )


class TestGrantedExtensionCannotBeGrantedTwice:
    """Replaying the grant would push the deadline out a second time."""

    def test_a_second_grant_on_the_same_request_is_refused(self):
        """PRD §3.5: "A state regulator resolves a pending request with a `decision` of
        `GRANT` or `DENY`; a request whose `status` is anything other than `PENDING`
        reports `ERR_EXTENSION_ALREADY_DECIDED`." PRD §3.5 on the grant length: "Under
        `IRS_990_EXTENSION` the server grants the smaller of 180 days and the state's
        `extension_max_days`, and `requested_days` is ignored entirely."

        Design: Corner/errors/deciding_an_already_granted_extension_rejected
        """
        ctx = setup_granted_extension()
        registration_id = ctx["registration"]["id"]

        response = decide_extension(ctx["extension_request"]["id"], "GRANT")

        validate_error(response, ApiErrorId.ERR_EXTENSION_ALREADY_DECIDED.value)
        requests, meta = validate_paginated(
            api_client.list_registration_extension_requests(
                registration_id, COMPLIANCE
            )
        )
        assert meta["total_count"] == 1, (
            f"The refused decision created nothing, got {meta['total_count']}"
        )
        assert requests[0]["status"] == "GRANTED", (
            f"The request stays granted, got {requests[0]['status']}"
        )
        assert requests[0]["granted_days"] == 90, (
            "The smaller of 180 and California's 90-day ceiling, got "
            f"{requests[0]['granted_days']}"
        )
        assert (
            read_registration(registration_id)["extended_due_date"]
            == "2027-02-12T00:00:00.000Z"
        ), "The deadline was pushed out once and only once"


class TestSettlementRequiresAnActivatedCampaign:
    """The state rung answers before the window rung can."""

    def test_settling_a_merely_filed_promotion_is_refused(self):
        """PRD §2.11 rung 12: "The promotion's `status` is in the from-set — `DRAFT` to
        file, `FILED` to activate, `ACTIVE` or `DEFICIENT_REMITTANCE` to settle →
        `ERR_INVALID_PROMOTION_STATE` (409). Applies to promotion filing, activation,
        and settlement."

        Design: Corner/errors/settling_a_promotion_that_was_never_activated_rejected
        """
        seed_california_profile(coventure_filing_required=True, coventure_buffer_days=7)
        organization = create_organization()
        certifier = create_officer(
            organization["id"], "Dana Reyes", "PRESIDENT", is_certifying_officer=True
        )
        ctx = setup_filed_promotion(organization["id"], ["CA"])
        move_clock_to("2026-10-01T00:00:00Z")

        response = settle_promotion(
            ctx["promotion"]["id"], certifier["id"], 1_600, 500_000
        )

        validate_error(response, ApiErrorId.ERR_INVALID_PROMOTION_STATE.value)
        reread = read_promotion(ctx["promotion"]["id"])
        assert reread["status"] == "FILED", (
            f"The campaign was never activated, got {reread['status']}"
        )
        assert reread["actual_units"] == 0, (
            f"No units were counted, got {reread['actual_units']}"
        )
        assert reread["final_benefit_cents"] == 0, (
            f"And nothing was owed, got {reread['final_benefit_cents']}"
        )


class TestSupersedePointerMustNameALiveRegistration:
    """A renewal cannot supersede a packet that never registered."""

    def test_a_renewal_pointing_at_a_draft_predecessor_is_refused(self):
        """PRD §2.11 rung 20: "`supersedes_registration_id`, when supplied, targets a
        registration of the same organization and state whose `status` is `REGISTERED`
        or `DELINQUENT` → `ERR_SUPERSEDE_TARGET_INVALID` (422). Applies to registration
        creation and review."

        Design: Corner/errors/superseding_a_filing_that_was_never_registered_rejected
        """
        seed_state_profile("CA", assurance_basis="GROSS_REVENUE")
        organization = create_organization()
        statement = create_financial_statement(organization)
        draft = open_filing(organization["id"], statement["id"], "CA")

        response = api_client.create_state_registration(
            state_registration_payload(
                organization["id"],
                statement["id"],
                "CA",
                "RENEWAL",
                "2026-07-01T00:00:00Z",
                "2027-07-01T00:00:00Z",
                fiscal_year=2027,
                supersedes_registration_id=draft["id"],
            ),
            COMPLIANCE,
        )

        validate_error(response, ApiErrorId.ERR_SUPERSEDE_TARGET_INVALID.value)
        assert read_registration(draft["id"])["status"] == "DRAFT", (
            "The named predecessor is untouched and still a draft"
        )
        assert read_organization(organization["id"])["registered_state_count"] == 0, (
            "No filing has registered"
        )


class TestFilingPostureIsOrganizationWide:
    """A California delinquency blocks a Nevada plea for more time."""

    def test_an_extension_on_an_untouched_filing_is_refused_while_the_charity_is_delinquent(
        self,
    ):
        """PRD §3.5: "And the organization's `filing_posture` must be `CURRENT`: a
        charity already carrying a delinquent filing anywhere may not ask for more time,
        and the attempt is rejected with `ERR_FILING_POSTURE_DELINQUENT`."

        Design: Corner/errors/extension_requested_while_the_organization_is_delinquent_rejected
        """
        ctx = setup_two_state_charity(
            domicile="CA",
            second_state="NV",
            second_profile_overrides={
                "renewal_due_rule": "FYE_PLUS_6M",
                "extension_max_days": 60,
            },
        )
        nevada = open_filing(
            ctx["organization"]["id"], ctx["financial_statement"]["id"], "NV"
        )
        move_clock_to("2026-11-15T00:00:00Z")
        run_sweep("CA")

        response = api_client.create_extension_request(
            extension_request_payload(
                nevada["id"], nevada["version"], "STATE_HARDSHIP", 30
            ),
            COMPLIANCE,
        )

        validate_error(response, ApiErrorId.ERR_FILING_POSTURE_DELINQUENT.value)
        organization = read_organization(ctx["organization"]["id"])
        assert organization["filing_posture"] == "DELINQUENT", (
            f"The sweep moved the posture, got {organization['filing_posture']}"
        )
        assert organization["delinquent_registration_count"] == 1, (
            "Only the Californian filing went delinquent, got "
            f"{organization['delinquent_registration_count']}"
        )
        assert read_registration(ctx["registration"]["id"])["status"] == "DELINQUENT", (
            "The swept filing is the delinquent one"
        )
        nevada_reread = read_registration(nevada["id"])
        assert nevada_reread["status"] == "DRAFT", (
            f"Nevada was never swept, got {nevada_reread['status']}"
        )
        assert nevada_reread["extended_due_date"] is None, (
            f"And got no extension, got {nevada_reread['extended_due_date']}"
        )


class TestSupersededStatementCannotBackANewFiling:
    """A restatement leaves the old identifier unusable, not silently repointed."""

    def test_a_filing_pointing_at_the_restated_statement_is_refused(self):
        """PRD §2.11 rung 21: "The statement named by `financial_statement_id` has
        `statement_status` equal to `CURRENT` and belongs to the same organization →
        `ERR_FINANCIAL_STATEMENT_SUPERSEDED` (422). Applies to registration creation and
        filing submission." PRD §3.2: "Filing a second statement for a `fiscal_year`
        that already has a current one is a **restatement**, and it is a three-link
        cascade rather than a simple insert. The prior statement moves `CURRENT` →
        `SUPERSEDED`."

        Design: Corner/errors/registration_backed_by_a_superseded_statement_rejected
        """
        seed_state_profile("CA", assurance_basis="GROSS_REVENUE")
        organization = create_organization()
        first = create_financial_statement(organization)
        second = create_financial_statement(
            organization,
            total_revenue_cents=27_500_000,
            contributions_cents=21_000_000,
            program_expense_cents=19_000_000,
            assurance_level="AUDIT",
        )

        response = api_client.create_state_registration(
            state_registration_payload(organization["id"], first["id"], "CA"),
            COMPLIANCE,
        )

        validate_error(response, ApiErrorId.ERR_FINANCIAL_STATEMENT_SUPERSEDED.value)
        by_id = {row["id"]: row for row in list_financial_statements(organization["id"])}
        assert by_id[first["id"]]["statement_status"] == "SUPERSEDED", (
            "The restated statement is superseded, got "
            f"{by_id[first['id']]['statement_status']}"
        )
        assert by_id[second["id"]]["statement_status"] == "CURRENT", (
            "The restatement is current, got "
            f"{by_id[second['id']]['statement_status']}"
        )
        assert read_organization(organization["id"])["registered_state_count"] == 0, (
            "No filing was opened on the stale statement"
        )


class TestAttachingTheReportIsNotTheAssurance:
    """A complete document set does not cure an unaudited statement."""

    def test_a_review_requirement_against_an_unassured_statement_is_refused(self):
        """PRD §3.4: "and the statement's `assurance_level` must be at or above
        `required_financial_attestation` on the ordered scale where `NONE` is weakest,
        `REVIEW` sits above it and `AUDIT` is strongest, or it is
        `ERR_ASSURANCE_LEVEL_INSUFFICIENT`."

        Design: Corner/errors/assurance_level_below_the_required_attestation_rejected
        """
        ctx = setup_draft_filing(statement_overrides={"assurance_level": "NONE"})

        response = submit_filing(ctx["registration"]["id"], ctx["certifier"]["id"])

        validate_error(response, ApiErrorId.ERR_ASSURANCE_LEVEL_INSUFFICIENT.value)
        assert ctx["registration"]["required_financial_attestation"] == "REVIEW", (
            "26,000,000 of gross revenue puts the requirement at review, got "
            f"{ctx['registration']['required_financial_attestation']}"
        )
        assert ctx["financial_statement"]["assurance_level"] == "NONE", (
            "But the statement was prepared with no assurance, got "
            f"{ctx['financial_statement']['assurance_level']}"
        )
        assert len(ctx["documents"]) == 3, (
            f"All three required documents are attached, got {len(ctx['documents'])}"
        )
        filing = read_registration(ctx["registration"]["id"])
        assert filing["status"] == "DRAFT", (
            f"The packet is still a draft, got {filing['status']}"
        )
        assert filing["submitted_at"] is None, (
            f"Nothing was stamped, got {filing['submitted_at']}"
        )


class TestDuplicateFilingCountsUnsubmittedRows:
    """The duplicate key answers before the overlap rule can."""

    def test_a_second_filing_for_the_same_state_and_year_is_refused(self):
        """PRD §2.11 rung 27: "No non-terminal registration already exists for the same
        organization, state and fiscal year → `ERR_DUPLICATE_STATE_REGISTRATION` (409).
        Applies to registration creation."

        Design: Corner/errors/second_filing_for_the_same_state_and_year_rejected
        """
        seed_state_profile("CA", assurance_basis="GROSS_REVENUE")
        organization = create_organization()
        statement = create_financial_statement(organization)
        incumbent = open_filing(organization["id"], statement["id"], "CA")

        response = api_client.create_state_registration(
            state_registration_payload(organization["id"], statement["id"], "CA"),
            COMPLIANCE,
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_STATE_REGISTRATION.value)
        assert incumbent["status"] == "DRAFT", (
            "The incumbent was never submitted, so only the duplicate-key rule can "
            f"fire, got {incumbent['status']}"
        )
        assert read_registration(incumbent["id"])["status"] == "DRAFT", (
            "And it is still a draft after the refusal"
        )
        _rows, meta = validate_paginated(
            api_client.list_state_registrations(
                COMPLIANCE, params={"organization_id": organization["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            f"Exactly one filing exists for the state and year, got {meta['total_count']}"
        )
        assert read_organization(organization["id"])["registered_state_count"] == 0, (
            "Neither filing has registered"
        )
