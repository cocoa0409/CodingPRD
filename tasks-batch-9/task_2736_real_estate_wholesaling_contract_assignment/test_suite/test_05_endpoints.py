"""
Endpoint surface: a create-and-read aggregate round-tripping through both read
paths, a re-runnable action endpoint, a create whose cross-reference mutates a
sibling row, and a read that exposes a persisted derived schedule.
"""

from decimal import Decimal

from test_helpers import (
    assert_assignment_offer,
    assert_buyer_capital_reconciled,
    assert_cash_buyer,
    assert_deal_analysis,
    assert_equity_pct_four_places,
    assert_pagination_meta,
    assert_purchase_contract,
    assert_seller_lead,
    assert_wholesaler,
    build_marketed_contract,
    build_underwritten_lead,
    comparable,
    elect,
    factories,
    list_all_offers,
    make_compliance_officer_headers,
    make_title_agent_headers,
    make_wholesaler_headers,
    read_buyer,
    read_contract,
    read_offer,
    record_lead,
    register_wholesaler,
    screen_lead,
    set_clock,
    submit_offer,
    validate_paginated,
    validate_success,
)


class TestWholesalerRosterEndpoints:
    """POST, GET-by-id and the filtered roster, and nothing else."""

    def test_registered_row_round_trips_and_the_roster_filter_excludes(self, api):
        """
        "Compliance staff and platform staff can page through the roster,
        narrowing it by `state_code` or by `licensure_status`; deal-level
        participants cannot read the roster at all, though any authenticated
        role may read a single wholesaler identified by its `wholesaler_id` in
        order to see the compliance counters that gate the deals they are party
        to."

        "The `meta` block of every list response carries `limit`, `offset`,
        `total_count` (the count of records matching the filters before the
        window is applied) and `has_more` (true when records remain beyond the
        current window)."

        Design: Corner/endpoints/standard_crud_wholesaler_create_and_read_round_trip
        """
        set_clock(api, "2026-08-01T00:00:00Z")
        texan = register_wholesaler(
            api, legal_name="Keystone Property Partners LLC", state_code="TX"
        )
        washingtonian = register_wholesaler(
            api,
            legal_name="Cascade Doorstep Homes LLC",
            state_code="WA",
            licensure_status="LICENSED_BROKER",
        )

        fetched = validate_success(
            api.get_wholesaler(texan["id"], make_wholesaler_headers(texan["id"])), 200
        )
        assert_wholesaler(
            fetched, legal_name="Keystone Property Partners LLC", version=1
        )
        assert fetched == texan, (
            "read-by-id must return the created row unchanged: "
            f"{texan} became {fetched}"
        )

        response = api.list_wholesalers(
            make_compliance_officer_headers(),
            {"state_code": "TX", "limit": 10, "offset": 0},
        )
        roster, meta = validate_paginated(response)

        assert_pagination_meta(
            meta, limit=10, offset=0, total_count=1, has_more=False
        )
        assert [row["id"] for row in roster] == [texan["id"]], (
            "the WA desk must be filtered out of a state_code=TX roster page, "
            f"got {roster}"
        )
        assert washingtonian["id"] not in [row["id"] for row in roster]


class TestProtectionScreenReRun:
    """The screen is an action endpoint that is legal to replay."""

    def test_re_running_the_same_variant_restamps_and_bumps_version(self, api):
        """
        "The screen drives `PROSPECT → SCREENED` on first use, and is fully
        re-runnable thereafter as a `SCREENED → SCREENED` self-transition that
        overwrites the previously stored tier under the newly requested
        variant. Either way it writes `screening_variant`, `net_equity_cents`,
        `equity_pct`, `protection_tier` and `screened_at`, stamps `screened_at`
        with the current logical instant, and increments the lead's `version`"

        Design: Corner/endpoints/protection_screen_rerun_restamps_screened_at_and_bumps_version
        """
        set_clock(api, "2026-08-04T00:00:00Z")
        wholesaler = register_wholesaler(api)
        lead = record_lead(api, wholesaler["id"])

        first = screen_lead(api, lead["id"], wholesaler["id"], "STATUTORY")
        assert_seller_lead(
            first,
            status="SCREENED",
            screened_at="2026-08-04T00:00:00Z",
            version=2,
        )

        set_clock(api, "2026-08-09T00:00:00Z")
        response = api.protection_screen(
            lead["id"],
            factories.protection_screen_payload("STATUTORY"),
            make_wholesaler_headers(wholesaler["id"]),
        )
        second = validate_success(response, 200)

        assert_seller_lead(
            second,
            status="SCREENED",
            screening_variant="STATUTORY",
            screened_at="2026-08-09T00:00:00Z",
            protection_tier="STANDARD",
            net_equity_cents=20000000,
            version=3,
        )
        assert_equity_pct_four_places(second["equity_pct"])
        assert Decimal(str(second["equity_pct"])) == Decimal("0.6667"), (
            f"the same variant must recompute the same equity: {second['equity_pct']!r}"
        )


