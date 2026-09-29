"""Exact thresholds: the 271-day long-term surcharge step, the zero-line confirmation
floor, and the last fulfillable unit of a lot."""
from test_helpers import (
    ApiErrorId,
    add_line_item,
    api_client,
    confirm_plan,
    create_plan,
    newest_quota,
    place_multi_channel_order,
    read_fulfillment_center,
    read_listing,
    read_lot,
    read_plan,
    read_seller,
    run_storage_billing,
    set_clock,
    setup_baseline,
    setup_received_lot,
    validate_error,
    validate_paginated,
)


def _assessments(lot_id: str, headers) -> list:
    rows, _meta = validate_paginated(
        api_client.list_storage_fee_assessments(lot_id, headers)
    )
    return rows


class TestLongTermSurchargeBucketBoundary:
    """30 cubic feet held from 2026-08-01: 270 aged days is free of surcharge, 271 is not."""

    def _thirty_units_received_on_the_first_of_august(self) -> dict:
        return setup_received_lot(
            units=30,
            appointment_window_start="2026-08-01T00:00:00Z",
            appointment_window_end="2026-08-02T00:00:00Z",
        )

    def test_two_hundred_seventy_aged_days_carries_no_long_term_surcharge(self):
        """At 270 days the lot pins the D181_270 bucket, so the run assesses only the
        2610-cent monthly fee — and the completed plan is swept closed.

        PRD 3.9: "The `aged_bucket` follows from `age_days` by four thresholds evaluated top
        down: `OVER_365` at 365 days or more, `D271_365` at 271 days or more, `D181_270` at
        181 days or more, and `UNDER_181` below that."
        PRD 3.9: "The long-term surcharge is stepped: two steps when the pinned `aged_bucket`
        is `OVER_365`, one step when it is `D271_365`, and none for `D181_270` or
        `UNDER_181`."

        Design: Difficulty/boundary_precision_check/ltsf_bucket_boundary_flips_at_exactly_271_aged_days
        """
        ctx = self._thirty_units_received_on_the_first_of_august()
        set_clock("2027-04-28T00:00:00Z")
        summary = run_storage_billing(run_note="epoch at 270 days")
        assert summary["billing_run_sequence"] == 1
        assert summary["total_assessed_cents"] == 2610
        assert summary["closed_plan_count"] == 1
        assert read_plan(ctx["plan"]["id"], ctx["seller_id"])["status"] == "CLOSED"

        row = _assessments(ctx["lot_id"], ctx["seller_headers"])[0]
        assert row["age_days_at_assessment"] == 270
        assert row["aged_bucket"] == "D181_270"
        assert row["ltsf_surcharge_cents"] == 0
        assert row["total_fee_cents"] == 2610

    def test_two_hundred_seventy_one_aged_days_adds_exactly_one_surcharge_step(self):
        """One further day flips the bucket to D271_365, which adds a single 18600-cent
        surcharge step on top of the unchanged monthly fee.

        PRD 3.9: "`ltsf_surcharge_cents` is `billable_cubic_feet` multiplied by the centre's
        `ltsf_rate_cents_per_cubic_foot` multiplied by that step count, rounded half up to
        whole cents."
        PRD 3.9: "`total_fee_cents` is `monthly_storage_fee_cents` plus
        `ltsf_surcharge_cents`."

        Design: Difficulty/boundary_precision_check/ltsf_bucket_boundary_flips_at_exactly_271_aged_days
        """
        ctx = self._thirty_units_received_on_the_first_of_august()
        set_clock("2027-04-28T00:00:00Z")
        run_storage_billing(run_note="epoch at 270 days")
        set_clock("2027-04-29T00:00:00Z")
        second = run_storage_billing(run_note="epoch at 271 days")
        assert second["billing_run_sequence"] == 2
        assert second["total_assessed_cents"] == 21210
        assert second["closed_plan_count"] == 0

        row = _assessments(ctx["lot_id"], ctx["seller_headers"])[1]
        assert row["age_days_at_assessment"] == 271
        assert row["aged_bucket"] == "D271_365"
        assert row["monthly_storage_fee_cents"] == 2610
        assert row["ltsf_surcharge_cents"] == 18600
        assert row["total_fee_cents"] == 21210

    def test_crossing_the_boundary_sets_the_exposure_flag_and_accrues_both_runs(self):
        """After the second run the lot reads 271 aged days, flags its long-term exposure
        and carries the summed 23820 cents, as does the seller.

        PRD 3.9: "A lot's `ltsf_exposed` flag is true exactly when its most recent
        assessment carried a `ltsf_surcharge_cents` greater than zero."
        PRD 3.9: "`age_days` is the whole number of days between the lot's
        `first_received_at` and the logical clock's current instant — the elapsed seconds
        divided by 86400 seconds per day, truncated downward — and it is refreshed both on
        every read of the lot and on every billing run."

        Design: Difficulty/boundary_precision_check/ltsf_bucket_boundary_flips_at_exactly_271_aged_days
        """
        ctx = self._thirty_units_received_on_the_first_of_august()
        set_clock("2027-04-28T00:00:00Z")
        first = run_storage_billing(run_note="epoch at 270 days")
        set_clock("2027-04-29T00:00:00Z")
        second = run_storage_billing(run_note="epoch at 271 days")
        assert first["downgraded_quota_count"] == 0
        assert first["expired_quota_count"] == 0
        assert second["downgraded_quota_count"] == 0
        assert second["expired_quota_count"] == 0

        lot = read_lot(ctx["lot_id"], ctx["seller_id"])
        assert lot["age_days"] == 271
        assert lot["ltsf_exposed"] is True
        assert lot["storage_fee_accrued_cents"] == 23820
        assert read_seller(ctx["seller_id"])["storage_fee_accrued_cents"] == 23820


