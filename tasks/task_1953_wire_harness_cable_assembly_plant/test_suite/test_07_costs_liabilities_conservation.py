"""Derived cost and liability arithmetic: dual-variant build-order roll-ups
(STANDARD vs ACTUAL), dual-variant consigned scrap liabilities (BOOK vs
REPLACEMENT), pinned per-line scrap-credit rounding, and the conserved piece /
unit bucket invariants across forward and compensating actions."""
from test_helpers import (
    assert_build_order,
    assert_consigned_lot,
    assert_consigned_lot_conservation,
    deliver_kit,
    get_order_kit,
    get_success_data,
    issue_line,
    make_build_order,
    make_consigned_lot,
    make_operator,
    pass_unit_tests,
    release_order_to_kitting,
    scrap_unit,
    setup_order_in_build,
    setup_qualified_line,
    ship_unit,
)
from test_helpers import TEST_USERS
from test_helpers import make_line_operator_headers

PLAN = TEST_USERS["production_planner_headers"]
MAT = TEST_USERS["materials_clerk_headers"]

# C1 consigned (1 x 450c standard) + T1 factory (4 x 25c standard).
DUAL_VARIANT_BOM = [
    {"find_number": "C1", "component_type": "CONNECTOR", "mpn": "CON-500",
     "qty_per_harness": 1, "supply_type": "CUSTOMER_CONSIGNED", "unit_cost_cents": 450},
    {"find_number": "T1", "component_type": "TERMINAL", "mpn": "TERM-20",
     "qty_per_harness": 4, "supply_type": "FACTORY_STOCK", "unit_cost_cents": 25},
]
CONSIGNED_ONLY_BOM = [
    {"find_number": "C1", "component_type": "CONNECTOR", "mpn": "CON-500",
     "qty_per_harness": 1, "supply_type": "CUSTOMER_CONSIGNED", "unit_cost_cents": 450},
]
THREE_LINE_133_BOM = [
    {"find_number": "F1", "component_type": "CONNECTOR", "mpn": "CON-133",
     "qty_per_harness": 1, "supply_type": "FACTORY_STOCK", "unit_cost_cents": 133},
    {"find_number": "F2", "component_type": "TERMINAL", "mpn": "TERM-133",
     "qty_per_harness": 1, "supply_type": "FACTORY_STOCK", "unit_cost_cents": 133},
    {"find_number": "F3", "component_type": "WIRE", "mpn": "WIRE-133",
     "qty_per_harness": 1, "supply_type": "FACTORY_STOCK", "unit_cost_cents": 133},
]


def _dual_variant_scene(api, tag):
    """Order qty 2 on the two-line BOM, fully kitted (consigned C1 from the
    lot at liability 500c) and delivered, with both units built."""
    line = setup_qualified_line(api, tag=tag, bom=DUAL_VARIANT_BOM)
    lot = make_consigned_lot(api, lot_code=f"LOT-{tag}", qty_received=10)
    return setup_order_in_build(api, line=line, tag=tag, qty_ordered=2,
                                default_lot_id=lot["id"], units=2)


