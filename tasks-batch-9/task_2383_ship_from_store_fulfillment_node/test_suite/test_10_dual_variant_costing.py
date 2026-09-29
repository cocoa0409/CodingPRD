"""Dual-variant computations: the two node scores, the two parcel-cost variants
and the two order-level cost passes.

Each test builds its own world from an empty database, drives one 2-unit or
9-unit parcel all the way to a tender, and then pins the two numbers the PRD
says are computed from the same formula but from different inputs.
"""

import pytest

from test_helpers import (
    close_windows,
    cost_comparison,
    read_assignment,
    read_order,
    read_store,
    set_clock,
    setup_shipped_assignment,
)


# ======================================================================
# Shared preambles
# ======================================================================


def _ship_two_units_in_a_large_box(order_code: str = "O-1002") -> dict:
    """One node S1 (zone 4, standard 12 min + 3 min/unit, 42 cents/min), one
    GROUND order to zone 4 for 2 units of a MEDIUM SKU, committed to S1,
    accepted at 09:10, fully picked, packed at 09:40 into a LARGE_BOX and
    tendered at 09:40 into the node's 09:00-12:00 pickup window.
    """
    return setup_shipped_assignment(
        node_preset="S1",
        sku_preset="SKU-A",
        on_hand_units=12,
        safety_stock_units=2,
        quantity=2,
        destination_zone=4,
        service_level="GROUND",
        order_code=order_code,
        clock="2026-08-03T09:00:00Z",
        package_type="LARGE_BOX",
        packaging_on_hand=10,
        pickup_start="2026-08-03T09:00:00Z",
        pickup_end="2026-08-03T12:00:00Z",
        parcel_capacity=5,
        accept_at="2026-08-03T09:10:00Z",
        pack_at="2026-08-03T09:40:00Z",
        package_type_on_pack="LARGE_BOX",
    )


def _ship_nine_units_in_the_derived_box(order_code: str = "O-1003") -> dict:
    """Same node S1, but a GROUND order to zone 4 for 9 units of the MEDIUM
    SKU, accepted at 09:05, fully picked, packed at 09:20 into the very
    MEDIUM_BOX the allocation implies, and tendered at 09:20.
    """
    return setup_shipped_assignment(
        node_preset="S1",
        sku_preset="SKU-A",
        on_hand_units=12,
        safety_stock_units=2,
        quantity=9,
        destination_zone=4,
        service_level="GROUND",
        order_code=order_code,
        clock="2026-08-03T09:00:00Z",
        packaging_on_hand=20,
        pickup_start="2026-08-03T09:00:00Z",
        pickup_end="2026-08-03T12:00:00Z",
        parcel_capacity=5,
        accept_at="2026-08-03T09:05:00Z",
        pack_at="2026-08-03T09:20:00Z",
    )


# ======================================================================
# Node governance score versus node routing score
# ======================================================================


