"""Boundary arithmetic: coverage clauses, ceilings, shrink, ratios and pools.

Every figure below is derived from the PRD's pinned formulas rather than read
back from a previous response, so a plausible-but-wrong ordering of the
valuation stages shows up as a wrong number rather than a wrong shape.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    assert_account_standing,
    assert_bag_drop_valuation,
    assert_center_pool,
    assert_coverage,
    assert_credit_entry,
    assert_fraud_posture,
    assert_ledger_entry,
    assert_liability_projection,
    assert_lot_settlement,
    assert_ratio_precision,
    assert_stamped_at,
    assert_visit_valuation,
    expected_shrink,
    make_distributor_headers,
)
from test_helpers import factories as f
from test_helpers import fixtures as h

INSTANT = "2026-08-05T09:00:00Z"
NEXT_DAY = "2026-08-06T09:00:00Z"


class TestCoverageClauseOrder:
    """The first failing clause is the one recorded, and it stops the rest."""

    def test_wine_fails_on_type_and_a_pouch_on_material(self, api):
        """A covered material cannot rescue an excluded beverage type.

        PRD: "Anything else — `WINE`, `DISTILLED_SPIRITS`, `MILK`, `INFANT_FORMULA`,
        `MEAL_REPLACEMENT` or `VEGETABLE_JUICE` — yields `coverage_status` `NOT_COVERED`
        with `coverage_reason` `EXCLUDED_BEVERAGE_TYPE`, and the remaining clauses are not
        consulted."

        PRD: "A `POUCH`, `ASEPTIC_BOX` or `PAPER_CARTON` yields `NOT_COVERED` with
        `coverage_reason` `EXCLUDED_MATERIAL`."

        PRD: "Approval is only available when the coverage determination came out
        `COVERED`; a `NOT_COVERED` label is refused with `ERR_PRODUCT_NOT_COVERED`."

        Design: Corner/calculations/coverage_clause_order_names_the_first_failing_clause
        """
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)
        headers = make_distributor_headers(distributor["id"])

        wine = h.create_draft_product(
            api,
            distributor["id"],
            brand_name="Cascade Vintage",
            beverage_type="WINE",
            container_material="ALUMINUM",
            fill_volume_ml=500,
            upc="011110000010",
        )
        pouch = h.create_draft_product(
            api,
            distributor["id"],
            brand_name="Cascade Pouch Water",
            beverage_type="WATER",
            container_material="POUCH",
            fill_volume_ml=500,
            upc="011110000011",
        )

        submitted_wine = h.submit_product(api, wine["id"], distributor["id"])
        assert_coverage(submitted_wine, "NOT_COVERED", "EXCLUDED_BEVERAGE_TYPE", 0)

        submitted_pouch = h.submit_product(api, pouch["id"], distributor["id"])
        assert_coverage(submitted_pouch, "NOT_COVERED", "EXCLUDED_MATERIAL", 0)

        response = api.post_registration_action(
            wine["id"], f.registration_action_payload("APPROVE"), ADMIN_HEADERS
        )
        validate_error(
            response, ApiErrorId.ERR_PRODUCT_NOT_COVERED.value, expected_status=409
        )

        stored = validate_success(api.get_beverage_product(wine["id"], headers))
        assert stored["registration_state"] == "SUBMITTED"
        assert stored["registered_at"] is None


class TestRetailerVisitCeilings:
    """Store size sets the per-visit ceiling; the daily cap is the programme's."""

    def test_a_small_and_a_large_store_bound_the_same_holder_differently(self, api):
        """24 containers at the small store, 50 at the large one, one shared bucket.

        PRD: "Store size sets the store's per-visit hand-count ceiling:
        `daily_limit_containers` is derived as 50 containers for a store of 5000 square feet
        or larger, and 24 containers for any smaller store."

        PRD: "A visit at a retailer — always hand-counted — takes the store's own
        `daily_limit_containers` as its base ceiling, which §3.2 derived from the store's
        floor area."

        PRD: "For an attributed visit the server first picks the applicable cap: at a
        redemption centre it is that centre's `daily_account_cap_containers`, and at a
        retailer it is the programme's default daily cap of 350 containers."

        Design: Corner/calculations/retailer_visit_limit_follows_store_area_threshold_and_program_default_cap
        """
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)
        product = h.create_registered_product(api, distributor["id"])
        small = h.create_retailer(
            api,
            store_name="Small Market",
            x_miles=20.0,
            y_miles=20.0,
            store_area_sqft=3000,
        )
        large = h.create_retailer(
            api,
            store_name="Large Market",
            x_miles=25.0,
            y_miles=25.0,
            store_area_sqft=6000,
        )
        account = h.create_account(api)

        assert small["daily_limit_containers"] == 24
        assert large["daily_limit_containers"] == 50

        small_headers = h.make_retailer_headers(small["id"])
        small_visit = h.open_retailer_visit(api, small["id"], account["id"])
        h.add_lot(api, small_visit["id"], product["id"], 30, small_headers)
        closed_small = h.close_count(api, small_visit["id"], small_headers)

        assert_visit_valuation(
            closed_small,
            visit_limit_applied=24,
            capped_count=24,
            shrink_adjustment_count=1,
            payable_count=23,
            refused_over_limit_count=6,
            payout_cents=230,
        )
        assert closed_small["shrink_adjustment_count"] == expected_shrink(24)

        holder = h.read_account(api, account["id"], ADMIN_HEADERS)
        assert holder["containers_redeemed_today"] == 23
        assert holder["redemption_day"] == "2026-08-05"
        assert holder["cap_reached_today"] is False

        large_headers = h.make_retailer_headers(large["id"])
        large_visit = h.open_retailer_visit(api, large["id"], account["id"])
        h.add_lot(api, large_visit["id"], product["id"], 60, large_headers)
        closed_large = h.close_count(api, large_visit["id"], large_headers)

        assert_visit_valuation(
            closed_large,
            visit_limit_applied=50,
            capped_count=50,
            shrink_adjustment_count=1,
            payable_count=49,
            refused_over_limit_count=10,
            payout_cents=490,
        )

        holder = h.read_account(api, account["id"], ADMIN_HEADERS)
        assert holder["containers_redeemed_today"] == 72
        assert holder["cap_reached_today"] is False

        for visit in (closed_small, closed_large):
            assert_fraud_posture(visit, False, None, "PENDING")


