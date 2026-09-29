"""Rules that refuse work: the securities gate, the forced-ineligible recording path,
the community-program coupling, the set-aside room test, the membership and minimum
principal gates on a new advance, and the five-day life of a prepayment quote."""
from test_helpers import *  # noqa: F401,F403


class TestCollateralEligibilityGates:
    """Two gates on the same review call, with opposite dispositions."""

    def test_a_security_under_a_blanket_lien_has_no_factor_to_apply(self, api):
        """PRD §3.4: "Then four condition checks in a pinned order: ... an asset whose
        `asset_class` is `AGENCY_MBS` or `TREASURY` must have an `effective_listing_mode`
        other than `BLANKET`, else `ERR_SECURITIES_REQUIRE_DELIVERY`, because no
        blanket-lien factor is defined for securities."

        Design: Corner/validations/securities_under_blanket_lien_rejected
        """
        env = applicant_member(api)
        execute_pledge_agreement(api, env.member_id, "BLANKET_LIEN")
        position = pledge_asset(
            api,
            env.member_id,
            asset_class="AGENCY_MBS",
            market_value_cents=10_000_000,
            unpaid_principal_balance_cents=None,
            ltv_bps=None,
            appraisal_date=CLOCK_START,
        )

        refused = api.review_asset_eligibility(position["id"], CREDIT_ONE, {})

        validate_error(refused, "ERR_SECURITIES_REQUIRE_DELIVERY", 409)
        blocked = read_asset(api, position["id"])
        assert_fields(
            blocked,
            status="UNDER_REVIEW",
            ineligibility_reason="NONE",
            effective_listing_mode="BLANKET",
        )
        assert_asset_valuation(blocked, 0, 0)

        execute_pledge_agreement(api, env.member_id, "SPECIFIC_LISTING")
        listed = validate_success(
            api.review_asset_eligibility(position["id"], CREDIT_ONE, {})
        )

        assert listed["status"] == "ELIGIBLE"
        assert_asset_valuation(listed, 9_000, 9_000_000)

    def test_the_forced_path_records_the_reason_instead_of_refusing(self, api):
        """PRD §3.4: "When at least one of them is failing, the review records the
        rejection instead of returning a 4xx: the asset moves `UNDER_REVIEW → INELIGIBLE`
        (or `SUSPENDED → INELIGIBLE`), `ineligibility_reason` is set to the **first**
        failing condition in the pinned order — `DOCUMENTATION_MISSING`, then
        `LTV_EXCEEDS_MAX`, then `DELINQUENT`, then `SECURITIES_NOT_DELIVERED` — and
        `discount_factor_bps` and `lendable_value_cents` are both set to 0."

        Design: Corner/validations/force_ineligible_records_reason_instead_of_returning_an_error
        """
        env = applicant_member(api)
        execute_pledge_agreement(api, env.member_id)
        forced = pledge_asset(api, env.member_id, ltv_bps=9_800)
        plain = pledge_asset(api, env.member_id, ltv_bps=9_800)

        recorded = assert_envelope(
            api.review_asset_eligibility(forced["id"], CREDIT_ONE, {"force_ineligible": True})
        )

        assert_fields(
            recorded, status="INELIGIBLE", ineligibility_reason="LTV_EXCEEDS_MAX"
        )
        assert_asset_valuation(recorded, 0, 0)
        assert_fields(
            env.refresh(),
            lendable_collateral_value_cents=0,
            borrowing_capacity_cents=0,
        )

        refused = api.review_asset_eligibility(plain["id"], CREDIT_ONE, {})

        validate_error(refused, "ERR_LTV_EXCEEDS_MAX", 409)
        assert_fields(
            read_asset(api, plain["id"]),
            status="UNDER_REVIEW",
            ineligibility_reason="NONE",
        )


