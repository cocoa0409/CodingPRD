"""Two coexisting valuations on a gear unit, and two coexisting prices on a repair order.

PRD §2.8 keeps a depreciated-purchase basis and a successor-MSRP basis on the
same unit at all times; PRD §3.7 keeps a PROVISIONAL quote and a FINAL invoice
on the same order, priced by the same arithmetic over different inputs.
"""

from test_helpers import (
    assert_common_fields,
    assert_estimate_breakdown,
    assert_money_cents,
    factories,
    validate_success,
)


# ==========================================================================
# Builders for the expedited paid-repair order the pricing instance needs.
# The `catalogue` fixture already pins the clock to 2026-06-15T09:00:00Z and
# wires the centre, the Ascent 2P/3P model pair, the PRO owner, unit
# AS2-00417 and the two certified technicians (PRD §3.1, §3.2).
# ==========================================================================
def _expedited_paid_order_with_provisional_quote(world):
    """Drive a PAID_REPAIR_REQUEST to an expedited order carrying a SENT quote.

    Assessment is USER_DAMAGE over FABRIC + ZIPPER, so adjudication offers paid
    repair; the order is opened with `expedite_requested` true and quoted for
    FABRIC 25 min + ZIPPER 35 min plus one 1800-cent slider.
    """
    scenario = world.scenario
    zip_lot = scenario.part_lot(
        world.model_id,
        part_code=factories.ZIP_PART_CODE,
        part_kind="ZIPPER_SLIDER",
        on_hand_units=4,
        unit_price_cents=3100,
        low_watermark_units=1,
    )
    claim = scenario.claim(
        world.center_id,
        world.item_id,
        intake_kind="PAID_REPAIR_REQUEST",
        reported_defect_type="ZIPPER_FAILURE",
        customer_narrative="Door zipper torn after a snag; also a scuffed floor patch.",
    )
    submitted = scenario.submit(claim["id"])
    scenario.assess(
        claim["id"],
        world.technician_id,
        expected_claim_version=submitted["version"],
        determination="USER_DAMAGE",
        required_work_types=["FABRIC", "ZIPPER"],
        estimated_labor_lines=[
            factories.labor_line("FABRIC", 25),
            factories.labor_line("ZIPPER", 35),
        ],
        estimated_parts_cents=1800,
        defect_notes="Snag damage, not a defect: zipper tape torn, floor abrasion.",
    )
    scenario.decide(claim["id"], decision_note="User damage: quote as paid repair.")
    order = scenario.repair_order(claim["id"], expedite_requested=True)
    provisional = scenario.estimate(
        order["id"],
        expected_repair_order_version=order["version"],
        labor_lines=[
            factories.labor_line("FABRIC", 25),
            factories.labor_line("ZIPPER", 35),
        ],
        parts_lines=[factories.parts_line(factories.ZIP_PART_CODE, 1, 1800)],
    )
    return {
        "zip_lot": zip_lot,
        "zip_lot_id": zip_lot["id"],
        "claim_id": claim["id"],
        "order": order,
        "order_id": order["id"],
        "provisional": provisional,
        "provisional_id": provisional["id"],
    }


def _drive_to_qc_passed(world, ctx):
    """Approve the quote, log 30 FABRIC + 40 ZIPPER actual minutes, consume the slider.

    Quality control is signed by the technician who authored no assessment on
    the claim, leaving the order in QC_PASSED / ESTIMATE_APPROVED.
    """
    scenario = world.scenario
    scenario.approve_estimate(ctx["provisional_id"], world.customer_id)
    fabric_block = scenario.work_block(
        ctx["order_id"],
        world.technician_id,
        work_type="FABRIC",
        start_at="2026-06-16T09:00:00Z",
        end_at="2026-06-16T11:00:00Z",
    )
    zipper_block = scenario.work_block(
        ctx["order_id"],
        world.technician_id,
        work_type="ZIPPER",
        start_at="2026-06-16T11:00:00Z",
        end_at="2026-06-16T13:00:00Z",
    )
    reservation = scenario.reserve_parts(
        ctx["order_id"], ctx["zip_lot_id"], factories.ZIP_PART_CODE, 1
    )
    scenario.consume_parts(reservation["id"], world.technician_id)
    scenario.bench_complete(
        ctx["order_id"],
        world.technician_id,
        [
            factories.work_log_entry(fabric_block["id"], 30),
            factories.work_log_entry(zipper_block["id"], 40),
        ],
    )
    scenario.qc(
        ctx["order_id"],
        world.second_technician_id,
        outcome="PASS",
        notes="Zipper runs clean, patch bonded.",
    )
    ctx.update(
        fabric_block=fabric_block,
        zipper_block=zipper_block,
        reservation=reservation,
        reservation_id=reservation["id"],
    )
    return ctx


