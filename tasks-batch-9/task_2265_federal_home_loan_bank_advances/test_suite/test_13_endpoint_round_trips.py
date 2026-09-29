"""Endpoints taken one at a time: a catalogue round trip, a pure computed read, the
exception fork of a custody confirmation, a substitution's three-entity link, and the
condition patch that reprices a member without touching its collateral."""
from test_helpers import *  # noqa: F401,F403


class TestAdvanceProductCatalogue:
    """Reference data with no lifecycle: what goes in must come back out."""

    def test_a_product_round_trips_every_declared_field(self, api):
        """PRD §3.5: "Four flags are optional: `flat_prepayment_fee_bps`, defaulting to 0
        and read only when the method is `FLAT_PCT`; `symmetric_credit_enabled`, defaulting
        to false, which permits a symmetric-method advance to settle at a negative (credit)
        fee; `requires_collateral_delivery`, defaulting to false, which forces delivered
        files at funding; and `community_program_flag`, defaulting to false, which restricts
        the product to community lending program use."

        Design: Corner/endpoints/advance_product_create_then_read_round_trip
        """
        pin_clock(api)

        response = api.create_advance_product(
            advance_product_payload(
                product_code="SYM-500",
                structure="CALLABLE",
                min_term_days=90,
                max_term_days=3_650,
                rate_bps=500,
                prepayment_fee_method="SYMMETRIC_MARKET_VALUE",
                activity_stock_pct_bps=400,
                min_principal_cents=2_500_000,
                symmetric_credit_enabled=True,
            ),
            ADMIN,
        )

        product = assert_envelope(response, 201)
        assert_common_fields(product)
        assert_fields(
            product,
            product_code="SYM-500",
            structure="CALLABLE",
            min_term_days=90,
            max_term_days=3_650,
            rate_bps=500,
            prepayment_fee_method="SYMMETRIC_MARKET_VALUE",
            activity_stock_pct_bps=400,
            min_principal_cents=2_500_000,
            flat_prepayment_fee_bps=0,
            version=1,
        )
        assert product["symmetric_credit_enabled"] is True
        assert product["requires_collateral_delivery"] is False
        assert product["community_program_flag"] is False
        stored = assert_envelope(api.get_advance_product(product["id"], ADMIN))
        assert stored == product


class TestBorrowingCapacityRead:
    """A pure read that persists nothing and defaults to the conservative variant."""

    def test_the_default_variant_is_certified_and_ignores_unreviewed_collateral(self, api):
        """PRD §3.5: "It accepts an optional `variant` query parameter of `CERTIFIED` or
        `PROVISIONAL`, defaulting to `CERTIFIED`, and returns an inline breakdown rather
        than a stored entity: the `variant` applied, the `lendable_collateral_value_cents`
        used, the `tier_cap_bps` read from the member's tier, the `statutory_cap_cents`, the
        `capacity_base_cents` after the minimum of the two capped terms, the
        `outstanding_advances_cents` deducted, the `commitments_cents` deducted, and the
        resulting `borrowing_capacity_cents`."

        Design: Corner/endpoints/borrowing_capacity_read_defaults_to_certified_variant
        """
        env = applicant_member(api)
        execute_pledge_agreement(api, env.member_id)
        asset = pledge_asset(api, env.member_id)

        default = env.capacity(headers=env.treasury)
        provisional = env.capacity("PROVISIONAL", headers=env.treasury)

        assert read_asset(api, asset["id"])["status"] == "UNDER_REVIEW"
        assert_capacity_breakdown(
            default,
            variant="CERTIFIED",
            lendable_collateral_value_cents=0,
            tier_cap_bps=10_000,
            statutory_cap_cents=2_400_000_000,
            capacity_base_cents=0,
            outstanding_advances_cents=0,
            commitments_cents=0,
            borrowing_capacity_cents=0,
        )
        assert_capacity_breakdown(
            provisional,
            variant="PROVISIONAL",
            lendable_collateral_value_cents=7_800_000,
            tier_cap_bps=10_000,
            statutory_cap_cents=2_400_000_000,
            capacity_base_cents=7_800_000,
            borrowing_capacity_cents=7_800_000,
        )


class TestSafekeepingExceptionBranch:
    """The confirmation endpoint forks on its outcome, and this is the losing fork."""

    def _asset_with_a_botched_delivery(self, api):
        env = member_with_eligible_sf(api)
        receipt = book_receipt(
            api,
            env.assets["sf"]["id"],
            file_count=12,
            delivery_date=CLOCK_START,
            return_date="2026-09-30T00:00:00Z",
        )
        response = api.confirm_safekeeping_receipt(
            receipt["id"],
            confirm_receipt_payload(
                "EXCEPTION", "note endorsement missing for 3 of 12 files"
            ),
            CUSTODIAN,
        )
        return env, response

    def test_a_botched_delivery_pushes_the_asset_back_to_review(self, api):
        """PRD §3.3: "With `outcome` `EXCEPTION`, the receipt moves `PENDING_DELIVERY →
        EXCEPTION` and the supplied `exception_note` is recorded on it. The parent asset's
        `documentation_status` is set to `EXCEPTION` and the asset itself is pushed back to
        `UNDER_REVIEW`, which zeroes its `lendable_value_cents` and
        `discount_factor_bps`."

        Design: Corner/endpoints/safekeeping_confirm_exception_returns_asset_to_under_review
        """
        env, response = self._asset_with_a_botched_delivery(api)

        receipt = assert_envelope(response)
        assert_fields(
            receipt,
            status="EXCEPTION",
            exception_note="note endorsement missing for 3 of 12 files",
            file_count=12,
        )
        asset = read_asset(api, env.assets["sf"]["id"])
        assert_fields(
            asset,
            documentation_status="EXCEPTION",
            status="UNDER_REVIEW",
            custody_location="MEMBER_VAULT",
        )
        assert_asset_valuation(asset, 0, 0)
        assert_fields(
            env.refresh(),
            lendable_collateral_value_cents=0,
            borrowing_capacity_cents=0,
        )

    def test_the_re_review_prices_in_the_documentation_exception(self, api):
        """PRD §3.4: "If `documentation_status` is `EXCEPTION`, subtract 700 basis
        points."

        Design: Corner/endpoints/safekeeping_confirm_exception_returns_asset_to_under_review
        """
        env, response = self._asset_with_a_botched_delivery(api)
        validate_success(response)

        reviewed = validate_success(
            api.review_asset_eligibility(env.assets["sf"]["id"], CREDIT_ONE, {})
        )

        assert reviewed["status"] == "ELIGIBLE"
        assert_asset_valuation(reviewed, 7_100, 14_200_000)
        assert env.refresh()["lendable_collateral_value_cents"] == 14_200_000


