"""The three compensating actions, each measured against the exact ledger it must
restore: the restock reservation, the lot's pool split, and the centre's commitment."""
from test_helpers import (
    add_line_item,
    api_client,
    cancel_plan,
    cancel_removal,
    confirm_plan,
    create_forecast,
    create_plan,
    newest_quota,
    read_fulfillment_center,
    read_listing,
    read_lot,
    read_plan,
    read_removal_order,
    read_seller,
    request_removal,
    revert_plan,
    setup_baseline,
    setup_lot_with_split_pools,
    validate_paginated,
)


def _plan_lines(plan_id: str, headers) -> list:
    rows, _meta = validate_paginated(api_client.list_plan_line_items(plan_id, headers))
    return rows


class TestPlanCancellationRestoresTheReservationLedger:
    """900 reserved units must come back to exactly zero, with no residue anywhere."""

    def _confirmed_plan_of_nine_hundred(self) -> dict:
        ctx = setup_baseline()
        plan = create_plan(
            ctx["seller_id"], ctx["fc_id"], "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"
        )
        line = add_line_item(plan["id"], ctx["seller_id"], ctx["listing_id"], 900)
        ctx["plan"] = confirm_plan(plan["id"], ctx["seller_id"])
        ctx["line_item"] = line
        return ctx

    def test_cancelling_a_confirmed_plan_returns_all_three_ledgers_to_zero(self):
        """The reservation, the quota consumption and the centre's commitment all stood at
        900 and all return to 0 in the same request.

        PRD 3.4: "Cancelling from `CONFIRMED` moves the plan `CONFIRMED → CANCELLED` and
        additionally decrements the seller's `restock_reserved_units` by the plan's
        `allocated_units`, decrements the active quota period's `utilized_units` by the same
        amount, and decrements the destination centre's `committed_receiving_units` by the
        plan's `declared_units`, restoring both conserved ledgers exactly; it then zeroes the
        plan's `allocated_units`, `final_allocated_units` and `provisional_allocated_units`
        before refreshing the other drafts."
        PRD 2.7: "Three operations are explicit **compensating actions** that must restore
        these invariants to their exact pre-operation values: reverting a confirmed plan to
        draft, cancelling a confirmed plan, and cancelling a requested removal order."

        Design: Difficulty/compensating_invariant/plan_cancel_restores_restock_reservation_ledger_exactly
        """
        ctx = self._confirmed_plan_of_nine_hundred()
        assert ctx["plan"]["allocated_units"] == 900
        assert read_seller(ctx["seller_id"])["restock_reserved_units"] == 900
        assert newest_quota(ctx["seller_id"])["utilized_units"] == 900

        cancelled = cancel_plan(
            ctx["plan"]["id"], ctx["seller_id"], cancellation_reason="supplier delay"
        )
        assert cancelled["status"] == "CANCELLED"
        assert read_seller(ctx["seller_id"])["restock_reserved_units"] == 0
        assert newest_quota(ctx["seller_id"])["utilized_units"] == 0
        assert read_fulfillment_center(ctx["fc_id"])["committed_receiving_units"] == 0

    def test_cancellation_zeroes_every_allocation_figure_but_keeps_the_declaration(self):
        """Both allocation figures on the plan and on its line go to 0 while
        `declared_units` still records what was intended, and nothing counts as in flight.

        PRD 2.7: "The first is the seller's reservation ledger: `restock_reserved_units` on a
        `SellerAccount` always equals the sum of `allocated_units` across that seller's
        inbound shipment plans whose `status` is `CONFIRMED`, `IN_TRANSIT` or
        `PARTIALLY_RECEIVED`."
        PRD 3.3: "`in_flight_units` is the sum of `units` over line items for this listing
        that belong to plans whose `status` is `CONFIRMED`, `IN_TRANSIT` or
        `PARTIALLY_RECEIVED`; line items on plans in `DRAFT`, `CANCELLED`,
        `RECEIVED_COMPLETE` or `CLOSED` are excluded."

        Design: Difficulty/compensating_invariant/plan_cancel_restores_restock_reservation_ledger_exactly
        """
        ctx = self._confirmed_plan_of_nine_hundred()
        cancel_plan(
            ctx["plan"]["id"], ctx["seller_id"], cancellation_reason="supplier delay"
        )

        plan = read_plan(ctx["plan"]["id"], ctx["seller_id"])
        assert plan["allocated_units"] == 0
        assert plan["final_allocated_units"] == 0
        assert plan["provisional_allocated_units"] == 0
        assert plan["declared_units"] == 900

        forecast = create_forecast(ctx["listing_id"], ctx["seller_id"])
        assert forecast["in_flight_units"] == 0


