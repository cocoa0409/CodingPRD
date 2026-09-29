"""Money arithmetic in the open: the two caps that bound a member's capacity, the
additive collateral penalties and the floor beneath them, the securities valuation
branch, and the two prepayment methods that read the market differently."""
from test_helpers import *  # noqa: F401,F403


def _pledging_applicant(api, **overrides):
    """A registered member with an executed blanket lien, ready to pledge."""
    env = applicant_member(api, **overrides)
    execute_pledge_agreement(api, env.member_id)
    return env


def _eligible_asset(api, env, **overrides):
    """Pledge one asset and put it through eligibility review."""
    asset = pledge_asset(api, env.member_id, **overrides)
    review_asset(api, asset["id"])
    return read_asset(api, asset["id"])


class TestCapacityCaps:
    """The capacity base is a minimum of a tier term and a statutory term."""

    def test_a_tier_three_member_keeps_only_three_quarters_of_its_collateral(self, api):
        """PRD §3.5: "First, a tier cap in basis points is read from the member's
        `credit_rating_tier`: tier 1 gives 10,000 basis points, tier 2 gives 9,000, tier 3
        gives 7,500 and tier 4 gives 5,000."

        Design: Corner/calculations/tier_three_cap_applied_to_lendable_collateral
        """
        env = _pledging_applicant(
            api,
            name="Cascade Mutual",
            charter_type="COMMERCIAL_BANK",
            total_assets_cents=5_000_000_000,
            credit_rating_tier=3,
        )
        asset = _eligible_asset(api, env)

        breakdown = env.capacity("CERTIFIED")

        assert_capacity_breakdown(
            breakdown,
            variant="CERTIFIED",
            lendable_collateral_value_cents=15_600_000,
            tier_cap_bps=7_500,
            statutory_cap_cents=1_500_000_000,
            capacity_base_cents=11_700_000,
            outstanding_advances_cents=0,
            commitments_cents=0,
            borrowing_capacity_cents=11_700_000,
        )
        assert_asset_valuation(asset, 7_800, 15_600_000)

    def test_the_thirty_percent_statutory_cap_binds_a_small_balance_sheet(self, api):
        """PRD §3.5: "Second, a statutory cap is computed as `total_assets_cents`
        multiplied by 3,000, divided by 10,000, rounded half up to whole cents — thirty
        percent of the member's balance sheet."

        Design: Corner/calculations/statutory_thirty_percent_cap_binds_below_tier_cap
        """
        env = _pledging_applicant(
            api,
            name="Tiny Mutual",
            charter_type="CREDIT_UNION",
            total_assets_cents=100_000_000,
            credit_rating_tier=1,
        )
        _eligible_asset(
            api,
            env,
            unpaid_principal_balance_cents=50_000_000,
            market_value_cents=52_000_000,
            ltv_bps=7_000,
        )

        breakdown = env.capacity("CERTIFIED")

        assert_capacity_breakdown(
            breakdown,
            lendable_collateral_value_cents=39_000_000,
            tier_cap_bps=10_000,
            statutory_cap_cents=30_000_000,
            capacity_base_cents=30_000_000,
            borrowing_capacity_cents=30_000_000,
        )

    def test_at_tier_four_the_minimum_switches_back_to_the_tier_term(self, api):
        """PRD §3.5: "Third, the capacity base is the lesser of two rounded terms: the
        member's lendable collateral value multiplied by the tier cap, divided by 10,000,
        rounded half up to whole cents; and the statutory cap."

        Design: Corner/calculations/statutory_thirty_percent_cap_binds_below_tier_cap
        """
        env = _pledging_applicant(
            api,
            name="Tiny Mutual Four",
            charter_type="CREDIT_UNION",
            total_assets_cents=100_000_000,
            credit_rating_tier=4,
        )
        _eligible_asset(
            api,
            env,
            unpaid_principal_balance_cents=50_000_000,
            market_value_cents=52_000_000,
            ltv_bps=7_000,
        )

        breakdown = env.capacity("CERTIFIED")

        assert_capacity_breakdown(
            breakdown,
            lendable_collateral_value_cents=39_000_000,
            tier_cap_bps=5_000,
            statutory_cap_cents=30_000_000,
            capacity_base_cents=19_500_000,
            borrowing_capacity_cents=19_500_000,
        )