class TestEmptyLineItemSetAtConfirmation:
    """Zero line items is the rejected side of the boundary; one line item passes."""

    def test_a_draft_with_no_line_items_cannot_be_confirmed(self):
        """A plan carrying no lines is refused at confirmation and nothing about it moves.

        PRD 3.4: "The plan's `status` must be `DRAFT` (`ERR_PLAN_NOT_DRAFT`); it must carry
        at least one line item (`ERR_PLAN_HAS_NO_LINE_ITEMS`); the destination centre's
        `receiving_status` must be `OPEN` or `THROTTLED`, never `SUSPENDED`
        (`ERR_FC_RECEIVING_SUSPENDED`)"
        PRD 3.3: "A new plan opens with `status` of `DRAFT`, `declared_units` of 0,
        `allocation_status` of `WITHIN_LIMIT`, `prep_compliance_status` of `PENDING`,
        `confirmed_at` of null, and every allocation and receipt figure at 0."

        Design: Difficulty/boundary_precision_check/confirm_plan_with_empty_line_item_set_boundary_rejected
        """
        ctx = setup_baseline()
        plan = create_plan(
            ctx["seller_id"], ctx["fc_id"], "2026-08-10T00:00:00Z", "2026-08-11T00:00:00Z"
        )
        response = api_client.confirm_plan(plan["id"], {}, ctx["seller_headers"])
        validate_error(response, ApiErrorId.ERR_PLAN_HAS_NO_LINE_ITEMS.value)

        stored = read_plan(plan["id"], ctx["seller_id"])
        assert stored["status"] == "DRAFT"
        assert stored["declared_units"] == 0
        assert stored["provisional_allocated_units"] == 0
        assert stored["confirmed_at"] is None
        assert newest_quota(ctx["seller_id"])["utilized_units"] == 0
        assert read_fulfillment_center(ctx["fc_id"])["committed_receiving_units"] == 0

    def test_a_single_line_item_is_enough_to_clear_the_structural_floor(self):
        """One line takes the plan over the floor, and the same confirmation now lands.

        PRD 3.4: "A successful confirmation moves the plan `DRAFT → CONFIRMED` and lands a
        coordinated set of writes."
        PRD 3.3: "Adding a line recomputes the plan's `declared_units` as the sum of `units`
        across its line items, and re-runs the provisional allocation waterfall."

        Design: Difficulty/boundary_precision_check/confirm_plan_with_empty_line_item_set_boundary_rejected
        """
        ctx = setup_baseline()
        plan = create_plan(
            ctx["seller_id"], ctx["fc_id"], "2026-08-10T00:00:00Z", "2026-08-11T00:00:00Z"
        )
        add_line_item(plan["id"], ctx["seller_id"], ctx["listing_id"], 100)
        confirmed = confirm_plan(plan["id"], ctx["seller_id"])
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["declared_units"] == 100
        assert confirmed["allocated_units"] == 100