class TestCommunityProgramCoupling:
    """The allocation flag is a biconditional, and the pool is charged in order."""

    def _community_request(self, api, requested_subsidy_cents):
        """A 2,000,000 rehabilitation request against a fresh 400,000 pool."""
        env = member_with_eligible_sf(api)
        product = create_product(
            api,
            product_code="CIP-C",
            rate_bps=300,
            prepayment_fee_method="NONE",
            community_program_flag=True,
        )
        allocation = create_allocation(api, program_code="CIP", subsidy_rate_bps=250)
        advance = request_advance(
            api,
            env,
            product["id"],
            term_days=365,
            requested_net_proceeds_cents=2_000_000,
            community_program_allocation_id=allocation["id"],
            community_bucket="REHABILITATION",
            requested_subsidy_cents=requested_subsidy_cents,
        )
        return env, allocation, advance

    def _read_allocation(self, api, allocation_id):
        return get_success_data(
            api.get_community_program_allocation(allocation_id, COMMUNITY)
        )

    def test_an_allocation_on_an_ordinary_product_is_refused_in_both_directions(self, api):
        """PRD §3.5: "A product whose `community_program_flag` is true requires a
        `community_program_allocation_id`, and a product whose flag is false forbids one;
        either mismatch is `ERR_PRODUCT_NOT_COMMUNITY_PROGRAM`."

        Design: Corner/validations/allocation_supplied_for_non_community_product_rejected
        """
        env = member_with_eligible_sf(api)
        plain = create_product(api)
        community = create_product(
            api,
            product_code="CIP-C",
            rate_bps=300,
            prepayment_fee_method="NONE",
            community_program_flag=True,
        )
        allocation = create_allocation(
            api, program_code="AHP_SETASIDE", subsidy_rate_bps=250
        )

        subsidised_plain_product = api.create_advance(
            advance_payload(
                env.member_id,
                plain["id"],
                env.version,
                term_days=180,
                requested_net_proceeds_cents=2_000_000,
                community_program_allocation_id=allocation["id"],
                community_bucket="FIRST_TIME_HOMEBUYER",
                requested_subsidy_cents=100_000,
            ),
            env.treasury,
        )
        bare_community_product = api.create_advance(
            advance_payload(
                env.member_id,
                community["id"],
                env.version,
                term_days=180,
                requested_net_proceeds_cents=2_000_000,
            ),
            env.treasury,
        )

        validate_error(
            subsidised_plain_product, "ERR_PRODUCT_NOT_COMMUNITY_PROGRAM", 409
        )
        validate_error(bare_community_product, "ERR_PRODUCT_NOT_COMMUNITY_PROGRAM", 409)
        accepted = request_advance(
            api,
            env,
            plain["id"],
            term_days=180,
            requested_net_proceeds_cents=2_000_000,
        )
        assert accepted["credit_status"] == "REQUESTED"
        assert_total_count(
            api.list_advances(CREDIT_ONE, {"member_bank_id": env.member_id}), 1
        )
        assert (
            self._read_allocation(api, allocation["id"])[
                "bucket_committed_first_time_cents"
            ]
            == 0
        )

    def test_the_purpose_bucket_plus_its_permitted_spill_is_the_real_limit(self, api):
        """PRD §3.6: "Otherwise, the purpose take is the lesser of the requested subsidy
        and the purpose bucket's free room; the spill is the requested subsidy minus that
        take. If the spill exceeds the general bucket's free room, the approval is rejected
        with `ERR_SETASIDE_POOL_EXHAUSTED`; otherwise the purpose bucket's committed figure
        is increased by the take and `bucket_committed_general_cents` is increased by the
        spill."

        Design: Corner/validations/setaside_request_exceeding_bucket_plus_spill_rejected
        """
        _env, allocation, advance = self._community_request(api, 300_000)

        refused = api.approve_advance(advance["id"], CREDIT_ONE)

        validate_error(refused, "ERR_SETASIDE_POOL_EXHAUSTED", 409)
        after = read_advance(api, advance["id"])
        assert after["credit_status"] == "REQUESTED"
        assert after["approved_by_user_id"] is None
        assert_fields(
            self._read_allocation(api, allocation["id"]),
            bucket_capacity_first_time_cents=140_000,
            bucket_capacity_rehabilitation_cents=100_000,
            bucket_capacity_general_cents=160_000,
            bucket_committed_rehabilitation_cents=0,
            bucket_committed_general_cents=0,
            committed_cents=0,
            remaining_cents=400_000,
            status="OPEN",
        )

    def test_a_request_that_fits_the_spill_charges_two_buckets(self, api):
        """PRD §3.6: "Spill only ever flows into `GENERAL` — it never crosses from one
        purpose bucket into the other."

        Design: Corner/validations/setaside_request_exceeding_bucket_plus_spill_rejected
        """
        _env, allocation, advance = self._community_request(api, 260_000)

        approved = assert_envelope(api.approve_advance(advance["id"], CREDIT_ONE))

        assert approved["credit_status"] == "CREDIT_APPROVED"
        assert_fields(
            self._read_allocation(api, allocation["id"]),
            bucket_committed_rehabilitation_cents=100_000,
            bucket_committed_general_cents=160_000,
            bucket_committed_first_time_cents=0,
            committed_cents=260_000,
            remaining_cents=140_000,
            status="OPEN",
        )


