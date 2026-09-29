"""Endpoints whose behaviour is not any single record's: the calendar, the clock.

A computed calendar has to sort, the logical clock has to govern every later
stamp, and two write endpoints have to name the right refusal.
"""

from test_helpers import (
    COMPLIANCE,
    NON_EXISTENT_UUID,
    ApiErrorId,
    activate_promotion,
    api_client,
    create_financial_statement,
    create_fundraiser,
    create_organization,
    draft_promotion,
    file_promotion,
    issue_enforcement_action,
    move_clock_to,
    open_filing,
    read_promotion,
    read_organization,
    register_fundraiser_in_state,
    seed_california_profile,
    seed_state_profile,
    state_registration_payload,
    validate_error,
    validate_success,
)


class TestComplianceCalendar:
    """The calendar is sorted by deadline, not by the order filings were opened."""

    def test_the_earlier_deadline_leads_even_though_its_filing_was_opened_second(self):
        """PRD §3.3: "For a whole-organization view there is a computed calendar
        capability, optionally narrowed to one `fiscal_year`, which returns
        `organization_id`, an `entry_count`, an `entries` collection carrying one entry
        per registration with that entry's `state_code`, `fiscal_year`,
        `renewal_due_date`, `effective_due_date`, `status` and
        `required_financial_attestation`, plus a `next_effective_due_date` naming the
        soonest deadline still ahead and a `delinquent_state_codes` list naming the
        states where the charity is currently delinquent. Entries are ordered by
        `effective_due_date` ascending, with `state_code` ascending breaking ties."

        Design: Corner/endpoints/compliance_calendar_orders_entries_by_effective_due_date
        """
        seed_state_profile("CA", assurance_basis="GROSS_REVENUE")
        seed_state_profile(
            "FL",
            renewal_due_rule="FYE_PLUS_6M",
            assurance_basis="GROSS_REVENUE",
            review_threshold_cents=50_000_000,
            audit_threshold_cents=100_000_000,
        )
        organization = create_organization()
        statement = create_financial_statement(organization)
        open_filing(organization["id"], statement["id"], "FL")
        open_filing(organization["id"], statement["id"], "CA")

        calendar = validate_success(
            api_client.get_compliance_calendar(
                organization["id"], COMPLIANCE, params={"fiscal_year": 2026}
            )
        )

        assert calendar["organization_id"] == organization["id"], (
            f"The calendar names its charity, got {calendar['organization_id']}"
        )
        assert calendar["entry_count"] == 2, (
            f"One entry per registration, got {calendar['entry_count']}"
        )
        assert calendar["entries"][0]["state_code"] == "CA", (
            "The soonest deadline leads regardless of creation order, got "
            f"{calendar['entries'][0]['state_code']}"
        )
        assert calendar["entries"][0]["effective_due_date"] == "2026-11-14T00:00:00.000Z", (
            "A June fiscal year end plus four months and fifteen days, got "
            f"{calendar['entries'][0]['effective_due_date']}"
        )
        assert calendar["entries"][0]["status"] == "DRAFT", (
            f"The entry carries the filing's status, got {calendar['entries'][0]['status']}"
        )
        assert calendar["entries"][1]["state_code"] == "FL", (
            f"Florida trails, got {calendar['entries'][1]['state_code']}"
        )
        assert calendar["entries"][1]["effective_due_date"] == "2026-12-30T00:00:00.000Z", (
            "Six calendar months from the same fiscal year end, got "
            f"{calendar['entries'][1]['effective_due_date']}"
        )
        assert calendar["next_effective_due_date"] == "2026-11-14T00:00:00.000Z", (
            "The soonest deadline still ahead, got "
            f"{calendar['next_effective_due_date']}"
        )
        assert calendar["delinquent_state_codes"] == [], (
            f"Nothing is delinquent yet, got {calendar['delinquent_state_codes']}"
        )


