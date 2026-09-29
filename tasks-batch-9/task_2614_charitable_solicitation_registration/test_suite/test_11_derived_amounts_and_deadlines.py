"""Derived money and derived dates, measured at their published boundaries.

The fee reads a contract's status rather than its existence, the tier boundary
is exclusive at one cent, an IRS-based extension discards what was asked for,
the clause set is resolved from three sources, and one December year end feeds
three different deadline rules.
"""

from test_helpers import (
    COMPLIANCE,
    api_client,
    create_financial_statement,
    create_organization,
    decide_extension,
    disclosure_statement_payload,
    draft_contract,
    file_contract,
    open_filing,
    read_contract,
    read_registration,
    request_extension,
    seed_california_profile,
    seed_state_profile,
    setup_draft_filing,
    setup_filed_contract,
    setup_filed_promotion,
    setup_registered_fundraiser,
    submit_filing,
    validate_success,
)


class TestPerContractFeeComponent:
    """A draft engagement costs nothing; filing it changes the next fee."""

    def test_the_per_contract_unit_is_added_only_once_the_contract_is_filed(self):
        """PRD §3.3: "The third component is the state's `per_contract_fee_cents`,
        which defaults to 0, multiplied by the number of that organization's
        fundraising contracts whose `status` is `FILED` or `LATE_FILED` and whose
        `state_codes` array contains this filing's state; contracts still in `DRAFT`
        and contracts already `VOIDED` are excluded, and the count is taken at the
        moment of evaluation with no time window."

        Design: Corner/calculations/filing_fee_counts_only_filed_contracts_in_the_state
        """
        ctx = setup_draft_filing()
        fundraiser, _registrations = setup_registered_fundraiser(
            ["CA"],
            legal_name="Northline Donor Services",
            bond_amount_cents=2_500_000,
            bond_expires_at="2028-12-31T00:00:00Z",
        )
        contract = draft_contract(
            ctx["organization"]["id"],
            fundraiser["id"],
            ["CA"],
            contract_end="2027-08-01T00:00:00Z",
            compensation_type="PERCENT_OF_GROSS",
            percent_of_gross=0.15,
            flat_fee_cents=0,
        )

        assert ctx["registration"]["filing_fee_cents"] == 24_000, (
            "With the engagement still in draft the fee is 16,000 times 1.5, got "
            f"{ctx['registration']['filing_fee_cents']}"
        )

        filed = validate_success(file_contract(contract["id"], fundraiser["id"]))
        submitted = validate_success(
            submit_filing(ctx["registration"]["id"], ctx["certifier"]["id"])
        )

        assert filed["status"] == "FILED", (
            f"The engagement was filed inside its window, got {filed['status']}"
        )
        assert filed["late_filing_surcharge_cents"] == 0, (
            f"Nothing was filed late, got {filed['late_filing_surcharge_cents']}"
        )
        assert submitted["filing_fee_cents"] == 26_250, (
            "15,000 tier base plus 1,000 surcharge plus one 1,500 contract unit, "
            f"times 1.5, got {submitted['filing_fee_cents']}"
        )
        assert submitted["status"] == "SUBMITTED", (
            f"The packet is with the regulator, got {submitted['status']}"
        )
        assert read_contract(contract["id"])["status"] == "FILED", (
            "The engagement stays filed after the packet is submitted"
        )