class TestSupersedingOfferLink:
    """supersedes_offer_id mutates the referenced row in the same request."""

    def test_superseding_bid_withdraws_the_prior_offer_and_repoints_capital(self, api):
        """
        "Optionally the offer names `supersedes_offer_id`, the identifier of one
        of the buyer's own earlier offers on the same contract that this bid
        replaces; when supplied, the referenced offer must belong to the same
        contract and the same buyer."

        "The superseded offer is driven to `WITHDRAWN` **first**, releasing its
        `buyer_deposit_cents` from the buyer's `committed_deposit_cents`, and
        the replacement bid is then measured against the freed capacity."

        "A cash buyer's `committed_deposit_cents` always equals the sum of
        `buyer_deposit_cents` across that buyer's offers in a live negotiation
        status, and `active_offer_count` always equals the count of those same
        offers."

        Design: Corner/endpoints/assignment_offer_supersede_link_withdraws_prior_offer
        """
        scenario = build_marketed_contract(
            api,
            clock="2026-08-06T00:00:00Z",
            buyer_price_cents=18500000,
            buyer_deposit_cents=1000000,
            structure_election="ASSIGNMENT_ELECTED",
            contract_kwargs={
                "purchase_price_cents": 18000000,
                "earnest_money_cents": 500000,
            },
        )
        first_offer_id = scenario.offer_id

        replacement = submit_offer(
            api,
            scenario.pc_id,
            scenario.buyer_id,
            18600000,
            scenario.refresh_contract()["version"],
            buyer_deposit_cents=1200000,
            supersedes_offer_id=first_offer_id,
        )

        assert_assignment_offer(
            replacement,
            supersedes_offer_id=first_offer_id,
            status="SUBMITTED",
            negotiation_round=1,
            buyer_price_cents=18600000,
            buyer_deposit_cents=1200000,
        )
        assert_assignment_offer(
            read_offer(api, first_offer_id, scenario.w_id), status="WITHDRAWN"
        )

        buyer = read_buyer(api, scenario.buyer_id, scenario.w_id)
        assert_cash_buyer(
            buyer,
            verified_funds_cents=25500000,
            committed_deposit_cents=1200000,
            available_funds_cents=24300000,
            active_offer_count=1,
            buyer_tier="STANDARD",
        )
        assert_buyer_capital_reconciled(
            buyer, list_all_offers(api, scenario.pc_id, scenario.w_id)
        )

        assert_purchase_contract(
            read_contract(api, scenario.pc_id, scenario.w_id),
            assignment_status="MARKETED",
        )


class TestComputedReadOfTheDoubleCloseSchedule:
    """A GET exposes the persisted schedule, tier selected from the base."""

    def test_read_returns_the_tier_two_schedule_with_a_null_spread(self, api):
        """
        "Step two selects the transactional lender's fee tier **from the
        grossed-up base**, never from the raw purchase price and never from the
        final total — this is the single most commonly mis-implemented part of
        the schedule, and it means a contract whose purchase price sits just
        under a tier edge is nevertheless priced in the next tier up."

        "A base from fifteen million cents up to but not including thirty
        million cents (three hundred thousand dollars) sits in the second tier,
        at two and a quarter percent with a minimum fee of forty-five thousand
        cents."

        "Step five is the spread, and it stays null until an offer on this
        contract reaches `ACCEPTED`: `double_close_spread_cents` is the
        accepted offer's `buyer_price_cents` less
        `total_funding_required_cents`."

        Design: Corner/endpoints/computed_read_purchase_contract_exposes_double_close_schedule
        """
        scenario = build_underwritten_lead(
            api,
            clock="2026-08-07T00:00:00Z",
            lead_kwargs={
                "estimated_market_value_cents": 42000000,
                "recorded_senior_lien_cents": 12000000,
            },
            analysis_kwargs={
                "comparables": [
                    comparable(42000000, 0.10, 10, 1800, 0),
                    comparable(42000000, 0.20, 10, 1800, 0),
                    comparable(42000000, 0.30, 10, 1800, 0),
                ]
            },
        )
        assert_seller_lead(scenario.lead, protection_tier="STANDARD")
        # floor(42000000 * 0.75) - 1000000 - 1000000 == 29500000.
        assert_deal_analysis(scenario.analysis, max_allowable_offer_cents=29500000)

        contract = validate_success(
            api.create_purchase_contract(
                factories.purchase_contract_payload(
                    scenario.lead_id,
                    scenario.analysis_id,
                    purchase_price_cents=29000000,
                    earnest_money_cents=500000,
                    option_start_at="2026-08-07T00:00:00Z",
                ),
                make_wholesaler_headers(scenario.w_id),
            ),
            201,
        )
        elect(api, contract["id"], scenario.w_id, "DOUBLE_CLOSE_ELECTED")

        response = api.get_purchase_contract(
            contract["id"], make_title_agent_headers("ta-1")
        )
        fetched = validate_success(response, 200)

        # 29000000 + round_half_up(29000000 * 0.021) == 29609000, and the base
        # sits in tier two, where round_half_up(29609000 * 0.0225) == 666203
        # clears the 45000 minimum.
        assert_purchase_contract(
            fetched,
            purchase_price_cents=29000000,
            structure_election="DOUBLE_CLOSE_ELECTED",
            funding_base_cents=29609000,
            transactional_lender_fee_cents=666203,
            total_funding_required_cents=30275203,
            double_close_spread_cents=None,
        )