class TestAdvanceCreationGuards:
    """Membership standing, then the term range, then the principal minimum."""

    def _applicant_with_collateral(self, api):
        """Collateral in place, membership stock bought but not yet issued."""
        env = applicant_member(api)
        subscription = subscribe_stock(api, env.member_id, 9_600_000)
        execute_pledge_agreement(api, env.member_id)
        asset = pledge_asset(api, env.member_id)
        review_asset(api, asset["id"])
        return env, subscription

    def test_an_applicant_cannot_borrow_however_much_it_has_pledged(self, api):
        """PRD §3.5: "The member's `membership_status` must be `ACTIVE` or `PROBATION`,
        else `ERR_MEMBERSHIP_NOT_ACTIVE`."

        Design: Corner/validations/advance_create_while_membership_applicant_rejected
        """
        env, subscription = self._applicant_with_collateral(api)
        product = create_product(api)

        refused = api.create_advance(
            advance_payload(
                env.member_id,
                product["id"],
                env.version,
                term_days=30,
                requested_net_proceeds_cents=5_000_000,
            ),
            env.treasury,
        )

        validate_error(refused, "ERR_MEMBERSHIP_NOT_ACTIVE", 409)
        member = env.refresh()
        assert member["committed_advances_cents"] == 0
        assert member["lendable_collateral_value_cents"] == 15_600_000
        assert_total_count(
            api.list_advances(CREDIT_ONE, {"member_bank_id": env.member_id}), 0
        )

        issue_stock(api, subscription["id"])
        activate_member(api, env.member_id)

        accepted = request_advance(
            api, env, product["id"], term_days=30, requested_net_proceeds_cents=5_000_000
        )
        assert accepted["credit_status"] == "REQUESTED"

    def test_the_membership_gate_precedes_the_term_range_check(self, api):
        """PRD §2.5: "Tier 8 also carries the state gates that guard whole families of
        operations: a member whose `membership_status` is neither `ACTIVE` nor `PROBATION`
        blocks advance creation, advance approval, advance funding and the start of
        verification field work with `ERR_MEMBERSHIP_NOT_ACTIVE` (409)."

        Design: Corner/validations/advance_create_while_membership_applicant_rejected
        """
        env, _subscription = self._applicant_with_collateral(api)
        product = create_product(api)

        refused = api.create_advance(
            advance_payload(
                env.member_id,
                product["id"],
                env.version,
                term_days=5_000,
                requested_net_proceeds_cents=5_000_000,
            ),
            env.treasury,
        )

        validate_error(refused, "ERR_MEMBERSHIP_NOT_ACTIVE", 409)

    def test_the_minimum_principal_is_measured_on_gross_not_net(self, api):
        """PRD §3.5: "`gross_principal_cents` must be at least the product's
        `min_principal_cents`, else `ERR_MIN_PRINCIPAL_NOT_MET`."

        Design: Corner/validations/gross_principal_below_product_minimum_rejected
        """
        env = member_with_eligible_sf(api)
        product = create_product(api)
        opening_version = env.version

        refused = api.create_advance(
            advance_payload(
                env.member_id,
                product["id"],
                opening_version,
                term_days=30,
                requested_net_proceeds_cents=900_000,
            ),
            env.treasury,
        )

        validate_error(refused, "ERR_MIN_PRINCIPAL_NOT_MET", 409)
        assert env.version == opening_version
        assert_total_count(
            api.list_advances(CREDIT_ONE, {"member_bank_id": env.member_id}), 0
        )

        at_the_bound = request_advance(
            api, env, product["id"], term_days=30, requested_net_proceeds_cents=1_000_000
        )
        assert_fields(
            at_the_bound, gross_principal_cents=1_000_000, credit_status="REQUESTED"
        )

    def test_the_gross_up_lifts_a_short_request_over_the_minimum(self, api):
        """PRD §3.5: "**Step three** sets `gross_principal_cents` to
        `requested_net_proceeds_cents` plus `activity_stock_cents`, an exact addition."

        Design: Corner/validations/gross_principal_below_product_minimum_rejected
        """
        env = member_with_eligible_sf(api)
        product = create_product(api)

        accepted = request_advance(
            api,
            env,
            product["id"],
            term_days=30,
            requested_net_proceeds_cents=950_000,
            fund_stock_from_advance=True,
        )

        assert_fields(
            accepted,
            gross_principal_cents=1_000_000,
            net_proceeds_cents=950_000,
            activity_stock_cents=50_000,
            credit_status="REQUESTED",
        )


