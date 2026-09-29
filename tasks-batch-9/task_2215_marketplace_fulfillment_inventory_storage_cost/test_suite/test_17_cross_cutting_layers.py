"""Cross-cutting breadth: the two optimistic-concurrency guards rejected then accepted after a
refetch, filtered pagination that stays deterministic across a mutation, the utilization
downgrade that needs a ratio strictly above one, and two aggregates on one listing that read
different lot-status sets."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_line_item,
    api_client,
    classify_unfulfillable,
    complete_removal,
    confirm_plan,
    create_plan,
    inbound_plan_payload,
    lot_version,
    lots_for_listing,
    read_listing,
    read_lot,
    read_quota,
    read_seller,
    receive_plan,
    register_fulfillment_center,
    removal_order_payload,
    request_removal,
    run_storage_billing,
    seller_version,
    set_clock,
    setup_baseline,
    setup_received_lot,
    ship_plan,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStaleSellerVersionThenRefetch:
    """The accepted plan bumps the guard; the replay is refused; the refetch works."""

    def _seller_with_a_quota_and_an_open_centre(self) -> dict:
        ctx = setup_baseline(with_listing=False)
        ctx["version_before"] = seller_version(ctx["seller_id"])
        return ctx

    def _draft_at(self, ctx: dict, start: str, end: str, guard: int):
        return api_client.create_inbound_shipment_plan(
            inbound_plan_payload(ctx["seller_id"], ctx["fc_id"], guard, start, end),
            ctx["seller_headers"],
        )

    def test_replaying_the_same_seller_version_is_refused_without_bumping_it(self):
        """The first plan takes the version from n to n+1; the second call replaying n is a 412
        that leaves the version exactly where the accepted write left it.

        PRD 2.10: "If `expected_seller_account_version` does not equal the seller's current
        `version`, the request is rejected with `ERR_STALE_SELLER_VERSION` (HTTP 412) and nothing
        is persisted."
        PRD 2.10: "A successful plan creation itself increments the seller's `version` by 1, so
        the next creation must quote the new value."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_seller_version_is_rejected_then_accepted_after_refetch
        """
        ctx = self._seller_with_a_quota_and_an_open_centre()
        validate_success(
            self._draft_at(
                ctx, "2026-08-10T00:00:00Z", "2026-08-11T00:00:00Z", ctx["version_before"]
            ),
            201,
        )
        validate_error(
            self._draft_at(
                ctx, "2026-08-12T00:00:00Z", "2026-08-13T00:00:00Z", ctx["version_before"]
            ),
            ApiErrorId.ERR_STALE_SELLER_VERSION.value, 412,
        )
        assert seller_version(ctx["seller_id"]) == ctx["version_before"] + 1

    def test_the_identical_body_succeeds_once_the_guard_is_refetched(self):
        """Nothing about the rejected body was wrong except its guard, so one refetch turns the
        same request into a second draft — and neither draft reserves anything.

        PRD 2.10: "Creating an inbound shipment plan requires a non-optional
        `expected_seller_account_version` field carrying the client's last observed `version` of
        the target `SellerAccount`."
        PRD 2.7: "The first is the seller's reservation ledger: `restock_reserved_units` on a
        `SellerAccount` always equals the sum of `allocated_units` across that seller's inbound
        shipment plans whose `status` is `CONFIRMED`, `IN_TRANSIT` or `PARTIALLY_RECEIVED`."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_seller_version_is_rejected_then_accepted_after_refetch
        """
        ctx = self._seller_with_a_quota_and_an_open_centre()
        self._draft_at(
            ctx, "2026-08-10T00:00:00Z", "2026-08-11T00:00:00Z", ctx["version_before"]
        )
        self._draft_at(
            ctx, "2026-08-12T00:00:00Z", "2026-08-13T00:00:00Z", ctx["version_before"]
        )
        second = validate_success(
            self._draft_at(
                ctx, "2026-08-12T00:00:00Z", "2026-08-13T00:00:00Z",
                seller_version(ctx["seller_id"]),
            ),
            201,
        )
        assert second["status"] == "DRAFT"
        assert seller_version(ctx["seller_id"]) == ctx["version_before"] + 2

        _rows, meta = validate_paginated(
            api_client.list_inbound_shipment_plans(
                ctx["seller_headers"], params={"seller_account_id": ctx["seller_id"]}
            )
        )
        assert meta["total_count"] == 2
        assert read_seller(ctx["seller_id"])["restock_reserved_units"] == 0


class TestStaleLotVersionThenRefetch:
    """Two removals on one lot, each needing a freshly observed lot version."""

    def _lot_of_sixty_units(self) -> dict:
        ctx = setup_received_lot(units=60)
        ctx["version_before"] = lot_version(ctx["lot_id"], ctx["seller_id"])
        return ctx

    def _removal_at(self, ctx: dict, units: int, start: str, end: str, guard: int):
        return api_client.create_removal_order(
            removal_order_payload(
                ctx["lot_id"], guard, units,
                removal_method="DISPOSAL", unit_pool="FULFILLABLE",
                removal_window_start=start, removal_window_end=end,
            ),
            ctx["seller_headers"],
        )

    def test_the_second_removal_is_refused_on_the_guard_not_on_the_window_or_pool(self):
        """The replayed request asks for a non-overlapping window and only 10 of the 40 units
        still free, so the 412 can only come from the version guard.

        PRD 2.10: "Creating a removal order requires a non-optional
        `expected_inventory_lot_version` field carrying the client's last observed `version` of
        the target `InventoryLot`."
        PRD 2.6: "7. Version guards on the two sizing writes described in §2.10 —
        `ERR_STALE_SELLER_VERSION` and `ERR_STALE_LOT_VERSION`, both HTTP 412."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_lot_version_is_rejected_then_accepted_after_refetch
        """
        ctx = self._lot_of_sixty_units()
        first = validate_success(
            self._removal_at(
                ctx, 20, "2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z", ctx["version_before"]
            ),
            201,
        )
        assert first["status"] == "REQUESTED"

        validate_error(
            self._removal_at(
                ctx, 10, "2026-09-10T00:00:00Z", "2026-09-11T00:00:00Z", ctx["version_before"]
            ),
            ApiErrorId.ERR_STALE_LOT_VERSION.value, 412,
        )
        assert lot_version(ctx["lot_id"], ctx["seller_id"]) == ctx["version_before"] + 1

    def test_both_reservations_stand_once_the_lot_version_is_refetched(self):
        """After the refetch the lot carries two requested removals holding 30 units between
        them, with 30 units left fulfillable.

        PRD 2.10: "A successful removal-order creation increments the lot's `version` by 1."
        PRD 2.7: "At the lot level, the same discipline applies: `units_reserved_for_removal` is
        exactly the units held by removal orders on that lot whose `status` is `REQUESTED`,
        `units_removed` is exactly the units retired by removal orders whose `status` is
        `COMPLETED`, and `units_shipped_mcf` is exactly the units consumed by multi-channel
        orders whose `order_status` is `MCF_SHIPPED`."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_lot_version_is_rejected_then_accepted_after_refetch
        """
        ctx = self._lot_of_sixty_units()
        self._removal_at(
            ctx, 20, "2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z", ctx["version_before"]
        )
        self._removal_at(
            ctx, 10, "2026-09-10T00:00:00Z", "2026-09-11T00:00:00Z", ctx["version_before"]
        )
        second = validate_success(
            self._removal_at(
                ctx, 10, "2026-09-10T00:00:00Z", "2026-09-11T00:00:00Z",
                lot_version(ctx["lot_id"], ctx["seller_id"]),
            ),
            201,
        )
        assert second["status"] == "REQUESTED"

        lot = read_lot(ctx["lot_id"], ctx["seller_id"])
        assert lot["version"] == ctx["version_before"] + 2
        assert lot["units_reserved_for_removal"] == 30
        assert lot["fulfillable_units"] == 30

        _rows, meta = validate_paginated(
            api_client.list_lot_removal_orders(ctx["lot_id"], ctx["seller_headers"])
        )
        assert meta["total_count"] == 2


class TestFilteredPaginationStaysDeterministic:
    """Three drafts paged 2 + 1, then one of them confirmed under the same filter."""

    def _three_drafts_in_creation_order(self) -> dict:
        ctx = setup_baseline()
        windows = [
            ("2026-08-10T00:00:00Z", "2026-08-11T00:00:00Z"),
            ("2026-08-12T00:00:00Z", "2026-08-13T00:00:00Z"),
            ("2026-08-14T00:00:00Z", "2026-08-15T00:00:00Z"),
        ]
        ctx["plan_ids"] = []
        for start, end in windows:
            plan = create_plan(ctx["seller_id"], ctx["fc_id"], start, end)
            add_line_item(plan["id"], ctx["seller_id"], ctx["listing_id"], 10)
            ctx["plan_ids"].append(plan["id"])
        return ctx

    def _draft_page(self, ctx: dict, limit: int, offset: int):
        return validate_paginated(
            api_client.list_inbound_shipment_plans(
                ctx["seller_headers"],
                params={
                    "seller_account_id": ctx["seller_id"],
                    "status": "DRAFT",
                    "limit": limit,
                    "offset": offset,
                },
            )
        )

    def test_the_filtered_set_pages_two_then_one_in_creation_order(self):
        """total_count counts the whole filtered set on both pages while has_more flips, and the
        rows arrive oldest first.

        PRD 2.3: "Both appear in the `meta` object of the response envelope alongside
        `total_count` (the total number of items matching the filter, ignoring pagination) and
        `has_more` (true when items remain beyond the current page)."
        PRD 2.3: "Unless a specific list operation says otherwise, list results are sorted by
        `created_at` in ascending order."

        Design: Corner/cross_cutting_complexity_layers/plan_listing_pages_deterministically_under_filter_and_mutation
        """
        ctx = self._three_drafts_in_creation_order()
        first_rows, first_meta = self._draft_page(ctx, 2, 0)
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert [row["id"] for row in first_rows] == ctx["plan_ids"][:2]

        second_rows, second_meta = self._draft_page(ctx, 2, 2)
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert [row["id"] for row in second_rows] == ctx["plan_ids"][2:]

    def test_confirming_one_plan_moves_it_between_the_two_filtered_sets(self):
        """The filter is applied before the window, so the DRAFT page loses a row and the same
        offset now starts at the second plan, while the CONFIRMED filter holds exactly one row
        under the default limit of 10.

        PRD 2.3: "Filters, where a list operation offers them, are exact-match equality on the
        named field and combine conjunctively."
        PRD 2.3: "The `limit` parameter caps the number of items returned; it defaults to 10, its
        minimum accepted value is 1 and its maximum accepted value is 100."

        Design: Corner/cross_cutting_complexity_layers/plan_listing_pages_deterministically_under_filter_and_mutation
        """
        ctx = self._three_drafts_in_creation_order()
        assert confirm_plan(ctx["plan_ids"][0], ctx["seller_id"])["status"] == "CONFIRMED"

        draft_rows, draft_meta = self._draft_page(ctx, 2, 0)
        assert draft_meta["total_count"] == 2
        assert draft_meta["has_more"] is False
        assert [row["id"] for row in draft_rows] == ctx["plan_ids"][1:]

        confirmed_rows, confirmed_meta = validate_paginated(
            api_client.list_inbound_shipment_plans(
                ctx["seller_headers"],
                params={"seller_account_id": ctx["seller_id"], "status": "CONFIRMED"},
            )
        )
        assert confirmed_meta["total_count"] == 1
        assert confirmed_meta["limit"] == 10
        assert [row["id"] for row in confirmed_rows] == ctx["plan_ids"][:1]


class TestUtilizationDowngradeNeedsARatioAboveOne:
    """Exactly at entitlement survives a run; four units over costs one tier step."""

    def _one_hundred_units_against_a_one_hundred_foot_entitlement(self) -> dict:
        ctx = setup_received_lot(
            units=100, seller={"storage_cubic_feet_entitlement": 100.0000}
        )
        return ctx

    def _receive_four_more_units(self, ctx: dict) -> None:
        plan = create_plan(
            ctx["seller_id"], ctx["fc_id"], "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"
        )
        line = add_line_item(
            plan["id"], ctx["seller_id"], ctx["listing_id"], 4, case_pack_units=1
        )
        confirm_plan(plan["id"], ctx["seller_id"])
        ship_plan(plan["id"], ctx["seller_id"])
        receive_plan(plan["id"], ctx["fc_id"], [(line["id"], 4, 0)])

    def test_a_ratio_of_exactly_one_costs_no_capacity(self):
        """100 cubic feet stored against a 100-cubic-foot entitlement reads 1.0000, and the run
        bills 8700 cents while leaving the elevated tier and its 3000-unit limit intact.

        PRD 3.9: "The seller's `storage_utilization_ratio` is that total divided by the seller's
        `storage_cubic_feet_entitlement`, rounded half up to four decimal places."
        PRD 3.9: "When the recomputed `storage_utilization_ratio` is strictly greater than 1.0000
        and the seller has a quota period whose `status` is `ACTIVE`, that period's
        `capacity_tier_downgrade_steps` increases by exactly 1, and the inventory performance
        score is re-run for it so that `capacity_tier` and `restock_limit_units` reflect the new
        step count."

        Design: Corner/cross_cutting_complexity_layers/utilization_downgrade_needs_a_ratio_strictly_above_one
        """
        ctx = self._one_hundred_units_against_a_one_hundred_foot_entitlement()
        assert read_seller(ctx["seller_id"])["storage_utilization_ratio"] == pytest.approx(
            1.0000
        )
        assert read_quota(ctx["quota_id"], ctx["seller_id"])["restock_limit_units"] == 3000

        summary = run_storage_billing(run_note="run at exactly full utilization")
        assert summary["total_assessed_cents"] == 8700

        quota = read_quota(ctx["quota_id"], ctx["seller_id"])
        assert quota["capacity_tier_downgrade_steps"] == 0
        assert quota["capacity_tier"] == "TIER_ELEVATED"
        assert quota["restock_limit_units"] == 3000

    def test_four_units_over_entitlement_cost_exactly_one_step_on_the_next_run(self):
        """A ratio of 1.0400 adds one downgrade step, moving the effective tier to standard and
        halving the limit to 1500 while the score itself stays at 1000.

        PRD 3.1: "The effective tier selects a multiplier — 3.0 for `TIER_ELEVATED`, 1.5 for
        `TIER_STANDARD`, 0.5 for `TIER_RESTRICTED` — and `restock_limit_units` is the floor of
        `base_capacity_units` multiplied by that multiplier."
        PRD 3.9: "At most one step is added per run, however far above entitlement the seller
        sits — repeated overuse costs repeated runs."

        Design: Corner/cross_cutting_complexity_layers/utilization_downgrade_needs_a_ratio_strictly_above_one
        """
        ctx = self._one_hundred_units_against_a_one_hundred_foot_entitlement()
        run_storage_billing(run_note="run at exactly full utilization")
        self._receive_four_more_units(ctx)
        assert read_seller(ctx["seller_id"])["storage_utilization_ratio"] == pytest.approx(
            1.0400
        )

        second = run_storage_billing(run_note="run above full utilization")
        assert second["total_assessed_cents"] == 9048

        quota = read_quota(ctx["quota_id"], ctx["seller_id"])
        assert quota["capacity_tier_downgrade_steps"] == 1
        assert quota["iprs_score"] == 1000
        assert quota["base_capacity_tier"] == "TIER_ELEVATED"
        assert quota["capacity_tier"] == "TIER_STANDARD"
        assert quota["restock_limit_units"] == 1500

        seller = read_seller(ctx["seller_id"])
        assert seller["storage_fee_accrued_cents"] == 17748
        assert seller["seller_status"] == "ACTIVE"


class TestListingAggregatesUseDifferentLotSets:
    """One listing, two lots, and two rollups that disagree about a depleted lot."""

    def _an_active_lot_and_a_depleted_one(self) -> dict:
        ctx = setup_received_lot(units=50)
        second_centre = register_fulfillment_center(fc_code="FC-B1", region_code="US-EAST")
        short_plan = create_plan(
            ctx["seller_id"], second_centre["id"],
            "2026-08-03T00:00:00Z", "2026-08-04T00:00:00Z",
        )
        short_line = add_line_item(
            short_plan["id"], ctx["seller_id"], ctx["listing_id"], 20
        )
        confirm_plan(short_plan["id"], ctx["seller_id"])
        ship_plan(short_plan["id"], ctx["seller_id"])
        receive_plan(short_plan["id"], second_centre["id"], [(short_line["id"], 18, 0)])

        lots = lots_for_listing(ctx["listing_id"], ctx["seller_id"])
        short_lot = next(
            lot for lot in lots if lot["fulfillment_center_id"] == second_centre["id"]
        )
        ctx["second_centre_id"] = second_centre["id"]
        ctx["full_lot_id"] = ctx["lot_id"]
        ctx["short_lot_id"] = short_lot["id"]
        return ctx

    def _classify_and_deplete(self, ctx: dict) -> None:
        classify_unfulfillable(ctx["full_lot_id"], ctx["fc_id"], 10)
        removal = request_removal(
            ctx["short_lot_id"], ctx["seller_id"], 18,
            removal_method="RETURN_TO_SELLER", unit_pool="FULFILLABLE",
            removal_window_start="2026-09-01T00:00:00Z",
            removal_window_end="2026-09-02T00:00:00Z",
        )
        set_clock("2026-09-01T00:00:00Z")
        complete_removal(removal["id"], ctx["second_centre_id"])

    def test_the_two_lots_end_in_different_status_dimensions(self):
        """The classified lot stays active with a 40 / 10 split; the emptied lot is depleted yet
        still remembers its two missing units.

        PRD 3.6: "it moves from either `ACTIVE` or `PARTIALLY_REMOVED` to `DEPLETED` when
        `units_received_total` is at least 1 while `fulfillable_units`, `unfulfillable_units` and
        `units_reserved_for_removal` are all 0."
        PRD 3.6: "The move subtracts that count from the lot's `fulfillable_units` and adds it to
        the lot's `unfulfillable_units`, leaving `units_received_total` unchanged, and stamps
        `unfulfillable_recorded_at` with the logical clock's current instant — the anchor of the
        `DAMAGED_WAREHOUSE` filing deadline."

        Design: Corner/cross_cutting_complexity_layers/listing_aggregates_reconcile_after_classification_and_depletion
        """
        ctx = self._an_active_lot_and_a_depleted_one()
        self._classify_and_deplete(ctx)

        full = read_lot(ctx["full_lot_id"], ctx["seller_id"])
        assert full["fulfillable_units"] == 40
        assert full["unfulfillable_units"] == 10
        assert full["lot_status"] == "ACTIVE"

        short = read_lot(ctx["short_lot_id"], ctx["seller_id"])
        assert short["fulfillable_units"] == 0
        assert short["units_removed"] == 18
        assert short["missing_units"] == 2
        assert short["lot_status"] == "DEPLETED"

    def test_the_listing_sums_stock_over_one_lot_set_and_shortfall_over_a_wider_one(self):
        """The depleted lot contributes nothing to the stock rollups yet still contributes its
        shortfall, which is exactly what keeps the discrepancy visible.

        PRD 3.2: "Its `fulfillable_units` is the sum of `fulfillable_units` over lots of this
        listing whose `lot_status` is `ACTIVE` or `PARTIALLY_REMOVED`; `unfulfillable_units` is
        the sum of `unfulfillable_units` over that same set of lots."
        PRD 3.2: "Its `missing_units` is the sum of lot-level `missing_units` over a wider set —
        lots whose `lot_status` is `ACTIVE`, `PARTIALLY_REMOVED` **or** `DEPLETED` — which is what
        keeps an unreimbursed shortfall visible after the physical units are gone."

        Design: Corner/cross_cutting_complexity_layers/listing_aggregates_reconcile_after_classification_and_depletion
        """
        ctx = self._an_active_lot_and_a_depleted_one()
        self._classify_and_deplete(ctx)

        listing = read_listing(ctx["listing_id"], ctx["seller_id"])
        assert listing["fulfillable_units"] == 40
        assert listing["unfulfillable_units"] == 10
        assert listing["missing_units"] == 2
        assert listing["inventory_health"] == "HEALTHY"
        assert listing["listing_status"] == "ACTIVE"
        assert read_seller(ctx["seller_id"])["open_discrepancy_units"] == 2