class TestHandCountShrinkCeiling:
    """Two per cent rounded up costs a whole container however small the count."""

    @staticmethod
    def _center_with_a_holder(api):
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)
        product = h.create_registered_product(api, distributor["id"])
        fleet = h.create_operational_center(
            api,
            {
                "site_name": "Bend Redemption Center",
                "daily_account_cap_containers": 300,
                "opening_cash_cents": 50000,
            },
        )
        account = h.create_account(api)
        return product, fleet["center"], account

    def test_one_container_is_swallowed_and_fifty_lose_exactly_one(self, api):
        """The single container yields nothing; fifty yield forty-nine.

        PRD: "A hand-counted visit is charged a two-per-cent shrink allowance:
        `shrink_adjustment_count` is two per cent of `capped_count` rounded **up** to the next
        whole container, which means any hand-counted visit with a `capped_count` of at least
        1 has a `payable_count` strictly below its `capped_count`."

        PRD: "`PAID_FULL` when its `paid_quantity` equals its `accepted_quantity` *and* that
        accepted quantity is greater than 0, `UNPAID` when its `paid_quantity` is 0, and
        `PAID_PARTIAL` in every remaining case."

        Design: Corner/calculations/hand_count_shrink_ceiling_can_swallow_the_only_container
        """
        product, center, account = self._center_with_a_holder(api)
        headers = h.make_center_headers(center["id"])

        first = h.open_center_hand_visit(api, center["id"], account["id"])
        h.add_lot(api, first["id"], product["id"], 1, headers)
        closed_first = h.close_count(api, first["id"], headers)

        assert_visit_valuation(
            closed_first,
            visit_limit_applied=50,
            capped_count=1,
            shrink_adjustment_count=1,
            payable_count=0,
            refused_over_limit_count=0,
            payout_cents=0,
        )
        assert closed_first["shrink_adjustment_count"] == expected_shrink(1)

        first_lots = h.list_lots(api, first["id"], headers)
        assert first_lots[0]["accepted_quantity"] == 1
        assert_lot_settlement(first_lots[0], paid_quantity=0, reconciliation_flag="UNPAID")

        assert (
            h.read_account(api, account["id"], ADMIN_HEADERS)[
                "containers_redeemed_today"
            ]
            == 0
        )

        second = h.open_center_hand_visit(api, center["id"], account["id"])
        h.add_lot(api, second["id"], product["id"], 50, headers)
        closed_second = h.close_count(api, second["id"], headers)

        assert closed_second["capped_count"] == 50
        assert closed_second["shrink_adjustment_count"] == 1
        assert closed_second["payable_count"] == 49
        assert closed_second["payout_cents"] == 490

        second_lots = h.list_lots(api, second["id"], headers)
        assert second_lots[0]["accepted_quantity"] == 50
        assert_lot_settlement(
            second_lots[0], paid_quantity=49, reconciliation_flag="PAID_PARTIAL"
        )

        assert (
            h.read_account(api, account["id"], ADMIN_HEADERS)[
                "containers_redeemed_today"
            ]
            == 49
        )

        assert_center_pool(
            h.read_center(api, center["id"], headers),
            accepted_container_count=51,
            unbatched_container_count=51,
        )