class TestLoanToValueBoundary:
    """95.00 percent is admissible collateral, and it is penalised collateral."""

    def test_the_ceiling_is_inclusive_and_the_asset_is_still_priced_down(self, api):
        """PRD §3.4: "If `ltv_bps` is strictly greater than 8,000, subtract 500 basis
        points."

        Design: Corner/calculations/ltv_exactly_at_max_stays_eligible_with_high_ltv_penalty
        """
        env = _pledging_applicant(api)
        asset = pledge_asset(api, env.member_id, ltv_bps=9_500)

        reviewed = assert_envelope(api.review_asset_eligibility(asset["id"], CREDIT_ONE, {}))

        assert_fields(reviewed, status="ELIGIBLE", ineligibility_reason="NONE")
        assert_asset_valuation(reviewed, 7_300, 14_600_000)
        assert env.refresh()["lendable_collateral_value_cents"] == 14_600_000

    def test_one_point_above_the_ceiling_is_refused_and_the_threshold_is_strict(self, api):
        """PRD §3.4: "Then four condition checks in a pinned order: ... `ltv_bps` must be
        no greater than 9,500 basis points (95.00 percent), else `ERR_LTV_EXCEEDS_MAX`."

        Design: Corner/calculations/ltv_exactly_at_max_stays_eligible_with_high_ltv_penalty
        """
        env = _pledging_applicant(api)
        too_high = pledge_asset(api, env.member_id, ltv_bps=9_501)
        at_threshold = pledge_asset(api, env.member_id, ltv_bps=8_000)

        refused = api.review_asset_eligibility(too_high["id"], CREDIT_ONE, {})
        priced = validate_success(
            api.review_asset_eligibility(at_threshold["id"], CREDIT_ONE, {})
        )

        validate_error(refused, "ERR_LTV_EXCEEDS_MAX", 409)
        stored = read_asset(api, too_high["id"])
        assert_fields(stored, status="UNDER_REVIEW")
        assert_asset_valuation(stored, 0, 0)
        assert_asset_valuation(priced, 7_800, 15_600_000)


class TestDelinquencyBands:
    """One day short of sixty is priced; sixty is not collateral at all."""

    def test_fifty_nine_days_is_priced_while_sixty_days_is_refused(self, api):
        """PRD §3.4: "If `delinquency_days` is 30 or more, subtract 1,000 basis points."

        Design: Corner/calculations/delinquency_exactly_sixty_days_forces_ineligible_while_fifty_nine_only_penalises
        """
        env = _pledging_applicant(api)
        sixty = pledge_asset(api, env.member_id, delinquency_days=60)
        fifty_nine = pledge_asset(api, env.member_id, delinquency_days=59)

        priced = validate_success(
            api.review_asset_eligibility(fifty_nine["id"], CREDIT_ONE, {})
        )
        refused = api.review_asset_eligibility(sixty["id"], CREDIT_ONE, {})

        assert priced["status"] == "ELIGIBLE"
        assert_asset_valuation(priced, 6_800, 13_600_000)
        validate_error(refused, "ERR_DELINQUENT_ASSET_INELIGIBLE", 409)
        stopped = read_asset(api, sixty["id"])
        assert stopped["status"] == "UNDER_REVIEW"
        assert_asset_valuation(stopped, 0, 0)
        assert env.refresh()["lendable_collateral_value_cents"] == 13_600_000

    def test_the_penalty_threshold_is_inclusive_at_thirty_days(self, api):
        """PRD §3.4: "Then four condition checks in a pinned order: ...
        `delinquency_days` must be strictly fewer than 60, else
        `ERR_DELINQUENT_ASSET_INELIGIBLE`."

        Design: Corner/calculations/delinquency_exactly_sixty_days_forces_ineligible_while_fifty_nine_only_penalises
        """
        env = _pledging_applicant(api)
        clean = pledge_asset(api, env.member_id, delinquency_days=29)
        penalised = pledge_asset(api, env.member_id, delinquency_days=30)

        unpenalised = validate_success(
            api.review_asset_eligibility(clean["id"], CREDIT_ONE, {})
        )
        docked = validate_success(
            api.review_asset_eligibility(penalised["id"], CREDIT_ONE, {})
        )

        assert_asset_valuation(unpenalised, 7_800, 15_600_000)
        assert_asset_valuation(docked, 6_800, 13_600_000)


