"""One error identity at a time: the path and body 404s that must stay distinguishable,
the four gates that refuse an eligibility review, the stock redemption floor, the two
funding preconditions, the posture term cap, and the community program's own refusals."""
from test_helpers import *  # noqa: F401,F403

UNSCOPED_TREASURY = make_treasury_officer_headers(UNSCOPED_TREASURY_USER_ID)


class TestPathAndBodyNotFound:
    """Ten identifiers, ten error ids: a child's 404 never reports its parent."""

    def test_the_member_bank_404_is_the_root_of_the_chain(self, api):
        """PRD §2.5: "A `member_bank_id` that does not resolve gives
        `ERR_MEMBER_BANK_NOT_FOUND`; `stock_subscription_id` gives
        `ERR_STOCK_SUBSCRIPTION_NOT_FOUND`; `collateral_asset_id` gives
        `ERR_COLLATERAL_ASSET_NOT_FOUND`; ... All ten are 404."

        Design: Corner/errors/member_bank_not_found
        """
        pin_clock(api)

        read = api.get_member_bank(UNKNOWN_MEMBER_BANK_ID, CREDIT_ONE)
        capacity = api.get_borrowing_capacity(UNKNOWN_MEMBER_BANK_ID, CREDIT_ONE)

        validate_error(read, "ERR_MEMBER_BANK_NOT_FOUND", 404)
        validate_error(capacity, "ERR_MEMBER_BANK_NOT_FOUND", 404)
        assert_error_envelope(read)

    def test_an_unknown_subscription_is_not_reported_as_its_member(self, api):
        """PRD §2.5: "**Path resource existence.** Path identifiers are resolved strictly
        left to right, and the first one that does not resolve determines the error. ...
        `stock_subscription_id` gives `ERR_STOCK_SUBSCRIPTION_NOT_FOUND`."

        Design: Corner/errors/stock_subscription_not_found
        """
        pin_clock(api)

        read = api.get_stock_subscription(UNKNOWN_STOCK_SUBSCRIPTION_ID, CREDIT_ONE)
        issued = api.issue_stock_subscription(UNKNOWN_STOCK_SUBSCRIPTION_ID, CREDIT_ONE)

        validate_error(read, "ERR_STOCK_SUBSCRIPTION_NOT_FOUND", 404)
        validate_error(issued, "ERR_STOCK_SUBSCRIPTION_NOT_FOUND", 404)

    def test_the_flat_receipt_path_names_the_receipt_not_the_asset(self, api):
        """PRD §2.5: "... `safekeeping_receipt_id` gives
        `ERR_SAFEKEEPING_RECEIPT_NOT_FOUND`; `collateral_verification_review_id` gives
        `ERR_REVIEW_NOT_FOUND`."

        Design: Corner/errors/safekeeping_receipt_not_found
        """
        pin_clock(api)

        read = api.get_safekeeping_receipt(UNKNOWN_SAFEKEEPING_RECEIPT_ID, CUSTODIAN)
        confirmed = api.confirm_safekeeping_receipt(
            UNKNOWN_SAFEKEEPING_RECEIPT_ID, confirm_receipt_payload("RECEIVED"), CUSTODIAN
        )

        validate_error(read, "ERR_SAFEKEEPING_RECEIPT_NOT_FOUND", 404)
        validate_error(confirmed, "ERR_SAFEKEEPING_RECEIPT_NOT_FOUND", 404)

    def test_an_unknown_review_404s_ahead_of_any_lifecycle_precondition(self, api):
        """PRD §2.5: "The practical consequence of this ladder is worth stating plainly: a
        request that is both unauthorised and fiscally impossible reports the authorisation
        failure; a member-scope violation surfaces ahead of a stale-version rejection; a
        stale version surfaces ahead of any state or business check; and a capacity
        shortfall is only ever reported once every structural, referential and safety
        condition has passed."

        Design: Corner/errors/verification_review_not_found
        """
        pin_clock(api)

        read = api.get_verification_review(UNKNOWN_REVIEW_ID, AUDITOR)
        begun = api.begin_field_work(UNKNOWN_REVIEW_ID, AUDITOR)

        validate_error(read, "ERR_REVIEW_NOT_FOUND", 404)
        validate_error(begun, "ERR_REVIEW_NOT_FOUND", 404)

    def test_an_unknown_finding_has_an_error_id_of_its_own(self, api):
        """PRD §2.5: "... `review_finding_id` gives `ERR_REVIEW_FINDING_NOT_FOUND`;
        `advance_product_id` gives `ERR_ADVANCE_PRODUCT_NOT_FOUND`."

        Design: Corner/errors/review_finding_not_found
        """
        pin_clock(api)

        read = api.get_review_finding(UNKNOWN_REVIEW_FINDING_ID, AUDITOR)
        waived = api.waive_review_finding(UNKNOWN_REVIEW_FINDING_ID, CREDIT_ONE)

        validate_error(read, "ERR_REVIEW_FINDING_NOT_FOUND", 404)
        validate_error(waived, "ERR_REVIEW_FINDING_NOT_FOUND", 404)

    def test_an_unknown_product_also_404s_from_the_advance_body(self, api):
        """PRD §2.5: "**Body foreign keys.** ... An unresolvable `advance_product_id` in an
        advance request gives `ERR_ADVANCE_PRODUCT_NOT_FOUND` (404)."

        Design: Corner/errors/advance_product_not_found
        """
        env = applicant_member(api)

        read = api.get_advance_product(UNKNOWN_ADVANCE_PRODUCT_ID, CREDIT_ONE)
        requested = api.create_advance(
            advance_payload(
                env.member_id,
                UNKNOWN_ADVANCE_PRODUCT_ID,
                env.version,
                term_days=30,
                requested_net_proceeds_cents=1_000_000,
            ),
            env.treasury,
        )

        validate_error(read, "ERR_ADVANCE_PRODUCT_NOT_FOUND", 404)
        validate_error(requested, "ERR_ADVANCE_PRODUCT_NOT_FOUND", 404)

    def test_an_unknown_quote_is_not_read_as_an_expired_quote(self, api):
        """PRD §2.5: "... `prepayment_event_id` gives `ERR_PREPAYMENT_EVENT_NOT_FOUND`;
        and `community_program_allocation_id` gives `ERR_ALLOCATION_NOT_FOUND`."

        Design: Corner/errors/prepayment_event_not_found
        """
        pin_clock(api)

        read = api.get_prepayment_event(UNKNOWN_PREPAYMENT_EVENT_ID, UNSCOPED_TREASURY)
        settled = api.settle_prepayment_event(UNKNOWN_PREPAYMENT_EVENT_ID, CREDIT_ONE)

        validate_error(read, "ERR_PREPAYMENT_EVENT_NOT_FOUND", 404)
        validate_error(settled, "ERR_PREPAYMENT_EVENT_NOT_FOUND", 404)

    def test_an_unknown_allocation_404s_before_the_community_product_rule(self, api):
        """PRD §2.5: "**Body foreign keys.** ... a supplied but unresolvable
        `community_program_allocation_id` gives `ERR_ALLOCATION_NOT_FOUND` (404)."

        Design: Corner/errors/community_program_allocation_not_found
        """
        env = applicant_member(api)
        plain = create_product(api)

        read = api.get_community_program_allocation(UNKNOWN_ALLOCATION_ID, COMMUNITY)
        requested = api.create_advance(
            advance_payload(
                env.member_id,
                plain["id"],
                env.version,
                term_days=30,
                requested_net_proceeds_cents=1_000_000,
                community_program_allocation_id=UNKNOWN_ALLOCATION_ID,
                community_bucket="FIRST_TIME_HOMEBUYER",
                requested_subsidy_cents=100_000,
            ),
            env.treasury,
        )

        validate_error(read, "ERR_ALLOCATION_NOT_FOUND", 404)
        validate_error(requested, "ERR_ALLOCATION_NOT_FOUND", 404)