class TestDualVariantCostRollup:
    def test_standard_cost_uses_pinned_bom_costs(self, api):
        """PRD §3.5: "The `standard_cost_cents` is `qty_built` multiplied by the per-harness standard cost — the sum, over the pinned BOM lines, of `qty_per_harness` times `unit_cost_cents` — and serves as the quoting and variance baseline."
        PRD §3.5: "The `qty_built` counter is the count of the order's harness units in `BUILT`, `TEST_PASS`, `REWORK`, `SUSPECT`, or `SHIPPED`; `qty_scrapped` counts units in `SCRAPPED`."

        Design: Difficulty/dual_variant_calc/build_cost_standard_vs_actual_rollup
        """
        ctx = _dual_variant_scene(api, "DV1")
        order = get_success_data(api.get_build_order(ctx["order"]["id"], PLAN))
        assert_build_order(order)
        # STANDARD variant: qty_built 2 x (1*450 + 4*25) = 2 x 550 = 1100 cents.
        assert order["standard_cost_cents"] == 1100, (
            f"STANDARD uses pinned BOM standard costs: {order}"
        )
        assert order["qty_built"] == 2, f"two serialized units built: {order}"

    def test_actual_cost_uses_issue_time_snapshots(self, api):
        """PRD §3.5: "The `actual_cost_cents` is the sum over all non-voided kit issues of the order of `qty_issued` times `unit_cost_snapshot_cents`, and equals `material_spent_cents`; the two variants diverge whenever consigned liability differs from standard cost or issues over- or under-ship against the BOM."
        PRD §3.6: "The cost snapshot is taken at issue time: for a consigned issue it is the lot's `unit_liability_cents`; for a factory issue it is the BOM component's `unit_cost_cents`."

        Design: Difficulty/dual_variant_calc/build_cost_standard_vs_actual_rollup
        """
        ctx = _dual_variant_scene(api, "DV1B")
        order = get_success_data(api.get_build_order(ctx["order"]["id"], PLAN))
        # ACTUAL variant: the consigned snapshot is the lot liability, not the
        # standard cost: 2 x 500 + 8 x 25 = 1200 cents, diverging from 1100.
        assert order["actual_cost_cents"] == 1200, (
            f"ACTUAL uses issue-time snapshots (lot liability 500, not standard 450): {order}"
        )
        assert order["material_spent_cents"] == 1200, (
            f"actual equals material spend: {order}"
        )
        assert order["standard_cost_cents"] != order["actual_cost_cents"], (
            f"the variants diverge when liability differs from standard: {order}"
        )


class TestDualVariantConsignedLiability:
    def _scrapped_lot_scene(self, api, tag):
        """Lot of 10; order qty 3 fully kitted from the lot and delivered;
        all three built units scrapped."""
        line = setup_qualified_line(api, tag=tag, bom=CONSIGNED_ONLY_BOM)
        lot = make_consigned_lot(api, lot_code=f"LOT-{tag}", qty_received=10)
        ctx = setup_order_in_build(api, line=line, tag=tag, qty_ordered=3,
                                   default_lot_id=lot["id"], units=3)
        for unit in ctx["units"]:
            scrap_unit(api, unit["id"], line["inspector"]["id"], reason="DAMAGE")
        return get_success_data(api.get_consigned_lot(lot["id"], MAT))

    def test_book_liability_settles_at_receipt_book_value(self, api):
        """PRD §3.6: "`book_liability_cents` is `qty_scrapped` times `unit_liability_cents` (the settlement-at-book-value variant), and `replacement_liability_cents` is `qty_scrapped` times `replacement_cost_cents` (the settlement-at-replacement-cost variant); the two diverge whenever replacement cost differs from book."
        PRD §3.6: "Scrapping a built unit moves its consigned content from `qty_consumed` into `qty_scrapped`."

        Design: Difficulty/dual_variant_calc/consigned_liability_book_vs_replacement
        """
        lot = self._scrapped_lot_scene(api, "DV2")
        assert_consigned_lot(lot)
        assert lot["qty_scrapped"] == 3, f"three built units' consigned pieces scrapped: {lot}"
        assert lot["qty_consumed"] == 0, f"all consumed pieces transferred to scrapped: {lot}"
        # BOOK_VALUE variant: 3 x 500 = 1500 cents.
        assert lot["book_liability_cents"] == 1500, f"book variant at receipt value: {lot}"

    def test_replacement_liability_diverges_from_book(self, api):
        """PRD §3.6: "`book_liability_cents` is `qty_scrapped` times `unit_liability_cents` (the settlement-at-book-value variant), and `replacement_liability_cents` is `qty_scrapped` times `replacement_cost_cents` (the settlement-at-replacement-cost variant); the two diverge whenever replacement cost differs from book."

        Design: Difficulty/dual_variant_calc/consigned_liability_book_vs_replacement
        """
        lot = self._scrapped_lot_scene(api, "DV2B")
        # REPLACEMENT_VALUE variant: 3 x 640 = 1920 cents, diverging from book 1500.
        assert lot["replacement_liability_cents"] == 1920, (
            f"replacement variant at current replacement cost: {lot}"
        )
        assert lot["book_liability_cents"] != lot["replacement_liability_cents"], (
            f"the variants diverge whenever replacement differs from book: {lot}"
        )