class TestStackedPenaltiesAndFloor:
    """Penalties are additive, and 2,000 basis points is the hard bottom."""

    def test_three_stacked_penalties_are_clamped_by_the_floor(self, api):
        """PRD §3.4: "Finally, take whichever is larger — the running result or a floor of
        2,000 basis points — and that is `discount_factor_bps`."

        Design: Corner/calculations/discount_factor_clamped_at_two_thousand_bps_floor
        """
        env = _pledging_applicant(api)
        asset = pledge_asset(
            api,
            env.member_id,
            asset_class="SMALL_BUSINESS",
            unpaid_principal_balance_cents=10_000_000,
            market_value_cents=12_000_000,
            ltv_bps=8_500,
            delinquency_days=45,
            documentation_status="EXCEPTION",
        )

        reviewed = assert_envelope(api.review_asset_eligibility(asset["id"], CREDIT_ONE, {}))

        assert_fields(
            reviewed, status="ELIGIBLE", collateral_basis_cents=10_000_000
        )
        assert_asset_valuation(reviewed, 2_000, 2_000_000)
        assert_fields(
            env.refresh(),
            lendable_collateral_value_cents=2_000_000,
            borrowing_capacity_cents=2_000_000,
        )


class TestStaleAppraisalPenalty:
    """Only commercial and multifamily paper ages; the penalty needs a full year."""

    def test_the_staleness_penalty_reaches_commercial_paper_only(self, api):
        """PRD §3.4: "If `asset_class` is `CRE` or `MULTIFAMILY` and the number of whole
        days from `appraisal_date` to the current logical-clock date is strictly greater
        than 365, subtract 300 basis points for a stale appraisal."

        Design: Corner/calculations/stale_appraisal_penalty_applies_to_cre_but_not_sf_mortgage
        """
        env = _pledging_applicant(api)
        mortgage = _eligible_asset(
            api, env, ltv_bps=7_000, appraisal_date="2024-01-15T00:00:00Z"
        )
        commercial = pledge_asset(
            api,
            env.member_id,
            asset_class="CRE",
            unpaid_principal_balance_cents=50_000_000,
            market_value_cents=52_000_000,
            ltv_bps=7_000,
            appraisal_date="2024-01-15T00:00:00Z",
        )

        reviewed = validate_success(
            api.review_asset_eligibility(commercial["id"], CREDIT_ONE, {})
        )

        assert reviewed["status"] == "ELIGIBLE"
        assert_asset_valuation(reviewed, 5_200, 26_000_000)
        assert_asset_valuation(read_asset(api, mortgage["id"]), 7_800, 15_600_000)
        assert env.refresh()["lendable_collateral_value_cents"] == 41_600_000

    def test_an_appraisal_exactly_a_year_old_is_not_yet_stale(self, api):
        """PRD §2.9: "Every date comparison in this system reads a server-held **logical
        clock** rather than wall-clock time: default timestamps, maturity computation,
        remaining-day counts, appraisal-age checks, verification-window gates,
        custody-window gates, quote validity and the shortfall cure deadline all resolve
        against it."

        Design: Corner/calculations/stale_appraisal_penalty_applies_to_cre_but_not_sf_mortgage
        """
        env = _pledging_applicant(api)
        commercial = pledge_asset(
            api,
            env.member_id,
            asset_class="CRE",
            unpaid_principal_balance_cents=50_000_000,
            market_value_cents=52_000_000,
            ltv_bps=7_000,
            appraisal_date="2025-08-01T00:00:00Z",
        )

        reviewed = validate_success(
            api.review_asset_eligibility(commercial["id"], CREDIT_ONE, {})
        )

        assert_asset_valuation(reviewed, 5_500, 27_500_000)
        assert env.refresh()["lendable_collateral_value_cents"] == 27_500_000