class TestPledgeAgreementGate:
    """No security agreement, no collateral."""

    def test_collateral_cannot_be_pledged_before_the_paperwork_exists(self, api):
        """PRD §3.2: "If the owning member's `pledge_agreement_status` is not `EXECUTED`,
        the pledge is rejected with `ERR_PLEDGE_AGREEMENT_NOT_EXECUTED`."

        Design: Corner/errors/asset_submission_without_executed_pledge_rejected
        """
        env = applicant_member(api)

        refused = api.create_collateral_asset(
            collateral_asset_payload(env.member_id), env.treasury
        )

        validate_error(refused, "ERR_PLEDGE_AGREEMENT_NOT_EXECUTED", 409)
        assert_total_count(
            api.list_collateral_assets(CREDIT_ONE, {"member_bank_id": env.member_id}), 0
        )
        member = env.refresh()
        assert_fields(
            member, pledge_agreement_status="NONE", pledge_mode="NONE", version=1
        )

        execute_pledge_agreement(api, env.member_id)

        accepted = validate_success(
            api.create_collateral_asset(
                collateral_asset_payload(env.member_id), env.treasury
            ),
            201,
        )
        assert_fields(
            accepted, status="UNDER_REVIEW", effective_listing_mode="BLANKET"
        )


class TestLoanFileConditionGates:
    """Missing files stop a review; an exception only prices it down."""

    def _asset_awaiting_review(self, api, **overrides):
        env = pledging_member(api)
        return env, pledge_asset(api, env.member_id, **overrides)

    def test_missing_files_stop_the_review_outright(self, api):
        """PRD §3.4: "Then four condition checks in a pinned order:
        `documentation_status` must not be `MISSING`, else `ERR_DOCUMENTATION_MISSING`."

        Design: Corner/errors/documentation_missing_blocks_eligibility_review
        """
        env, asset = self._asset_awaiting_review(api, documentation_status="MISSING")

        refused = api.review_asset_eligibility(asset["id"], CREDIT_ONE, {})

        validate_error(refused, "ERR_DOCUMENTATION_MISSING", 409)
        stored = read_asset(api, asset["id"])
        assert_fields(
            stored, status="UNDER_REVIEW", ineligibility_reason="NONE"
        )
        assert_asset_valuation(stored, 0, 0)
        assert env.refresh()["lendable_collateral_value_cents"] == 0

    def test_the_same_asset_is_lendable_once_the_files_are_merely_flawed(self, api):
        """PRD §3.4: "If `documentation_status` is `EXCEPTION`, subtract 700 basis
        points."

        Design: Corner/errors/documentation_missing_blocks_eligibility_review
        """
        env, asset = self._asset_awaiting_review(api, documentation_status="MISSING")
        recorded = review_asset(api, asset["id"], force_ineligible=True)

        amend_documentation(api, asset["id"], documentation_status="EXCEPTION")
        repriced = validate_success(
            api.review_asset_eligibility(asset["id"], CREDIT_ONE, {})
        )

        assert_fields(
            recorded, status="INELIGIBLE", ineligibility_reason="DOCUMENTATION_MISSING"
        )
        assert_asset_valuation(recorded, 0, 0)
        assert_fields(
            repriced,
            status="ELIGIBLE",
            documentation_status="EXCEPTION",
            ineligibility_reason="NONE",
        )
        assert_asset_valuation(repriced, 7_100, 14_200_000)
        assert env.refresh()["lendable_collateral_value_cents"] == 14_200_000

    def test_one_basis_point_past_the_inclusive_ceiling_is_refused(self, api):
        """PRD §3.4: "Then four condition checks in a pinned order: ... `ltv_bps` must be
        no greater than 9,500 basis points (95.00 percent), else `ERR_LTV_EXCEEDS_MAX`."

        Design: Corner/errors/ltv_above_maximum_rejected
        """
        env, asset = self._asset_awaiting_review(api, ltv_bps=9_501)

        refused = api.review_asset_eligibility(asset["id"], CREDIT_ONE, {})

        validate_error(refused, "ERR_LTV_EXCEEDS_MAX", 409)
        stored = read_asset(api, asset["id"])
        assert_fields(stored, status="UNDER_REVIEW", ineligibility_reason="NONE")
        assert_asset_valuation(stored, 0, 0)
        assert env.refresh()["lendable_collateral_value_cents"] == 0

    def test_a_corrected_ratio_brings_the_asset_back_at_a_penalised_factor(self, api):
        """PRD §3.4: "The amendment always pushes the asset back to `UNDER_REVIEW` — from
        `ELIGIBLE`, from `INELIGIBLE` or from `SUSPENDED` alike — updates the supplied
        fields, sets `discount_factor_bps` and `lendable_value_cents` to 0 for as long as
        the asset stays `UNDER_REVIEW`, recomputes `collateral_basis_cents` and
        `effective_listing_mode`, and then recomputes the member's
        `lendable_collateral_value_cents` and `borrowing_capacity_cents` and re-derives
        `collateral_posture`."

        Design: Corner/errors/ltv_above_maximum_rejected
        """
        env, asset = self._asset_awaiting_review(api, ltv_bps=9_501)
        recorded = review_asset(api, asset["id"], force_ineligible=True)

        amended = amend_documentation(api, asset["id"], ltv_bps=9_500)
        repriced = validate_success(
            api.review_asset_eligibility(asset["id"], CREDIT_ONE, {})
        )

        assert_fields(
            recorded, status="INELIGIBLE", ineligibility_reason="LTV_EXCEEDS_MAX"
        )
        assert_fields(amended, status="UNDER_REVIEW", ltv_bps=9_500)
        assert_asset_valuation(amended, 0, 0)
        assert repriced["status"] == "ELIGIBLE"
        assert_asset_valuation(repriced, 7_300, 14_600_000)
        assert env.refresh()["lendable_collateral_value_cents"] == 14_600_000

    def test_sixty_days_delinquent_is_no_longer_collateral(self, api):
        """PRD §3.4: "Then four condition checks in a pinned order: ...
        `delinquency_days` must be strictly fewer than 60, else
        `ERR_DELINQUENT_ASSET_INELIGIBLE`."

        Design: Corner/errors/delinquency_beyond_sixty_days_rejected
        """
        env, asset = self._asset_awaiting_review(
            api, ltv_bps=7_000, delinquency_days=60
        )

        refused = api.review_asset_eligibility(asset["id"], CREDIT_ONE, {})

        validate_error(refused, "ERR_DELINQUENT_ASSET_INELIGIBLE", 409)
        stored = read_asset(api, asset["id"])
        assert stored["status"] == "UNDER_REVIEW"
        assert_asset_valuation(stored, 0, 0)

        recorded = review_asset(api, asset["id"], force_ineligible=True)

        assert_fields(
            recorded, status="INELIGIBLE", ineligibility_reason="DELINQUENT"
        )
        assert env.refresh()["lendable_collateral_value_cents"] == 0