class TestQuoteValidityWindow:
    """Five days of life, inclusive of the fifth, and expiry is self-inflicted."""

    def _funded_advance_with_a_full_quote(self, api):
        """A 10,000,000 advance for 360 days, quoted for full prepayment on day one."""
        env = member_with_eligible_sf(api)
        subscribe_and_issue(api, env.member_id, 450_000, "ACTIVITY")
        product = create_product(api)
        advance = funded_advance(
            api,
            env,
            product["id"],
            term_days=360,
            requested_net_proceeds_cents=10_000_000,
            fund_stock_from_advance=False,
        )
        quote = quote_prepayment(api, env, advance["id"], 10_000_000, "FULL")
        return env, advance, quote

    def test_a_stale_quote_expires_itself_on_the_settle_attempt(self, api):
        """PRD §3.7: "An attempt after the five-day validity window has passed is not
        merely refused: the event itself moves `QUOTED → EXPIRED` and `ERR_QUOTE_EXPIRED`
        (409) is returned, with no change to any advance or member field."

        Design: Corner/validations/prepayment_settlement_after_quote_validity_window_rejected
        """
        _env, advance, quote = self._funded_advance_with_a_full_quote(api)
        pin_clock(api, "2026-08-07T00:00:00Z")

        refused = api.settle_prepayment_event(quote["id"], CREDIT_ONE)

        validate_error(refused, "ERR_QUOTE_EXPIRED", 409)
        expired = get_success_data(api.get_prepayment_event(quote["id"], CREDIT_ONE))
        assert_fields(expired, status="EXPIRED", settled_fee_cents=None)
        after = read_advance(api, advance["id"])
        assert_advance_dimensions(after, "FUNDED", "SECURED")
        assert after["outstanding_principal_cents"] == 10_000_000

    def test_the_fifth_day_is_still_inside_the_window(self, api):
        """PRD §3.7: "Settlement is legal only while `status` is `QUOTED` and only while
        the logical clock is at or before `quote_date` plus five days; the advance's
        `credit_status` must be `FUNDED`, else `ERR_INVALID_STATE`; and a `FULL`
        prepayment requires `prepay_amount_cents` to equal the advance's
        `outstanding_principal_cents` exactly, else `ERR_INVALID_REQUEST`."

        Design: Corner/validations/prepayment_settlement_after_quote_validity_window_rejected
        """
        _env, advance, quote = self._funded_advance_with_a_full_quote(api)
        pin_clock(api, "2026-08-06T00:00:00Z")

        settled = assert_envelope(api.settle_prepayment_event(quote["id"], CREDIT_ONE))

        assert settled["status"] == "SETTLED"
        after = read_advance(api, advance["id"])
        assert_advance_dimensions(after, "PREPAID", "RELEASED")
        assert after["outstanding_principal_cents"] == 0
