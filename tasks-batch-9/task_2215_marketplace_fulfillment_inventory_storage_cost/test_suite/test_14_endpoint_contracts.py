"""Endpoint breadth: the bulk receipt that applies two lines in one call, the removal
completion gated on its window opening, the lot age recomputed on read against the bucket a
billing run pins, and the throttle that halves a centre's effective window capacity."""
from test_helpers import (
    ApiErrorId,
    add_line_item,
    api_client,
    complete_removal,
    confirm_plan,
    create_listing,
    create_plan,
    lots_for_listing,
    newest_quota,
    read_fulfillment_center,
    read_listing,
    read_lot,
    read_plan,
    read_removal_order,
    read_seller,
    receive_plan,
    request_removal,
    run_storage_billing,
    set_clock,
    set_receiving_posture,
    setup_baseline,
    setup_received_lot,
    ship_plan,
    validate_error,
    validate_paginated,
)


def _line_rows(plan_id: str, headers) -> list:
    rows, _meta = validate_paginated(api_client.list_plan_line_items(plan_id, headers))
    return rows


def _line_by_id(plan_id: str, headers, line_id: str) -> dict:
    for row in _line_rows(plan_id, headers):
        if row["id"] == line_id:
            return row
    raise AssertionError(f"line item {line_id} missing from plan {plan_id}")


class TestOneReceiveCallAppliesEveryLine:
    """A single truck carrying two SKUs: one line complete, one line 20 units short."""

    def _in_transit_plan_with_two_lines(self) -> dict:
        ctx = setup_baseline()
        ctx["beta_listing_id"] = create_listing(ctx["seller_id"], sku="SKU-BETA")["id"]
        plan = create_plan(
            ctx["seller_id"], ctx["fc_id"], "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"
        )
        ctx["alpha_line"] = add_line_item(
            plan["id"], ctx["seller_id"], ctx["listing_id"], 100
        )
        ctx["beta_line"] = add_line_item(
            plan["id"], ctx["seller_id"], ctx["beta_listing_id"], 50
        )
        confirm_plan(plan["id"], ctx["seller_id"])
        ctx["plan"] = ship_plan(plan["id"], ctx["seller_id"], carrier_reference="CR-14")
        return ctx

    def test_both_lines_are_credited_and_the_shortfall_stays_on_its_own_line(self):
        """130 of the 150 declared units land in one call, and the 20-unit shortfall is
        attributed to the short line alone.

        PRD 3.5: "Each line's own `received_units` accumulates across calls, and the plan's
        `received_units` is the sum over its lines."
        PRD 3.5: "The first link is the crediting itself, together with shortfall arithmetic:
        the plan's `missing_units` becomes its `declared_units` minus its `received_units`, and
        each line's `shortfall_units` becomes that line's declared `units` minus its
        accumulated `received_units`."

        Design: Corner/endpoints/bulk_receive_applies_every_line_atomically_in_one_call
        """
        ctx = self._in_transit_plan_with_two_lines()
        received = receive_plan(
            ctx["plan"]["id"], ctx["fc_id"],
            [
                {
                    "shipment_line_item_id": ctx["alpha_line"]["id"],
                    "received_units": 100,
                    "unfulfillable_units": 0,
                },
                {
                    "shipment_line_item_id": ctx["beta_line"]["id"],
                    "received_units": 30,
                    "unfulfillable_units": 0,
                },
            ],
            receipt_note="one truck, two SKUs",
        )
        assert received["status"] == "PARTIALLY_RECEIVED"
        assert received["received_units"] == 130
        assert received["missing_units"] == 20

        alpha = _line_by_id(
            ctx["plan"]["id"], ctx["seller_headers"], ctx["alpha_line"]["id"]
        )
        beta = _line_by_id(ctx["plan"]["id"], ctx["seller_headers"], ctx["beta_line"]["id"])
        assert alpha["received_units"] == 100
        assert alpha["shortfall_units"] == 0
        assert beta["received_units"] == 30
        assert beta["shortfall_units"] == 20

    def test_each_line_lands_in_its_own_lot_and_only_the_short_listing_reports_missing(self):
        """Two lots, one per line item, and the healthy listing carries no trace of the other
        line's discrepancy while the seller-level ledger carries all 20 units.

        PRD 3.5: "Candidates are lots whose listing matches the line's `sku_listing_id`, whose
        `fulfillment_center_id` matches the plan's `destination_fc_id`, and whose `lot_status`
        is `ACTIVE` or `PARTIALLY_REMOVED`; they are ranked by ascending `first_received_at`,
        with ascending `created_at` as tie-break, and the first candidate wins."
        PRD 2.7: "`open_discrepancy_units` equals the sum of lot-level `missing_units` over the
        lots of that seller's listings whose `reconciliation_status` is `DISCREPANCY_OPEN` or
        `DISCREPANCY_CLAIMED`."

        Design: Corner/endpoints/bulk_receive_applies_every_line_atomically_in_one_call
        """
        ctx = self._in_transit_plan_with_two_lines()
        receive_plan(
            ctx["plan"]["id"], ctx["fc_id"],
            [
                {
                    "shipment_line_item_id": ctx["alpha_line"]["id"],
                    "received_units": 100,
                    "unfulfillable_units": 0,
                },
                {
                    "shipment_line_item_id": ctx["beta_line"]["id"],
                    "received_units": 30,
                    "unfulfillable_units": 0,
                },
            ],
        )
        assert len(lots_for_listing(ctx["listing_id"], ctx["seller_id"])) == 1
        assert len(lots_for_listing(ctx["beta_listing_id"], ctx["seller_id"])) == 1

        alpha_listing = read_listing(ctx["listing_id"], ctx["seller_id"])
        assert alpha_listing["fulfillable_units"] == 100
        assert alpha_listing["missing_units"] == 0
        assert alpha_listing["listing_status"] == "ACTIVE"
        assert alpha_listing["inventory_health"] == "HEALTHY"

        beta_listing = read_listing(ctx["beta_listing_id"], ctx["seller_id"])
        assert beta_listing["fulfillable_units"] == 30
        assert beta_listing["missing_units"] == 20

        assert read_seller(ctx["seller_id"])["open_discrepancy_units"] == 20