class TestOutOfStateRatioPrecision:
    """The ratio is recomputed per lot at four places and stays under the hold."""

    def test_one_in_thirty_then_three_in_forty_stay_below_a_tenth(self, api):
        """0.0333 and 0.0750 both sit under the strictly-greater-than test.

        PRD: "`out_of_state_ratio` is `out_of_state_marked_total` divided by
        `presented_total`, rounded to 4 decimal places, and defined as 0 when
        `presented_total` is 0."

        PRD: "The first is out-of-state marking: if the visit's `out_of_state_ratio` —
        computed as in §3.4, rounded to 4 decimal places — is **strictly greater** than one
        tenth, `fraud_hold` becomes true, `withhold_reason` becomes `OUT_OF_STATE_RATIO`, and
        the account's `fraud_strikes` increments by 1 with `last_strike_reason`
        `OUT_OF_STATE_RATIO`."

        Design: Corner/calculations/out_of_state_ratio_rounds_to_four_places_and_stays_below_the_hold
        """
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)
        product = h.create_registered_product(api, distributor["id"])
        fleet = h.create_operational_center(
            api,
            {
                "site_name": "Bend Redemption Center",
                "daily_account_cap_containers": 300,
                "opening_cash_cents": 50000,
            },
        )
        center, machine = fleet["center"], fleet["machine"]
        headers = h.make_center_headers(center["id"])
        visit = h.open_center_machine_visit(api, center["id"], machine["id"])

        first_lot = h.add_lot(
            api,
            visit["id"],
            product["id"],
            30,
            headers,
            out_of_state_marked_quantity=1,
            expected_visit_version=visit["version"],
        )
        after_first = h.read_visit(api, visit["id"], headers)
        assert after_first["out_of_state_ratio"] == 0.0333
        assert_ratio_precision(after_first["out_of_state_ratio"])
        assert after_first["presented_total"] == 30
        assert after_first["out_of_state_marked_total"] == 1
        assert after_first["raw_accepted_count"] == 29

        assert first_lot["accepted_quantity"] == 29
        assert first_lot["rejected_quantity"] == 1
        assert first_lot["reject_reason"] == "OUT_OF_STATE"
        assert first_lot["deposit_value_cents"] == 290

        second_lot = h.add_lot(
            api,
            visit["id"],
            product["id"],
            10,
            headers,
            out_of_state_marked_quantity=2,
        )
        after_second = h.read_visit(api, visit["id"], headers)
        assert after_second["out_of_state_ratio"] == 0.075
        assert after_second["presented_total"] == 40
        assert after_second["out_of_state_marked_total"] == 3
        assert after_second["raw_accepted_count"] == 37
        assert second_lot["accepted_quantity"] == 8
        assert second_lot["reject_reason"] == "OUT_OF_STATE"

        closed = h.close_count(api, visit["id"], headers)
        assert_visit_valuation(
            closed,
            visit_limit_applied=144,
            capped_count=37,
            shrink_adjustment_count=0,
            payable_count=37,
            refused_over_limit_count=0,
            payout_cents=370,
        )
        assert_fraud_posture(closed, False, None, "PENDING")

        assert h.read_machine(api, machine["id"], headers)["bin_filled_count"] == 37


