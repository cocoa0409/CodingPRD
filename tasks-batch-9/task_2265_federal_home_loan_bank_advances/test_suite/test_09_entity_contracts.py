"""Entity contracts: what a create returns, which fields default, which fields the
server owns, how a list paginates, and how a parent reference is resolved."""
from test_helpers import *  # noqa: F401,F403


class TestMemberBankRegistrationContract:
    """The registration response, its computed stock band and its defaults."""

    def test_registration_returns_every_declared_member_field(self, api):
        """PRD §3.1: "A newly registered institution begins with `membership_status`
        `APPLICANT`, `pledge_mode` `NONE`, `pledge_agreement_status` `NONE`,
        `pledge_agreement_effective_date` null, `collateral_posture` `OPEN`,
        `shortfall_status` `NONE`, `verification_haircut_bps` 0,
        `latest_review_outcome` `NONE`, and a `version` of 1."

        Design: Corner/entities/member_bank_creation_returns_all_declared_fields
        """
        pin_clock(api)

        response = api.create_member_bank(
            member_bank_payload(credit_rating_tier=None), ADMIN
        )

        member = assert_envelope(response, 201)
        assert_common_fields(member)
        assert_fields(
            member,
            name="Harbor Savings",
            charter_type="THRIFT",
            total_assets_cents=8_000_000_000,
            membership_status="APPLICANT",
            pledge_mode="NONE",
            pledge_agreement_status="NONE",
            pledge_agreement_effective_date=None,
            collateral_posture="OPEN",
            shortfall_status="NONE",
            verification_haircut_bps=0,
            latest_review_outcome="NONE",
            version=1,
        )
        assert member["created_at"] == "2026-08-01T00:00:00.000Z"
        assert member["updated_at"] == member["created_at"]
        assert_stock_position(
            member,
            required_membership_stock_cents=9_600_000,
            stock_held_cents=0,
            stock_deficiency_cents=9_600_000,
        )
        assert_fields(
            member, lendable_collateral_value_cents=0, borrowing_capacity_cents=0
        )

    def test_the_single_row_read_echoes_the_create_and_never_mutates(self, api):
        """PRD §2.4: "`version` (integer): a counter that starts at 1 when the resource
        is created and increases by exactly 1 on each subsequent mutation of that
        resource."

        Design: Corner/entities/member_bank_retrieval_returns_stored_row
        """
        env = applicant_member(api)

        first = assert_envelope(api.get_member_bank(env.member_id, CREDIT_ONE))
        second = assert_envelope(api.get_member_bank(env.member_id, CREDIT_ONE))

        assert_fields(
            first,
            id=env.member_id,
            version=1,
            name="Harbor Savings",
            charter_type="THRIFT",
            total_assets_cents=8_000_000_000,
            credit_rating_tier=1,
        )
        assert second == first

    def test_an_absent_required_input_is_a_request_shape_failure(self, api):
        """PRD §2.5: "**Request shape.** Applying to every endpoint that accepts a body
        or query parameters: a required field absent, a field of the wrong type, an enum
        value outside its declared set, a numeric field outside its declared range ...
        each yields `ERR_INVALID_REQUEST` (422)."

        Design: Corner/entities/member_bank_missing_charter_type_returns_4XX
        """
        pin_clock(api)
        bodies = (
            {"name": "Harbor Savings", "total_assets_cents": 8_000_000_000},
            {"charter_type": "THRIFT", "total_assets_cents": 8_000_000_000},
            {"name": "Harbor Savings", "charter_type": "THRIFT"},
            {
                "name": "Harbor Savings",
                "charter_type": "THRIFT",
                "total_assets_cents": 99_999_999,
            },
        )

        for body in bodies:
            response = api.create_member_bank(body, ADMIN)

            validate_error(response, "ERR_INVALID_REQUEST", 422)
            assert_error_envelope(response)

    def test_the_optional_credit_inputs_default_to_tier_two_and_no_certification(self, api):
        """PRD §3.1: "Two further inputs are optional: `credit_rating_tier`, an internal
        credit tier from 1 through 4 where 1 is strongest, defaulting to 2; and
        `cdfi_certified`, a boolean stating whether the institution holds an active CDFI
        certification, defaulting to false."

        Design: Corner/entities/member_bank_credit_rating_tier_defaults_to_two
        """
        env = applicant_member(api, credit_rating_tier=None)

        member = env.refresh()

        assert_fields(member, credit_rating_tier=2, cdfi_certified=False)
        assert member["delivery_required"] is False
        assert_capacity_breakdown(env.capacity(), tier_cap_bps=9_000)

    def test_the_membership_requirement_is_clamped_into_its_band(self, api):
        """PRD §3.1: "That raw figure is then clamped into a band: if it falls below
        1,000,000 cents (ten thousand dollars) it is raised to 1,000,000 cents, and if it
        exceeds 250,000,000 cents (two and a half million dollars) it is lowered to
        250,000,000 cents."

        Design: Corner/entities/member_bank_required_membership_stock_computed_at_minimum_floor
        """
        pin_clock(api)

        tiny = get_success_data(
            api.create_member_bank(
                member_bank_payload(
                    name="Tiny Mutual",
                    charter_type="CREDIT_UNION",
                    total_assets_cents=100_000_000,
                    credit_rating_tier=3,
                ),
                ADMIN,
            )
        )
        huge = get_success_data(
            api.create_member_bank(
                member_bank_payload(
                    name="Colossal Trust", total_assets_cents=300_000_000_000
                ),
                ADMIN,
            )
        )

        assert_stock_position(
            tiny,
            required_membership_stock_cents=1_000_000,
            required_total_stock_cents=1_000_000,
            stock_deficiency_cents=1_000_000,
        )
        assert_stock_position(
            huge,
            required_membership_stock_cents=250_000_000,
            required_total_stock_cents=250_000_000,
            stock_deficiency_cents=250_000_000,
        )