class TestScrapCreditRounding:
    def test_scrap_credit_rounds_each_line_before_summing(self, api):
        """PRD §3.7: "for each BOM line of the unit's pinned drawing revision — all supply types included — a line credit of `qty_per_harness` times `unit_cost_cents` times the 0.8 recovery rate is rounded half-up to integer cents, and the per-line credits are then summed into a unit credit (the rounding order is pinned: round each line first, then sum; summing first and rounding once is a different, rejected result)."
        PRD §3.7: "The unit credit accumulates into the order's `scrap_recovery_credit_cents`."

        Design: Difficulty/combinatorial_formula/scrap_credit_per_line_rounding
        """
        ctx = setup_order_in_build(api, tag="CF2", qty_ordered=1, units=1,
                                   line_kwargs={"bom": THREE_LINE_133_BOM})
        inspector = ctx["line"]["inspector"]
        scrap_unit(api, ctx["units"][0]["id"], inspector["id"], reason="DAMAGE")
        order = get_success_data(api.get_build_order(ctx["order"]["id"], PLAN))
        # Per line: round_half_up(1 x 133 x 0.8) = round_half_up(106.4) = 106;
        # three lines -> 318. The rejected sum-then-round order would give 319.
        assert order["scrap_recovery_credit_cents"] == 318, (
            f"round each line first (106), then sum (318): {order}"
        )

    def test_scrap_of_last_unit_auto_cancels_order(self, api):
        """PRD §3.7: "Third, the order's `qty_built`, `qty_scrapped`, and `standard_cost_cents` recompute, and the order-level checks run: `IN_BUILD → TESTING` when the sum reaches `qty_ordered`, `TESTING → CANCELLED` when `qty_built` has fallen to zero (every built unit scrapped), and the completion check above."

        Design: Difficulty/combinatorial_formula/scrap_credit_per_line_rounding
        """
        ctx = setup_order_in_build(api, tag="CF2B", qty_ordered=1, units=1,
                                   line_kwargs={"bom": THREE_LINE_133_BOM})
        inspector = ctx["line"]["inspector"]
        scrap_unit(api, ctx["units"][0]["id"], inspector["id"], reason="DAMAGE")
        order = get_success_data(api.get_build_order(ctx["order"]["id"], PLAN))
        assert order["qty_scrapped"] == 1 and order["qty_built"] == 0, (
            f"the only unit moved to the scrapped bucket: {order}"
        )
        assert order["status"] == "CANCELLED", (
            f"qty_built fell to zero in TESTING -> CANCELLED: {order}"
        )


