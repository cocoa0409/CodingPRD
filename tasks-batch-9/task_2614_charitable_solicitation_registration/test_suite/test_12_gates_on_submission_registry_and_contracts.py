"""The gates: what a packet must carry, what a state must want, what a bond must cover.

Each of these rules refuses something a careless client would expect to work,
and each refusal has to name its own code and leave the record untouched.
"""

from test_helpers import (
    COMPLIANCE,
    ApiErrorId,
    api_client,
    attach_document,
    create_disclosure_statement,
    create_financial_statement,
    create_fundraiser,
    create_officer,
    create_organization,
    draft_contract,
    file_contract,
    fundraiser_registration_payload,
    make_fundraiser_agent_headers,
    move_clock_to,
    open_filing,
    organization_payload,
    read_contract,
    read_fundraiser,
    read_organization,
    read_registration,
    register_fundraiser_in_state,
    seed_california_profile,
    seed_state_profile,
    setup_draft_filing,
    state_registration_payload,
    submit_filing,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestOfficerRosterGate:
    """One officer's unexplained conviction blocks the whole organization."""

    def test_an_unexplained_conviction_blocks_the_submission_before_the_document_check(
        self,
    ):
        """PRD §3.1: "From these the server derives `disclosure_status`: the row is
        `INCOMPLETE` when `criminal_conviction_disclosed` is true while
        `conviction_explanation` is null or an empty string, and `COMPLETE` in every
        other case — including the ordinary case of no conviction at all, where the
        missing narrative is not a defect." PRD §2.11 rung 17: "Every officer
        disclosure of the organization has `disclosure_status` equal to `COMPLETE` →
        `ERR_OFFICER_DISCLOSURE_INCOMPLETE` (422). Applies to filing submission."

        Design: Corner/validations/submit_with_an_incomplete_officer_disclosure_rejected
        """
        seed_state_profile("CA", assurance_basis="GROSS_REVENUE")
        organization = create_organization()
        statement = create_financial_statement(organization)
        certifier = create_officer(
            organization["id"], "Dana Reyes", "PRESIDENT", is_certifying_officer=True
        )
        undisclosed = create_officer(
            organization["id"],
            "Rae Mensah",
            "TREASURER",
            criminal_conviction_disclosed=True,
        )
        filing = open_filing(organization["id"], statement["id"], "CA")

        response = submit_filing(
            filing["id"],
            certifier["id"],
            certification_note="Certified under penalty of perjury.",
        )

        validate_error(response, ApiErrorId.ERR_OFFICER_DISCLOSURE_INCOMPLETE.value)
        assert undisclosed["disclosure_status"] == "INCOMPLETE", (
            "A conviction with no narrative is incomplete, got "
            f"{undisclosed['disclosure_status']}"
        )
        assert certifier["disclosure_status"] == "COMPLETE", (
            "No conviction at all is not a defect, got "
            f"{certifier['disclosure_status']}"
        )
        assert read_registration(filing["id"])["status"] == "DRAFT", (
            "The refused submission left the packet in draft"
        )


class TestRequiredDocumentSetGate:
    """A review-level filing needs the review report, not merely two documents."""

    def test_a_packet_short_the_review_report_is_refused(self):
        """PRD §3.4: "Every filing needs a document of `doc_type`
        `GOVERNING_DOCUMENT` and one of `doc_type` `FINANCIAL_STATEMENT`. A filing
        whose `required_financial_attestation` is `REVIEW` additionally needs a
        `REVIEW_REPORT`, and a filing whose requirement is `AUDIT` additionally needs
        an `AUDIT_OPINION`."

        Design: Corner/validations/submit_without_the_required_review_report_rejected
        """
        ctx = setup_draft_filing(attach_documents=False)
        registration_id = ctx["registration"]["id"]
        attach_document(registration_id, ctx["preparer"]["id"], "GOVERNING_DOCUMENT")
        attach_document(registration_id, ctx["preparer"]["id"], "FINANCIAL_STATEMENT")

        response = submit_filing(registration_id, ctx["certifier"]["id"])

        validate_error(response, ApiErrorId.ERR_REQUIRED_DOCUMENT_MISSING.value)
        filing = read_registration(registration_id)
        assert filing["required_financial_attestation"] == "REVIEW", (
            "The requirement is what makes the third document mandatory, got "
            f"{filing['required_financial_attestation']}"
        )
        assert filing["status"] == "DRAFT", (
            f"The packet is still a draft, got {filing['status']}"
        )
        assert filing["submitted_at"] is None, (
            f"Nothing was stamped, got {filing['submitted_at']}"
        )


class TestStateMustWantTheRegistration:
    """A state that requires no registration accepts no filing."""

    def test_a_filing_for_a_state_that_requires_none_is_refused(self):
        """PRD §3.3: "A filing may not be opened at all for a state whose profile has
        `registration_required` set to false, which reports
        `ERR_STATE_REGISTRATION_NOT_REQUIRED`."

        Design: Corner/validations/registration_in_a_state_that_does_not_require_it_rejected
        """
        seed_state_profile(
            "TX",
            registration_required=False,
            renewal_due_rule="CALENDAR_MAY_15",
            assurance_basis="CONTRIBUTIONS_ONLY",
            review_threshold_cents=100_000_000,
            audit_threshold_cents=500_000_000,
        )
        organization = create_organization(domicile_state_code="TX")
        statement = create_financial_statement(organization)

        response = api_client.create_state_registration(
            state_registration_payload(organization["id"], statement["id"], "TX"),
            COMPLIANCE,
        )

        validate_error(
            response, ApiErrorId.ERR_STATE_REGISTRATION_NOT_REQUIRED.value
        )
        assert read_organization(organization["id"])["registered_state_count"] == 0, (
            "No registration was opened, so nothing is counted"
        )


class TestUniquenessIsScopedPerState:
    """The same fiscal year in a second state is not a duplicate."""

    def test_an_identical_coverage_year_in_a_second_state_is_accepted(self):
        """PRD §3.3: "First, at most one non-terminal filing may exist per
        organization, state and fiscal year: if another filing for the same triple
        exists in any status other than `EXPIRED` or `WITHDRAWN`, the create is
        rejected with `ERR_DUPLICATE_STATE_REGISTRATION`." The overlap rule is scoped
        the same way: the interval "is compared against the coverage intervals of every
        other filing for the same organization and state".

        Design: Corner/validations/duplicate_registration_rule_permits_the_same_year_in_a_second_state
        """
        seed_state_profile("CA", assurance_basis="GROSS_REVENUE")
        seed_state_profile("NV", assurance_basis="GROSS_REVENUE")
        organization = create_organization()
        statement = create_financial_statement(organization)
        california = open_filing(organization["id"], statement["id"], "CA")

        response = api_client.create_state_registration(
            state_registration_payload(organization["id"], statement["id"], "NV"),
            COMPLIANCE,
        )
        nevada = validate_success(response, 201)

        assert nevada["status"] == "DRAFT", (
            f"The second state accepts the filing, got {nevada['status']}"
        )
        assert nevada["state_code"] == "NV", (
            f"It belongs to Nevada, got {nevada['state_code']}"
        )
        assert nevada["fiscal_year"] == california["fiscal_year"], (
            "Both filings report the same fiscal year, got "
            f"{nevada['fiscal_year']} and {california['fiscal_year']}"
        )
        assert read_registration(california["id"])["status"] == "DRAFT", (
            "The Californian filing is undisturbed"
        )


class TestEinUniqueness:
    """The employer identification number is unique on its own."""

    def test_a_differently_named_charity_may_not_reuse_an_ein(self):
        """PRD §2.11 rung 28: "`ein` is unused by another organization, and
        `state_code` unused by another profile → `ERR_DUPLICATE_IDENTIFIER` (409).
        Applies to organization creation and state-profile creation."

        Design: Corner/validations/duplicate_ein_on_a_second_organization_rejected
        """
        seed_state_profile("CA", assurance_basis="GROSS_REVENUE")
        seed_state_profile("NV", assurance_basis="GROSS_REVENUE")
        incumbent = create_organization()

        response = api_client.create_organization(
            organization_payload(
                legal_name="Cedar Ridge Alliance",
                ein="123456789",
                domicile_state_code="NV",
                fiscal_year_end_month=12,
            ),
            COMPLIANCE,
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value)
        surviving = read_organization(incumbent["id"])
        assert surviving["legal_name"] == "Harbor Light Foundation", (
            f"The incumbent keeps its name, got {surviving['legal_name']}"
        )
        assert surviving["ein"] == "123456789", (
            f"And keeps its identifier, got {surviving['ein']}"
        )
        _rows, meta = validate_paginated(api_client.list_organizations(COMPLIANCE))
        assert meta["total_count"] == 1, (
            f"The refused create added nothing, got {meta['total_count']}"
        )


class TestBondFloorIsInclusive:
    """One cent short of the state minimum is no bond at all."""

    def test_a_bond_one_cent_below_the_minimum_is_refused(self):
        """PRD §3.6: "The bond must be adequate: `bond_on_file_cents` must be at least
        the state's `fundraiser_bond_minimum_cents` (which defaults to 0), **and** the
        firm's own `bond_expires_at` must be strictly after the `expires_at` of the
        registration being created — a bond that lapses mid-registration is no bond at
        all. Either failure reports `ERR_BOND_INSUFFICIENT`."

        Design: Corner/validations/fundraiser_registration_below_the_state_bond_minimum_rejected
        """
        seed_california_profile()
        fundraiser = create_fundraiser(
            legal_name="Northline Donor Services",
            bond_amount_cents=2_500_000,
            bond_expires_at="2028-12-31T00:00:00Z",
        )

        response = api_client.create_fundraiser_registration(
            fundraiser_registration_payload(
                fundraiser["id"], "CA", 2_499_999, "2027-12-31T00:00:00Z"
            ),
            make_fundraiser_agent_headers(fundraiser["id"]),
        )

        validate_error(response, ApiErrorId.ERR_BOND_INSUFFICIENT.value)
        assert read_fundraiser(fundraiser["id"])["registry_status"] == "UNREGISTERED", (
            "No registration exists, so the firm never registered"
        )
        _rows, meta = validate_paginated(
            api_client.list_fundraiser_registrations(
                fundraiser["id"], make_fundraiser_agent_headers(fundraiser["id"])
            )
        )
        assert meta["total_count"] == 0, (
            f"No registration row was created, got {meta['total_count']}"
        )


class TestContractFilingWindow:
    """The due date only downgrades the outcome; the hard stop bars it."""

    def _drafted_engagement(self, **profile_overrides):
        seed_california_profile(**profile_overrides)
        organization = create_organization()
        fundraiser = create_fundraiser(
            legal_name="Northline Donor Services",
            bond_amount_cents=2_500_000,
            bond_expires_at="2028-12-31T00:00:00Z",
        )
        register_fundraiser_in_state(
            fundraiser["id"], "CA", expires_at="2027-12-31T00:00:00Z"
        )
        return organization, fundraiser

    def test_filing_a_day_past_the_hard_stop_is_refused_and_leaves_a_draft_forever(self):
        """PRD §3.6: "Beyond `filing_due_date` there is a further sixty days of grace —
        the hard stop — after which no filing is accepted at all." PRD §3.6: "And the
        logical clock must be at or before `filing_due_date` plus the sixty-day hard
        stop, or it reports `ERR_CONTRACT_FILING_WINDOW_CLOSED`."

        Design: Corner/validations/contract_filed_past_the_hard_stop_rejected
        """
        organization, fundraiser = self._drafted_engagement()
        contract = draft_contract(
            organization["id"],
            fundraiser["id"],
            ["CA"],
            contract_end="2027-08-01T00:00:00Z",
            compensation_type="PERCENT_OF_GROSS",
            percent_of_gross=0.15,
            flat_fee_cents=0,
        )
        move_clock_to("2026-10-11T00:00:00Z")

        response = file_contract(contract["id"], fundraiser["id"])

        validate_error(response, ApiErrorId.ERR_CONTRACT_FILING_WINDOW_CLOSED.value)
        reread = read_contract(contract["id"])
        assert reread["status"] == "DRAFT", (
            f"The engagement can never be filed now, got {reread['status']}"
        )
        assert reread["filing_due_date"] == "2026-08-11T00:00:00.000Z", (
            f"An August 1 start plus ten days, got {reread['filing_due_date']}"
        )
        assert reread["filed_at"] is None, (
            f"Nothing was stamped, got {reread['filed_at']}"
        )
        assert reread["late_filing_surcharge_cents"] == 0, (
            f"No surcharge was levied, got {reread['late_filing_surcharge_cents']}"
        )

    def test_filing_inside_the_grace_band_lands_in_late_filed_and_moves_the_copy(self):
        """PRD §3.6: "A clock strictly after `filing_due_date` but still within the
        sixty-day grace drives `DRAFT` → `LATE_FILED`, stamps `filed_at` identically,
        and sets `late_filing_surcharge_cents` to $100.00 — 10,000 cents — the flat
        late-contract surcharge." PRD §3.6: "Both outcomes then recompute
        `compliance_status` on every disclosure statement of the client charity whose
        `state_code` appears in the contract's `state_codes`".

        Design: Corner/validations/contract_filed_inside_the_grace_band_becomes_late_filed
        """
        organization, fundraiser = self._drafted_engagement(
            disclosure_required_clauses=["REGISTRATION_DISCLOSURE"]
        )
        contract = draft_contract(
            organization["id"],
            fundraiser["id"],
            ["CA"],
            contract_end="2027-08-01T00:00:00Z",
            compensation_type="FLAT_FEE",
            flat_fee_cents=900_000,
        )
        script = create_disclosure_statement(
            organization["id"],
            "CA",
            material_type="PHONE_SCRIPT",
            included_clauses=["REGISTRATION_DISCLOSURE"],
        )
        assert script["compliance_status"] == "COMPLIANT", (
            "Before the engagement is filed the script says everything the state "
            f"demands, got {script['compliance_status']}"
        )
        move_clock_to("2026-08-20T00:00:00Z")

        filed = validate_success(file_contract(contract["id"], fundraiser["id"]))

        assert filed["status"] == "LATE_FILED", (
            f"Nine days past the due date is late, not refused, got {filed['status']}"
        )
        assert filed["late_filing_surcharge_cents"] == 10_000, (
            f"The flat late surcharge is 10,000 cents, got "
            f"{filed['late_filing_surcharge_cents']}"
        )
        assert filed["filed_at"] == "2026-08-20T00:00:00.000Z", (
            f"The filing instant is the logical clock, got {filed['filed_at']}"
        )
        statements, _meta = validate_paginated(
            api_client.list_organization_disclosure_statements(
                organization["id"], COMPLIANCE, params={"state_code": "CA"}
            )
        )
        assert statements[0]["compliance_status"] == "NON_COMPLIANT", (
            "A late-filed solicitor engagement adds a clause the script lacks, got "
            f"{statements[0]['compliance_status']}"
        )