class TestCollateralAssetContract:
    """A pledged asset's defaults, its server-owned fields and its listing."""

    def test_a_minimal_pledge_takes_every_optional_default(self, api):
        """PRD §3.2: "`ltv_bps`, the loan-to-value in basis points where 8,000 means
        80.00 percent, permitted from 0 through 20,000 and defaulting to 0 for
        securities; `delinquency_days`, a non-negative day count that defaults to 0;
        `documentation_status`, one of `COMPLETE`, `EXCEPTION` or `MISSING`, defaulting
        to `COMPLETE`; and `custody_location`, one of `MEMBER_VAULT`,
        `THIRD_PARTY_CUSTODIAN` or `FHLB_SAFEKEEPING`, defaulting to `MEMBER_VAULT`."

        Design: Corner/entities/collateral_asset_documentation_and_custody_defaults_applied
        """
        env = pledging_member(api)

        response = api.create_collateral_asset(
            collateral_asset_payload(
                env.member_id, ltv_bps=None, delinquency_days=None
            ),
            env.treasury,
        )

        asset = assert_envelope(response, 201)
        assert_fields(
            asset,
            documentation_status="COMPLETE",
            custody_location="MEMBER_VAULT",
            ltv_bps=0,
            delinquency_days=0,
            status="UNDER_REVIEW",
            ineligibility_reason="NONE",
        )
        assert_asset_valuation(asset, 0, 0)
        assert_asset_valuation(review_asset(api, asset["id"]), 7_800, 15_600_000)

    def test_the_server_owns_status_version_and_lendable_value(self, api):
        """PRD §3.2: "A newly pledged asset starts with `status` `UNDER_REVIEW`,
        `ineligibility_reason` `NONE`, `discount_factor_bps` 0, `lendable_value_cents` 0
        and `replaces_asset_id` null; its `collateral_basis_cents` and
        `effective_listing_mode` are computed at once."

        Design: Corner/entities/collateral_asset_system_fields_generated_and_status_input_ignored
        """
        env = pledging_member(api)

        asset = validate_success(
            api.create_collateral_asset(
                collateral_asset_payload(
                    env.member_id,
                    status="ELIGIBLE",
                    version=99,
                    lendable_value_cents=99_999_999,
                ),
                env.treasury,
            ),
            201,
        )

        assert_fields(
            asset,
            status="UNDER_REVIEW",
            version=1,
            lendable_value_cents=0,
            discount_factor_bps=0,
            replaces_asset_id=None,
            collateral_basis_cents=20_000_000,
            effective_listing_mode="BLANKET",
        )
        assert is_valid_uuid(asset["id"])
        assert asset["created_at"] == "2026-08-01T00:00:00.000Z"
        assert env.refresh()["lendable_collateral_value_cents"] == 0

    def test_an_out_of_enum_or_out_of_range_pledge_is_refused(self, api):
        """PRD §3.2: "The eight collateral classes are `SF_MORTGAGE`, `MULTIFAMILY`,
        `CRE`, `HELOC`, `SMALL_BUSINESS`, `CDFI_COMMUNITY`, `AGENCY_MBS` and
        `TREASURY`."

        Design: Corner/entities/collateral_asset_invalid_asset_class_enum_rejected
        """
        env = pledging_member(api)
        overrides = (
            {"asset_class": "AUTO_LOAN"},
            {"market_value_cents": 0},
            {"ltv_bps": 20_001},
        )

        for override in overrides:
            response = api.create_collateral_asset(
                collateral_asset_payload(env.member_id, **override), env.treasury
            )

            validate_error(response, "ERR_INVALID_REQUEST", 422)

        assert_total_count(
            api.list_collateral_assets(CREDIT_ONE, {"member_bank_id": env.member_id}), 0
        )

    def test_the_asset_list_pages_and_counts_the_filtered_set(self, api):
        """PRD §2.3: "Every list response reports `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope. `total_count` counts all
        records matching the filters before pagination is applied; `has_more` is true
        when records remain beyond the current page."

        Design: Corner/entities/collateral_asset_listing_paginates_with_total_count_and_has_more
        """
        env = pledging_member(api)
        pledge_asset(api, env.member_id)
        add_heloc(api, env, review=False)
        add_cre(api, env, review=False)
        scope = {"member_bank_id": env.member_id}

        first_page = assert_page(
            api.list_collateral_assets(CREDIT_ONE, dict(scope, limit=2, offset=0)),
            2,
            0,
            3,
            True,
        )
        second_page = assert_page(
            api.list_collateral_assets(CREDIT_ONE, dict(scope, limit=2, offset=2)),
            2,
            2,
            3,
            False,
        )
        unpaged = assert_page(
            api.list_collateral_assets(CREDIT_ONE, scope), 10, 0, 3, False
        )

        assert len(first_page) == 2
        assert len(second_page) == 1
        assert len(unpaged) == 3
        assert_total_count(
            api.list_collateral_assets(
                CREDIT_ONE, dict(scope, asset_class="HELOC")
            ),
            1,
        )