class TestSecuritiesValuationBranch:
    """Securities are valued off market value, and only when listed or delivered."""

    def test_a_treasury_position_is_valued_off_market_value_alone(self, api):
        """PRD §3.2: "For `AGENCY_MBS` and `TREASURY` it equals `market_value_cents`."

        Design: Corner/calculations/securities_basis_uses_market_value_not_unpaid_principal
        """
        env = applicant_member(api)
        execute_pledge_agreement(api, env.member_id, "SPECIFIC_LISTING")
        position = pledge_asset(
            api,
            env.member_id,
            asset_class="TREASURY",
            market_value_cents=10_000_000,
            unpaid_principal_balance_cents=None,
            ltv_bps=None,
            appraisal_date=CLOCK_START,
        )

        reviewed = assert_envelope(
            api.review_asset_eligibility(position["id"], CREDIT_ONE, {})
        )

        assert_fields(
            reviewed,
            status="ELIGIBLE",
            effective_listing_mode="SPECIFIC",
            unpaid_principal_balance_cents=0,
            collateral_basis_cents=10_000_000,
        )
        assert_asset_valuation(reviewed, 9_500, 9_500_000)

    def test_delivering_the_agency_position_lifts_its_factor(self, api):
        """PRD §3.4: "`AGENCY_MBS`: 9,000 under `SPECIFIC`, 9,400 under `DELIVERED`; no
        base factor exists under `BLANKET`."

        Design: Corner/calculations/securities_basis_uses_market_value_not_unpaid_principal
        """
        env = applicant_member(api)
        execute_pledge_agreement(api, env.member_id, "SPECIFIC_LISTING")
        position = pledge_asset(
            api,
            env.member_id,
            asset_class="AGENCY_MBS",
            market_value_cents=10_000_000,
            unpaid_principal_balance_cents=None,
            ltv_bps=None,
            appraisal_date=CLOCK_START,
        )
        listed = validate_success(
            api.review_asset_eligibility(position["id"], CREDIT_ONE, {})
        )

        deliver_asset(api, position["id"])

        assert_fields(listed, collateral_basis_cents=10_000_000, status="ELIGIBLE")
        assert_asset_valuation(listed, 9_000, 9_000_000)
        delivered = read_asset(api, position["id"])
        assert delivered["effective_listing_mode"] == "DELIVERED"
        assert_asset_valuation(delivered, 9_400, 9_400_000)


