"""Two quantities in this service exist in two variants at once.

The tolling fee is quoted from the pump's nominal ramp rate at scheduling time and
re-derived from the chart recorder at disposition time.  A package failure rate is
read both as one load's own instantaneous reading and as its customer's pooled
trailing rate over a moving ninety-day window.  Each pair is exercised on a
single set of stored rows, so any divergence is attributable to the variant alone.
"""

from test_helpers import (
    assert_instant_equals,
    inspect_load,
    read_customer,
    read_cycle,
    read_load,
    run_day_close,
    set_clock,
    setup_dispositioned_clean_cycle,
    setup_loaded_cycle,
)


# --------------------------------------------------------------------------- #
# the estimated and actual tolling fee on one cycle
# --------------------------------------------------------------------------- #
def test_estimated_cycle_time_comes_from_the_pumps_nominal_ramp_rate():
    """A cycle scheduled for 600 MPa on a machine ramping at 6.0 MPa/s and taking
    12 seconds to decompress is quoted at 180 + 100 + 180 + 12 seconds.

    PRD 3.5: "**Cycle time** is the sum of four terms: a flat 180 seconds of
    load-and-unload handling, the come-up time to reach target pressure, the hold
    time at pressure, and the vessel's fixed `decompression_seconds`."
    PRD 3.5: "Under the **ESTIMATED** variant used at scheduling time, come-up is
    the cycle's `target_pressure_mpa` divided by the vessel's
    `pump_ramp_rate_mpa_per_sec`, rounded up to a whole second, and hold is the
    cycle's `target_hold_seconds`; the result is stored as
    `estimated_cycle_seconds`."
    PRD 3.5: "Before the row is written, the service computes the cycle's
    estimated duration and price, which in turn fixes `scheduled_end` as
    `scheduled_start` advanced by `estimated_cycle_seconds`, and therefore fixes
    the interval of vessel occupancy the schedule must respect."

    Design: Difficulty/dual_variant_calc/tolling_fee_estimated_vs_actual_same_cycle
    """
    world = setup_loaded_cycle()
    cycle = world["cycle"]

    assert cycle["estimated_cycle_seconds"] == 472
    assert_instant_equals(cycle["scheduled_end"], "2026-08-05T09:07:52Z")


def test_estimated_tolling_fee_prices_the_half_full_chamber_at_eleven_thousand_four_hundred():
    """Two of four baskets is 50.00 percent utilisation, which draws the heaviest
    surcharge and, through the gross charge, the richest credit: 8 billable
    minutes of base, a 20 percent surcharge and a 5 percent credit.

    PRD 3.5: "Billable minutes are the cycle seconds divided by 60 and rounded
    **up** to a whole minute, however small the remainder; the base charge in
    cents is billable minutes multiplied by 1,250 cents per minute."
    PRD 3.5: "Chamber utilisation, `utilization_pct`, is 100 multiplied by the
    cycle's `baskets_used_total` and divided by the vessel's `basket_count`,
    rounded half up to two decimal places."
    PRD 3.5: "The net tolling fee is the gross charge minus the credit, and under
    the ESTIMATED variant it is stored as `estimated_tolling_fee_cents`."

    Design: Difficulty/dual_variant_calc/tolling_fee_estimated_vs_actual_same_cycle
    """
    world = setup_loaded_cycle()
    cycle = world["cycle"]

    assert cycle["baskets_used_total"] == 2
    assert cycle["utilization_pct"] == 50.00
    assert cycle["estimated_tolling_fee_cents"] == 11400


def test_actual_tolling_fee_reprices_the_same_cycle_from_the_measured_record():
    """The chart recorder measured 104 seconds of come-up and 195 seconds of hold
    against a 100/180 plan, so the run is 491 seconds and bills a ninth minute:
    11250 of base, 2250 of surcharge and a 675-cent credit.

    PRD 3.8: "At disposition, cycle time and price are recomputed under the
    **ACTUAL** variant."
    PRD 3.6: "Its own `actual_cycle_seconds` is the 180 seconds of load-and-unload
    handling plus the recorded `come_up_seconds` plus the recorded
    `actual_hold_seconds` plus the vessel's `decompression_seconds`."
    PRD 3.8: "with exactly two substitutions: come-up time is the control-point
    record's measured `come_up_seconds` rather than a figure derived from the
    pump's nominal ramp rate, and hold time is the record's measured
    `actual_hold_seconds` rather than the cycle's target."

    Design: Difficulty/dual_variant_calc/tolling_fee_estimated_vs_actual_same_cycle
    """
    world = setup_dispositioned_clean_cycle()
    cycle = world["cycle"]

    assert cycle["actual_cycle_seconds"] == 491
    assert cycle["actual_tolling_fee_cents"] == 12825
    assert cycle["state"] == "DISPOSITIONED"