class TestStockRedemptionFloor:
    """The floor is measured on what would be left, not on what is held now."""

    def test_the_last_of_the_membership_stock_cannot_be_handed_back(self, api):
        """PRD §3.1: "Both steps enforce the same floor: if `stock_held_cents` minus this
        subscription's `amount_cents` would fall below `required_total_stock_cents`, the
        request is rejected with `ERR_STOCK_REDEMPTION_WOULD_BREACH_REQUIREMENT`."

        Design: Corner/errors/membership_stock_redemption_breaching_requirement_rejected
        """
        env = active_member(api)
        membership = env.subscriptions["membership"]

        refused = api.request_stock_redemption(membership["id"], env.treasury)

        validate_error(refused, "ERR_STOCK_REDEMPTION_WOULD_BREACH_REQUIREMENT", 409)
        assert (
            get_success_data(api.get_stock_subscription(membership["id"], CREDIT_ONE))[
                "status"
            ]
            == "ISSUED"
        )
        assert_stock_position(
            env.refresh(),
            stock_held_cents=9_600_000,
            required_total_stock_cents=9_600_000,
            excess_stock_cents=0,
        )

        spare = subscribe_and_issue(api, env.member_id, 1_000_000)
        requested = assert_envelope(
            api.request_stock_redemption(spare["id"], env.treasury)
        )

        assert requested["status"] == "REDEMPTION_REQUESTED"
        assert env.refresh()["stock_held_cents"] == 10_600_000