class TestFeeTierBoundary:
    """One cent of public support decides which tier applies."""

    def test_the_first_tier_boundary_is_exclusive_at_twenty_five_thousand_dollars(self):
        """PRD §3.3: "The first component is a tier selected on the supporting
        statement's `contributions_cents`: public support below $25,000 selects a base
        of $25.00; support from $25,000 up to but not including $100,000 selects
        $50.00; support from $100,000 up to but not including $500,000 selects $150.00;
        and support of $500,000 or more selects $400.00."

        Design: Corner/calculations/filing_fee_tier_boundary_at_contributions_2500000
        """
        seed_california_profile()
        below = create_organization()
        at = create_organization(
            legal_name="Cedar Ridge Alliance", ein="223456789"
        )
        below_statement = create_financial_statement(
            below,
            total_revenue_cents=2_499_999,
            contributions_cents=2_499_999,
            program_expense_cents=1_800_000,
            fundraising_expense_cents=400_000,
            management_expense_cents=200_000,
            assurance_level="NONE",
        )
        at_statement = create_financial_statement(
            at,
            total_revenue_cents=2_500_000,
            contributions_cents=2_500_000,
            program_expense_cents=1_800_000,
            fundraising_expense_cents=400_000,
            management_expense_cents=200_000,
            assurance_level="NONE",
        )

        below_filing = open_filing(
            below["id"], below_statement["id"], "CA", "RENEWAL"
        )
        at_filing = open_filing(at["id"], at_statement["id"], "CA", "RENEWAL")

        assert below_filing["filing_fee_cents"] == 3_500, (
            "2,499,999 stays in the 2,500 tier, plus the 1,000 surcharge, got "
            f"{below_filing['filing_fee_cents']}"
        )
        assert at_filing["filing_fee_cents"] == 6_000, (
            "Exactly 2,500,000 jumps to the 5,000 tier, plus the surcharge, got "
            f"{at_filing['filing_fee_cents']}"
        )
        assert below_filing["required_financial_attestation"] == "NONE", (
            "Neither charity is near the review threshold, got "
            f"{below_filing['required_financial_attestation']}"
        )
        assert at_filing["required_financial_attestation"] == "NONE", (
            f"The same holds at the boundary, got "
            f"{at_filing['required_financial_attestation']}"
        )


class TestExtensionGrantLength:
    """The federal basis discards the number of days asked for."""

    def test_an_irs_based_grant_takes_the_state_maximum_and_ignores_the_request(self):
        """PRD §3.5: "Under `IRS_990_EXTENSION` the server grants the smaller of 180
        days and the state's `extension_max_days`, and `requested_days` is ignored
        entirely — a charity riding its federal extension gets the statutory maximum
        the state permits, no more and no less." PRD §3.5 on the grant's effects: "the
        linked filing has its `extended_due_date` set to `renewal_due_date` plus
        `granted_days`, its `effective_due_date` recomputed, and its `version`
        incremented".

        Design: Corner/calculations/extension_grant_ignores_requested_days_under_irs_basis
        """
        seed_california_profile()
        organization = create_organization()
        statement = create_financial_statement(organization)
        filing = open_filing(organization["id"], statement["id"], "CA")
        extension = request_extension(
            filing["id"], filing["version"], "IRS_990_EXTENSION", 5
        )

        granted = validate_success(decide_extension(extension["id"], "GRANT"))

        assert granted["status"] == "GRANTED", (
            f"The regulator granted the request, got {granted['status']}"
        )
        assert granted["granted_days"] == 90, (
            "The smaller of 180 statutory days and California's 90-day maximum, got "
            f"{granted['granted_days']}"
        )
        assert granted["requested_days"] == 5, (
            f"What was asked for is recorded but ignored, got {granted['requested_days']}"
        )
        assert granted["decided_at"] == "2026-08-01T00:00:00.000Z", (
            f"The decision is stamped at the logical clock, got {granted['decided_at']}"
        )
        reread = read_registration(filing["id"])
        assert reread["renewal_due_date"] == "2026-11-14T00:00:00.000Z", (
            f"The unextended deadline is untouched, got {reread['renewal_due_date']}"
        )
        assert reread["extended_due_date"] == "2027-02-12T00:00:00.000Z", (
            f"November 14 plus ninety days, got {reread['extended_due_date']}"
        )
        assert reread["effective_due_date"] == "2027-02-12T00:00:00.000Z", (
            f"The extended date now governs, got {reread['effective_due_date']}"
        )