class TestRemovalCancellationRestoresTheLotPoolSplit:
    """30 reserved units must return to the pool they came from, not to the other one."""

    def _requested_removal_from_the_unfulfillable_pool(self) -> dict:
        ctx = setup_lot_with_split_pools(70, 30)
        ctx["removal"] = request_removal(
            ctx["lot_id"], ctx["seller_id"], 30,
            removal_method="DISPOSAL", unit_pool="UNFULFILLABLE",
            removal_window_start="2026-09-01T00:00:00Z",
            removal_window_end="2026-09-02T00:00:00Z",
        )
        return ctx

    def test_cancellation_returns_the_units_to_the_unfulfillable_pool(self):
        """The 30 units go back where they were drawn from, leaving the fulfillable pool at
        70 and the lot's total untouched throughout.

        PRD 3.6: "The move `REQUESTED → CANCELLED` returns the reservation to the pool it
        came from: `requested_units` is subtracted from the lot's `units_reserved_for_removal`
        and added back to `fulfillable_units` when the order's `unit_pool` was `FULFILLABLE`,
        or back to `unfulfillable_units` when it was `UNFULFILLABLE` — restoring the exact
        pool split and leaving `units_received_total` unchanged."
        PRD 2.7: "The second is the lot's unit conservation: the cumulative
        `units_received_total` of an `InventoryLot` always equals the sum of its
        `fulfillable_units`, `unfulfillable_units`, `units_reserved_for_removal`,
        `units_removed` and `units_shipped_mcf`."

        Design: Difficulty/compensating_invariant/removal_cancel_restores_lot_pool_split_exactly
        """
        ctx = self._requested_removal_from_the_unfulfillable_pool()
        before = read_lot(ctx["lot_id"], ctx["seller_id"])
        assert before["units_reserved_for_removal"] == 30
        assert before["unfulfillable_units"] == 0

        cancelled = cancel_removal(
            ctx["removal"]["id"], ctx["seller_id"],
            cancellation_reason="will liquidate instead",
        )
        assert cancelled["status"] == "CANCELLED"

        lot = read_lot(ctx["lot_id"], ctx["seller_id"])
        assert lot["unfulfillable_units"] == 30
        assert lot["fulfillable_units"] == 70
        assert lot["units_reserved_for_removal"] == 0
        assert lot["units_removed"] == 0
        assert lot["units_received_total"] == 100
        assert lot["lot_status"] == "ACTIVE"

    def test_a_cancelled_removal_never_settles_and_the_listing_rollup_follows(self):
        """No money is priced on the cancelled order, and the listing's unfulfillable
        rollup is back to 30 with the listing still active.

        PRD 3.6: "`removal_fee_cents`, `liquidation_recovery_cents` and
        `net_settlement_cents` all stay at 0, and `completed_at` stays null: a cancelled
        removal never settles."
        PRD 3.2: "Its `fulfillable_units` is the sum of `fulfillable_units` over lots of this
        listing whose `lot_status` is `ACTIVE` or `PARTIALLY_REMOVED`; `unfulfillable_units`
        is the sum of `unfulfillable_units` over that same set of lots."

        Design: Difficulty/compensating_invariant/removal_cancel_restores_lot_pool_split_exactly
        """
        ctx = self._requested_removal_from_the_unfulfillable_pool()
        cancel_removal(
            ctx["removal"]["id"], ctx["seller_id"],
            cancellation_reason="will liquidate instead",
        )

        order = read_removal_order(ctx["removal"]["id"], ctx["seller_id"])
        assert order["removal_fee_cents"] == 0
        assert order["liquidation_recovery_cents"] == 0
        assert order["net_settlement_cents"] == 0
        assert order["completed_at"] is None

        listing = read_listing(ctx["listing_id"], ctx["seller_id"])
        assert listing["unfulfillable_units"] == 30
        assert listing["fulfillable_units"] == 70
        assert listing["listing_status"] == "ACTIVE"