class TestFundingPreconditions:
    """Two things funding insists on that approval never looked at."""

    def test_funding_needs_the_activity_stock_already_bought(self, api):
        """PRD §3.6: "And when `fund_stock_from_advance` is false, the member's
        `stock_deficiency_cents` must be exactly 0, else `ERR_ACTIVITY_STOCK_DEFICIENT`."

        Design: Corner/errors/funding_without_activity_stock_rejected
        """
        env = member_with_eligible_sf(api)
        product = create_product(api)
        advance = approved_advance(
            api,
            env,
            product["id"],
            term_days=30,
            requested_net_proceeds_cents=1_000_000,
        )

        refused = api.fund_advance(advance["id"], CREDIT_TWO)

        validate_error(refused, "ERR_ACTIVITY_STOCK_DEFICIENT", 409)
        stalled = read_advance(api, advance["id"])
        assert_advance_dimensions(stalled, "CREDIT_APPROVED", "PENDING_VERIFICATION")
        assert stalled["outstanding_principal_cents"] == 0
        assert_stock_position(
            env.refresh(),
            required_activity_stock_cents=50_000,
            stock_deficiency_cents=50_000,
        )

        subscribe_and_issue(api, env.member_id, 50_000, "ACTIVITY")
        funded = validate_success(api.fund_advance(advance["id"], CREDIT_TWO))

        assert_advance_dimensions(funded, "FUNDED", "SECURED")
        assert funded["outstanding_principal_cents"] == 1_000_000

    def test_a_delivery_product_will_not_fund_on_undelivered_files(self, api):
        """PRD §3.6: "Delivery is checked from two directions: if the product's
        `requires_collateral_delivery` is true, or if the member's derived
        `delivery_required` is true, then every `ELIGIBLE` asset of the member must have
        `effective_listing_mode` equal to `DELIVERED`; if even one does not, funding is
        rejected with `ERR_DELIVERY_NOT_CONFIRMED`."

        Design: Corner/errors/funding_a_delivery_product_without_received_files_rejected
        """
        env = member_with_eligible_sf(api)
        product = create_product(
            api, product_code="DEL-450", requires_collateral_delivery=True
        )
        advance = approved_advance(
            api,
            env,
            product["id"],
            term_days=30,
            requested_net_proceeds_cents=950_000,
            fund_stock_from_advance=True,
        )

        refused = api.fund_advance(advance["id"], CREDIT_TWO)

        validate_error(refused, "ERR_DELIVERY_NOT_CONFIRMED", 409)
        assert read_advance(api, advance["id"])["credit_status"] == "CREDIT_APPROVED"
        assert_total_count(api.list_stock_subscriptions(CREDIT_ONE), 1)

        deliver_asset(api, env.assets["sf"]["id"])
        delivered = read_asset(api, env.assets["sf"]["id"])
        funded = validate_success(api.fund_advance(advance["id"], CREDIT_TWO))

        assert delivered["effective_listing_mode"] == "DELIVERED"
        assert_asset_valuation(delivered, 9_200, 18_400_000)
        assert_advance_dimensions(funded, "FUNDED", "SECURED")
        rows = assert_total_count(api.list_stock_subscriptions(CREDIT_ONE), 2)
        activity = [row for row in rows if row["subscription_type"] == "ACTIVITY"]
        assert len(activity) == 1
        assert_fields(
            activity[0],
            amount_cents=50_000,
            status="ISSUED",
            advance_id=advance["id"],
        )