class TestNodeScoreVariants:
    def test_close_writes_review_score_and_eligibility_score_that_diverge(self):
        """PRD §3.3: "Because the governance score is computed before the epoch's committed units are cleared, its capacity component still sees the epoch's commitments, so a node's `review_score` and its `eligibility_score` legitimately diverge within the very same close."
        PRD §3.3: "`review_score` blends two windows: seven tenths of the performance ratio of the window being closed plus three tenths of the performance ratio of the previous closed window, or, when no previous closed window exists, the ratio of the window being closed on its own."
        PRD §3.3: "The **capacity component** starts from capacity headroom: the larger of 0 and `daily_unit_capacity` minus `units_committed_epoch`. That headroom is divided by a reference of 200 units, the quotient is capped at 1, and the result is multiplied by a weight of 40."
        PRD §3.9: "Each window's `node_action` is decided and applied, and each node's `review_score` is written on the governance-blended basis of §3.3 from the pre-reset counters."
        PRD §3.9: "Each window's `status` becomes `CLOSED`, its `closed_at_utc` is set to the clock instant, and each node's `units_committed_epoch` is reset to 0."
        PRD §3.9: "Every node whose `node_status` is `ELIGIBLE` or `PROBATION` has its `eligibility_score` recomputed against the just-closed window, with `eligibility_score_basis` set to `TRAILING_WINDOW`."

        Design: Difficulty/dual_variant_calc/node_posture_score_diverges_from_governance_review_score
        """
        ctx = _ship_two_units_in_a_large_box(order_code="O-1001")

        set_clock("2026-08-03T09:45:00Z")
        close_windows()

        store = read_store(ctx["store"]["id"])

        assert store["review_score"] == pytest.approx(83.60, abs=0.01), (
            "review_score is the governance-blended score written at the posture "
            "step, whose capacity component still sees the epoch's 2 committed "
            f"units: expected 83.60, got {store['review_score']}"
        )
        assert store["eligibility_score"] == pytest.approx(84.00, abs=0.01), (
            "eligibility_score is rescored after the close reset "
            "units_committed_epoch to 0: expected 84.00, got "
            f"{store['eligibility_score']}"
        )
        assert store["review_score"] != store["eligibility_score"], (
            "the governance score and the routing score must diverge within the "
            "same close because only the latter sees the cleared commitments"
        )
        assert store["eligibility_score_basis"] == "TRAILING_WINDOW", (
            "the rescore step records eligibility_score_basis as TRAILING_WINDOW, "
            f"got {store['eligibility_score_basis']}"
        )
        assert store["units_committed_epoch"] == 0, (
            "closing the window resets units_committed_epoch to 0, got "
            f"{store['units_committed_epoch']}"
        )

    def test_close_settles_window_metrics_and_leaves_the_node_eligible(self):
        """PRD §3.1: "Registration also opens the node's first performance window at the network's current epoch — the highest `epoch` across all existing windows, or 1 when no window exists anywhere yet — with `opened_at_utc` set to the clock instant and `closed_at_utc` null."
        PRD §3.9: "`fill_rate` is exactly 1.0000 when `units_promised` is 0, and otherwise `units_shipped` divided by `units_promised` rounded half-up to four decimal places."
        PRD §3.9: "`avg_cycle_time_minutes` is exactly 0.00 when `assignments_shipped` is 0, and otherwise the sum of `cycle_time_minutes` over the shipped assignments divided by `assignments_shipped`, rounded half-up to two decimal places."
        PRD §3.9: "`cancellation_rate` is exactly 0.0000 when `assignments_created` is 0, and otherwise `assignments_rejected` plus `assignments_cancelled`, divided by `assignments_created`, rounded half-up to four decimal places."
        PRD §3.9: "`store_cost_per_order_cents` is 0 when `assignments_shipped` is 0, and otherwise the sum of `final_cost_cents` over the shipped assignments divided by `assignments_shipped`, rounded half-up to whole cents."
        PRD §3.9: "`dc_cost_per_order_cents` is 0 when `assignments_shipped` is 0, and otherwise computed by taking, for each shipped assignment, the distribution-centre base charge for its order's `destination_zone` plus 120 cents multiplied by that assignment's `picked_units`, summing those across the shipped assignments, dividing by `assignments_shipped`, and rounding half-up to whole cents."
        PRD §3.9: "The window's `cost_index_bps` is 0 when `dc_cost_per_order_cents` is 0, and otherwise `store_cost_per_order_cents` multiplied by 10000, divided by `dc_cost_per_order_cents`, rounded half-up."
        PRD §3.9: "`breached` is true exactly when `breach_flags` is non-empty."
        PRD §3.9: "Otherwise it is `DEACTIVATION` when the window is breached and the node's `consecutive_breach_windows` plus 1 reaches 2; `PROBATION` when the window is breached, the node's `node_status` is `ELIGIBLE`, and `consecutive_breach_windows` plus 1 is still below 2; `RECOVERY` when the window is not breached and the node's `node_status` is `PROBATION`; and `NONE` in every other case."

        Design: Difficulty/dual_variant_calc/node_posture_score_diverges_from_governance_review_score
        """
        ctx = _ship_two_units_in_a_large_box(order_code="O-1001")

        set_clock("2026-08-03T09:45:00Z")
        closed = close_windows()

        assert len(closed) == 1, (
            f"the ops-run should close the single node's one open window, got {len(closed)}"
        )
        window = closed[0]

        assert window["epoch"] == 1, (
            f"the only node's first window sits at epoch 1, got {window['epoch']}"
        )
        assert window["fill_rate"] == pytest.approx(1.0000, abs=0.01), (
            "2 units promised and 2 units shipped gives a fill_rate of 1.0000, got "
            f"{window['fill_rate']}"
        )
        assert window["cancellation_rate"] == pytest.approx(0.0000, abs=0.01), (
            "no rejection and no cancellation gives a cancellation_rate of 0.0000, "
            f"got {window['cancellation_rate']}"
        )
        assert window["avg_cycle_time_minutes"] == pytest.approx(40.00, abs=0.01), (
            "the single shipped assignment's cycle time is 09:00 to 09:40, so "
            f"avg_cycle_time_minutes is 40.00, got {window['avg_cycle_time_minutes']}"
        )
        assert window["store_cost_per_order_cents"] == 1900, (
            "store_cost_per_order_cents averages the shipped assignment's "
            f"final_cost_cents: expected 1900, got {window['store_cost_per_order_cents']}"
        )
        assert window["dc_cost_per_order_cents"] == 2090, (
            "the zone-4 DC base charge of 1850 plus 120 cents per picked unit gives "
            f"2090, got {window['dc_cost_per_order_cents']}"
        )
        assert window["cost_index_bps"] == 9091, (
            "1900 * 10000 / 2090 rounded half-up is 9091, got "
            f"{window['cost_index_bps']}"
        )
        assert window["breach_flags"] == [], (
            f"a full-fill, fast, cancellation-free window breaches nothing, got {window['breach_flags']}"
        )
        assert window["breached"] is False, (
            "breached is true exactly when breach_flags is non-empty"
        )
        assert window["node_action"] == "NONE", (
            "an unbreached window at an ELIGIBLE node falls to NONE, got "
            f"{window['node_action']}"
        )

        store = read_store(ctx["store"]["id"])
        assert store["node_status"] == "ELIGIBLE", (
            f"a NONE action leaves the node's posture untouched, got {store['node_status']}"
        )