class TestMcfDrawExhaustsTheFulfillablePoolExactly:
    """40 units against a 40-unit lot is the accepted boundary; the next unit is not."""

    def test_the_draw_empties_the_lot_and_depletes_it(self):
        """The order consumes the whole lot in one allocation, which sends the lot to
        DEPLETED and suppresses the listing for ZERO_FULFILLABLE.

        PRD 3.7: "From each lot in turn the draw is the smaller of that lot's
        `fulfillable_units` and the units still needed; the lot's `fulfillable_units`
        decreases by the draw, its `units_shipped_mcf` increases by the draw, and an object
        naming that lot's identifier and the drawn count is appended to the order's
        `consumed_lot_allocations` in draw order."
        PRD 3.7: "A lot emptied by the draw — `units_received_total` of at least 1 with
        `fulfillable_units`, `unfulfillable_units` and `units_reserved_for_removal` all at 0
        — moves to `DEPLETED` exactly as it would after a removal."

        Design: Difficulty/boundary_precision_check/mcf_draw_exhausts_fulfillable_pool_exactly_then_next_unit_rejected
        """
        ctx = setup_received_lot(units=40)
        order = place_multi_channel_order(
            ctx["seller_id"], ctx["listing_id"], 40, 2.00, "ZONE_2", "MCF", 19400
        )
        assert order["mcf_fee_cents"] == 19400
        assert order["order_status"] == "MCF_SHIPPED"
        assert order["consumed_lot_allocations"] == [
            {"inventory_lot_id": ctx["lot_id"], "units": 40}
        ]

        lot = read_lot(ctx["lot_id"], ctx["seller_id"])
        assert lot["fulfillable_units"] == 0
        assert lot["units_shipped_mcf"] == 40
        assert lot["units_received_total"] == 40
        assert lot["lot_status"] == "DEPLETED"

        listing = read_listing(ctx["listing_id"], ctx["seller_id"])
        assert listing["listing_status"] == "SUPPRESSED"
        assert listing["suppression_reason"] == "ZERO_FULFILLABLE"
        assert listing["inventory_health"] == "OUT_OF_STOCK"

    def test_one_unit_beyond_the_pool_is_rejected_and_nothing_is_persisted(self):
        """With the pool at zero the next single-unit order finds no candidate lot, so no
        order row survives and the seller's accrual stops at the first order's fee.

        PRD 3.7: "If the candidates are exhausted while units are still needed, the entire
        request is rejected with `ERR_NO_FULFILLABLE_INVENTORY` and nothing whatsoever is
        persisted — no partial draw, no order row."
        PRD 2.7: "And `mcf_fee_accrued_cents` equals the sum of `mcf_fee_cents` across that
        seller's multi-channel orders whose `order_status` is `MCF_SHIPPED`."

        Design: Difficulty/boundary_precision_check/mcf_draw_exhausts_fulfillable_pool_exactly_then_next_unit_rejected
        """
        ctx = setup_received_lot(units=40)
        place_multi_channel_order(
            ctx["seller_id"], ctx["listing_id"], 40, 2.00, "ZONE_2", "MCF", 19400
        )
        response = api_client.create_multi_channel_order(
            {
                "sku_listing_id": ctx["listing_id"],
                "units": 1,
                "billable_weight_lb": 2.00,
                "destination_zone": "ZONE_2",
                "fulfillment_channel": "MCF",
                "self_fulfilled_cost_cents": 19400,
            },
            ctx["seller_headers"],
        )
        validate_error(response, ApiErrorId.ERR_NO_FULFILLABLE_INVENTORY.value)

        _rows, meta = validate_paginated(
            api_client.list_listing_multi_channel_orders(
                ctx["listing_id"], ctx["seller_headers"]
            )
        )
        assert meta["total_count"] == 1
        assert read_seller(ctx["seller_id"])["mcf_fee_accrued_cents"] == 19400