class TestRestrictedPostureTermCap:
    """A thin cushion is still a cushion, and it caps the term rather than the money."""

    def _member_with_a_thin_cushion(self, api):
        """15,000,000 funded against 15,600,000 of lendable value: capacity 600,000."""
        env = member_with_eligible_sf(api)
        subscribe_and_issue(api, env.member_id, 680_000, "ACTIVITY")
        product = create_product(api)
        advance = funded_advance(
            api,
            env,
            product["id"],
            term_days=30,
            requested_net_proceeds_cents=15_000_000,
        )
        return env, product, advance

    def test_a_restricted_member_may_not_borrow_past_ninety_days(self, api):
        """PRD §3.5: "The member's `collateral_posture` must not be `FROZEN`, else
        `ERR_COLLATERAL_POSTURE_FROZEN`; and a member whose posture is `RESTRICTED` may not
        request a term longer than 90 days, which is rejected with
        `ERR_POSTURE_RESTRICTED_TERM_LIMIT`."

        Design: Corner/errors/posture_restricted_blocks_long_term_advance
        """
        env, product, _advance = self._member_with_a_thin_cushion(api)

        refused = api.create_advance(
            advance_payload(
                env.member_id,
                product["id"],
                env.version,
                term_days=180,
                requested_net_proceeds_cents=1_000_000,
            ),
            env.treasury,
        )

        validate_error(refused, "ERR_POSTURE_RESTRICTED_TERM_LIMIT", 409)
        member = env.refresh()
        assert_fields(
            member,
            collateral_posture="RESTRICTED",
            borrowing_capacity_cents=600_000,
            total_outstanding_advances_cents=15_000_000,
            shortfall_status="NONE",
        )

    def test_at_exactly_ninety_days_the_term_cap_yields_to_the_capacity_rule(self, api):
        """PRD §3.5: "Advance creation is gated on the **provisional** variant, because
        the request being created is not yet a commitment: if `gross_principal_cents`
        exceeds the member's provisional capacity, the request is rejected with
        `ERR_INSUFFICIENT_BORROWING_CAPACITY`."

        Design: Corner/errors/posture_restricted_blocks_long_term_advance
        """
        env, product, _advance = self._member_with_a_thin_cushion(api)

        refused = api.create_advance(
            advance_payload(
                env.member_id,
                product["id"],
                env.version,
                term_days=90,
                requested_net_proceeds_cents=1_000_000,
            ),
            env.treasury,
        )

        validate_error(refused, "ERR_INSUFFICIENT_BORROWING_CAPACITY", 409)
        assert_capacity_breakdown(
            env.capacity("PROVISIONAL"),
            lendable_collateral_value_cents=15_600_000,
            outstanding_advances_cents=15_000_000,
            commitments_cents=0,
            borrowing_capacity_cents=600_000,
        )
        assert_total_count(
            api.list_advances(CREDIT_ONE, {"member_bank_id": env.member_id}), 1
        )