class TestRemovalCompletionWaitsForItsWindow:
    """One second early is refused; the exact start instant is accepted."""

    def _requested_disposal_of_twenty_units(self) -> dict:
        ctx = setup_received_lot(units=60)
        ctx["removal"] = request_removal(
            ctx["lot_id"], ctx["seller_id"], 20,
            removal_method="DISPOSAL", unit_pool="FULFILLABLE",
            removal_window_start="2026-09-01T00:00:00Z",
            removal_window_end="2026-09-02T00:00:00Z",
        )
        return ctx

    def test_completion_one_second_before_the_start_is_refused_and_changes_nothing(self):
        """The order is still REQUESTED with its 20 units still reserved and nothing priced.

        PRD 3.6: "the logical clock must have reached the `removal_window_start`, with the exact
        instant accepted, otherwise `ERR_REMOVAL_WINDOW_NOT_OPEN`."
        PRD 3.6: "A successful request opens at `status` of `REQUESTED` with `removal_fee_cents`,
        `liquidation_recovery_cents` and `net_settlement_cents` all at 0 and `completed_at`
        null."

        Design: Corner/endpoints/removal_completion_is_conditional_on_the_window_having_opened
        """
        ctx = self._requested_disposal_of_twenty_units()
        assert ctx["removal"]["removal_fee_cents"] == 0

        set_clock("2026-08-31T23:59:59Z")
        response = api_client.complete_removal_order(
            ctx["removal"]["id"], {}, ctx["fc_headers"]
        )
        validate_error(response, ApiErrorId.ERR_REMOVAL_WINDOW_NOT_OPEN.value, 409)

        order = read_removal_order(ctx["removal"]["id"], ctx["seller_id"])
        assert order["status"] == "REQUESTED"
        assert order["completed_at"] is None
        assert read_lot(ctx["lot_id"], ctx["seller_id"])["units_reserved_for_removal"] == 20

    def test_the_same_call_settles_the_disposal_once_the_clock_reaches_the_start(self):
        """At exactly 2026-09-01 the reservation is retired, the lot becomes partially removed
        and the disposal is priced at 100 plus 15 a unit.

        PRD 3.6: "Completion moves the order `REQUESTED → COMPLETED`, converting the reservation
        into retirement: `requested_units` is subtracted from the lot's
        `units_reserved_for_removal` and added to its `units_removed`, again leaving
        `units_received_total` unchanged."
        PRD 3.6: "Under `DISPOSAL`, `removal_fee_cents` is a base of 100 cents plus 15 cents for
        each requested unit."

        Design: Corner/endpoints/removal_completion_is_conditional_on_the_window_having_opened
        """
        ctx = self._requested_disposal_of_twenty_units()
        set_clock("2026-09-01T00:00:00Z")
        completed = complete_removal(
            ctx["removal"]["id"], ctx["fc_id"], completion_note="disposed on schedule"
        )
        assert completed["status"] == "COMPLETED"
        assert completed["completed_at"].startswith("2026-09-01T00:00:00")
        assert completed["removal_fee_cents"] == 400
        assert completed["liquidation_recovery_cents"] == 0
        assert completed["net_settlement_cents"] == -400

        lot = read_lot(ctx["lot_id"], ctx["seller_id"])
        assert lot["units_reserved_for_removal"] == 0
        assert lot["units_removed"] == 20
        assert lot["fulfillable_units"] == 40
        assert lot["lot_status"] == "PARTIALLY_REMOVED"
        assert lot["last_removal_completed_at"].startswith("2026-09-01T00:00:00")
        assert read_listing(ctx["listing_id"], ctx["seller_id"])["fulfillable_units"] == 40