class TestPayableWaterfall:
    """One payable figure spread over four lots gives three different flags."""

    def test_the_waterfall_stops_before_the_last_lot(self, api):
        """240 payable containers pay two lots fully, one partly and one not at all.

        PRD: "Walking the lots in that order, each lot's `paid_quantity` is the lesser of its
        own `accepted_quantity` and whatever remains undistributed, and the remainder shrinks
        by that amount before the next lot is considered."

        PRD: "A machine-counted visit at a redemption centre has a base ceiling of 240
        containers."

        Design: Corner/calculations/payable_waterfall_leaves_the_last_lot_entirely_unpaid
        """
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)
        product = h.create_registered_product(api, distributor["id"])
        fleet = h.create_operational_center(
            api,
            {"site_name": "Bend Redemption Center", "opening_cash_cents": 50000},
        )
        center, machine = fleet["center"], fleet["machine"]
        assert center["daily_account_cap_containers"] == 350
        account = h.create_account(api)
        headers = h.make_center_headers(center["id"])

        visit = h.open_center_machine_visit(
            api, center["id"], machine["id"], account["id"]
        )
        h.add_lots(api, visit["id"], product["id"], [100, 100, 100, 10], headers)

        closed = validate_success(api.close_count(visit["id"], headers))

        assert closed["raw_accepted_count"] == 310
        assert_visit_valuation(
            closed,
            visit_limit_applied=240,
            capped_count=240,
            shrink_adjustment_count=0,
            payable_count=240,
            refused_over_limit_count=70,
            payout_cents=2400,
        )

        lots = h.list_lots(api, visit["id"], headers)
        assert len(lots) == 4
        assert_lot_settlement(lots[0], paid_quantity=100, reconciliation_flag="PAID_FULL")
        assert_lot_settlement(lots[1], paid_quantity=100, reconciliation_flag="PAID_FULL")
        assert_lot_settlement(
            lots[2], paid_quantity=40, reconciliation_flag="PAID_PARTIAL"
        )
        assert_lot_settlement(lots[3], paid_quantity=0, reconciliation_flag="UNPAID")

        assert_fraud_posture(closed, False, None, "PENDING")

        holder = h.read_account(api, account["id"], ADMIN_HEADERS)
        assert holder["containers_redeemed_today"] == 240
        assert holder["cap_reached_today"] is False
        assert_account_standing(holder, "ACTIVE", 0, None)

        assert_center_pool(
            h.read_center(api, center["id"], headers),
            accepted_container_count=310,
            unbatched_container_count=310,
        )


class TestDailyBucketRollover:
    """A bucket belongs to one date, so the next day starts from zero."""

    def test_the_next_days_visit_resets_the_bucket_before_adding(self, api, world):
        """100 containers on the fifth do not narrow the sixth's allowance.

        PRD: "If the account's `redemption_day` differs from the visit's `visit_date`,
        `redemption_day` is set to the visit's date and `containers_redeemed_today` is first
        reset to 0 — the bucket belongs to one date only."

        PRD: "It then works out how much of that cap the account has already used *on this
        visit's date*: the account's `containers_redeemed_today` if the account's
        `redemption_day` equals the visit's `visit_date`, and 0 otherwise, because a bucket
        belonging to an earlier date carries no weight."

        Design: Corner/calculations/daily_bucket_resets_on_the_next_visit_date
        """
        headers = world.center_headers
        day_one = h.create_counted_center_visit(
            api,
            world.center_id,
            world.machine_id,
            world.product_id,
            [100],
            world.account_id,
        )
        holder = h.read_account(api, world.account_id, ADMIN_HEADERS)
        assert holder["containers_redeemed_today"] == 100
        assert holder["redemption_day"] == "2026-08-05"

        h.set_clock(api, NEXT_DAY)
        day_two = h.open_center_machine_visit(
            api, world.center_id, world.machine_id, world.account_id
        )
        assert day_two["visit_date"] == "2026-08-06"
        h.add_lot(api, day_two["id"], world.product_id, 10, headers)
        closed_two = h.close_count(api, day_two["id"], headers)

        assert closed_two["capped_count"] == 10
        assert closed_two["payable_count"] == 10
        assert closed_two["payout_cents"] == 100

        holder = h.read_account(api, world.account_id, ADMIN_HEADERS)
        assert holder["containers_redeemed_today"] == 10
        assert holder["redemption_day"] == "2026-08-06"
        assert holder["cap_reached_today"] is False

        kept = h.read_visit(api, day_one["id"], headers)
        assert kept["payable_count"] == 100
        assert kept["payout_cents"] == 1000

        assert_center_pool(
            h.read_center(api, world.center_id, headers),
            accepted_container_count=110,
        )