class TestReferenceDataAndJunctionRows:
    """Intra-record ranges, the par-multiple rule, and the subscription junction."""

    def test_a_product_whose_term_range_inverts_is_refused(self, api):
        """PRD §3.5: "A product carries a unique `product_code`; a `structure` of
        `FIXED_TERM`, `ADJUSTABLE`, `AMORTIZING`, `CALLABLE` or `PUTABLE`; a
        `min_term_days` of at least 1 and a `max_term_days` no smaller than
        `min_term_days`; a strictly positive contractual coupon `rate_bps`; ... an
        `activity_stock_pct_bps` between 0 and 2,000 expressing the activity-based stock
        obligation as basis points of gross principal; and a strictly positive
        `min_principal_cents`."

        Design: Corner/entities/advance_product_max_term_below_min_term_rejected
        """
        pin_clock(api)
        overrides = (
            {"min_term_days": 400, "max_term_days": 90},
            {"activity_stock_pct_bps": 2_001},
            {"rate_bps": 0},
            {"min_principal_cents": 0},
        )

        for override in overrides:
            response = api.create_advance_product(
                advance_product_payload(product_code="BAD-1", **override), ADMIN
            )

            validate_error(response, "ERR_INVALID_REQUEST", 422)

    def test_a_subscription_off_the_par_multiple_gets_its_own_error_id(self, api):
        """PRD §2.5: "At this same tier, a stock subscription whose `amount_cents` is not
        an exact multiple of the 10,000-cent par value is rejected with the more specific
        `ERR_STOCK_NOT_PAR_MULTIPLE` (422)."

        Design: Corner/entities/stock_subscription_amount_not_par_multiple_rejected
        """
        env = applicant_member(api)

        refused = api.create_stock_subscription(
            stock_subscription_payload(env.member_id, 9_605_000), CREDIT_ONE
        )

        validate_error(refused, "ERR_STOCK_NOT_PAR_MULTIPLE", 422)
        assert_total_count(api.list_stock_subscriptions(CREDIT_ONE), 0)
        assert env.refresh()["stock_held_cents"] == 0

    def test_a_non_positive_amount_falls_back_to_the_generic_shape_error(self, api):
        """PRD §3.1: "The amount must be strictly positive and an exact multiple of the
        10,000-cent par value; a non-multiple is rejected with
        `ERR_STOCK_NOT_PAR_MULTIPLE`."

        Design: Corner/entities/stock_subscription_amount_not_par_multiple_rejected
        """
        env = applicant_member(api)

        zero = api.create_stock_subscription(
            stock_subscription_payload(env.member_id, 0), CREDIT_ONE
        )
        accepted = api.create_stock_subscription(
            stock_subscription_payload(env.member_id, 9_600_000), CREDIT_ONE
        )

        validate_error(zero, "ERR_INVALID_REQUEST", 422)
        subscription = validate_success(accepted, 201)
        assert_fields(subscription, amount_cents=9_600_000, status="SUBSCRIBED")
        assert_shares(subscription)

    def test_the_activity_subscription_joins_its_member_and_its_advance(self, api):
        """PRD §3.6: "When `fund_stock_from_advance` is true, an `ACTIVITY` subscription
        of `amount_cents` equal to `activity_stock_cents` is created with its `advance_id`
        pointing at this advance and is immediately `ISSUED` in the same request — its
        `SUBSCRIBED` state is never observable on this path."

        Design: Corner/entities/stock_subscription_joins_member_and_advance_as_junction_row
        """
        env = member_with_eligible_sf(api)
        product = create_product(api)
        advance = funded_advance(
            api,
            env,
            product["id"],
            term_days=30,
            requested_net_proceeds_cents=950_000,
            fund_stock_from_advance=True,
        )

        rows = assert_total_count(api.list_stock_subscriptions(CREDIT_ONE), 2)

        activity = [row for row in rows if row["subscription_type"] == "ACTIVITY"]
        membership = [row for row in rows if row["subscription_type"] == "MEMBERSHIP"]
        assert len(activity) == 1
        assert len(membership) == 1
        assert_fields(
            activity[0],
            member_bank_id=env.member_id,
            advance_id=advance["id"],
            amount_cents=50_000,
            status="ISSUED",
        )
        assert_fields(
            membership[0],
            member_bank_id=env.member_id,
            advance_id=None,
            amount_cents=9_600_000,
            status="ISSUED",
        )
        assert env.refresh()["stock_held_cents"] == 9_650_000