class TestPrepaymentFeeMethods:
    """Yield maintenance is one-sided; the flat method never reads the calendar."""

    def _funded_ten_million(self, api, **product_overrides):
        """A 10,000,000 advance for 30 days, funded on the opening clock instant."""
        env = member_with_eligible_sf(api)
        subscribe_and_issue(api, env.member_id, 450_000, "ACTIVITY")
        product = create_product(api, **product_overrides)
        advance = funded_advance(
            api,
            env,
            product["id"],
            term_days=30,
            requested_net_proceeds_cents=10_000_000,
            fund_stock_from_advance=False,
        )
        return env, advance

    def test_yield_maintenance_floors_a_negative_spread_at_zero(self, api):
        """PRD §3.7: "Under `YIELD_MAINTENANCE`, the base fee is computed with the spread
        floored at 0, so a market rate above the advance's coupon produces a raw fee of 0
        rather than a negative number."

        Design: Corner/calculations/yield_maintenance_quote_is_zero_when_market_rate_exceeds_advance_rate
        """
        env, advance = self._funded_ten_million(api)
        set_market_rate(api, 500)

        response = api.create_prepayment_quote(
            advance["id"],
            prepayment_quote_payload(10_000_000, "FULL"),
            env.treasury,
        )

        quote = assert_envelope(response, 201)
        assert_fields(
            quote,
            status="QUOTED",
            quoted_market_rate_bps=500,
            quoted_remaining_days=30,
            quoted_fee_cents=0,
            admin_fee_cents=0,
            symmetric_credit_cents=0,
        )
        assert advance["rate_bps"] == 425

    def test_the_same_quote_at_the_default_market_rate_prices_the_spread(self, api):
        """PRD §3.7: "The base fee is a single rounded quantity: multiply the principal by
        the spread, multiply by the remaining days, divide by the product of 10,000 and
        360, and round half up to whole cents — one rounding applied to the whole product,
        never a chain of roundings."

        Design: Corner/calculations/yield_maintenance_quote_is_zero_when_market_rate_exceeds_advance_rate
        """
        env, advance = self._funded_ten_million(api)

        quote = validate_success(
            api.create_prepayment_quote(
                advance["id"],
                prepayment_quote_payload(10_000_000, "FULL"),
                env.treasury,
            ),
            201,
        )

        assert_fields(
            quote,
            quoted_market_rate_bps=300,
            quoted_remaining_days=30,
            quoted_fee_cents=10_417,
        )

    def test_the_flat_fee_is_the_same_at_six_days_as_at_thirty(self, api):
        """PRD §3.7: "Under `FLAT_PCT`, the raw fee is the principal multiplied by the
        product's `flat_prepayment_fee_bps`, divided by 10,000, rounded half up — the
        spread and the remaining days are not consulted."

        Design: Corner/calculations/flat_pct_prepayment_fee_ignores_remaining_term
        """
        env, advance = self._funded_ten_million(
            api,
            product_code="FL-150",
            prepayment_fee_method="FLAT_PCT",
            flat_prepayment_fee_bps=150,
        )
        early = quote_prepayment(api, env, advance["id"], 3_000_000, "PARTIAL")
        pin_clock(api, "2026-08-25T00:00:00Z")

        late = validate_success(
            api.create_prepayment_quote(
                advance["id"],
                prepayment_quote_payload(3_000_000, "PARTIAL"),
                env.treasury,
            ),
            201,
        )

        assert_fields(
            early, prepay_kind="PARTIAL", quoted_remaining_days=30, quoted_fee_cents=45_000
        )
        assert_fields(
            late,
            status="QUOTED",
            prepay_kind="PARTIAL",
            quoted_remaining_days=6,
            quoted_fee_cents=45_000,
        )

    def test_settlement_adds_only_the_administrative_fee(self, api):
        """PRD §3.7: "`settled_fee_cents` is the raw fee plus `admin_fee_cents`."

        Design: Corner/calculations/flat_pct_prepayment_fee_ignores_remaining_term
        """
        env, advance = self._funded_ten_million(
            api,
            product_code="FL-150",
            prepayment_fee_method="FLAT_PCT",
            flat_prepayment_fee_bps=150,
        )
        pin_clock(api, "2026-08-25T00:00:00Z")
        quote = quote_prepayment(api, env, advance["id"], 3_000_000, "PARTIAL")

        settled = assert_envelope(api.settle_prepayment_event(quote["id"], CREDIT_ONE))

        assert_fields(
            settled,
            status="SETTLED",
            settled_remaining_days=6,
            admin_fee_cents=1_500,
            settled_fee_cents=46_500,
            fee_delta_cents=1_500,
        )
        after = read_advance(api, advance["id"])
        assert after["credit_status"] == "FUNDED"
        assert after["outstanding_principal_cents"] == 7_000_000