def test_the_two_variants_disagree_and_the_sole_load_carries_the_actual_fee():
    """The estimate survives disposition untouched at 11400 while the actual fee
    lands at 12825, and the single participating load takes all of the latter.

    PRD 3.8: "The two variants routinely disagree for identical scheduling inputs,
    because a slower pump or a longer hold can cross a whole-minute boundary and
    thereby change the billable minutes, the surcharge base and even the credit
    tier."
    PRD 3.8: "Alongside the fee, disposition advances the cycle to
    `DISPOSITIONED`, stamps `dispositioned_at` with the logical clock, and moves
    each participating load's `disposition_state` from `PENDING` to `ALLOCATED`"

    Design: Difficulty/dual_variant_calc/tolling_fee_estimated_vs_actual_same_cycle
    """
    world = setup_dispositioned_clean_cycle()
    cycle = world["cycle"]
    load = world["load"]

    assert cycle["estimated_tolling_fee_cents"] == 11400
    assert cycle["actual_tolling_fee_cents"] == 12825
    assert cycle["actual_tolling_fee_cents"] != cycle["estimated_tolling_fee_cents"]
    assert load["allocated_fee_cents"] == 12825
    assert load["disposition_state"] == "ALLOCATED"


# --------------------------------------------------------------------------- #
# the instantaneous load rate and the customer's trailing rate
# --------------------------------------------------------------------------- #
def test_one_loads_own_failure_rate_reads_three_thousand_parts_per_million():
    """Three leaking units in exactly one thousand inspected is 3000 ppm, which
    puts the liability on the brand owner and prices handling plus rework.

    PRD 3.8: "The load's failure rate, `leaker_ppm`, is one million multiplied by
    `leaker_units` and divided by `units_inspected`, rounded half up to a whole
    part per million."
    PRD 3.8: "At 3,000 ppm or above, the `chargeback_party` is `CUSTOMER`
    outright — a single bad pallet makes the brand owner liable immediately."
    PRD 3.8: "Handling is `leaker_units` multiplied by 125 cents per leaking
    unit."

    Design: Difficulty/dual_variant_calc/leaker_rate_instantaneous_load_vs_trailing_90d_customer
    """
    world = setup_dispositioned_clean_cycle()

    inspect_load(world["load"]["id"], units_inspected=1000, leaker_units=3)
    load = read_load(world["load"]["id"])

    assert load["leaker_ppm"] == 3000
    assert load["chargeback_party"] == "CUSTOMER"
    assert load["chargeback_cents"] == 6788


def test_the_day_close_sweep_pools_the_same_counts_into_the_customers_trailing_rate():
    """The end-of-day sweep pools the load's three leakers over its thousand
    inspected units and writes 3000 ppm onto the customer.

    PRD 3.9: "The population for one customer is every load drawn from that
    customer's pallets whose `inspection_state` is `INSPECTED` and whose parent
    cycle's `dispositioned_at` falls inside the window."
    PRD 3.9: "otherwise it is one million multiplied by the sum of `leaker_units`
    across the population, divided by the sum of `units_inspected` across the same
    population, rounded half up to a whole part per million."
    PRD 3.9: "The sweep reports `expired_qualification_count`, the number of
    qualifications it moved to `EXPIRED`; `customers_rescored`, the number of
    customers whose trailing rate it recomputed; and `closed_at`, the logical
    clock instant at which the sweep ran."

    Design: Difficulty/dual_variant_calc/leaker_rate_instantaneous_load_vs_trailing_90d_customer
    """
    world = setup_dispositioned_clean_cycle()
    inspect_load(world["load"]["id"], units_inspected=1000, leaker_units=3)

    report = run_day_close()

    assert report["customers_rescored"] == 1
    assert_instant_equals(report["closed_at"], "2026-08-03T08:00:00Z")
    assert read_customer(world["customer"]["id"])["trailing_leaker_ppm"] == 3000


def test_the_trailing_window_drops_the_load_while_its_own_rate_never_ages():
    """Once the clock has moved past the ninety days, the same sweep rescores the
    customer to zero, and the load's own reading is untouched at 3000 ppm.

    PRD 3.9: "The window runs from 90 days before the current logical clock
    instant through that instant, inclusive at both ends."
    PRD 3.9: "When that population is empty the customer's `trailing_leaker_ppm`
    is 0"
    PRD 3.9: "Note that the pooling is across the whole population rather than an
    average of per-load rates, and that the window drops anything older — so the
    very load that produced a 3,000 ppm instantaneous reading contributes nothing
    to the customer's trailing rate once its cycle has aged out of the ninety
    days."

    Design: Difficulty/dual_variant_calc/leaker_rate_instantaneous_load_vs_trailing_90d_customer
    """
    world = setup_dispositioned_clean_cycle()
    inspect_load(world["load"]["id"], units_inspected=1000, leaker_units=3)
    run_day_close()
    assert read_customer(world["customer"]["id"])["trailing_leaker_ppm"] == 3000

    set_clock("2026-11-15T08:00:00Z")
    run_day_close()

    assert read_customer(world["customer"]["id"])["trailing_leaker_ppm"] == 0
    assert read_load(world["load"]["id"])["leaker_ppm"] == 3000
    assert read_cycle(world["cycle"]["id"])["actual_tolling_fee_cents"] == 12825