class TestCenterPoolCountsCountedVisitsOnly:
    """An unfinished count contributes nothing to the batching pool."""

    def test_the_pool_only_grows_when_the_second_count_closes(self, api):
        """100 containers are visible while 60 are still being counted.

        PRD: "A centre's `accepted_container_count` is the running sum of
        `accepted_quantity` over the container lots of its visits whose `count_status` is
        `COUNTED`; its `batched_container_count` is the running sum of `container_count` over
        its commodity batches whose `status` is `ACCUMULATING`, `SORTED`, `BALED` or `SOLD`;
        and `unbatched_container_count` is `accepted_container_count` minus
        `batched_container_count` — the pool a new batch may draw from."

        Design: Corner/calculations/center_pool_counts_only_counted_visits
        """
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)
        product = h.create_registered_product(api, distributor["id"])
        fleet = h.create_operational_center(
            api,
            {"site_name": "Bend Redemption Center", "opening_cash_cents": 50000},
        )
        center, machine = fleet["center"], fleet["machine"]
        headers = h.make_center_headers(center["id"])

        h.create_counted_center_visit(
            api, center["id"], machine["id"], product["id"], [100]
        )
        second = h.open_center_machine_visit(api, center["id"], machine["id"])
        h.add_lot(api, second["id"], product["id"], 60, headers)

        assert h.read_visit(api, second["id"], headers)["count_status"] == "COUNTING"
        assert_center_pool(
            h.read_center(api, center["id"], headers),
            accepted_container_count=100,
            batched_container_count=0,
            unbatched_container_count=100,
        )

        closed_second = h.close_count(api, second["id"], headers)
        assert closed_second["raw_accepted_count"] == 60
        assert closed_second["payable_count"] == 60

        assert_center_pool(
            h.read_center(api, center["id"], headers),
            accepted_container_count=160,
            unbatched_container_count=160,
        )

        _, meta = validate_paginated(
            api.list_redemption_visits(headers, params={"count_status": "COUNTED"})
        )
        assert meta["total_count"] == 2


class TestLiabilityProjectionIgnoresRevenue:
    """Material revenue sits in the ledger without moving the liability."""

    def test_the_replay_walks_three_lines_and_only_two_move_the_liability(self, api):
        """3000 initiated, 775 earned on glass-free PET and 1000 paid out leave 2000.

        PRD: "Each line contributes its `amount_cents` to the running total, except lines
        whose `entry_type` is `HANDLING_FEE` or `MATERIAL_REVENUE`, which contribute nothing:
        those are pure money movements against programme funding and do not change what the
        programme owes to redeemers."

        PRD: "On success the server stamps `paid_at` with the current logical instant,
        decreases the centre's `cash_drawer_balance_cents` by `payout_cents`, and appends a
        deposit ledger line into that quarter whose `entry_type` is `REDEMPTION_PAID`, whose
        `amount_cents` is the negative of `payout_cents` — paying a redemption discharges
        liability — whose `container_count` is `payable_count`, whose `source_kind` is
        `REDEMPTION_VISIT` and whose `source_ref_id` is this visit's `id`."

        Design: Corner/calculations/liability_projection_ignores_material_revenue_and_tracks_payouts
        """
        world = h.build_world(
            api, center_overrides={"site_name": "Bend Redemption Center"}
        )
        headers = world.center_headers
        h.initiate_deposits(
            api, world.distributor_id, world.product_id, 300, world.period_id
        )
        visit = h.create_counted_center_visit(
            api, world.center_id, world.machine_id, world.product_id, [100]
        )
        h.payout_action(api, visit["id"], "APPROVE", headers)

        batch = h.create_baled_batch(api, world.center_id, 100, 0.0, [50.00])
        sold = h.sell_batch(
            api, batch["id"], world.center_id, "SPOT", 20000, world.period_id
        )
        assert sold["net_revenue_cents"] == 775

        paid = h.payout_action(api, visit["id"], "PAY", headers)

        entries, meta = validate_paginated(
            api.list_ledger_entries(world.period_id, ADMIN_HEADERS)
        )
        assert meta["total_count"] == 3
        assert [entry["entry_type"] for entry in entries] == [
            "DEPOSIT_INITIATED",
            "MATERIAL_REVENUE",
            "REDEMPTION_PAID",
        ]
        assert_ledger_entry(
            entries[0],
            "DEPOSIT_INITIATED",
            amount_cents=3000,
            container_count=300,
            source_kind="DISTRIBUTOR",
            liability_after_cents=3000,
        )
        assert_ledger_entry(
            entries[1],
            "MATERIAL_REVENUE",
            amount_cents=775,
            container_count=0,
            source_kind="COMMODITY_BATCH",
            liability_after_cents=3000,
        )
        assert_ledger_entry(
            entries[2],
            "REDEMPTION_PAID",
            amount_cents=-1000,
            container_count=100,
            source_kind="REDEMPTION_VISIT",
            liability_after_cents=2000,
            source_ref_id=visit["id"],
        )
        assert assert_liability_projection(entries) == 2000

        period = h.read_period(api, world.period_id)
        assert period["outstanding_liability_cents"] == 2000
        assert period["deposits_initiated_cents"] == 3000
        assert period["redemptions_paid_cents"] == 1000
        assert period["material_revenue_cents"] == 775
        assert period["containers_initiated_count"] == 300
        assert period["containers_redeemed_count"] == 100

        assert paid["payout_status"] == "PAID"
        assert_stamped_at(paid["paid_at"], INSTANT)

        assert (
            h.read_center(api, world.center_id, headers)["cash_drawer_balance_cents"]
            == 49000
        )