class TestGearItemReplacementValueVariantDivergence:
    """PRD §2.8 — the depreciated-purchase basis and the successor-MSRP basis."""

    def test_depreciated_basis_walks_the_purchase_price_down_by_completed_years(
        self, catalogue
    ):
        """Unit AS2-00417 is 37 months old, so 30% depreciation leaves 52430 cents.

        "First, `age_months` is the number of whole months elapsed from the unit's `purchase_date` to the logical clock instant, floored, where a month is counted as elapsed once the same day-of-month is reached."
        "The depreciation fraction is ten percent for each completed year, capped so it can never exceed sixty percent — that is, the lesser of 0.60 and 0.10 multiplied by the completed years."
        "The depreciated value is then the greater of that residual floor and the unit's `purchase_price_cents` multiplied by one minus the depreciation fraction, rounded half up to whole cents."
        "Coverage is a three-valued field: `warranty_state` is `LIFETIME` whenever the unit's model carries `lifetime_warranty`; otherwise it is `IN_WARRANTY` as long as the logical clock instant is at or before the `purchase_date` advanced by the model's `warranty_years` in whole calendar years; and otherwise it is `EXPIRED`."

        Design: Difficulty/dual_variant_calc/gear_item_replacement_value_variant_divergence
        """
        item = catalogue.item

        assert item["age_months"] == 37, item
        assert item["warranty_state"] == "IN_WARRANTY", item
        assert_money_cents(item["replacement_value_depreciated_cents"])
        assert item["replacement_value_depreciated_cents"] == 52430, item

    def test_residual_floor_does_not_bind_and_the_successor_catalogue_is_ignored(
        self, catalogue
    ):
        """The 19975-cent residual floor loses the greater-of against 52430 cents.

        "A residual floor is computed as the model's own `msrp_cents` multiplied by twenty-five percent, rounded half up to whole cents."
        "The depreciated value is then the greater of that residual floor and the unit's `purchase_price_cents` multiplied by one minus the depreciation fraction, rounded half up to whole cents."
        "This basis ignores the successor catalogue entirely."

        Design: Difficulty/dual_variant_calc/gear_item_replacement_value_variant_divergence
        """
        item = catalogue.scenario.read_item(catalogue.item_id)

        assert catalogue.model["msrp_cents"] == 79900, catalogue.model
        assert item["replacement_value_depreciated_cents"] == 52430, item
        assert item["replacement_value_depreciated_cents"] != 19975, (
            "the residual floor must lose the greater-of on this unit"
        )
        assert item["replacement_value_depreciated_cents"] > 19975, item

    def test_successor_basis_prices_ninety_percent_of_the_successor_msrp(
        self, catalogue
    ):
        """The discontinued model's successor MSRP of 99900 cents prices out at 89910.

        "The base list price is the successor model's `msrp_cents` when the unit's model has both a non-null `discontinued_at` and a non-null `successor_model_id`; in every other case it is the unit's own model's `msrp_cents`."
        "The successor valuation is that base list price multiplied by ninety percent, rounded half up to whole cents."
        "This basis ignores what the customer paid and how old the unit is."

        Design: Difficulty/dual_variant_calc/gear_item_replacement_value_variant_divergence
        """
        assert catalogue.model["discontinued_at"] is not None, catalogue.model
        assert catalogue.model["successor_model_id"] == catalogue.successor_id
        assert catalogue.successor["msrp_cents"] == 99900, catalogue.successor

        item = catalogue.item
        assert_money_cents(item["replacement_value_successor_cents"])
        assert item["replacement_value_successor_cents"] == 89910, item

    def test_both_valuations_coexist_on_one_row_and_diverge_by_37480_cents(
        self, catalogue, api, agent_headers
    ):
        """One read of the unit carries both bases, 37480 cents apart.

        "A single physical unit carries **two** replacement valuations at all times, and they answer different questions."
        "The split matters because the two bases feed different obligations."
        "The depreciated basis caps a repair-type liability reservation and is the arithmetic basis of trade-in credit."
        "The successor basis is the denominator of the repair-versus-replace ratio and is the full amount of a replacement-type liability reservation."

        Design: Difficulty/dual_variant_calc/gear_item_replacement_value_variant_divergence
        """
        item = validate_success(api.get_gear_item(catalogue.item_id, agent_headers))
        assert_common_fields(item)

        assert item["replacement_value_depreciated_cents"] == 52430, item
        assert item["replacement_value_successor_cents"] == 89910, item
        assert (
            item["replacement_value_successor_cents"]
            - item["replacement_value_depreciated_cents"]
            == 37480
        ), item