class TestRevertToDraftRestoresTheCentreCommitment:
    """500 committed units must come back to zero and the plan must be re-sized as a draft."""

    def _confirmed_plan_of_five_hundred(self) -> dict:
        ctx = setup_baseline()
        plan = create_plan(
            ctx["seller_id"], ctx["fc_id"], "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"
        )
        line = add_line_item(plan["id"], ctx["seller_id"], ctx["listing_id"], 500)
        ctx["plan"] = confirm_plan(plan["id"], ctx["seller_id"])
        ctx["line_item"] = line
        return ctx

    def test_reverting_releases_the_centre_commitment_and_the_reservation(self):
        """The centre's commitment stood at 500 and returns to 0, along with the seller's
        reservation and the period's consumption.

        PRD 3.4: "It decrements the seller's `restock_reserved_units` by the plan's
        `allocated_units`, decrements the active quota period's `utilized_units` by the same
        amount, and decrements the destination centre's `committed_receiving_units` by the
        plan's `declared_units` — restoring both conserved ledgers exactly."
        PRD 2.7: "The third is the centre's receiving commitment: `committed_receiving_units`
        on a `FulfillmentCenter` always equals the sum of `declared_units` across plans whose
        `destination_fc_id` is that centre and whose `status` is `CONFIRMED`, `IN_TRANSIT` or
        `PARTIALLY_RECEIVED`."

        Design: Difficulty/compensating_invariant/plan_revert_to_draft_restores_fc_committed_units_exactly
        """
        ctx = self._confirmed_plan_of_five_hundred()
        assert ctx["plan"]["status"] == "CONFIRMED"
        assert read_fulfillment_center(ctx["fc_id"])["committed_receiving_units"] == 500

        reverted = revert_plan(
            ctx["plan"]["id"], ctx["seller_id"], revert_reason="line items need editing"
        )
        assert reverted["status"] == "DRAFT"
        assert read_fulfillment_center(ctx["fc_id"])["committed_receiving_units"] == 0
        assert read_seller(ctx["seller_id"])["restock_reserved_units"] == 0
        assert newest_quota(ctx["seller_id"])["utilized_units"] == 0

    def test_reverting_clears_the_final_figures_and_re_derives_the_provisional_ones(self):
        """The plan drops every FINAL figure and its stamp, then re-sizes itself as a draft
        granting the full 500 units within limit.

        PRD 3.4: "It then zeroes the plan's `allocated_units` and `final_allocated_units` and
        every line's `final_allocated_units`, resets `prep_compliance_status` to `PENDING`,
        sets `confirmed_at` back to null, and recomputes the `PROVISIONAL` waterfall for this
        plan."
        PRD 3.3: "For `PROVISIONAL`, each line's grant is written to its
        `provisional_allocated_units` and the total to the plan's
        `provisional_allocated_units`; the plan's `allocation_status` becomes `WITHIN_LIMIT`
        when that total equals `declared_units` and `OVER_LIMIT` otherwise."

        Design: Difficulty/compensating_invariant/plan_revert_to_draft_restores_fc_committed_units_exactly
        """
        ctx = self._confirmed_plan_of_five_hundred()
        reverted = revert_plan(
            ctx["plan"]["id"], ctx["seller_id"], revert_reason="line items need editing"
        )
        assert reverted["provisional_allocated_units"] == 500

        plan = read_plan(ctx["plan"]["id"], ctx["seller_id"])
        assert plan["confirmed_at"] is None
        assert plan["final_allocated_units"] == 0
        assert plan["allocated_units"] == 0
        assert plan["allocation_status"] == "WITHIN_LIMIT"
        assert plan["prep_compliance_status"] == "PENDING"

        line = _plan_lines(ctx["plan"]["id"], ctx["seller_headers"])[0]
        assert line["final_allocated_units"] == 0
        assert line["provisional_allocated_units"] == 500
