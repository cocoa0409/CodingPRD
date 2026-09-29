"""The tolling fee is assembled from ordered stages, then divided by basket weight.

The surcharge is applied before any credit and the credit tier is keyed on the
gross charge, so an under-filled chamber can buy itself a richer discount.  On the
way out, the net fee is split by truncation with the leftover cents handed to the
heaviest loads, which is the only allocation that sums back to the fee.
"""

from test_helpers import (
    assert_allocation_sums_to,
    book_load,
    disposition_cycle,
    read_cycle,
    read_load,
    setup_loaded_cycle,
    setup_three_load_cycle_on_second_vessel,
)


# --------------------------------------------------------------------------- #
# surcharge before credit, credit tier keyed on gross
# --------------------------------------------------------------------------- #
def test_the_utilisation_surcharge_is_applied_before_any_loyalty_credit():
    """A 50.00 percent chamber draws the 0.20 surcharge on a 10000-cent base,
    producing a 12000-cent gross charge before anything is subtracted.

    PRD 3.5: "Next comes the utilisation surcharge, and it is applied *before* any
    credit."
    PRD 3.5: "When utilisation is below 60.00 percent the surcharge rate is 0.20;
    otherwise, when utilisation is below 85.00 percent the rate is 0.08; at 85.00
    percent or above there is no surcharge."
    PRD 3.5: "The surcharge in cents is the base charge multiplied by that rate,
    rounded half up to a whole cent. The gross charge is the base charge plus the
    surcharge."

    Design: Difficulty/combinatorial_formula/fee_surcharge_lifts_loyalty_tier_pinned_order
    """
    world = setup_loaded_cycle()
    cycle = world["cycle"]

    assert cycle["utilization_pct"] == 50.00
    assert cycle["estimated_cycle_seconds"] == 472
    # 8 billable minutes at 1250 cents is a 10000-cent base; the 0.20 surcharge
    # adds 2000, and the 0.05 credit on the 12000-cent gross removes 600.
    assert cycle["estimated_tolling_fee_cents"] == 11400


def test_the_loyalty_tier_is_keyed_on_the_gross_charge_not_on_the_base_charge():
    """The 10000-cent base alone would earn only the 0.03 tier and leave 11640;
    keyed on the 12000-cent gross the cycle earns 0.05 and lands at 11400.

    PRD 3.5: "A loyalty credit is then subtracted, and the tier it lands in is
    keyed on the **gross** charge — base plus surcharge — not on the base charge
    alone."
    PRD 3.5: "This matters: a badly under-filled chamber can be pushed into a
    richer credit tier by its own surcharge, and that is the intended behaviour."
    PRD 3.5: "When the gross charge is at least 12,000 cents the credit rate is
    0.05; otherwise, when the gross charge is at least 8,000 cents the credit rate
    is 0.03; below 8,000 cents there is no credit."

    Design: Difficulty/combinatorial_formula/fee_surcharge_lifts_loyalty_tier_pinned_order
    """
    world = setup_loaded_cycle()
    cycle = world["cycle"]

    assert cycle["state"] == "LOADED"
    assert cycle["estimated_tolling_fee_cents"] == 11400
    assert cycle["estimated_tolling_fee_cents"] != 11640


def test_each_booking_tightens_the_estimate_as_the_chamber_fills():
    """A second load lifts utilisation from 50.00 to 100.00 percent, which removes
    the surcharge, drops the gross charge to the base and re-tiers the credit.

    PRD 3.5: "The cycle's `baskets_used_total`, `utilization_pct`,
    `estimated_cycle_seconds`, `estimated_tolling_fee_cents` and `scheduled_end`
    are all recomputed under the ESTIMATED variant, so each booking tightens the
    estimate as the chamber fills."
    PRD 3.5: "When utilisation is below 60.00 percent the surcharge rate is 0.20;
    otherwise, when utilisation is below 85.00 percent the rate is 0.08; at 85.00
    percent or above there is no surcharge."

    Design: Difficulty/combinatorial_formula/fee_surcharge_lifts_loyalty_tier_pinned_order
    """
    from test_helpers import add_stored_pallet

    world = setup_loaded_cycle()
    second_pallet = add_stored_pallet(world, "PAL-002", 800)
    book_load(
        world["cycle"]["id"],
        second_pallet["id"],
        world["contract"]["id"],
        baskets_used=2,
        units_loaded=800,
    )
    cycle = read_cycle(world["cycle"]["id"])

    assert cycle["baskets_used_total"] == 4
    assert cycle["utilization_pct"] == 100.00
    # No surcharge at 100.00 percent: the 10000-cent base is also the gross, so
    # the credit rate is 0.03 and the estimate is 10000 - 300.
    assert cycle["estimated_tolling_fee_cents"] == 9700