# ======================================================================
# Assignment provisional cost versus assignment final cost
# ======================================================================


class TestAssignmentCostVariants:
    def test_ship_seals_final_cost_beside_the_provisional_standard_cost(self):
        """PRD §3.8: "The **provisional** variant, written to the assignment's `provisional_cost_cents` at candidate evaluation and at assignment creation, charges the labour *standard*: `labor_standard_minutes_per_order` plus `pick_labor_minutes_per_unit` multiplied by `assigned_units`."
        PRD §3.8: "Its charged units are `assigned_units`, and its charged package is `derived_package_type`."
        PRD §3.8: "The **final** variant, written to `final_cost_cents` at ship, charges *actual* clocked labour: the greater of `labor_minutes_actual` and a 10-minute billable minimum, where `labor_minutes_actual` is the whole minutes from `accepted_at` to `packed_at` with remaining seconds discarded."
        PRD §3.8: "Its charged units are `picked_units`, and its charged package is the `package_type` the associate actually recorded at pack."
        PRD §3.8: "**Labour cost** is the charged labour minutes multiplied by the node's `labor_rate_cents_per_minute`, rounded up to the next whole cent."
        PRD §3.8: "**Packaging cost** is the base cost of the charged package type — 45 cents for a `POLY_MAILER`, 85 for a `SMALL_BOX`, 130 for a `MEDIUM_BOX` and 190 for a `LARGE_BOX` — plus 15 cents of dunnage per charged unit."
        PRD §3.8: "The assignment's cost is labour cost plus packaging cost plus ship cost."
        PRD §3.5: "`derived_package_type` is the package the provisional cost assumes: take the heaviest `package_class` among the allocation's SKUs by package rank and map it, so `SMALL` becomes `SMALL_BOX`, `MEDIUM` becomes `MEDIUM_BOX` and `LARGE` becomes `LARGE_BOX`."
        PRD §3.5: "On success `packed_at` is set to the clock instant, `package_type` is stored, and `labor_minutes_actual` is computed as the elapsed time from `accepted_at` to `packed_at` expressed in whole minutes with any remaining seconds discarded."
        PRD §3.6: "The assignment's `status` becomes `SHIPPED`, `shipped_at` is set to the clock instant, `carrier_pickup_id` is stored, and `cycle_time_minutes` is computed as the elapsed time from `created_at` to `shipped_at` in whole minutes with remaining seconds discarded."

        Design: Difficulty/dual_variant_calc/assignment_provisional_cost_versus_final_cost_at_ship
        """
        ctx = _ship_two_units_in_a_large_box(order_code="O-1002")
        assignment = read_assignment(ctx["assignment"]["id"])

        assert assignment["status"] == "SHIPPED", (
            f"the tender moves the assignment to SHIPPED, got {assignment['status']}"
        )
        assert assignment["provisional_cost_cents"] == 1336, (
            "the provisional variant charges the 18-minute labour standard, the "
            "derived MEDIUM_BOX and 2 assigned units: expected 1336, got "
            f"{assignment['provisional_cost_cents']}"
        )
        assert assignment["final_cost_cents"] == 1900, (
            "the final variant charges 30 actual clocked minutes, the LARGE_BOX "
            "recorded at pack and 2 picked units: expected 1900, got "
            f"{assignment['final_cost_cents']}"
        )
        assert assignment["provisional_cost_cents"] != assignment["final_cost_cents"], (
            "the two variants must diverge for this allocation because actual "
            "labour exceeded the standard and a bigger box was used"
        )
        assert assignment["labor_minutes_actual"] == pytest.approx(30, abs=0.01), (
            "accepted at 09:10 and packed at 09:40 is 30 whole minutes, got "
            f"{assignment['labor_minutes_actual']}"
        )
        assert assignment["derived_package_type"] == "MEDIUM_BOX", (
            "a MEDIUM package_class maps to MEDIUM_BOX, got "
            f"{assignment['derived_package_type']}"
        )
        assert assignment["package_type"] == "LARGE_BOX", (
            "pack stores the package the associate actually used, got "
            f"{assignment['package_type']}"
        )
        assert assignment["cycle_time_minutes"] == 40, (
            "created at 09:00 and shipped at 09:40 is 40 whole minutes, got "
            f"{assignment['cycle_time_minutes']}"
        )

    def test_order_final_cost_and_variance_follow_the_only_parcel(self):
        """PRD §3.6: "From `PENDING`, a ship that leaves `shipped_units` above 0 with that same sum exactly equal to `total_units` moves the order straight to `SHIPPED`, writing `final_cost_cents` on the final variant, setting `cost_variance_cents` to `final_cost_cents` minus `provisional_cost_cents`, and recomputing `cost_index_bps` against the final figure."
        PRD §3.8: "The **provisional** variant, kept live in `provisional_cost_cents` after every routing change and every assignment status change, includes the order's assignments whose `status` is neither `REJECTED` nor `CANCELLED` — that is, the five non-terminal statuses plus `SHIPPED` — using each one's `provisional_cost_cents`."
        PRD §3.8: "The **final** variant, written to `final_cost_cents` when `fulfillment_status` becomes `SHIPPED`, includes only assignments at `status` `SHIPPED`, using each one's `final_cost_cents`; because the component sum changes, the fee tier can land in a different band than the provisional pass did, which is exactly what `cost_variance_cents` — `final_cost_cents` minus `provisional_cost_cents` — is there to expose."
        PRD §3.8: "The network fee is the pre-fee subtotal multiplied by that rate, rounded half-up to whole cents, and the store cost is the pre-fee subtotal plus the network fee."
        PRD §3.8: "The distribution-centre baseline is a per-zone handling figure plus a per-unit charge: 1450 cents for `destination_zone` 1, then 1560, 1700, 1850, 2010, 2180, 2360 and 2550 cents for zones 2 through 8, plus 120 cents multiplied by the order's `total_units`."
        PRD §3.8: "The cost index in basis points is the store cost multiplied by 10000, divided by the baseline, rounded half-up — and 0 when the baseline is 0."

        Design: Difficulty/dual_variant_calc/assignment_provisional_cost_versus_final_cost_at_ship
        """
        ctx = _ship_two_units_in_a_large_box(order_code="O-1002")
        order = read_order(ctx["order"]["id"])

        assert order["fulfillment_status"] == "SHIPPED", (
            "the single parcel resolves every unit of the order, got "
            f"{order['fulfillment_status']}"
        )
        assert order["provisional_cost_cents"] == 1416, (
            "the provisional pass sums the assignment's 1336 and adds the 6.0 "
            f"percent network fee: expected 1416, got {order['provisional_cost_cents']}"
        )
        assert order["final_cost_cents"] == 2014, (
            "the final pass sums the shipped assignment's 1900 and adds the 6.0 "
            f"percent network fee: expected 2014, got {order['final_cost_cents']}"
        )
        assert order["cost_variance_cents"] == 598, (
            "cost_variance_cents is final_cost_cents minus provisional_cost_cents: "
            f"expected 598, got {order['cost_variance_cents']}"
        )
        assert order["cost_index_bps"] == 9636, (
            "the index is recomputed against the final figure, 2014 * 10000 / 2090: "
            f"expected 9636, got {order['cost_index_bps']}"
        )