class TestLotAgeAgainstTheBillingRun:
    """A ten-unit lot read at receipt, read 200 days later, then billed."""

    def _ten_units_received_on_the_first_of_august(self) -> dict:
        return setup_received_lot(units=10)

    def test_age_days_is_refreshed_on_every_read_of_the_lot(self):
        """The lot reads 0 days old on the day it arrives and 200 days old after the clock
        moves, with no billing run in between.

        PRD 3.9: "`age_days` is the whole number of days between the lot's `first_received_at`
        and the logical clock's current instant — the elapsed seconds divided by 86400 seconds
        per day, truncated downward — and it is refreshed both on every read of the lot and on
        every billing run."

        Design: Corner/endpoints/lot_age_days_is_recomputed_on_read_while_bucket_waits_for_a_billing_run
        """
        ctx = self._ten_units_received_on_the_first_of_august()
        assert read_lot(ctx["lot_id"], ctx["seller_id"])["age_days"] == 0

        set_clock("2027-02-17T00:00:00Z")
        assert read_lot(ctx["lot_id"], ctx["seller_id"])["age_days"] == 200

    def test_the_billing_run_pins_the_bucket_and_charges_storage_without_a_surcharge(self):
        """At 200 days the lot sits in the 181-to-270 bucket, so it pays the monthly rate on
        10 cubic feet and no long-term surcharge at all.

        PRD 3.9: "The `aged_bucket` follows from `age_days` by four thresholds evaluated top
        down: `OVER_365` at 365 days or more, `D271_365` at 271 days or more, `D181_270` at 181
        days or more, and `UNDER_181` below that."
        PRD 3.9: "The long-term surcharge is stepped: two steps when the pinned `aged_bucket`
        is `OVER_365`, one step when it is `D271_365`, and none for `D181_270` or `UNDER_181`."

        Design: Corner/endpoints/lot_age_days_is_recomputed_on_read_while_bucket_waits_for_a_billing_run
        """
        ctx = self._ten_units_received_on_the_first_of_august()
        set_clock("2027-02-17T00:00:00Z")
        summary = run_storage_billing(run_note="february epoch")
        assert summary["total_assessed_cents"] == 870

        rows, meta = validate_paginated(
            api_client.list_storage_fee_assessments(ctx["lot_id"], ctx["seller_headers"])
        )
        assert meta["total_count"] == 1
        assert rows[0]["age_days_at_assessment"] == 200
        assert rows[0]["aged_bucket"] == "D181_270"
        assert rows[0]["ltsf_surcharge_cents"] == 0
        assert rows[0]["total_fee_cents"] == 870

        lot = read_lot(ctx["lot_id"], ctx["seller_id"])
        assert lot["aged_bucket"] == "D181_270"
        assert lot["ltsf_exposed"] is False
        assert lot["storage_fee_accrued_cents"] == 870
        assert read_seller(ctx["seller_id"])["storage_fee_accrued_cents"] == 870