# --------------------------------------------------------------------------- #
# the waterfall allocation across three loads
# --------------------------------------------------------------------------- #
def test_the_three_load_run_freezes_a_net_fee_of_eleven_thousand_five_hundred_forty_two():
    """Four of six baskets is 66.67 percent, which draws the 0.08 surcharge on a
    9-minute base, and the 12150-cent gross earns the 0.05 credit.

    PRD 3.5: "Chamber utilisation, `utilization_pct`, is 100 multiplied by the
    cycle's `baskets_used_total` and divided by the vessel's `basket_count`,
    rounded half up to two decimal places."
    PRD 3.8: "The arithmetic is identical to the estimated variant of §3.5 in
    every step — the flat 180 seconds of handling, the vessel's
    `decompression_seconds`, the round-up to whole billable minutes, the 1,250
    cents per minute base, the utilisation surcharge tiers at 60.00 and 85.00
    percent with rates of 0.20 and 0.08, the gross-keyed loyalty credit tiers at
    12,000 and 8,000 cents with rates of 0.05 and 0.03, and the final
    subtraction"

    Design: Difficulty/combinatorial_formula/cycle_fee_allocation_floor_then_remainder_by_baskets
    """
    world = setup_three_load_cycle_on_second_vessel()

    disposition_cycle(world["cycle"]["id"])
    cycle = read_cycle(world["cycle"]["id"])

    assert cycle["actual_cycle_seconds"] == 495
    assert cycle["utilization_pct"] == 66.67
    assert cycle["actual_tolling_fee_cents"] == 11542


def test_shares_are_truncated_and_the_leftover_cent_goes_to_the_heaviest_load():
    """The one-basket loads truncate from 2885.5 to 2885 and the two-basket load
    takes both its exact 5771 and the single leftover cent.

    PRD 3.8: "Each load's base share is the total multiplied by that load's
    `baskets_used`, divided by the divisor, and then **truncated downward** to a
    whole cent."
    PRD 3.8: "Truncation leaves a remainder — the total minus the sum of the
    truncated shares, always at least zero and always fewer cents than there are
    participating loads — and those leftover cents are handed out one cent at a
    time to the loads at the front of a queue ordered by `baskets_used`
    descending and then by `created_at` ascending."

    Design: Difficulty/combinatorial_formula/cycle_fee_allocation_floor_then_remainder_by_baskets
    """
    world = setup_three_load_cycle_on_second_vessel()

    disposition_cycle(world["cycle"]["id"])

    assert read_load(world["loadA"]["id"])["allocated_fee_cents"] == 2885
    assert read_load(world["loadB"]["id"])["allocated_fee_cents"] == 2885
    assert read_load(world["loadC"]["id"])["allocated_fee_cents"] == 5772


def test_the_allocated_shares_sum_back_to_the_fee_being_divided():
    """2885 + 2885 + 5772 is exactly 11542; rounding each share half up would have
    produced 11543 and broken the identity.

    PRD 3.8: "At that point the allocated amounts sum to the total exactly."
    PRD 3.8: "Rounding each share half up independently and then summing them is
    the tempting alternative and is **not** what this service does, because it
    produces a total that does not match the fee being divided."

    Design: Difficulty/combinatorial_formula/cycle_fee_allocation_floor_then_remainder_by_baskets
    """
    world = setup_three_load_cycle_on_second_vessel()

    disposition_cycle(world["cycle"]["id"])
    cycle = read_cycle(world["cycle"]["id"])
    loads = [
        read_load(world["loadA"]["id"]),
        read_load(world["loadB"]["id"]),
        read_load(world["loadC"]["id"]),
    ]

    assert_allocation_sums_to(loads, cycle["actual_tolling_fee_cents"])
    assert sum(load["allocated_fee_cents"] for load in loads) == 11542