class TestConservationInvariants:
    def test_consigned_buckets_across_issue_scrap_return(self, api):
        """PRD §3.6: "A consigned lot tracks five quantity buckets, and their sum is a conserved invariant: `qty_on_hand` plus `qty_issued_open` plus `qty_consumed` plus `qty_scrapped` plus `qty_returned` always equals `qty_received`, across every forward-and-compensating action pair the plant performs."
        PRD §3.6: "Scrapping a built unit moves its consigned content from `qty_consumed` into `qty_scrapped`."
        PRD §3.6: "Returning the lot to the customer adds all of `qty_on_hand` into `qty_returned` and zeroes `qty_on_hand`."
        PRD §3.6: "A lot return to the customer, performed by the `MaterialsClerk`, moves `ACTIVE → RETURNED` after the bucket transfer described above."

        Design: Difficulty/compensating_invariant/consigned_piece_conservation_across_issue_scrap_return
        """
        line = setup_qualified_line(api, tag="CI1", bom=CONSIGNED_ONLY_BOM)
        lot = make_consigned_lot(api, lot_code="LOT-CI1", qty_received=10)
        ctx = setup_order_in_build(api, line=line, tag="CI1", qty_ordered=4,
                                   default_lot_id=lot["id"], units=4)
        scrap_unit(api, ctx["units"][0]["id"], line["inspector"]["id"], reason="DAMAGE")
        returned_lot = get_success_data(api.return_consigned_lot(lot["id"], MAT))
        assert returned_lot["status"] == "RETURNED", (
            f"lot return moves ACTIVE -> RETURNED: {returned_lot}"
        )
        lot_after = get_success_data(api.get_consigned_lot(lot["id"], MAT))
        # received 10; issued+delivered 4; scrapped 1; returned the remaining 6.
        assert lot_after["qty_on_hand"] == 0, f"return zeroed on-hand: {lot_after}"
        assert lot_after["qty_issued_open"] == 0, f"nothing remains issued: {lot_after}"
        assert lot_after["qty_consumed"] == 3, f"three pieces stayed consumed: {lot_after}"
        assert lot_after["qty_scrapped"] == 1, f"one piece scrapped inside its unit: {lot_after}"
        assert lot_after["qty_returned"] == 6, f"six on-hand pieces returned: {lot_after}"
        assert_consigned_lot_conservation(lot_after)

    def test_consigned_bucket_invariant_holds_at_each_step(self, api):
        """PRD §3.6: "A consigned lot tracks five quantity buckets, and their sum is a conserved invariant: `qty_on_hand` plus `qty_issued_open` plus `qty_consumed` plus `qty_scrapped` plus `qty_returned` always equals `qty_received`, across every forward-and-compensating action pair the plant performs."
        PRD §3.6: "Issuing moves pieces from `qty_on_hand` into `qty_issued_open`. Line-side delivery of a kit moves its consigned pieces from `qty_issued_open` into `qty_consumed`."

        Design: Difficulty/compensating_invariant/consigned_piece_conservation_across_issue_scrap_return
        """
        line = setup_qualified_line(api, tag="CI1S", bom=CONSIGNED_ONLY_BOM)
        lot = make_consigned_lot(api, lot_code="LOT-CI1S", qty_received=10)
        order = make_build_order(api, drawing_id=line["drawing"]["id"],
                                 order_code="BO-CI1S", qty_ordered=4)
        release_order_to_kitting(api, order["id"])
        kit = get_order_kit(api, order["id"])
        issue_line(api, kit["id"], line["components"]["C1"]["id"], 4,
                   "CONSIGNED_LOT", consigned_lot_id=lot["id"])
        snap = get_success_data(api.get_consigned_lot(lot["id"], MAT))
        assert (snap["qty_on_hand"], snap["qty_issued_open"], snap["qty_consumed"],
                snap["qty_scrapped"], snap["qty_returned"]) == (6, 4, 0, 0, 0), (
            f"issue moved 4 pieces on_hand -> issued_open: {snap}"
        )
        assert_consigned_lot_conservation(snap)
        deliver_kit(api, kit["id"])
        snap = get_success_data(api.get_consigned_lot(lot["id"], MAT))
        assert (snap["qty_on_hand"], snap["qty_issued_open"], snap["qty_consumed"],
                snap["qty_scrapped"], snap["qty_returned"]) == (6, 0, 4, 0, 0), (
            f"delivery moved 4 pieces issued_open -> consumed: {snap}"
        )
        assert_consigned_lot_conservation(snap)
        builder = make_operator(api, name="LO CI1S", badge="B-LO-CI1S")
        unit = get_success_data(
            api.create_harness_unit(order["id"], make_line_operator_headers(builder["id"]))
        )
        scrap_unit(api, unit["id"], line["inspector"]["id"], reason="DAMAGE")
        snap = get_success_data(api.get_consigned_lot(lot["id"], MAT))
        assert (snap["qty_on_hand"], snap["qty_issued_open"], snap["qty_consumed"],
                snap["qty_scrapped"], snap["qty_returned"]) == (6, 0, 3, 1, 0), (
            f"scrap moved the unit's piece consumed -> scrapped: {snap}"
        )
        assert_consigned_lot_conservation(snap)
        api.return_consigned_lot(lot["id"], MAT)
        snap = get_success_data(api.get_consigned_lot(lot["id"], MAT))
        assert (snap["qty_on_hand"], snap["qty_issued_open"], snap["qty_consumed"],
                snap["qty_scrapped"], snap["qty_returned"]) == (0, 0, 3, 1, 6), (
            f"lot return swept on-hand into returned: {snap}"
        )
        assert_consigned_lot_conservation(snap)

    def test_build_then_scrap_conserves_unit_sum(self, api):
        """PRD §3.5: "The sum `qty_built` plus `qty_scrapped` is conserved across a build followed by its compensating scrap — the unit moves buckets, the sum does not change — and is invariant under shipping; when that sum reaches `qty_ordered`, the order advances `IN_BUILD → TESTING`."
        PRD §3.5: "The `qty_built` counter is the count of the order's harness units in `BUILT`, `TEST_PASS`, `REWORK`, `SUSPECT`, or `SHIPPED`; `qty_scrapped` counts units in `SCRAPPED`."

        Design: Difficulty/compensating_invariant/harness_unit_bucket_conservation_across_build_scrap_ship
        """
        ctx = setup_order_in_build(api, tag="CI2", qty_ordered=3, units=3)
        inspector = ctx["line"]["inspector"]
        scrap_unit(api, ctx["units"][0]["id"], inspector["id"], reason="QC_SUSPECT")
        order = get_success_data(api.get_build_order(ctx["order"]["id"], PLAN))
        assert order["qty_built"] == 2 and order["qty_scrapped"] == 1, (
            f"build-then-scrap moved one unit between buckets: {order}"
        )
        assert order["qty_built"] + order["qty_scrapped"] == 3 == order["qty_ordered"], (
            f"the sum is conserved across the compensating scrap: {order}"
        )

    def test_ship_leaves_unit_bucket_sum_unchanged(self, api):
        """PRD §3.5: "The sum `qty_built` plus `qty_scrapped` is conserved across a build followed by its compensating scrap — the unit moves buckets, the sum does not change — and is invariant under shipping; when that sum reaches `qty_ordered`, the order advances `IN_BUILD → TESTING`."
        PRD §3.7: "Shipping is the happy-path exit: a `ShippingClerk` ships a unit in `TEST_PASS`, moving it to the terminal `SHIPPED`; shipping a unit in any other status rejects with `ERR_UNIT_NOT_SHIPPABLE`."

        Design: Difficulty/compensating_invariant/harness_unit_bucket_conservation_across_build_scrap_ship
        """
        ctx = setup_order_in_build(api, tag="CI2B", qty_ordered=3, units=3)
        inspector = ctx["line"]["inspector"]
        scrap_unit(api, ctx["units"][0]["id"], inspector["id"], reason="QC_SUSPECT")
        u2 = ctx["units"][1]
        pass_unit_tests(api, u2["id"], inspector["id"])
        ship_unit(api, u2["id"])
        u2_after = get_success_data(api.get_harness_unit(u2["id"], PLAN))
        assert u2_after["status"] == "SHIPPED", f"tested unit shipped: {u2_after}"
        order = get_success_data(api.get_build_order(ctx["order"]["id"], PLAN))
        # SHIPPED still counts toward qty_built; the scrapped unit stays scrapped.
        assert order["qty_built"] == 2 and order["qty_scrapped"] == 1, (
            f"shipping does not disturb the conserved sum: {order}"
        )
        assert order["qty_built"] + order["qty_scrapped"] == order["qty_ordered"]