# ======================================================================
# Order-level provisional pass versus final pass
# ======================================================================


class TestOrderCostTierVariants:
    def test_cost_comparison_final_pass_keys_the_fee_on_the_final_subtotal(self):
        """PRD §3.8: "Its body reports the `order_id`, the `variant` used — `FINAL` when the order's `fulfillment_status` is `SHIPPED` and `PROVISIONAL` otherwise — the `parcel_count`, the `component_sum_cents`, the `split_penalty_cents` and `reroute_overhead_cents` actually applied, the `pre_fee_subtotal_cents`, the `network_fee_rate` used and the resulting `network_fee_cents`, the `store_cost_cents`, the `dc_baseline_cost_cents`, the `cost_index_bps` and the `savings_vs_dc_cents`."
        PRD §3.8: "The pre-fee subtotal is that component sum, plus a split penalty of 175 cents for each parcel beyond the first, plus a reroute overhead of 90 cents multiplied by the order's `reroute_attempt_count`."
        PRD §3.8: "The overhead fee rate is then keyed on the pre-fee subtotal: 6.0 percent when the subtotal is strictly below 2000 cents, 4.5 percent when it is strictly below 5000 cents, and 3.0 percent at or above 5000 cents."
        PRD §3.8: "**That tier lookup order is pinned**: the rate is read from the pre-fee subtotal, it is never re-read from the total after the fee has been added, and the fee never re-tiers itself."
        PRD §3.8: "The network fee is the pre-fee subtotal multiplied by that rate, rounded half-up to whole cents, and the store cost is the pre-fee subtotal plus the network fee."
        PRD §3.8: "The **final** variant, written to `final_cost_cents` when `fulfillment_status` becomes `SHIPPED`, includes only assignments at `status` `SHIPPED`, using each one's `final_cost_cents`; because the component sum changes, the fee tier can land in a different band than the provisional pass did, which is exactly what `cost_variance_cents` — `final_cost_cents` minus `provisional_cost_cents` — is there to expose."
        PRD §3.8: "The distribution-centre baseline is a per-zone handling figure plus a per-unit charge: 1450 cents for `destination_zone` 1, then 1560, 1700, 1850, 2010, 2180, 2360 and 2550 cents for zones 2 through 8, plus 120 cents multiplied by the order's `total_units`."
        PRD §3.8: "Savings versus the distribution centre are the baseline minus the store cost, and may of course be negative."

        Design: Difficulty/dual_variant_calc/order_cost_tier_flips_between_provisional_and_final_pass
        """
        ctx = _ship_nine_units_in_the_derived_box(order_code="O-1003")

        comparison = cost_comparison(ctx["order"]["id"])

        assert comparison["variant"] == "FINAL", (
            "a SHIPPED order reads on the FINAL variant, got "
            f"{comparison['variant']}"
        )
        assert comparison["parcel_count"] == 1, (
            f"only one assignment shipped, got {comparison['parcel_count']}"
        )
        assert comparison["component_sum_cents"] == 1590, (
            "the final pass sums the shipped assignment's final cost of 15 actual "
            "labour minutes, the MEDIUM_BOX and 9 picked units: expected 1590, got "
            f"{comparison['component_sum_cents']}"
        )
        assert comparison["split_penalty_cents"] == 0, (
            "a single parcel carries no split penalty, got "
            f"{comparison['split_penalty_cents']}"
        )
        assert comparison["reroute_overhead_cents"] == 0, (
            "no reroute attempt happened, got "
            f"{comparison['reroute_overhead_cents']}"
        )
        assert comparison["pre_fee_subtotal_cents"] == 1590, (
            "the pre-fee subtotal is the component sum with no penalty and no "
            f"overhead: expected 1590, got {comparison['pre_fee_subtotal_cents']}"
        )
        assert comparison["network_fee_rate"] == pytest.approx(0.060, abs=0.0001), (
            "a pre-fee subtotal strictly below 2000 cents keys the 6.0 percent "
            f"tier, got {comparison['network_fee_rate']}"
        )
        assert comparison["network_fee_cents"] == 95, (
            "1590 at 6.0 percent rounded half-up is 95, got "
            f"{comparison['network_fee_cents']}"
        )
        assert comparison["store_cost_cents"] == 1685, (
            "the store cost is 1590 plus the 95-cent fee, got "
            f"{comparison['store_cost_cents']}"
        )
        assert comparison["dc_baseline_cost_cents"] == 2930, (
            "the zone-4 baseline of 1850 plus 120 cents for each of 9 units is "
            f"2930, got {comparison['dc_baseline_cost_cents']}"
        )
        assert comparison["cost_index_bps"] == 5751, (
            "1685 * 10000 / 2930 rounded half-up is 5751, got "
            f"{comparison['cost_index_bps']}"
        )
        assert comparison["savings_vs_dc_cents"] == 1245, (
            "savings are the 2930 baseline minus the 1685 store cost, got "
            f"{comparison['savings_vs_dc_cents']}"
        )

    def test_order_cost_variance_is_negative_when_the_fee_tier_drops(self):
        """PRD §3.8: "The **provisional** variant, kept live in `provisional_cost_cents` after every routing change and every assignment status change, includes the order's assignments whose `status` is neither `REJECTED` nor `CANCELLED` — that is, the five non-terminal statuses plus `SHIPPED` — using each one's `provisional_cost_cents`."
        PRD §3.8: "The **final** variant, written to `final_cost_cents` when `fulfillment_status` becomes `SHIPPED`, includes only assignments at `status` `SHIPPED`, using each one's `final_cost_cents`; because the component sum changes, the fee tier can land in a different band than the provisional pass did, which is exactly what `cost_variance_cents` — `final_cost_cents` minus `provisional_cost_cents` — is there to expose."
        PRD §3.8: "The overhead fee rate is then keyed on the pre-fee subtotal: 6.0 percent when the subtotal is strictly below 2000 cents, 4.5 percent when it is strictly below 5000 cents, and 3.0 percent at or above 5000 cents."
        PRD §3.6: "From `PENDING`, a ship that leaves `shipped_units` above 0 with that same sum exactly equal to `total_units` moves the order straight to `SHIPPED`, writing `final_cost_cents` on the final variant, setting `cost_variance_cents` to `final_cost_cents` minus `provisional_cost_cents`, and recomputing `cost_index_bps` against the final figure."

        Design: Difficulty/dual_variant_calc/order_cost_tier_flips_between_provisional_and_final_pass
        """
        ctx = _ship_nine_units_in_the_derived_box(order_code="O-1003")
        order = read_order(ctx["order"]["id"])

        assert order["provisional_cost_cents"] == 2715, (
            "the provisional pass keys its fee on a 2598-cent subtotal, so the 4.5 "
            f"percent tier applies: expected 2715, got {order['provisional_cost_cents']}"
        )
        assert order["final_cost_cents"] == 1685, (
            "the final pass keys its fee on a 1590-cent subtotal, so the 6.0 "
            f"percent tier applies: expected 1685, got {order['final_cost_cents']}"
        )
        assert order["cost_variance_cents"] == -1030, (
            "cost_variance_cents is final minus provisional and goes negative when "
            f"the cheaper actual labour drops the fee tier: expected -1030, got "
            f"{order['cost_variance_cents']}"
        )
