"""Money and selection arithmetic: the deposit's two-step rounding, the premium's
clamps and flat tiers, the ledger's accumulation, and the filters that pick a winner,
a backup and a risk score."""

from test_helpers import (
    CLOCK_CONTRACT,
    CLOCK_EVENT_OPEN,
    CLOCK_LOT_CLOSE,
    CLOCK_SETUP,
    COUNTY_PRIMARY,
    COUNTY_SECONDARY,
    OPS_CONTRACT,
    TEST_USERS,
    add_lot,
    api_client,
    assert_forfeiture_conserved,
    assert_settlement_conserved,
    assert_timestamp_equals,
    close_lot,
    create_event,
    create_exclusion,
    create_offer,
    disclosed_asset,
    eligibility_assessment,
    execute_contract,
    expected_buyer_premium,
    expected_doc_fee,
    expected_forfeiture_split,
    expected_platform_fee,
    expected_required_deposit,
    expected_total_due,
    fallen_out_contract,
    fund,
    funded_bidder,
    funded_bidders,
    lift_exclusion,
    list_holds,
    list_lot_contracts,
    make_auction_ops_headers,
    open_event,
    place_bid,
    read_bid,
    read_bidder,
    read_event,
    read_listing,
    read_lot,
    read_seller,
    register_bidder,
    scheduled_lot,
    second_chance_offer_payload,
    set_clock,
    settlement_preview,
    sold_lot,
    validate_error,
    validate_paginated,
    verify_bidder,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["auction_ops_headers"]

WINDOW_START = "2026-09-15T17:00:00Z"
WINDOW_END = "2026-09-15T18:00:00Z"
EVENT_START = "2026-09-15T17:00:00Z"
EVENT_END = "2026-09-15T19:00:00Z"


class TestDepositArithmetic:
    def test_the_deposit_is_five_percent_of_the_opening_times_the_occupancy_multiplier(self):
        """The basis is the opening bid and nothing else — not the 40000000 estimate and
        not the 30000000 reserve — and the tenant multiplier lifts 1000000 to 1250000.

        PRD: "The multiplier is 1.50 for `OWNER_OCCUPIED`, 1.25 for `TENANT_OCCUPIED`, 1.00
        for `VACANT`, and 1.50 for `UNKNOWN` — an unknown occupancy is priced as
        conservatively as an owner-occupied one, because the platform cannot rule out an
        eviction."

        Design: Corner/calculations/required_deposit_correct_result_for_tenant_occupied_lot
        """
        set_clock(CLOCK_SETUP)
        bundle = disclosed_asset(
            occupancy_status="TENANT_OCCUPIED",
            title_condition="CLEAR",
            org_name="Correct Result Bank",
            seller_type="BANK",
            contact_email="c@correct.example",
            settlement_account_ref="ACH-CORR",
            street_address="1 Correct Rd",
            city="Oakland",
            estimated_value_cents=40000000,
        )
        assert bundle.listing["eviction_risk_tier"] == "HIGH"

        event = create_event(
            title="Correct Result Event", starts_at=EVENT_START, ends_at=EVENT_END
        )
        lot = add_lot(
            event["id"],
            bundle.listing_id,
            lot_window_start_at=WINDOW_START,
            lot_window_end_at=WINDOW_END,
            opening_bid_cents=20000000,
            reserve_price_cents=30000000,
        )

        assert lot["required_deposit_cents"] == 1250000
        assert lot["required_deposit_cents"] == expected_required_deposit(
            20000000, "TENANT_OCCUPIED"
        )
        assert lot["required_deposit_cents"] != 1000000
        assert lot["required_deposit_cents"] != 1500000
        assert lot["min_increment_cents"] == 500000

    def test_the_percentage_and_the_multiplier_each_round_on_their_own(self):
        """Rounding twice in the pinned order gives 1500002, one cent more than the
        1500001 a single rounding of the whole product would produce.

        PRD: "Then that base is multiplied by an occupancy multiplier read from the asset's
        `occupancy_status` as it stands at the moment of lot creation, and the product is
        rounded half up to whole cents to give `required_deposit_cents`."

        Design: Corner/calculations/required_deposit_double_rounds_percentage_then_multiplier
        """
        set_clock(CLOCK_SETUP)
        bundle = disclosed_asset(
            occupancy_status="OWNER_OCCUPIED",
            title_condition="JUNIOR_LIENS",
            org_name="Double Round Bank",
            seller_type="BANK",
            contact_email="d@double.example",
            settlement_account_ref="ACH-DBLR",
            street_address="1 Double Round Rd",
            city="Oakland",
            estimated_value_cents=30000000,
        )
        assert bundle.listing["eviction_risk_tier"] == "MEDIUM"

        event = create_event(
            title="Double Round Event", starts_at=EVENT_START, ends_at=EVENT_END
        )
        lot = add_lot(
            event["id"],
            bundle.listing_id,
            lot_window_start_at=WINDOW_START,
            lot_window_end_at=WINDOW_END,
            opening_bid_cents=20000010,
            reserve_price_cents=20000010,
        )

        assert lot["required_deposit_cents"] == 1500002
        assert lot["required_deposit_cents"] != 1500001
        assert lot["required_deposit_cents"] != 1500000

    def test_the_deposit_floor_lifts_small_lots_without_pulling_large_ones_down(self):
        """Three lots straddle the floor in one event: 499999 is lifted to 500000, an
        exact 500000 stays, and 500001 is kept, because the floor is a maximum.

        PRD: "First a base is taken as the larger of a floor of 500000 cents — five
        thousand dollars — and five percent of `opening_bid_cents` rounded half up to whole
        cents."

        Design: Corner/calculations/deposit_floor_boundary_at_exactly_five_hundred_thousand
        """
        set_clock(CLOCK_SETUP)
        first = disclosed_asset(
            org_name="Floor Boundary Bank",
            seller_type="BANK",
            contact_email="f@floor.example",
            settlement_account_ref="ACH-FLOOR",
            street_address="1 Floor Rd",
            city="Oakland",
            estimated_value_cents=20000000,
        )
        second = disclosed_asset(
            seller=first.seller, street_address="2 Floor Rd", city="Oakland",
            estimated_value_cents=20000000,
        )
        third = disclosed_asset(
            seller=first.seller, street_address="3 Floor Rd", city="Oakland",
            estimated_value_cents=20000000,
        )
        event = create_event(
            title="Floor Boundary Event", starts_at=EVENT_START, ends_at=EVENT_END
        )

        lot_one = add_lot(
            event["id"], first.listing_id, lot_number=1,
            lot_window_start_at=WINDOW_START, lot_window_end_at=WINDOW_END,
            opening_bid_cents=9999980, reserve_price_cents=9999980,
        )
        lot_two = add_lot(
            event["id"], second.listing_id, lot_number=2,
            lot_window_start_at=WINDOW_START, lot_window_end_at=WINDOW_END,
            opening_bid_cents=10000000, reserve_price_cents=10000000,
        )
        lot_three = add_lot(
            event["id"], third.listing_id, lot_number=3,
            lot_window_start_at=WINDOW_START, lot_window_end_at=WINDOW_END,
            opening_bid_cents=10000020, reserve_price_cents=10000020,
        )

        assert lot_one["required_deposit_cents"] == 500000
        assert lot_two["required_deposit_cents"] == 500000
        assert lot_three["required_deposit_cents"] == 500001

        refreshed = read_event(event["id"])
        assert refreshed["lot_count"] == 3
        assert refreshed["version"] == 4


class TestBuyerPremiumShape:
    def test_the_premium_clamps_bite_after_the_surcharges_at_both_ends(self):
        """A 200000 raw premium is lifted to the 250000 floor and a 7400000 raw premium —
        600 plus 150 plus 175 basis points — is cut to the 6000000 ceiling.

        PRD: "The rounded figure is finally clamped: it is raised to a floor of 250000
        cents (two thousand five hundred dollars) if it falls below that, and lowered to a
        ceiling of 6000000 cents (sixty thousand dollars) if it exceeds that."

        Design: Corner/calculations/premium_floor_and_cap_constants_clamp_both_ends
        """
        set_clock(CLOCK_SETUP)
        small = disclosed_asset(
            occupancy_status="VACANT",
            title_condition="CLEAR",
            org_name="Clamp Both Ends Bank",
            seller_type="BANK",
            contact_email="c@clamp.example",
            settlement_account_ref="ACH-CLMP",
            street_address="1 Clamp Rd",
            city="Oakland",
            estimated_value_cents=3000000,
        )
        large = disclosed_asset(
            seller=small.seller,
            occupancy_status="OWNER_OCCUPIED",
            title_condition="CLOUDED",
            street_address="2 Clamp Rd",
            city="Oakland",
            estimated_value_cents=90000000,
        )
        assert small.listing["eviction_risk_tier"] == "LOW"
        assert large.listing["eviction_risk_tier"] == "HIGH"

        event = create_event(title="Clamp Event", starts_at=EVENT_START, ends_at=EVENT_END)
        lot_a = add_lot(
            event["id"], small.listing_id, lot_number=1,
            lot_window_start_at=WINDOW_START, lot_window_end_at=WINDOW_END,
            opening_bid_cents=2000000, reserve_price_cents=2000000,
        )
        lot_b = add_lot(
            event["id"], large.listing_id, lot_number=2,
            lot_window_start_at=WINDOW_START, lot_window_end_at=WINDOW_END,
            opening_bid_cents=80000000, reserve_price_cents=80000000,
        )
        assert lot_a["required_deposit_cents"] == 500000
        assert lot_b["required_deposit_cents"] == 6000000

        bidder = funded_bidder(
            6500000, legal_name="Clamp Capital LLC", email="bid@clamp.example"
        )
        set_clock(CLOCK_EVENT_OPEN)
        open_event(event["id"])
        place_bid(lot_a["id"], bidder["id"], 2000000)
        place_bid(lot_b["id"], bidder["id"], 80000000)

        set_clock(CLOCK_LOT_CLOSE)
        closed_a = close_lot(lot_a["id"])
        closed_b = close_lot(lot_b["id"])

        assert closed_a["provisional_buyer_premium_cents"] == 250000
        assert closed_a["provisional_buyer_premium_cents"] != 200000
        assert closed_b["provisional_buyer_premium_cents"] == 6000000
        assert closed_b["provisional_buyer_premium_cents"] != 7400000
        assert closed_b["provisional_buyer_premium_cents"] != 4800000
        assert closed_b["provisional_buyer_premium_cents"] == expected_buyer_premium(
            80000000, "OWNER_OCCUPIED", "CLOUDED"
        )

        wallet = read_bidder(bidder["id"])
        assert wallet["deposit_funded_cents"] == 6500000
        assert wallet["deposit_available_cents"] == 0
        assert read_event(event["id"])["event_status"] == "CLOSED"

    def test_the_premium_rounds_half_up_on_an_exact_half_cent(self):
        """875 basis points on a hammer of 20000040 lands on exactly 1750003.5 raw cents,
        which half-up resolves to 1750004 where truncation and half-even give 1750003.

        PRD: "The price is then multiplied by that single combined rate and the product is
        rounded half up to whole cents **exactly once**."

        Design: Corner/calculations/premium_rounds_half_up_at_the_exact_half_cent
        """
        scenario = scheduled_lot(
            occupancy_status="VACANT",
            title_condition="JUNIOR_LIENS",
            org_name="Half Cent Bank",
            seller_type="BANK",
            contact_email="h@halfcent.example",
            settlement_account_ref="ACH-HALF",
            street_address="1 Half Cent Rd",
            city="Oakland",
            estimated_value_cents=30000000,
            event_title="Half Cent Event",
            starts_at=EVENT_START,
            ends_at=EVENT_END,
            lot_window_start_at=WINDOW_START,
            lot_window_end_at=WINDOW_END,
            opening_bid_cents=20000040,
            reserve_price_cents=20000040,
        )
        assert read_listing(scenario.listing_id)["eviction_risk_tier"] == "MEDIUM"
        assert scenario.lot["required_deposit_cents"] == 1000002

        bidder = funded_bidder(
            1100000, legal_name="Half Cent Partners LLC", email="bid@halfcent.example"
        )
        set_clock(CLOCK_EVENT_OPEN)
        open_event(scenario.event_id)
        place_bid(scenario.lot_id, bidder["id"], 20000040)

        set_clock(CLOCK_LOT_CLOSE)
        closed = close_lot(scenario.lot_id)

        assert closed["hammer_price_cents"] == 20000040
        assert closed["provisional_buyer_premium_cents"] == 1750004
        assert closed["provisional_buyer_premium_cents"] != 1750003
        assert closed["provisional_buyer_premium_cents"] == expected_buyer_premium(
            20000040, "VACANT", "JUNIOR_LIENS"
        )
        assert read_bidder(bidder["id"])["deposit_available_cents"] == 99998

    def test_one_cent_more_hammer_can_cost_two_hundred_thousand_cents_less_premium(self):
        """The tier rate is flat over the whole price rather than marginal, so a 9999999
        hammer pays 1000000 while a 10000000 hammer pays only 800000.

        PRD: "First a tier rate keyed on the price being premiumed: 0.10 when that price is
        strictly below 10000000 cents (one hundred thousand dollars), 0.08 when it is at
        least 10000000 cents but strictly below 50000000 cents (five hundred thousand
        dollars), and 0.06 at or above 50000000 cents."

        Design: Corner/calculations/premium_tier_boundary_makes_a_higher_hammer_cheaper
        """
        set_clock(CLOCK_SETUP)
        below = disclosed_asset(
            org_name="Tier Edge Bank",
            seller_type="BANK",
            contact_email="t@tieredge.example",
            settlement_account_ref="ACH-TIER",
            street_address="1 Tier Rd",
            city="Oakland",
            estimated_value_cents=15000000,
        )
        at_floor = disclosed_asset(
            seller=below.seller, street_address="2 Tier Rd", city="Oakland",
            estimated_value_cents=15000000,
        )
        event = create_event(title="Tier Edge Event", starts_at=EVENT_START, ends_at=EVENT_END)
        lot_a = add_lot(
            event["id"], below.listing_id, lot_number=1,
            lot_window_start_at=WINDOW_START, lot_window_end_at=WINDOW_END,
            opening_bid_cents=9999999, reserve_price_cents=9999999,
        )
        lot_b = add_lot(
            event["id"], at_floor.listing_id, lot_number=2,
            lot_window_start_at=WINDOW_START, lot_window_end_at=WINDOW_END,
            opening_bid_cents=10000000, reserve_price_cents=10000000,
        )
        assert lot_a["required_deposit_cents"] == 500000
        assert lot_b["required_deposit_cents"] == 500000

        bidder = funded_bidder(
            1000000, legal_name="Tier Edge Partners LLC", email="bid@tieredge.example"
        )
        set_clock(CLOCK_EVENT_OPEN)
        open_event(event["id"])
        place_bid(lot_a["id"], bidder["id"], 9999999)
        place_bid(lot_b["id"], bidder["id"], 10000000)

        set_clock(CLOCK_LOT_CLOSE)
        closed_a = close_lot(lot_a["id"])
        closed_b = close_lot(lot_b["id"])

        assert closed_a["provisional_buyer_premium_cents"] == 1000000
        assert closed_b["provisional_buyer_premium_cents"] == 800000
        assert (
            closed_a["provisional_buyer_premium_cents"]
            > closed_b["provisional_buyer_premium_cents"]
        )
        assert closed_a["hammer_price_cents"] < closed_b["hammer_price_cents"]

    def test_the_two_premium_variants_are_written_by_different_requests(self):
        """Closing writes only the provisional figure — no contract exists yet — and
        execution writes the final one; with the title verified clear beforehand the
        preview's variant delta is exactly 0.

        PRD: "It returns the `auction_lot_id` it was asked about, the `hammer_price_cents`
        and `contract_price_cents`, the `provisional_premium_cents` and
        `final_premium_cents` side by side, the `premium_variant_delta_cents` as the final
        premium less the provisional premium — a negative figure when a title search
        improved the recorded condition after the hammer fell — and the `doc_fee_cents`,
        `total_due_cents`, `settlement_gross_cents`, `seller_net_cents` and
        `platform_fee_cents` that would be posted."

        Design: Corner/calculations/provisional_is_written_at_close_and_final_only_at_contract
        """
        scenario = sold_lot(
            clear_title=True,
            org_name="Variant Split Bank",
            seller_type="BANK",
            contact_email="v@variant.example",
            settlement_account_ref="ACH-VAR",
            default_commission_bps=500,
            street_address="1 Variant Rd",
            city="Oakland",
            estimated_value_cents=26000000,
            event_title="Variant Split Event",
            starts_at=EVENT_START,
            ends_at=EVENT_END,
            lot_window_start_at=WINDOW_START,
            lot_window_end_at=WINDOW_END,
            opening_bid_cents=20000000,
            reserve_price_cents=20000000,
            bid_amount_cents=20000000,
            funded_cents=1000000,
            bidder_legal_name="Variant Split Partners LLC",
            bidder_email="bid@variant.example",
        )
        assert scenario.lot["provisional_buyer_premium_cents"] == 1600000
        assert list_lot_contracts(scenario.lot_id) == []

        set_clock(CLOCK_CONTRACT)
        contract = execute_contract(scenario.lot_id)

        assert contract["final_buyer_premium_cents"] == 1600000
        assert contract["settlement_gross_cents"] == 21600000
        assert contract["buyer_premium_cents"] == 1600000
        assert contract["platform_fee_cents"] == 1070000
        assert contract["seller_net_cents"] == 18930000
        assert_settlement_conserved(contract)

        preview = settlement_preview(scenario.lot_id)
        assert preview["provisional_premium_cents"] == 1600000
        assert preview["final_premium_cents"] == 1600000
        assert preview["premium_variant_delta_cents"] == 0


class TestSelectionFilters:
    def test_a_suspended_backup_empties_the_pool_until_the_exclusion_is_lifted(self):
        """The pool reads the bidder's current registration axis, not just the bid: while
        the only outbid bidder is suspended the offer is refused, and the lift re-admits the
        very same bid at its own amount.

        PRD: "Candidates are the bids on the fallen-out lot whose `bid_status` is `OUTBID`,
        whose `amount_cents` is greater than or equal to the lot's `reserve_price_cents`,
        and whose bidder is currently both `REGISTERED` on the registration axis and
        `VERIFIED` on the identity axis."

        Design: Corner/calculations/backup_pool_excludes_suspended_bidder_until_exclusion_is_lifted
        """
        scenario = scheduled_lot(
            org_name="Filter Pool Bank",
            seller_type="BANK",
            contact_email="f@filter.example",
            settlement_account_ref="ACH-FILT",
            street_address="2 Filter Rd",
            city="Oakland",
            estimated_value_cents=26000000,
            event_title="Filter Pool Event",
            starts_at=EVENT_START,
            ends_at=EVENT_END,
            lot_window_start_at=WINDOW_START,
            lot_window_end_at=WINDOW_END,
            opening_bid_cents=20000000,
            reserve_price_cents=20000000,
        )
        backup = funded_bidder(
            1000000,
            legal_name="Backup Pool Bidder LLC",
            email="backup@filter.example",
            mailing_address="3 Filter Rd, Oakland CA",
            document_reference="KYC-FILT-B",
            funding_reference="WIRE-FILT-B",
        )
        winner = funded_bidder(
            1000000,
            legal_name="Winner Bidder LLC",
            email="winner@filter.example",
            mailing_address="4 Filter Rd, Oakland CA",
            document_reference="KYC-FILT-W",
            funding_reference="WIRE-FILT-W",
        )

        set_clock(CLOCK_EVENT_OPEN)
        open_event(scenario.event_id)
        set_clock("2026-09-15T17:10:00Z")
        backup_bid = place_bid(scenario.lot_id, backup["id"], 20000000)
        set_clock("2026-09-15T17:20:00Z")
        place_bid(scenario.lot_id, winner["id"], 20500000)

        set_clock("2026-09-15T17:25:00Z")
        exclusion = create_exclusion(
            backup["id"],
            "SANCTIONS_LIST",
            "2026-09-15T17:25:00Z",
            notes="list match during the sale",
        )
        assert read_bidder(backup["id"])["registration_status"] == "SUSPENDED"

        set_clock(CLOCK_LOT_CLOSE)
        closed = close_lot(scenario.lot_id)
        assert closed["lot_status"] == "CLOSED_SOLD"
        assert closed["hammer_price_cents"] == 20500000

        validate_error(
            api_client.create_second_chance_offer(
                scenario.lot_id,
                second_chance_offer_payload(),
                make_auction_ops_headers(OPS_CONTRACT),
            ),
            "ERR_NO_BACKUP_BIDDER",
            409,
        )
        rejected = read_bid(backup_bid["id"])
        assert rejected["bid_status"] == "OUTBID"
        assert rejected["amount_cents"] == 20000000

        lift_exclusion(exclusion["id"], notes="cleared on manual review")
        assert read_bidder(backup["id"])["registration_status"] == "REGISTERED"

        offer = create_offer(scenario.lot_id)
        assert offer["offered_bidder_id"] == backup["id"]
        assert offer["offer_price_cents"] == 20000000
        assert offer["status"] == "OUTSTANDING"
        assert_timestamp_equals(offer["expires_at"], "2026-09-18T18:05:00Z")

    def test_each_acceptance_demotes_its_predecessor_and_the_backup_is_the_runner_up(self):
        """Three ascending bids leave one standing bid and two released holds, and the
        second chance goes to the second-highest amount rather than the latest loser.

        PRD: "Candidates rank by `amount_cents` descending, ties break in favour of the
        earlier bid `created_at`, and any remaining tie breaks in favour of the earlier
        bidder `created_at`."

        Design: Corner/calculations/bid_ladder_demotes_in_order_and_backup_ranks_by_amount_not_recency
        """
        scenario = scheduled_lot(
            org_name="Bid Ladder Bank",
            seller_type="BANK",
            contact_email="b@ladder.example",
            settlement_account_ref="ACH-LADR",
            street_address="1 Ladder Rd",
            city="Oakland",
            estimated_value_cents=26000000,
            event_title="Bid Ladder Event",
            starts_at=EVENT_START,
            ends_at=EVENT_END,
            lot_window_start_at=WINDOW_START,
            lot_window_end_at=WINDOW_END,
            opening_bid_cents=20000000,
            reserve_price_cents=20000000,
            min_increment_cents=500000,
        )
        first, second, third = funded_bidders(3, 1000000, prefix="Ladder Bidder")

        set_clock(CLOCK_EVENT_OPEN)
        open_event(scenario.event_id)
        set_clock("2026-09-15T17:10:00Z")
        bid_one = place_bid(scenario.lot_id, first["id"], 20000000)
        set_clock("2026-09-15T17:11:00Z")
        bid_two = place_bid(scenario.lot_id, second["id"], 20500000)
        set_clock("2026-09-15T17:12:00Z")
        bid_three = place_bid(scenario.lot_id, third["id"], 21000000)
        assert bid_three["bid_status"] == "ACTIVE"

        set_clock(CLOCK_LOT_CLOSE)
        closed = close_lot(scenario.lot_id)
        assert closed["hammer_price_cents"] == 21000000
        assert read_bid(bid_three["id"])["bid_status"] == "WINNING"
        assert read_bid(bid_one["id"])["bid_status"] == "OUTBID"
        assert read_bid(bid_two["id"])["bid_status"] == "OUTBID"

        offer = create_offer(scenario.lot_id, expires_at="2026-09-20T00:00:00Z")
        assert offer["offered_bidder_id"] == second["id"]
        assert offer["offer_price_cents"] == 20500000
        assert offer["offered_bidder_id"] != first["id"]
        assert offer["offered_bidder_id"] != third["id"]
        assert_timestamp_equals(offer["expires_at"], "2026-09-20T00:00:00Z")

        assert read_bidder(first["id"])["deposit_available_cents"] == 1000000
        assert read_bidder(second["id"])["deposit_available_cents"] == 1000000
        assert read_bidder(third["id"])["deposit_available_cents"] == 0

    def test_the_deposit_weight_is_the_only_one_that_needs_a_lot_in_context(self):
        """The same bidder scores 55 with a lot supplied and 45 without it, and the stored
        screen score is the lotless reading.

        PRD: "The deposit penalty applies only when the assessment has been given a
        specific lot to reason about, and then only when the bidder's
        `deposit_available_cents` is strictly less than that lot's `required_deposit_cents`;
        with no lot in context the deposit penalty is never applied."

        Design: Corner/calculations/screen_risk_score_sums_four_weights_and_deposit_weight_needs_lot_context
        """
        scenario = scheduled_lot(
            org_name="Weighted Score Bank",
            seller_type="BANK",
            contact_email="w@weights.example",
            settlement_account_ref="ACH-WGHT",
            street_address="1 Weights Rd",
            city="Oakland",
            estimated_value_cents=26000000,
            event_title="Weighted Score Event",
            starts_at=EVENT_START,
            ends_at=EVENT_END,
            lot_window_start_at=WINDOW_START,
            lot_window_end_at=WINDOW_END,
            opening_bid_cents=20000000,
            reserve_price_cents=20000000,
        )
        assert scenario.lot["required_deposit_cents"] == 1000000

        bidder = register_bidder(
            legal_name="Unverified Weights LLC",
            email="w@weightsbid.example",
            mailing_address="2 Weights Rd, Oakland CA",
        )
        create_exclusion(
            bidder["id"], "SANCTIONS_LIST", CLOCK_SETUP, notes="screening list match"
        )

        with_lot = eligibility_assessment(
            bidder["id"], mode="SCREEN", auction_lot_id=scenario.lot_id
        )
        assert with_lot["risk_score"] == 55
        assert with_lot["eligible"] is False
        assert with_lot["identity_penalty_applied"] == 25
        assert with_lot["exclusion_penalty_applied"] == 20
        assert with_lot["fallout_penalty_applied"] == 0
        assert with_lot["deposit_penalty_applied"] == 10
        assert with_lot["counted_exclusion_count"] == 1
        assert 25 + 20 + 0 + 10 == with_lot["risk_score"]

        bare = eligibility_assessment(bidder["id"])
        assert bare["mode"] == "SCREEN"
        assert bare["risk_score"] == 45
        assert bare["deposit_penalty_applied"] == 0
        assert bare["eligible"] is False

        stored = read_bidder(bidder["id"])
        assert stored["registration_status"] == "PENDING_REVIEW"
        assert stored["screen_risk_score"] == 45


class TestLedgerAndAllocation:
    def test_repeated_wires_accumulate_instead_of_replacing(self):
        """Three wires of 1000000, 500000 and 1 leave 1500001 funded, and with no holds
        outstanding the available balance tracks the funded total exactly.

        PRD: "Funding increases `deposit_funded_cents` by the amount, recomputes the
        deposit ledger and the screen score, and advances the bidder's `version` by 1."

        Design: Corner/calculations/deposit_funding_accumulates_across_repeated_wires
        """
        set_clock("2026-09-10T00:00:00Z")
        bidder = register_bidder(
            legal_name="Running Total LLC",
            email="r@runningtotal.example",
            mailing_address="1 Running Rd, Oakland CA",
        )
        verified = verify_bidder(bidder["id"], "VERIFIED", "KYC-RUN-1")
        assert verified["deposit_funded_cents"] == 0

        first = fund(bidder["id"], 1000000, "WIRE-RUN-1")
        assert first["deposit_funded_cents"] == 1000000
        assert first["deposit_available_cents"] == 1000000

        second = fund(bidder["id"], 500000, "WIRE-RUN-2")
        assert second["deposit_funded_cents"] == 1500000
        assert second["deposit_available_cents"] == 1500000

        third = fund(bidder["id"], 1, "WIRE-RUN-3")
        assert third["deposit_funded_cents"] == 1500001
        assert third["deposit_available_cents"] == 1500001

        assert read_bidder(bidder["id"])["deposit_forfeited_cents"] == 0
        assert list_holds(bidder_id=bidder["id"]) == []

    def test_the_forfeiture_remainder_cent_lands_in_the_platform_bucket(self):
        """A forfeited 1000001 splits 600001 to the seller and 400000 to the platform, and
        the seller ledger ends at the forfeiture share alone once the posted net is voided.

        PRD: "`forfeiture_seller_net_cents` is the `forfeited_deposit_cents` multiplied by
        6000 basis points and divided by ten thousand — sixty percent — rounded half up to
        whole cents, and `forfeiture_platform_fee_cents` is whatever remains after
        subtracting the seller's share from the forfeited amount."

        Design: Corner/calculations/forfeiture_remainder_lands_in_the_platform_bucket
        """
        scenario = fallen_out_contract(
            clear_title_before_close=True,
            fallout_at="2026-10-01T00:00:00Z",
            org_name="Remainder Cent Bank",
            seller_type="BANK",
            contact_email="r@remainder.example",
            settlement_account_ref="ACH-REMD",
            default_commission_bps=500,
            street_address="1 Remainder Rd",
            city="Oakland",
            estimated_value_cents=26000000,
            event_title="Remainder Cent Event",
            starts_at=EVENT_START,
            ends_at=EVENT_END,
            lot_window_start_at=WINDOW_START,
            lot_window_end_at=WINDOW_END,
            opening_bid_cents=20000020,
            reserve_price_cents=20000020,
            bid_amount_cents=20000020,
            funded_cents=1100000,
            bidder_legal_name="Remainder Cent Partners LLC",
            bidder_email="bid@remainder.example",
        )
        contract = scenario.contract

        assert read_lot(scenario.lot_id)["required_deposit_cents"] == 1000001
        assert contract["contract_price_cents"] == 20000020
        assert contract["final_buyer_premium_cents"] == 1600002
        assert contract["platform_fee_cents"] == 1070001
        assert contract["platform_fee_cents"] == expected_platform_fee(
            20000020, 500, "CLEAR"
        )
        assert contract["seller_net_cents"] == 18930019
        assert contract["doc_fee_cents"] == expected_doc_fee(20000020, 1600002) == 95000
        assert contract["total_due_cents"] == expected_total_due(
            20000020, 1600002, 95000
        ) == 21695022

        assert contract["contract_status"] == "FALLOUT"
        assert contract["settlement_status"] == "VOID"
        assert contract["forfeited_deposit_cents"] == 1000001

        seller_share, platform_share = expected_forfeiture_split(1000001)
        assert contract["forfeiture_seller_net_cents"] == seller_share == 600001
        assert contract["forfeiture_platform_fee_cents"] == platform_share == 400000
        assert (
            contract["forfeiture_seller_net_cents"]
            + contract["forfeiture_platform_fee_cents"]
            == contract["forfeited_deposit_cents"]
        )
        assert contract["forfeiture_seller_net_cents"] != 600000
        assert contract["forfeiture_platform_fee_cents"] != 400001
        assert_forfeiture_conserved(contract)

        assert read_seller(scenario.seller_id)["settled_net_cents"] == 600001

        buyer = read_bidder(scenario.bidder_id)
        assert buyer["deposit_forfeited_cents"] == 1000001
        assert buyer["deposit_available_cents"] == 99999
        assert buyer["fallout_count"] == 1
        assert buyer["registration_status"] == "REGISTERED"
        assert read_listing(scenario.listing_id)["listing_status"] == "RELIST_PENDING"


class TestCountyIntervals:
    def test_a_thirty_one_minute_gap_and_a_neighbouring_county_both_clear_the_buffer(self):
        """The half-hour buffer widens each event's interval but never crosses a county
        line: two Alameda sessions a minute clear of the buffer and a fully overlapping
        Contra Costa session are all accepted.

        PRD: "A candidate event conflicts with another event of the same county whose
        `event_status` is `SCHEDULED`, `LIVE` or `POSTPONED` when the candidate's start is
        at or before that other event's end plus the buffer **and** that other event's start
        is at or before the candidate's end plus the buffer."

        Design: Corner/calculations/county_windows_outside_the_buffer_and_other_counties_are_disjoint
        """
        set_clock(CLOCK_SETUP)
        anchor = create_event(
            title="Anchor Alameda Event",
            county_code=COUNTY_PRIMARY,
            starts_at=EVENT_START,
            ends_at=EVENT_END,
        )

        early = create_event(
            title="Earlier Alameda Event",
            county_code=COUNTY_PRIMARY,
            starts_at="2026-09-15T15:00:00Z",
            ends_at="2026-09-15T16:29:00Z",
        )
        late = create_event(
            title="Later Alameda Event",
            county_code=COUNTY_PRIMARY,
            starts_at="2026-09-15T19:31:00Z",
            ends_at="2026-09-15T20:30:00Z",
        )
        other_county = create_event(
            title="Overlapping Contra Costa Event",
            county_code=COUNTY_SECONDARY,
            starts_at=EVENT_START,
            ends_at=EVENT_END,
        )

        for created in (anchor, early, late, other_county):
            assert created["event_status"] == "SCHEDULED"

        _alameda, alameda_meta = validate_paginated(
            api_client.list_auction_events(ADMIN, params={"county_code": COUNTY_PRIMARY})
        )
        assert alameda_meta["total_count"] == 3

        contra_costa, contra_meta = validate_paginated(
            api_client.list_auction_events(ADMIN, params={"county_code": COUNTY_SECONDARY})
        )
        assert contra_meta["total_count"] == 1
        assert contra_costa[0]["id"] == other_county["id"]

        assert_timestamp_equals(read_event(anchor["id"])["starts_at"], EVENT_START)