class TestRepairOrderProvisionalQuoteVsFinalInvoiceDivergence:
    """PRD §3.7 — the PROVISIONAL quote and the FINAL invoice on one order."""

    def test_provisional_quote_prices_typed_minutes_and_typed_part_prices(
        self, catalogue
    ):
        """FABRIC 25 min + ZIPPER 35 min and an 1800-cent quoted slider total 11223 cents.

        "Taking the lines in ascending order of `work_type`, each line's charge is the hourly labour rate for its `work_type` multiplied by that line's `minutes`, divided by sixty, rounded half up to a whole cent."
        "The hourly rates are 8500 cents for `FABRIC`, 9500 cents for `ZIPPER`, 11000 cents for `FRAME` and 9000 cents for `INSULATION`."
        "**Step three** applies a capped shop supply fee on labour alone: `shop_supply_fee_cents` is the lesser of 2500 cents and seven percent of `labor_subtotal_cents` rounded half up."
        "**Step five** applies loyalty: `loyalty_discount_cents` is `subtotal_cents` multiplied by the owner's tier rate, rounded half up, where a `STANDARD` owner's rate is zero percent and a `PRO` owner's rate is ten percent."
        "**Step six** applies expedite: `expedite_fee_cents` is 3500 cents on a `FINAL` row when the order's `expedite_requested` is true, and zero in every other case — a `PROVISIONAL` row always carries zero here, even on an expedited order."
        "A `PROVISIONAL` row prices the bench-standard minutes an agent typed into `labor_lines` and the list prices they typed into `parts_lines`, and carries no expedite fee."

        Design: Difficulty/dual_variant_calc/repair_order_provisional_quote_vs_final_invoice_divergence
        """
        ctx = _expedited_paid_order_with_provisional_quote(catalogue)
        provisional = ctx["provisional"]

        assert ctx["order"]["expedite_requested"] is True, ctx["order"]
        assert provisional["variant"] == "PROVISIONAL", provisional
        assert provisional["status"] == "SENT", provisional
        assert_estimate_breakdown(
            provisional,
            labor_subtotal_cents=9084,
            parts_subtotal_cents=1800,
            shop_supply_fee_cents=636,
            subtotal_cents=11520,
            loyalty_discount_cents=1152,
            expedite_fee_cents=0,
            tax_cents=855,
            total_cents=11223,
        )

    def test_final_invoice_prices_logged_minutes_consumed_lot_price_and_expedite(
        self, catalogue, api, agent_headers
    ):
        """Logged 30 + 40 minutes, the lot's own 3100-cent slider and 3500 expedite total 17842.

        "A `FINAL` row is derived by the server and accepts no lines from the caller at all: its labour lines come from the order's work blocks whose `status` is `COMPLETED`, grouped by `work_type` with the group's minutes being the sum of `actual_minutes` for that work type and the groups taken in ascending `work_type` order; its parts lines come from the order's reservations whose `status` is `CONSUMED`, each priced at its lot's `unit_price_cents`, with `RESERVED` and `RELEASED` reservations excluded entirely."
        "And a `FINAL` row charges the expedite fee when the order asked for it."
        "On success a new estimate row is minted with `variant` `FINAL` directly in `status` `INVOICED` — a final row never passes through `SENT` or `APPROVED` — priced by the `FINAL` variant above, and the order's `final_invoice_total_cents` is set from that row's `total_cents` while its `billing_status` moves `ESTIMATE_APPROVED` → `INVOICED`."
        "**Step seven** taxes the discounted, expedited base: `tax_cents` is 8.25 percent of the quantity `subtotal_cents` minus `loyalty_discount_cents` plus `expedite_fee_cents`, rounded half up."
        "**Step eight** totals: `total_cents` is `subtotal_cents` minus `loyalty_discount_cents` plus `expedite_fee_cents` plus `tax_cents`."

        Design: Difficulty/dual_variant_calc/repair_order_provisional_quote_vs_final_invoice_divergence
        """
        ctx = _drive_to_qc_passed(
            catalogue, _expedited_paid_order_with_provisional_quote(catalogue)
        )

        final_row = validate_success(
            api.invoice_order(ctx["order_id"], agent_headers), 201
        )

        assert final_row["variant"] == "FINAL", final_row
        assert final_row["status"] == "INVOICED", final_row
        assert_estimate_breakdown(
            final_row,
            labor_subtotal_cents=10583,
            parts_subtotal_cents=3100,
            shop_supply_fee_cents=741,
            subtotal_cents=14424,
            loyalty_discount_cents=1442,
            expedite_fee_cents=3500,
            tax_cents=1360,
            total_cents=17842,
        )

    def test_final_parts_line_charges_the_lot_price_not_the_quoted_price(
        self, catalogue
    ):
        """The consumed slider bills at the lot's 3100 cents, not the 1800 cents quoted.

        "**Step two** handles parts exactly: `parts_subtotal_cents` is the sum over the parts lines of `units` multiplied by `unit_price_cents`, with no rounding because every term is already a whole number of cents."
        "A `PROVISIONAL` row prices the bench-standard minutes an agent typed into `labor_lines` and the list prices they typed into `parts_lines`, and carries no expedite fee."
        "A substitution therefore reprices its line, since the substituted lot's own `unit_price_cents` is what is charged."

        Design: Difficulty/dual_variant_calc/repair_order_provisional_quote_vs_final_invoice_divergence
        """
        ctx = _drive_to_qc_passed(
            catalogue, _expedited_paid_order_with_provisional_quote(catalogue)
        )
        final_row = catalogue.scenario.invoice(ctx["order_id"])

        assert ctx["zip_lot"]["unit_price_cents"] == 3100, ctx["zip_lot"]
        assert ctx["provisional"]["parts_subtotal_cents"] == 1800, ctx["provisional"]
        assert final_row["parts_subtotal_cents"] == 3100, final_row

    def test_order_records_both_totals_and_a_6619_cent_reconciliation_delta(
        self, catalogue, api, agent_headers
    ):
        """The order carries 11223 provisional against 17842 final on the same row.

        "The two pricing variants differ in their inputs, not their arithmetic, and identical nominal work can therefore produce two different totals."
        "On approval the estimate moves `SENT` → `APPROVED`, its `decided_at` is stamped, the order's `provisional_estimate_total_cents` is set from the estimate's `total_cents`, and the order's `billing_status` moves `ESTIMATE_SENT` → `ESTIMATE_APPROVED` — which is the moment the bench dimension is unlocked and `QUEUED` → `IN_WORK` becomes reachable."
        "On success a new estimate row is minted with `variant` `FINAL` directly in `status` `INVOICED` — a final row never passes through `SENT` or `APPROVED` — priced by the `FINAL` variant above, and the order's `final_invoice_total_cents` is set from that row's `total_cents` while its `billing_status` moves `ESTIMATE_APPROVED` → `INVOICED`."

        Design: Difficulty/dual_variant_calc/repair_order_provisional_quote_vs_final_invoice_divergence
        """
        ctx = _drive_to_qc_passed(
            catalogue, _expedited_paid_order_with_provisional_quote(catalogue)
        )
        catalogue.scenario.invoice(ctx["order_id"])

        order = validate_success(
            api.get_repair_order(ctx["order_id"], agent_headers)
        )

        assert order["billing_status"] == "INVOICED", order
        assert order["provisional_estimate_total_cents"] == 11223, order
        assert order["final_invoice_total_cents"] == 17842, order
        assert (
            order["final_invoice_total_cents"]
            - order["provisional_estimate_total_cents"]
            == 6619
        ), order