class TestCommunityLendingEligibility:
    """Eligibility is derived from the tier, so the tier is what unlocks the pool."""

    def _tier_four_member_with_a_pool(self, api):
        env = applicant_member(
            api,
            name="Cascade Mutual",
            charter_type="COMMERCIAL_BANK",
            total_assets_cents=5_000_000_000,
            credit_rating_tier=4,
        )
        subscribe_and_issue(api, env.member_id, 6_000_000)
        activate_member(api, env.member_id)
        execute_pledge_agreement(api, env.member_id)
        asset = pledge_asset(api, env.member_id)
        review_asset(api, asset["id"])
        product = create_product(
            api,
            product_code="CIP-C",
            rate_bps=300,
            prepayment_fee_method="NONE",
            community_program_flag=True,
        )
        allocation = create_allocation(api, program_code="CIP", subsidy_rate_bps=250)
        return env, product, allocation

    def test_a_tier_four_member_is_barred_from_the_set_aside(self, api):
        """PRD §3.5: "When an allocation is supplied, the member's derived
        `community_lending_eligible` must be true, else
        `ERR_NOT_COMMUNITY_LENDING_ELIGIBLE`."

        Design: Corner/errors/non_community_eligible_member_rejected_for_setaside_advance
        """
        env, product, allocation = self._tier_four_member_with_a_pool(api)

        refused = api.create_advance(
            advance_payload(
                env.member_id,
                product["id"],
                env.version,
                term_days=60,
                requested_net_proceeds_cents=2_000_000,
                community_program_allocation_id=allocation["id"],
                community_bucket="FIRST_TIME_HOMEBUYER",
                requested_subsidy_cents=100_000,
            ),
            env.treasury,
        )

        validate_error(refused, "ERR_NOT_COMMUNITY_LENDING_ELIGIBLE", 409)
        member = env.refresh()
        assert member["community_lending_eligible"] is False
        assert member["delivery_required"] is True
        assert_fields(
            get_success_data(
                api.get_community_program_allocation(allocation["id"], COMMUNITY)
            ),
            committed_cents=0,
            remaining_cents=400_000,
            status="OPEN",
        )

    def test_a_tier_three_upgrade_opens_the_programme(self, api):
        """PRD §3.1: "`community_lending_eligible` is derived, never supplied: it is true
        when `membership_status` is `ACTIVE`, and `credit_rating_tier` is 3 or lower, and
        additionally either `cdfi_certified` is true or `charter_type` is anything other
        than `INSURANCE_COMPANY`."

        Design: Corner/errors/non_community_eligible_member_rejected_for_setaside_advance
        """
        env, product, allocation = self._tier_four_member_with_a_pool(api)

        upgraded = amend_condition(api, env.member_id, credit_rating_tier=3)
        accepted = validate_success(
            api.create_advance(
                advance_payload(
                    env.member_id,
                    product["id"],
                    env.version,
                    term_days=60,
                    requested_net_proceeds_cents=2_000_000,
                    community_program_allocation_id=allocation["id"],
                    community_bucket="FIRST_TIME_HOMEBUYER",
                    requested_subsidy_cents=100_000,
                ),
                env.treasury,
            ),
            201,
        )

        assert upgraded["community_lending_eligible"] is True
        assert upgraded["delivery_required"] is False
        assert_fields(
            accepted,
            credit_status="REQUESTED",
            gross_principal_cents=2_000_000,
            requested_subsidy_cents=100_000,
            rate_bps=50,
        )