class TestPledgeSubstitution:
    """One call touches three entities: the replacement, the outgoing asset, its files."""

    def _delivered_heloc_then_substituted(self, api):
        env = pledging_member(api)
        heloc = add_heloc(api, env)
        receipt = book_receipt(
            api,
            heloc["id"],
            file_count=4,
            delivery_date=CLOCK_START,
            return_date="2026-09-30T00:00:00Z",
        )
        confirm_receipt(api, receipt["id"], "RECEIVED")
        before = read_asset(api, heloc["id"])
        response = api.substitute_collateral_asset(
            heloc["id"], substitution_payload(env.version), env.treasury
        )
        return env, heloc, receipt, before, response

    def test_the_replacement_back_references_the_asset_it_displaced(self, api):
        """PRD §3.9: "A successful substitution creates a replacement asset from the request
        body with `replaces_asset_id` set to the `id` of the outgoing asset and `status`
        `UNDER_REVIEW`; the replacement is what comes back in the response."

        Design: Corner/endpoints/substitution_links_replacement_and_returns_the_outgoing_files
        """
        env, heloc, _receipt, before, response = self._delivered_heloc_then_substituted(api)

        replacement = assert_envelope(response, 201)
        assert_asset_valuation(before, 6_400, 640_000)
        assert replacement["id"] != heloc["id"]
        assert_fields(
            replacement,
            replaces_asset_id=heloc["id"],
            status="UNDER_REVIEW",
            asset_class="SF_MORTGAGE",
            collateral_basis_cents=20_000_000,
        )
        assert_asset_valuation(replacement, 0, 0)
        outgoing = read_asset(api, heloc["id"])
        assert outgoing["status"] == "SUBSTITUTED"
        assert_asset_valuation(outgoing, 0, 0)
        assert env.refresh()["lendable_collateral_value_cents"] == 0
        assert_asset_valuation(review_asset(api, replacement["id"]), 7_800, 15_600_000)

    def test_the_outgoing_files_are_returned_and_the_chain_is_listable(self, api):
        """PRD §3.9: "Every safekeeping receipt of the outgoing asset whose `status` is
        `RECEIVED` or `EXCEPTION` moves to `RETURNED`, after which no further
        custody-window conflict is raised against it."

        Design: Corner/endpoints/substitution_links_replacement_and_returns_the_outgoing_files
        """
        _env, heloc, receipt, _before, response = self._delivered_heloc_then_substituted(api)
        replacement = validate_success(response, 201)

        returned = assert_total_count(
            api.list_safekeeping_receipts(
                CUSTODIAN, {"collateral_asset_id": heloc["id"]}
            ),
            1,
        )
        chain = assert_total_count(
            api.list_collateral_assets(CREDIT_ONE, {"replaces_asset_id": heloc["id"]}), 1
        )

        assert returned[0]["id"] == receipt["id"]
        assert returned[0]["status"] == "RETURNED"
        assert chain[0]["id"] == replacement["id"]


class TestMemberConditionPatch:
    """One supplied field, two derivations, and not one asset moved."""

    def test_a_tier_downgrade_forces_delivery_and_halves_the_cap(self, api):
        """PRD §3.1: "A supplied `credit_rating_tier` re-derives `delivery_required`, then
        re-runs the capacity and posture computations — a tier downgrade to 4 therefore
        forces delivery and can shrink capacity in the same request."

        Design: Corner/endpoints/condition_patch_to_tier_four_forces_delivery_and_reprices_capacity
        """
        env = member_with_eligible_sf(api)

        member = assert_envelope(
            api.patch_member_bank_condition(
                env.member_id, condition_payload(credit_rating_tier=4), CREDIT_ONE
            )
        )

        assert_fields(
            member,
            credit_rating_tier=4,
            lendable_collateral_value_cents=15_600_000,
            borrowing_capacity_cents=7_800_000,
            collateral_posture="OPEN",
            membership_status="ACTIVE",
        )
        assert member["delivery_required"] is True
        assert member["community_lending_eligible"] is False
        asset = read_asset(api, env.assets["sf"]["id"])
        assert asset["effective_listing_mode"] == "BLANKET"
        assert_asset_valuation(asset, 7_800, 15_600_000)