class TestLogicalClockGovernsLaterStamps:
    """Moving the clock moves every timestamp the server later writes."""

    def test_an_action_issued_after_the_clock_moves_stamps_and_derives_from_it(self):
        """PRD §2.4: "It maintains a single logical clock that reads exactly
        `2026-08-01T00:00:00Z` until a platform administrator moves it, by supplying a
        `to_iso8601` instant to the clock-setting capability; the response echoes the
        new instant as `current_utc`." PRD §3.9: "`issued_at` is stamped with the
        current logical clock, and `cure_deadline` is `issued_at` plus that state's
        `cure_period_days` in whole days."

        Design: Corner/endpoints/clock_endpoint_governs_every_later_deadline_stamp
        """
        seed_state_profile(
            "CA",
            assurance_basis="GROSS_REVENUE",
            cure_period_days=30,
            reinstatement_fee_cents=12_500,
        )
        organization = create_organization()
        statement = create_financial_statement(organization)
        filing = open_filing(organization["id"], statement["id"], "CA")

        clock = move_clock_to("2026-09-15T00:00:00Z")
        action = issue_enforcement_action(
            organization["id"],
            filing["id"],
            "PENALTY_ASSESSMENT",
            penalty_cents_override=5_000,
        )

        assert clock["current_utc"] == "2026-09-15T00:00:00.000Z", (
            f"The clock echoes its new instant, got {clock['current_utc']}"
        )
        assert action["issued_at"] == "2026-09-15T00:00:00.000Z", (
            f"The issuing stamp is the logical clock, got {action['issued_at']}"
        )
        assert action["cure_deadline"] == "2026-10-15T00:00:00.000Z", (
            f"Thirty whole days after issuance, got {action['cure_deadline']}"
        )
        assert action["state_code"] == "CA", (
            f"The state is copied from the linked filing, got {action['state_code']}"
        )
        assert action["penalty_cents"] == 5_000, (
            f"The override is taken verbatim, got {action['penalty_cents']}"
        )
        assert action["settlement_total_cents"] == 0, (
            f"A new action settles nothing, got {action['settlement_total_cents']}"
        )


class TestPromotionWindowPolarity:
    """One clock instant satisfies filing and defeats activation."""

    def test_activating_the_campaign_that_was_just_legally_filed_is_refused(self):
        """PRD §3.7: filing "requires that the logical clock be strictly before
        `promo_start` — a promotion already underway cannot be filed, and the attempt
        reports `ERR_PROMOTION_WINDOW_NOT_OPEN`". PRD §3.7 on activation: "The logical
        clock must also lie inside the closed window, at or after `promo_start` and at
        or before `promo_end`, or the attempt reports
        `ERR_PROMOTION_WINDOW_NOT_OPEN`."

        Design: Corner/endpoints/promotion_activation_before_the_window_opens_rejected
        """
        seed_california_profile(coventure_filing_required=True, coventure_buffer_days=7)
        organization = create_organization()
        coventurer = create_fundraiser(
            legal_name="BrightMart Retail Co",
            fundraiser_type="COMMERCIAL_COVENTURER",
            bond_amount_cents=2_500_000,
            bond_expires_at="2028-12-31T00:00:00Z",
        )
        register_fundraiser_in_state(
            coventurer["id"],
            "CA",
            bond_on_file_cents=2_500_000,
            expires_at="2027-12-31T00:00:00Z",
        )
        promotion = draft_promotion(
            organization["id"],
            coventurer["id"],
            ["CA"],
            promo_start="2026-09-01T00:00:00Z",
            promo_end="2026-09-30T00:00:00Z",
        )
        validate_success(file_promotion(promotion["id"]))

        response = activate_promotion(promotion["id"])

        validate_error(response, ApiErrorId.ERR_PROMOTION_WINDOW_NOT_OPEN.value)
        reread = read_promotion(promotion["id"])
        assert reread["status"] == "FILED", (
            f"The refused activation leaves the campaign filed, got {reread['status']}"
        )
        assert reread["projected_benefit_cents"] == 750_000, (
            "250 per unit across 3,000 projected units, got "
            f"{reread['projected_benefit_cents']}"
        )
        assert reread["disclosure_clause_required"] is True, (
            "California requires a co-venture filing for this campaign"
        )


class TestBodyForeignKeyOrderOnFilingCreate:
    """With the organization and the state both good, the statement is what fails."""

    def test_an_unresolvable_financial_statement_is_reported_as_its_own_not_found(self):
        """PRD §2.9: "Foreign keys arriving in a request body are resolved in a fixed
        order so that the reported error is deterministic when more than one is wrong:
        `organization_id` first, then `state_code` or every element of `state_codes`,
        then `financial_statement_id`, then `registration_id`, then
        `prepared_by_officer_id`, then `fundraiser_id`, then `coventurer_id`, and
        finally `supersedes_registration_id`."

        Design: Corner/endpoints/registration_create_with_unknown_financial_statement_returns_not_found
        """
        seed_state_profile("CA", assurance_basis="GROSS_REVENUE")
        organization = create_organization()

        response = api_client.create_state_registration(
            state_registration_payload(organization["id"], NON_EXISTENT_UUID, "CA"),
            COMPLIANCE,
        )

        validate_error(response, ApiErrorId.ERR_FINANCIAL_STATEMENT_NOT_FOUND.value)
        assert read_organization(organization["id"])["registered_state_count"] == 0, (
            "No filing was opened, so nothing is counted"
        )