class TestSubsidyCapAndPoolClosure:
    """The cap reads the principal; the pool reads its own remaining cents."""

    def _harbor_with_a_community_pool(self, api):
        env = member_with_eligible_sf(api)
        product = create_product(
            api,
            product_code="CIP-C",
            rate_bps=300,
            prepayment_fee_method="NONE",
            community_program_flag=True,
        )
        allocation = create_allocation(api, program_code="CIP", subsidy_rate_bps=250)
        return env, product, allocation

    def _subsidised_request(self, api, env, product, allocation, bucket, subsidy, net):
        return api.create_advance(
            advance_payload(
                env.member_id,
                product["id"],
                env.version,
                term_days=365,
                requested_net_proceeds_cents=net,
                community_program_allocation_id=allocation["id"],
                community_bucket=bucket,
                requested_subsidy_cents=subsidy,
            ),
            env.treasury,
        )

    def _read_allocation(self, api, allocation_id):
        return get_success_data(
            api.get_community_program_allocation(allocation_id, COMMUNITY)
        )

    def test_the_subsidy_cap_is_measured_against_gross_principal(self, api):
        """PRD §3.5: "And any `requested_subsidy_cents` must not exceed 2,000 basis points
        — one fifth — of `gross_principal_cents`, that cap being computed as
        `gross_principal_cents` multiplied by 2,000, divided by 10,000, rounded half up to
        whole cents; a subsidy exactly equal to the cap passes, and one above it is
        rejected with `ERR_SUBSIDY_EXCEEDS_PRINCIPAL_CAP`."

        Design: Corner/errors/subsidy_above_twenty_percent_of_gross_principal_rejected
        """
        env, product, allocation = self._harbor_with_a_community_pool(api)

        refused = self._subsidised_request(
            api, env, product, allocation, "FIRST_TIME_HOMEBUYER", 300_000, 1_000_000
        )

        validate_error(refused, "ERR_SUBSIDY_EXCEEDS_PRINCIPAL_CAP", 409)
        assert_total_count(
            api.list_advances(CREDIT_ONE, {"member_bank_id": env.member_id}), 0
        )
        assert_fields(
            self._read_allocation(api, allocation["id"]),
            committed_cents=0,
            remaining_cents=400_000,
            status="OPEN",
        )

    def test_a_subsidy_exactly_at_the_cap_is_accepted(self, api):
        """PRD §3.5: "Two constraints then read the computed principal.
        `gross_principal_cents` must be at least the product's `min_principal_cents`, else
        `ERR_MIN_PRINCIPAL_NOT_MET`."

        Design: Corner/errors/subsidy_above_twenty_percent_of_gross_principal_rejected
        """
        env, product, allocation = self._harbor_with_a_community_pool(api)

        accepted = validate_success(
            self._subsidised_request(
                api,
                env,
                product,
                allocation,
                "FIRST_TIME_HOMEBUYER",
                200_000,
                1_000_000,
            ),
            201,
        )

        assert_fields(
            accepted,
            gross_principal_cents=1_000_000,
            requested_subsidy_cents=200_000,
            credit_status="REQUESTED",
        )
        assert self._read_allocation(api, allocation["id"])["committed_cents"] == 0

    def test_the_pool_closes_on_its_last_cent_and_refuses_the_next_approval(self, api):
        """PRD §3.6: "If the commit consumes the last remaining cent so that
        `remaining_cents` becomes exactly 0, the allocation moves `OPEN → CLOSED`, and any
        subsequent approval against it is rejected with `ERR_ALLOCATION_CLOSED`."

        Design: Corner/errors/approve_against_a_fully_committed_allocation_rejected
        """
        env, product, allocation = self._harbor_with_a_community_pool(api)
        first = validate_success(
            self._subsidised_request(
                api,
                env,
                product,
                allocation,
                "FIRST_TIME_HOMEBUYER",
                300_000,
                2_000_000,
            ),
            201,
        )
        approve_advance(api, first["id"])
        second = validate_success(
            self._subsidised_request(
                api, env, product, allocation, "REHABILITATION", 100_000, 2_000_000
            ),
            201,
        )
        approve_advance(api, second["id"])
        third = validate_success(
            self._subsidised_request(
                api, env, product, allocation, "GENERAL", 10_000, 1_000_000
            ),
            201,
        )

        refused = api.approve_advance(third["id"], CREDIT_ONE)

        validate_error(refused, "ERR_ALLOCATION_CLOSED", 409)
        assert_fields(
            self._read_allocation(api, allocation["id"]),
            bucket_committed_first_time_cents=140_000,
            bucket_committed_rehabilitation_cents=100_000,
            bucket_committed_general_cents=160_000,
            committed_cents=400_000,
            remaining_cents=0,
            status="CLOSED",
        )
        stalled = read_advance(api, third["id"])
        assert_fields(
            stalled, credit_status="REQUESTED", approved_by_user_id=None
        )