class TestBagDropAdjustmentDelta:
    """Crediting posts only the true-up, never the whole final credit again."""

    def test_the_provisional_advance_is_topped_up_by_a_hundred_and_fifty(self, api):
        """800 advanced, 950 justified, so the journal shows 800 then 150.

        PRD: "`provisional_units` is the lesser of `declared_count` and 250 units, and
        `provisional_credit_cents` is `provisional_units` multiplied by 8 cents."

        PRD: "From that gross the programme deducts a flat bag service fee of 50 cents,
        exactly once per count: `final_credit_cents` is `gross_final_cents` less 50 cents,
        floored at 0, so a bag holding fewer than five containers yields no credit rather
        than a debt."

        PRD: "It appends a credit journal line with `entry_type` `ADJUSTMENT`, `amount_cents`
        equal to the bag's `adjustment_cents`, `source_kind` `BAG_DROP` and `source_ref_id`
        equal to this bag's `id` — the signed true-up between what was advanced and what the
        count justified — and recomputes the account's `credit_balance_cents`."

        Design: Corner/calculations/bag_drop_variant_switch_posts_only_the_adjustment_delta
        """
        world = h.build_world(
            api, center_overrides={"site_name": "Bend Redemption Center"}
        )
        headers = world.center_headers
        h.initiate_deposits(
            api, world.distributor_id, world.product_id, 300, world.period_id
        )

        bag = h.create_bag_drop(api, world.account_id, world.center_id)
        assert bag["status"] == "DROPPED"
        assert bag["provisional_units"] == 100
        assert bag["provisional_credit_cents"] == 800
        assert_stamped_at(bag["dropped_at"], INSTANT)
        assert (
            h.read_account(api, world.account_id, ADMIN_HEADERS)["credit_balance_cents"]
            == 800
        )

        counted = h.submit_bag_count(api, bag["id"], [60, 40], bag["version"])
        assert counted["status"] == "COUNTED"
        assert_bag_drop_valuation(
            counted,
            counted_lines=2,
            counted_total=100,
            gross_final_cents=1000,
            final_credit_cents=950,
            adjustment_cents=150,
            variance_pct=0.0,
            variance_flag=False,
        )
        holder = h.read_account(api, world.account_id, ADMIN_HEADERS)
        assert holder["credit_balance_cents"] == 800
        assert holder["fraud_strikes"] == 0

        credited = h.settle_bag(api, bag["id"], "CREDIT", headers)
        assert credited["status"] == "CREDITED"
        assert_stamped_at(credited["settled_at"], INSTANT)
        assert (
            h.read_account(api, world.account_id, ADMIN_HEADERS)["credit_balance_cents"]
            == 950
        )

        rows, meta = validate_paginated(
            api.list_credit_entries(world.account_id, ADMIN_HEADERS)
        )
        assert meta["total_count"] == 2
        assert_credit_entry(
            rows[0],
            "PROVISIONAL",
            amount_cents=800,
            balance_after_cents=800,
            source_kind="BAG_DROP",
            source_ref_id=bag["id"],
        )
        assert_credit_entry(
            rows[1],
            "ADJUSTMENT",
            amount_cents=150,
            balance_after_cents=950,
            source_kind="BAG_DROP",
            source_ref_id=bag["id"],
        )

        ledger = h.list_ledger(api, world.period_id, entry_type="BAG_DROP_CREDIT")
        assert len(ledger) == 1
        assert_ledger_entry(
            ledger[0],
            "BAG_DROP_CREDIT",
            amount_cents=-950,
            container_count=100,
            source_kind="BAG_DROP",
            liability_after_cents=2050,
            source_ref_id=bag["id"],
        )

        period = h.read_period(api, world.period_id)
        assert period["redemptions_paid_cents"] == 950
        assert period["containers_redeemed_count"] == 100
        assert period["outstanding_liability_cents"] == 2050