class TestParentAndForeignKeyResolution:
    """Unknown path ids, unknown parents and a body reference outside the aggregate."""

    def test_an_unknown_advance_path_id_is_a_typed_404(self, api):
        """PRD §2.5: "**Path resource existence.** Path identifiers are resolved strictly
        left to right, and the first one that does not resolve determines the error. ...
        `advance_id` gives `ERR_ADVANCE_NOT_FOUND`."

        Design: Corner/entities/advance_not_found_returns_404
        """
        pin_clock(api)

        response = api.get_advance(UNKNOWN_ADVANCE_ID, CREDIT_ONE)

        validate_error(response, "ERR_ADVANCE_NOT_FOUND", 404)
        error = assert_error_envelope(response)
        assert error["message"]

    def test_a_child_create_under_an_unknown_parent_reports_the_parent(self, api):
        """PRD §2.5: "`collateral_asset_id` gives `ERR_COLLATERAL_ASSET_NOT_FOUND`."

        Design: Corner/entities/safekeeping_receipt_parent_asset_not_found
        """
        pin_clock(api)

        response = api.create_safekeeping_receipt(
            UNKNOWN_COLLATERAL_ASSET_ID, safekeeping_receipt_payload(), CUSTODIAN
        )

        validate_error(response, "ERR_COLLATERAL_ASSET_NOT_FOUND", 404)
        assert_total_count(api.list_safekeeping_receipts(CUSTODIAN), 0)

    def test_a_finding_may_not_reach_across_into_another_members_asset(self, api):
        """PRD §3.8: "The sampled asset must belong to the same member as the review; an
        asset owned by a different member is rejected with `ERR_ASSET_MEMBER_MISMATCH`."

        Design: Corner/entities/review_finding_against_other_members_asset_rejected
        """
        env = pledging_member(api)
        pledge_asset(api, env.member_id)
        other = second_member(api)
        execute_pledge_agreement(api, other.member_id)
        foreign_asset = pledge_asset(api, other.member_id)
        review = review_in_field_work(api, env)

        response = api.create_review_finding(
            review["id"], review_finding_payload(foreign_asset["id"]), AUDITOR
        )

        validate_error(response, "ERR_ASSET_MEMBER_MISMATCH", 409)
        assert_total_count(
            api.list_review_findings(
                AUDITOR, {"collateral_verification_review_id": review["id"]}
            ),
            0,
        )

    def test_an_unresolvable_body_reference_precedes_the_mismatch_tier(self, api):
        """PRD §2.5: "**Body foreign keys.** ... an unresolvable `collateral_asset_id` in
        a finding body gives `ERR_COLLATERAL_ASSET_NOT_FOUND` (404)."

        Design: Corner/entities/review_finding_against_other_members_asset_rejected
        """
        env = pledging_member(api)
        pledge_asset(api, env.member_id)
        review = review_in_field_work(api, env)

        response = api.create_review_finding(
            review["id"],
            review_finding_payload(UNKNOWN_COLLATERAL_ASSET_ID),
            AUDITOR,
        )

        validate_error(response, "ERR_COLLATERAL_ASSET_NOT_FOUND", 404)
        assert_total_count(
            api.list_review_findings(
                AUDITOR, {"collateral_verification_review_id": review["id"]}
            ),
            0,
        )