class TestThrottlingHalvesTheEffectiveCapacity:
    """Stored capacity 1200, effective ceiling 600: 700 is refused and 600 exactly passes."""

    def _two_drafts_of_seven_hundred_and_six_hundred(self) -> dict:
        ctx = setup_baseline(center={"receiving_capacity_units_per_window": 1200})
        big = create_plan(
            ctx["seller_id"], ctx["fc_id"], "2026-08-10T00:00:00Z", "2026-08-11T00:00:00Z"
        )
        add_line_item(big["id"], ctx["seller_id"], ctx["listing_id"], 700)
        small = create_plan(
            ctx["seller_id"], ctx["fc_id"], "2026-08-10T00:00:00Z", "2026-08-11T00:00:00Z"
        )
        add_line_item(small["id"], ctx["seller_id"], ctx["listing_id"], 600)
        ctx["big_plan_id"] = big["id"]
        ctx["small_plan_id"] = small["id"]
        return ctx

    def test_the_throttle_leaves_stored_capacity_alone_but_refuses_seven_hundred(self):
        """The centre still advertises 1200 units per window, yet the 700-unit plan now
        exceeds the halved ceiling and stays in draft.

        PRD 3.1: "Either an `FcOperator` acting for that centre or a `MarketplaceAdmin` may
        later adjust its posture, revising `receiving_status` to `OPEN`, `THROTTLED` or
        `SUSPENDED`, and revising `receiving_capacity_units_per_window`."
        PRD 3.4: "That total must not exceed the centre's effective capacity, which is
        `receiving_capacity_units_per_window` when the centre's `receiving_status` is `OPEN`
        and the floor of half that figure when it is `THROTTLED`."

        Design: Corner/endpoints/throttling_a_fulfillment_center_halves_its_effective_window_capacity
        """
        ctx = self._two_drafts_of_seven_hundred_and_six_hundred()
        throttled = set_receiving_posture(ctx["fc_id"], receiving_status="THROTTLED")
        assert throttled["receiving_status"] == "THROTTLED"
        assert throttled["receiving_capacity_units_per_window"] == 1200

        response = api_client.confirm_plan(ctx["big_plan_id"], {}, ctx["seller_headers"])
        validate_error(
            response, ApiErrorId.ERR_FC_RECEIVING_CAPACITY_EXCEEDED.value, 422
        )
        assert read_plan(ctx["big_plan_id"], ctx["seller_id"])["status"] == "DRAFT"
        assert read_fulfillment_center(ctx["fc_id"])["committed_receiving_units"] == 0

    def test_six_hundred_units_pass_because_equality_is_accepted(self):
        """The plan that lands exactly on the halved ceiling confirms and takes up the whole
        commitment, reservation and quota consumption.

        PRD 3.4: "Equality passes; only a strict excess is rejected, with
        `ERR_FC_RECEIVING_CAPACITY_EXCEEDED`."
        PRD 3.4: "The seller's `restock_reserved_units` increases by the plan's
        `allocated_units`, the active quota period's `utilized_units` increases by the same
        amount, and the destination centre's `committed_receiving_units` increases by the plan's
        `declared_units`."

        Design: Corner/endpoints/throttling_a_fulfillment_center_halves_its_effective_window_capacity
        """
        ctx = self._two_drafts_of_seven_hundred_and_six_hundred()
        set_receiving_posture(ctx["fc_id"], receiving_status="THROTTLED")

        confirmed = confirm_plan(ctx["small_plan_id"], ctx["seller_id"])
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["final_allocated_units"] == 600

        assert read_fulfillment_center(ctx["fc_id"])["committed_receiving_units"] == 600
        assert read_seller(ctx["seller_id"])["restock_reserved_units"] == 600
        assert newest_quota(ctx["seller_id"])["utilized_units"] == 600
