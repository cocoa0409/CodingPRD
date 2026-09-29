"""Endpoint-level behaviour: what one call writes, links and recomputes.

Three of these turn on an endpoint doing deliberately less than its neighbours —
a rejection that moves nothing, a publication refused until its predecessor has
run, a read that recomputes without mutating — and one on a create that draws its
two parents from two different places.
"""

from test_helpers import (
    ADMIN,
    ANALYST,
    ERR_INSTRUMENT_NOT_FOUND,
    ERR_MTM_RUN_INVALID_STATE,
    NON_EXISTENT_UUID,
    OPS,
    TREASURY,
    assert_money,
    assert_mtm_totals,
    assert_nothing_pinned,
    assert_planned_economics,
    assert_price,
    assert_station_supply,
    factories as f,
    fixtures as fx,
    ids_of,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_INSTRUMENT_ID = "0d5a7e13-9c48-4b62-8f10-2a6c4d9e7b35"


class TestDirectiveRejection:
    def test_rejection_pins_no_price_and_keeps_the_planned_figures_readable(self, api):
        """PRD §3.8: "Rejecting it advances `PROPOSED → REJECTED` with a
        `reject_reason`, pins no prices, moves no inventory, and increments the
        directive's `version` by one."

        The planned figures computed at creation — a 368.9-gallon penalty and
        978.82 of net saving — stay on the row for the audit trail, while
        `approved_by_user_id` is never stamped because PRD §3.8 stamps it only on
        approval.

        Design: Corner/endpoints/reject_directive_pins_no_prices_and_moves_no_fuel
        """
        ctx = fx.setup_proposed_directive(
            api, 3000, policy_overrides=dict(policy_code="FY27-TANK")
        )

        data = validate_success(
            api.reject_tankering_directive(
                ctx["directive"]["id"],
                f.reject_directive_payload(
                    "Downline aircraft swap removed the tankering opportunity."
                ),
                headers=OPS,
            )
        )

        assert data["status"] == "REJECTED"
        assert data["approved_by_user_id"] is None
        assert data["revision_count"] == 0
        assert_nothing_pinned(data)
        assert_planned_economics(
            data,
            planned_burn_penalty_gallons=368.9,
            planned_net_savings_usd=978.82,
        )

    def test_rejection_moves_no_fuel_and_leaves_the_pricing_source_intact(self, api):
        """PRD §3.2: "Airline-owned gallons at a station move through exactly
        three doors: an explicit inventory adjustment, the loading of a tankering
        directive, and the reconciliation of a tankering directive."

        PRD §3.2: "`days_cover` is `effective_inventory_gallons` divided by
        `avg_daily_liftings_gallons`, rounded to two decimal places" and "from the
        minimum up to but not including twice the minimum it is `WATCH`" — 500,000
        gallons over 100,000 daily liftings is 5.00 days against a 3.00 minimum.

        PRD §3.2: "On creation the server computes `all_in_price_usd_per_gal` as
        the sum of `index_price_usd_per_gal`, `differential_usd_per_gal` and the
        station's `into_plane_fee_usd_per_gal`, rounded to four decimal places".

        Design: Corner/endpoints/reject_directive_pins_no_prices_and_moves_no_fuel
        """
        ctx = fx.setup_proposed_directive(
            api, 3000, policy_overrides=dict(policy_code="FY27-TANK")
        )
        rejected = validate_success(
            api.reject_tankering_directive(
                ctx["directive"]["id"],
                f.reject_directive_payload(
                    "Downline aircraft swap removed the tankering opportunity."
                ),
                headers=OPS,
            )
        )

        origin = fx.read_station(api, ctx["origin"]["id"])
        assert_station_supply(
            origin,
            inventory_gallons=500000,
            days_cover=5.00,
            supply_posture="WATCH",
        )

        rows, meta = validate_paginated(
            api.list_leg_tankering_directives(
                ctx["leg"]["id"], headers=OPS, params={"status": "REJECTED"}
            )
        )
        assert len(rows) == 1
        assert meta["total_count"] == 1
        assert ids_of(rows) == [rejected["id"]]

        contracts, _meta = validate_paginated(
            api.list_supply_contracts(
                ctx["origin"]["id"], headers=OPS, params={"status": "ACTIVE"}
            )
        )
        assert len(contracts) == 1
        assert contracts[0]["contract_ref"] == "ORD-2027-A"
        assert_price(contracts[0]["all_in_price_usd_per_gal"], 2.4700)


class TestMarkToMarketPublicationGate:
    def test_publishing_an_open_run_is_refused_and_stamps_nothing(self, api):
        """PRD §3.7: "**Publishing** the run is reserved to a `RiskPolicyAdmin`,
        is valid only as `COMPUTED → PUBLISHED`" and "publishing a run that is
        still `OPEN` or already `PUBLISHED`, is rejected with
        `ERR_MTM_RUN_INVALID_STATE`."

        PRD §3.7: "A new run is `OPEN`, with `instrument_count`, `total_mtm_usd`,
        `designated_mtm_usd`, `undesignated_mtm_usd`, `margin_calls_created` and
        `settled_instrument_count` all at zero and `computed_at` and
        `published_at` null."

        Design: Corner/endpoints/mtm_publish_before_compute_returns_409_then_succeeds_after_compute
        """
        run = fx.do_open_mtm_run(api, "2027-02", 2.7500)

        validate_error(
            api.publish_mtm_run(run["id"], headers=ADMIN),
            ERR_MTM_RUN_INVALID_STATE,
            409,
        )

        after = fx.read_mtm_run(api, run["id"])
        assert after["status"] == "OPEN"
        assert after["published_at"] is None
        assert after["computed_at"] is None
        assert after["version"] == 1

    def test_the_identical_call_succeeds_once_the_empty_run_is_computed(self, api):
        """PRD §3.7: "Scope is every hedge instrument in the system whose
        `trade_status` is `EXECUTED` at the moment of the call" — an empty scope
        is a legitimate `COMPUTED` run, so the gate is the run's status and not
        the presence of trades.

        PRD §3.7: "Publication sets `published_at` from the logical clock and then
        runs a four-part cascade followed by settlement, in that order."

        Design: Corner/endpoints/mtm_publish_before_compute_returns_409_then_succeeds_after_compute
        """
        run = fx.do_open_mtm_run(api, "2027-02", 2.7500)
        validate_error(
            api.publish_mtm_run(run["id"], headers=ADMIN),
            ERR_MTM_RUN_INVALID_STATE,
            409,
        )

        computed = fx.do_compute_mtm_run(api, run["id"])
        assert_mtm_totals(
            computed,
            status="COMPUTED",
            instrument_count=0,
            total_mtm_usd=0.00,
            designated_mtm_usd=0.00,
            undesignated_mtm_usd=0.00,
        )

        published = validate_success(api.publish_mtm_run(run["id"], headers=ADMIN))
        assert_mtm_totals(
            published,
            status="PUBLISHED",
            margin_calls_created=0,
            settled_instrument_count=0,
        )
        assert published["published_at"] is not None


class TestCollateralPostingLinkage:
    @staticmethod
    def _executed_trade_and_its_dealer(api):
        return fx.setup_active_program_with_executed_swap(
            api,
            single_forecast=True,
            policy_overrides=dict(
                policy_code="FY27-CORNER",
                min_coverage_pct=5.00,
                max_single_counterparty_pct=100.00,
                max_earnings_volatility_usd=500000.00,
                eligible_fleet_types=["NARROWBODY"],
            ),
            counterparty_overrides=dict(
                counterparty_code="DLRC",
                legal_name="Dealer C Bank NA",
                credit_rating="A",
            ),
            program_overrides=dict(
                program_code="HP-CORNER",
                route_groups=["DOMESTIC_SHORT"],
                target_coverage_pct=30.00,
            ),
            swap_overrides=dict(
                notional_gallons=1000000,
                strike_usd_per_gal=2.5000,
                maturity_month="2027-03",
            ),
        )

    def test_an_unresolvable_instrument_in_the_body_is_reported_as_a_404(self, api):
        """PRD §2.5: "**Body foreign-key existence.** Every identifier supplied in
        a request body — `policy_id`, `counterparty_id`, `hedge_instrument_id`,
        `origin_station_id`, `destination_station_id`, `hedge_program_id` or
        `tankering_directive_id` — must resolve to an existing row, otherwise
        `ERR_POLICY_NOT_FOUND`, `ERR_COUNTERPARTY_NOT_FOUND`,
        `ERR_INSTRUMENT_NOT_FOUND`, `ERR_STATION_NOT_FOUND`,
        `ERR_PROGRAM_NOT_FOUND` or `ERR_DIRECTIVE_NOT_FOUND`, whichever matches
        the unresolved identifier (404)."

        The counterparty in the path resolves, so only the body reference can be
        at fault.

        Design: Corner/endpoints/collateral_posting_links_counterparty_from_path_and_instrument_from_body
        """
        ctx = self._executed_trade_and_its_dealer(api)
        counterparty = fx.read_counterparty(api, ctx["counterparty"]["id"])

        validate_error(
            api.create_collateral_posting(
                counterparty["id"],
                f.collateral_posting_payload(
                    UNKNOWN_INSTRUMENT_ID, counterparty["version"], "CASH"
                ),
                headers=ADMIN,
            ),
            ERR_INSTRUMENT_NOT_FOUND,
            404,
        )

    def test_the_row_takes_one_parent_from_the_path_and_the_other_from_the_body(
        self, api
    ):
        """PRD §3.5: "Its `counterparty_id` is taken from the path when a
        `RiskPolicyAdmin` raises one manually, and from the covered trade when a
        mark-to-market publication synthesises one. A manual requirement names the
        trade it covers by `hedge_instrument_id` in the body".

        PRD §3.5: "Creation opens the row in `REQUIRED` status with `origin`
        `MANUAL` and `posted_amount_usd` at 0, and freezes `required_amount_usd`
        at that moment as the trade's `margin_requirement_usd` less its
        `collateral_posted_usd`, floored at zero".

        The one row is then reachable from both parents' sub-resource lists.

        Design: Corner/endpoints/collateral_posting_links_counterparty_from_path_and_instrument_from_body
        """
        ctx = self._executed_trade_and_its_dealer(api)
        counterparty = fx.read_counterparty(api, ctx["counterparty"]["id"])
        instrument_id = ctx["instrument"]["id"]

        posting = validate_success(
            api.create_collateral_posting(
                counterparty["id"],
                f.collateral_posting_payload(
                    instrument_id, counterparty["version"], "CASH"
                ),
                headers=ADMIN,
            ),
            201,
        )
        assert posting["counterparty_id"] == counterparty["id"]
        assert posting["hedge_instrument_id"] == instrument_id
        assert posting["status"] == "REQUIRED"
        assert posting["origin"] == "MANUAL"
        assert_money(posting["required_amount_usd"], 60000.00, "required_amount_usd")
        assert_money(posting["posted_amount_usd"], 0, "posted_amount_usd")

        by_instrument, instrument_meta = validate_paginated(
            api.list_instrument_collateral_postings(
                instrument_id, headers=TREASURY, params={"status": "REQUIRED"}
            )
        )
        assert instrument_meta["total_count"] == 1
        assert ids_of(by_instrument) == [posting["id"]]

        by_counterparty, counterparty_meta = validate_paginated(
            api.list_counterparty_collateral_postings(
                counterparty["id"], headers=TREASURY, params={"origin": "MANUAL"}
            )
        )
        assert counterparty_meta["total_count"] == 1
        assert ids_of(by_counterparty) == [posting["id"]]


class TestUpliftCapFollowsTheActivePolicy:
    @staticmethod
    def _a_leg_under_a_twelve_thousand_gallon_ceiling(api):
        fx.set_clock(api, fx.TANKERING_CLOCK)
        policy_a = fx.do_create_policy(api, policy_code="FY27-CAP-A")
        origin = fx.do_create_station(
            api,
            iata_code="DFW",
            name="Dallas Fort Worth",
            into_plane_fee_usd_per_gal=0.0450,
            avg_daily_liftings_gallons=100000,
        )
        destination = fx.do_create_station(
            api,
            iata_code="ORD",
            name="Chicago OHare",
            into_plane_fee_usd_per_gal=0.0800,
            avg_daily_liftings_gallons=80000,
        )
        leg = fx.do_create_leg(
            api,
            origin["id"],
            destination["id"],
            flight_number="FA100",
            departure_date="2027-02-10",
            planned_burn_gallons=15000,
            tank_capacity_gallons=26500,
            landing_weight_lbs=130000,
            max_landing_weight_lbs=205000,
        )
        return {"policy_a": policy_a, "leg": leg}

    def test_the_cap_is_the_smallest_headroom_and_reading_it_mutates_nothing(self, api):
        """PRD §3.8: "From that envelope the server derives `uplift_cap_gallons`,
        the maximum gallons this leg may ever tanker, as the smallest of three
        headrooms. Tank headroom is `tank_capacity_gallons` less
        `planned_burn_gallons` less a fixed 900-gallon reserve that is never
        available for tankering."

        PRD §2.4: "reading a single flight leg recomputes `uplift_cap_gallons`,
        but neither read increments `version` or touches `updated_at`."

        Tank headroom 10,600.00 is smaller than the 11,194.03 weight headroom and
        smaller than the 12,000-gallon policy term.

        Design: Corner/endpoints/uplift_cap_read_follows_the_active_policy_after_supersession
        """
        ctx = self._a_leg_under_a_twelve_thousand_gallon_ceiling(api)

        leg = fx.read_flight_leg(api, ctx["leg"]["id"])
        assert_money(leg["uplift_cap_gallons"], 10600.00, "uplift_cap_gallons")
        assert leg["version"] == 1

    def test_a_superseding_policy_lowers_the_cap_without_touching_the_leg(self, api):
        """PRD §3.8: "The third term is the `max_tankering_uplift_gallons` of the
        single `ACTIVE` hedging policy" and "The cap is recomputed on every read
        of the leg".

        PRD §2.9: "Creating a new policy for a fiscal year that already has an
        `ACTIVE` policy sets the older row's `status` to `SUPERSEDED` and
        increments that row's `version` by one; the new row is created `ACTIVE`
        with `open_exception_count` at 0."

        PRD §2.9: "Two limits, by contrast, are read from whichever policy is
        `ACTIVE` at the moment of evaluation rather than from a programme's bound
        policy: `max_tankering_uplift_gallons`, which caps a single leg's uplift".

        Design: Corner/endpoints/uplift_cap_read_follows_the_active_policy_after_supersession
        """
        ctx = self._a_leg_under_a_twelve_thousand_gallon_ceiling(api)
        assert_money(
            fx.read_flight_leg(api, ctx["leg"]["id"])["uplift_cap_gallons"],
            10600.00,
            "uplift_cap_gallons",
        )

        policy_b = validate_success(
            api.create_hedge_policy(
                f.hedge_policy_payload(
                    policy_code="FY27-CAP-B", max_tankering_uplift_gallons=5000
                ),
                headers=ADMIN,
            ),
            201,
        )
        assert policy_b["status"] == "ACTIVE"
        assert fx.read_policy(api, ctx["policy_a"]["id"])["status"] == "SUPERSEDED"

        leg = fx.read_flight_leg(api, ctx["leg"]["id"])
        assert_money(leg["uplift_cap_gallons"], 5000.00, "uplift_cap_gallons")
        assert leg["version"] == 1
        assert_money(
            leg["tank_capacity_gallons"], 26500, "tank_capacity_gallons"
        )