class TestDisclosureRequirementResolution:
    """Two live engagements add two clauses, interleaved into canonical order."""

    def test_a_solicitor_engagement_and_a_filed_promotion_add_both_clauses(self):
        """PRD §3.8: "To that base the server adds `PAID_SOLICITOR_IDENTITY` whenever
        the charity has a fundraising contract whose `status` is `FILED` or
        `LATE_FILED`, whose `state_codes` contains this statement's state, and whose
        firm's `fundraiser_type` is `PROFESSIONAL_SOLICITOR`". PRD §3.8: "that list
        also fixes the order in which every derived clause array is emitted:
        `REGISTRATION_DISCLOSURE`, then `FINANCIAL_STATEMENT_AVAILABILITY`, then
        `PAID_SOLICITOR_IDENTITY`, then `TAX_DEDUCTIBILITY`, then
        `PERCENT_TO_CHARITY`."

        Design: Corner/calculations/disclosure_resolution_adds_both_conditional_clauses_in_canonical_order
        """
        seed_california_profile(
            disclosure_required_clauses=[
                "REGISTRATION_DISCLOSURE",
                "FINANCIAL_STATEMENT_AVAILABILITY",
            ]
        )
        organization = create_organization()
        setup_filed_contract(
            organization["id"],
            ["CA"],
            fundraiser_overrides={
                "legal_name": "Northline Donor Services",
                "bond_amount_cents": 2_500_000,
                "bond_expires_at": "2028-12-31T00:00:00Z",
            },
            contract_overrides={
                "contract_end": "2027-08-01T00:00:00Z",
                "compensation_type": "PERCENT_OF_GROSS",
                "percent_of_gross": 0.15,
                "flat_fee_cents": 0,
            },
        )
        promotion_ctx = setup_filed_promotion(organization["id"], ["CA"])

        statement = validate_success(
            api_client.create_disclosure_statement(
                disclosure_statement_payload(
                    organization["id"],
                    "CA",
                    "WEB",
                    included_clauses=["FINANCIAL_STATEMENT_AVAILABILITY"],
                ),
                COMPLIANCE,
            ),
            201,
        )

        assert statement["required_clauses"] == [
            "REGISTRATION_DISCLOSURE",
            "FINANCIAL_STATEMENT_AVAILABILITY",
            "PAID_SOLICITOR_IDENTITY",
            "PERCENT_TO_CHARITY",
        ], (
            "The two conditional clauses are interleaved, not appended, got "
            f"{statement['required_clauses']}"
        )
        assert statement["missing_clauses"] == [
            "REGISTRATION_DISCLOSURE",
            "PAID_SOLICITOR_IDENTITY",
            "PERCENT_TO_CHARITY",
        ], f"Three of the four clauses are absent, got {statement['missing_clauses']}"
        assert statement["compliance_status"] == "NON_COMPLIANT", (
            f"The copy is short three clauses, got {statement['compliance_status']}"
        )
        assert promotion_ctx["promotion"]["projected_benefit_cents"] == 750_000, (
            "250 per unit across 3,000 projected units, got "
            f"{promotion_ctx['promotion']['projected_benefit_cents']}"
        )

    def test_a_state_demanding_nothing_makes_empty_copy_compliant(self):
        """PRD §3.8: "The empty case is worth spelling out: in a state with no base
        clauses and no live solicitor or promotion engagement, `required_clauses` is
        empty, `missing_clauses` is empty, and the material is `COMPLIANT` even though
        `included_clauses` is itself empty — there is nothing the law demanded and
        nothing was omitted."

        Design: Corner/calculations/disclosure_empty_required_set_is_compliant_with_no_clauses
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

        statement = validate_success(
            api_client.create_disclosure_statement(
                disclosure_statement_payload(
                    organization["id"], "TX", "PRINT", included_clauses=[]
                ),
                COMPLIANCE,
            ),
            201,
        )

        assert statement["required_clauses"] == [], (
            f"Texas demands no clause, got {statement['required_clauses']}"
        )
        assert statement["missing_clauses"] == [], (
            f"Nothing can be missing, got {statement['missing_clauses']}"
        )
        assert statement["compliance_status"] == "COMPLIANT", (
            f"Empty copy is compliant here, got {statement['compliance_status']}"
        )
        assert statement["material_type"] == "PRINT", (
            f"The material type is recorded, got {statement['material_type']}"
        )


class TestRenewalRuleArithmeticOrder:
    """One December year end, three rules, three different answers."""

    def test_the_day_is_clamped_before_the_fifteen_days_are_added(self):
        """PRD §3.3: "The pinned order is observable: for a December fiscal year end in
        2025, the four-month-plus-fifteen-day rule advances 2025-12-31 to 2026-04-30 —
        the day clamped from 31 down to 30 — and then adds fifteen days to reach
        2026-05-15. Adding the fifteen days first would have produced 2026-05-15 and
        then advanced four months to 2026-09-15, which is wrong." PRD §3.3 on the other
        two rules: "Under `FYE_PLUS_6M` the server advances six calendar months with
        the same day clamping and performs no day arithmetic at all. Under
        `CALENDAR_MAY_15` the deadline ignores the fiscal month entirely and falls on
        May 15 of the calendar year following the year of the fiscal year end date, at
        midnight UTC."

        Design: Corner/calculations/renewal_deadline_clamps_the_day_before_day_arithmetic
        """
        seed_state_profile("CA", assurance_basis="GROSS_REVENUE")
        seed_state_profile(
            "FL",
            renewal_due_rule="FYE_PLUS_6M",
            assurance_basis="GROSS_REVENUE",
            review_threshold_cents=50_000_000,
            audit_threshold_cents=100_000_000,
        )
        seed_state_profile(
            "WA",
            renewal_due_rule="CALENDAR_MAY_15",
            assurance_basis="CONTRIBUTIONS_ONLY",
            review_threshold_cents=300_000_000,
            audit_threshold_cents=500_000_000,
        )
        organization = create_organization(fiscal_year_end_month=12)
        statement = create_financial_statement(organization, fiscal_year=2025)

        coverage = {
            "fiscal_year": 2025,
            "coverage_start": "2025-01-01T00:00:00Z",
            "coverage_end": "2026-01-01T00:00:00Z",
        }
        california = open_filing(
            organization["id"], statement["id"], "CA", **coverage
        )
        florida = open_filing(organization["id"], statement["id"], "FL", **coverage)
        washington = open_filing(
            organization["id"], statement["id"], "WA", **coverage
        )

        assert california["renewal_due_date"] == "2026-05-15T00:00:00.000Z", (
            "December 31 clamped to April 30, then fifteen days, got "
            f"{california['renewal_due_date']}"
        )
        assert california["effective_due_date"] == "2026-05-15T00:00:00.000Z", (
            "With no extension the effective date is the same, got "
            f"{california['effective_due_date']}"
        )
        assert florida["renewal_due_date"] == "2026-06-30T00:00:00.000Z", (
            f"Six months clamped to June 30 with no day arithmetic, got "
            f"{florida['renewal_due_date']}"
        )
        assert washington["renewal_due_date"] == "2026-05-15T00:00:00.000Z", (
            "May 15 of the following calendar year, got "
            f"{washington['renewal_due_date']}"
        )
        assert california["required_financial_attestation"] == "REVIEW", (
            "26,000,000 clears California's 20,000,000 threshold, got "
            f"{california['required_financial_attestation']}"
        )
        assert washington["required_financial_attestation"] == "NONE", (
            "20,000,000 of contributions is far below Washington's threshold, got "
            f"{washington['required_financial_attestation']}"
        )