class TestFrozenSubstitutionGuard:
    """While frozen, a member may only trade up."""

    def _frozen_member_holding_a_heloc(self, api):
        """The mortgage's files go missing, leaving a 500,000 HELOC against 15,000,000."""
        env = member_with_eligible_sf(api)
        heloc = add_heloc(api, env)
        subscribe_and_issue(api, env.member_id, 680_000, "ACTIVITY")
        product = create_product(api)
        funded_advance(
            api,
            env,
            product["id"],
            term_days=30,
            requested_net_proceeds_cents=15_000_000,
        )
        amend_documentation(
            api, env.assets["sf"]["id"], documentation_status="MISSING"
        )
        return env, heloc

    def test_a_frozen_member_may_not_trade_down(self, api):
        """PRD §3.9: "Beyond the stale-version check of §2.7, one safety rule applies:
        while the member's `collateral_posture` is `FROZEN`, a substitution is permitted
        only if the replacement's hypothetical `lendable_value_cents` is greater than or
        equal to the outgoing asset's `lendable_value_cents`."

        Design: Corner/errors/substitution_reducing_lendable_value_while_frozen_rejected
        """
        env, heloc = self._frozen_member_holding_a_heloc(api)

        refused = api.substitute_collateral_asset(
            heloc["id"],
            substitution_payload(
                env.version,
                asset_class="HELOC",
                unpaid_principal_balance_cents=100_000,
                market_value_cents=100_000,
                ltv_bps=7_000,
            ),
            env.treasury,
        )

        validate_error(refused, "ERR_SUBSTITUTION_REDUCES_LENDABLE_VALUE", 409)
        assert_total_count(
            api.list_collateral_assets(CREDIT_ONE, {"replaces_asset_id": heloc["id"]}), 0
        )
        stayed = read_asset(api, heloc["id"])
        assert stayed["status"] == "ELIGIBLE"
        assert_asset_valuation(stayed, 5_000, 500_000)
        assert_fields(
            env.refresh(),
            lendable_collateral_value_cents=500_000,
            collateral_posture="FROZEN",
            shortfall_status="OPEN",
        )

    def test_a_frozen_member_may_still_trade_up(self, api):
        """PRD §3.9: "A frozen member trading down into a strictly lower-valued asset is
        rejected with `ERR_SUBSTITUTION_REDUCES_LENDABLE_VALUE`. When the posture is not
        `FROZEN`, no value comparison is made."

        Design: Corner/errors/substitution_reducing_lendable_value_while_frozen_rejected
        """
        env, heloc = self._frozen_member_holding_a_heloc(api)

        replacement = assert_envelope(
            api.substitute_collateral_asset(
                heloc["id"],
                substitution_payload(
                    env.version,
                    asset_class="HELOC",
                    unpaid_principal_balance_cents=2_000_000,
                    market_value_cents=2_000_000,
                    ltv_bps=7_000,
                ),
                env.treasury,
            ),
            201,
        )

        assert_fields(
            replacement,
            replaces_asset_id=heloc["id"],
            status="UNDER_REVIEW",
            collateral_basis_cents=2_000_000,
        )
        assert read_asset(api, heloc["id"])["status"] == "SUBSTITUTED"
        assert_asset_valuation(review_asset(api, replacement["id"]), 5_000, 1_000_000)
        assert env.refresh()["lendable_collateral_value_cents"] == 1_000_000
