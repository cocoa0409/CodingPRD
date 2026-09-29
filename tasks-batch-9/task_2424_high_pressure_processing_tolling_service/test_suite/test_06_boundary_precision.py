"""Two thresholds in this service are exercised on the nose and one notch off.

The leaker rate's chargeback threshold is inclusive, so 3 leakers in exactly one
thousand units is enough to charge the brand owner while 2 in eight hundred is not.
The three critical-control-point comparisons are all strict, so a hold that exactly
equals the requirement is compliant while one second short is a deviation.
"""

from test_helpers import (
    add_stored_pallet,
    book_load,
    capture_cycle_log,
    commission_second_vessel,
    disposition_cycle,
    first_deviation_on_load,
    inspect_load,
    list_chargeback_lines,
    list_deviations,
    read_customer,
    read_cycle,
    read_load,
    read_lot,
    schedule_cycle,
    setup_running_cycle,
    setup_two_pallet_dispositioned_cycle,
    start_cycle,
)


# --------------------------------------------------------------------------- #
# leaker_ppm against the inclusive 3,000 ppm chargeback threshold
# --------------------------------------------------------------------------- #
def test_three_leakers_in_exactly_one_thousand_units_charges_the_brand_owner():
    """3000 ppm on the nose satisfies the at-or-above test, so handling plus half
    the load's 5456-cent allocation is billed to the customer.

    PRD 3.8: "At 3,000 ppm or above, the `chargeback_party` is `CUSTOMER` outright —
    a single bad pallet makes the brand owner liable immediately."
    PRD 3.8: "Rework is half the load's `allocated_fee_cents` — the allocated fee
    multiplied by 0.50 and rounded half up to a whole cent — but only when the load's
    `leaker_ppm` is at least 3,000; below that threshold the rework component is 0."

    Design: Difficulty/boundary_precision_check/leaker_ppm_exactly_at_chargeback_threshold
    """
    world = setup_two_pallet_dispositioned_cycle()
    assert world["cycle"]["utilization_pct"] == 100.00
    assert world["cycle"]["actual_tolling_fee_cents"] == 10912
    assert world["load"]["allocated_fee_cents"] == 5456

    inspect_load(world["load"]["id"], units_inspected=1000, leaker_units=3)
    load = read_load(world["load"]["id"])

    assert load["leaker_ppm"] == 3000
    assert load["chargeback_party"] == "CUSTOMER"
    assert load["chargeback_cents"] == 3103
    assert load["inspection_state"] == "INSPECTED"


def test_the_at_threshold_load_mints_a_package_leaker_line_and_a_major_deviation():
    """Being at the threshold both bills the line and raises the package-failure
    deviation that will block the whole cycle's releases.

    PRD 3.8: "Their sum is stored as `chargeback_cents`, and a chargeback line is
    minted with `basis` of `PACKAGE_LEAKER`, `amount_cents` equal to that sum,
    `customer_id` taken from the pallet behind the load, `cycle_load_id` naming this
    load, and `status` of `PENDING`; the customer's `chargeback_balance_cents` is
    recomputed upward accordingly."
    PRD 3.8: "A load at or above 3,000 ppm additionally raises a fresh `Deviation` at
    `OPEN`, with `deviation_type` of `PACKAGE_FAILURE_RATE`, `severity` of `MAJOR`,
    `worst_shortfall_pct` of 0.00, `cycle_load_id` pointing at this load and
    `cycle_log_id` null."

    Design: Difficulty/boundary_precision_check/leaker_ppm_exactly_at_chargeback_threshold
    """
    world = setup_two_pallet_dispositioned_cycle()

    inspect_load(world["load"]["id"], units_inspected=1000, leaker_units=3)
    lines = list_chargeback_lines(cycle_load_id=world["load"]["id"])
    deviation = first_deviation_on_load(world["load"]["id"])

    assert len(lines) == 1
    assert lines[0]["basis"] == "PACKAGE_LEAKER"
    assert lines[0]["amount_cents"] == 3103
    assert lines[0]["status"] == "PENDING"
    assert deviation["deviation_type"] == "PACKAGE_FAILURE_RATE"
    assert deviation["severity"] == "MAJOR"
    assert deviation["worst_shortfall_pct"] == 0.00
    assert deviation["status"] == "OPEN"
    assert deviation["cycle_log_id"] is None


def test_one_notch_below_the_threshold_leaves_the_cost_with_the_facility():
    """2 leakers in 800 units is 2500 ppm — inside the watch band but below 3,000 —
    and with the customer's stored trailing rate at 0 the facility absorbs it.

    PRD 3.8: "Failing that, the `chargeback_party` is still `CUSTOMER` when this
    load's rate is at least 1,500 ppm **and** the customer's stored
    `trailing_leaker_ppm` is at least 2,000 ppm, which is the facility's way of
    charging a repeat offender for a reading it would otherwise absorb."
    PRD 3.8: "When the party is `FACILITY`, the load's `chargeback_cents` is 0, no
    chargeback line is created, and the customer's `chargeback_balance_cents` is
    unchanged."

    Design: Difficulty/boundary_precision_check/leaker_ppm_exactly_at_chargeback_threshold
    """
    world = setup_two_pallet_dispositioned_cycle()

    inspect_load(world["load2"]["id"], units_inspected=800, leaker_units=2)
    load2 = read_load(world["load2"]["id"])

    assert load2["leaker_ppm"] == 2500
    assert load2["chargeback_party"] == "FACILITY"
    assert load2["chargeback_cents"] == 0
    assert list_chargeback_lines(cycle_load_id=world["load2"]["id"]) == []
    assert list_deviations(cycle_load_id=world["load2"]["id"]) == []


def test_only_the_at_threshold_load_moves_the_customers_balance():
    """Inspecting both loads leaves the balance holding exactly the one pending
    line, and the trailing rate stays at 0 because inspection never recomputes it.

    PRD 2.9: "The **chargeback balance** on a customer holds that
    `chargeback_balance_cents` always equals the sum of `amount_cents` over that
    customer's chargeback lines whose `status` is `PENDING`, whatever the line's
    `basis`."
    PRD 3.8: "The customer's `trailing_leaker_ppm` is read exactly as stored — the
    value left behind by the last end-of-day sweep — and is never recomputed inline
    by the inspection."

    Design: Difficulty/boundary_precision_check/leaker_ppm_exactly_at_chargeback_threshold
    """
    world = setup_two_pallet_dispositioned_cycle()

    inspect_load(world["load"]["id"], units_inspected=1000, leaker_units=3)
    inspect_load(world["load2"]["id"], units_inspected=800, leaker_units=2)
    customer = read_customer(world["customer"]["id"])

    assert customer["chargeback_balance_cents"] == 3103
    assert customer["trailing_leaker_ppm"] == 0


# --------------------------------------------------------------------------- #
# the three CCP comparisons at, and one second past, their limits
# --------------------------------------------------------------------------- #
def test_pressure_hold_and_water_temperature_exactly_at_their_limits_are_compliant():
    """600.0 MPa against a required 600.0, 180 seconds against a required 180 and
    8.0 C against an 8.0 C ceiling raise no flag at all.

    PRD 3.6: "Three flags are then evaluated and collected in a fixed order that is
    never re-sorted: `UNDER_PRESSURE` when the recorded pressure is strictly below
    the required pressure, `SHORT_HOLD` when the recorded hold is strictly below the
    required hold, and `TEMP_EXCURSION` when the recorded water temperature is
    strictly above the limit."
    PRD 3.6: "The record's `ccp_verdict` is `WITHIN_LIMITS` when the flag list is
    empty and `DEVIATION` otherwise."

    Design: Difficulty/boundary_precision_check/actual_hold_exactly_equals_required_hold
    """
    world = setup_running_cycle()

    record = capture_cycle_log(
        world["cycle"]["id"],
        actual_pressure_mpa=600.0,
        actual_hold_seconds=180,
        come_up_seconds=100,
        water_temp_c=8.0,
    )

    assert record["ccp_verdict"] == "WITHIN_LIMITS"
    assert record["deviation_flags"] == []


def test_the_compliant_record_takes_the_clean_branch_and_creates_no_deviation():
    """A `WITHIN_LIMITS` record advances the run to `COMPLETED_CLEAN`, leaves the
    pallet off hold, and — once dispositioned — prices out identically to the
    estimate because the measured come-up and hold matched the plan.

    PRD 3.6: "On the clean branch the cycle advances `RUNNING → COMPLETED_CLEAN`, no
    deviation is created, and every pallet's `release_state` stays exactly where it
    was at `NOT_RELEASED`."
    PRD 3.6: "Its own `actual_cycle_seconds` is the 180 seconds of load-and-unload
    handling plus the recorded `come_up_seconds` plus the recorded
    `actual_hold_seconds` plus the vessel's `decompression_seconds`."

    Design: Difficulty/boundary_precision_check/actual_hold_exactly_equals_required_hold
    """
    world = setup_running_cycle()
    capture_cycle_log(
        world["cycle"]["id"],
        actual_pressure_mpa=600.0,
        actual_hold_seconds=180,
        come_up_seconds=100,
        water_temp_c=8.0,
    )
    assert read_cycle(world["cycle"]["id"])["state"] == "COMPLETED_CLEAN"
    assert list_deviations(cycle_id=world["cycle"]["id"]) == []

    disposition_cycle(world["cycle"]["id"])
    cycle = read_cycle(world["cycle"]["id"])

    assert cycle["actual_cycle_seconds"] == 472
    assert cycle["actual_tolling_fee_cents"] == 11400
    assert cycle["actual_tolling_fee_cents"] == cycle["estimated_tolling_fee_cents"]
    assert read_lot(world["lot"]["id"])["release_state"] == "NOT_RELEASED"


def test_one_second_short_of_the_required_hold_is_a_major_short_hold_deviation():
    """179 seconds against a required 180 is a 0.56 percent shortfall, which is under
    the 5.00 percent line and therefore MAJOR rather than CRITICAL.

    PRD 3.6: "The hold shortfall is 0.00 when the recorded hold is at least the
    required hold, and otherwise 100 multiplied by the required hold minus the
    recorded hold, divided by the required hold."
    PRD 3.6: "The largest of those three percentages becomes the deviation's
    `worst_shortfall_pct`, and its `severity` is `CRITICAL` when that figure is at
    least 5.00 percent and `MAJOR` otherwise."
    PRD 3.6: "First, a `Deviation` is created at `OPEN`, pointing at this cycle and
    at this control-point record through `cycle_log_id`, with `cycle_load_id` null,
    its `deviation_type` set to the **first** entry of `deviation_flags` in the fixed
    order `UNDER_PRESSURE`, `SHORT_HOLD`, `TEMP_EXCURSION`, and its `severity` and
    `worst_shortfall_pct` as computed above"

    Design: Difficulty/boundary_precision_check/actual_hold_exactly_equals_required_hold
    """
    world = setup_running_cycle()
    second_pallet = add_stored_pallet(world, "PAL-002", 800)
    second_vessel = commission_second_vessel()
    sibling = schedule_cycle(second_vessel["id"], world["family"]["id"])
    book_load(
        sibling["id"],
        second_pallet["id"],
        world["contract"]["id"],
        baskets_used=2,
        units_loaded=800,
        expected_cycle_version=sibling["version"],
    )
    start_cycle(sibling["id"])

    record = capture_cycle_log(
        sibling["id"],
        actual_pressure_mpa=600.0,
        actual_hold_seconds=179,
        come_up_seconds=120,
        water_temp_c=7.0,
    )
    deviations = list_deviations(cycle_id=sibling["id"])

    assert record["ccp_verdict"] == "DEVIATION"
    assert record["deviation_flags"] == ["SHORT_HOLD"]
    assert read_cycle(sibling["id"])["state"] == "COMPLETED_DEVIATED"
    assert len(deviations) == 1
    assert deviations[0]["deviation_type"] == "SHORT_HOLD"
    assert deviations[0]["severity"] == "MAJOR"
    assert deviations[0]["worst_shortfall_pct"] == 0.56
    assert deviations[0]["status"] == "OPEN"


def test_both_branches_move_the_units_out_of_the_chamber():
    """Whether the record is compliant or not, the shared consequences run: every
    loaded pallet's chamber units become treated units.

    PRD 3.6: "Both branches share a common set of consequences: the immutable record
    is appended, the cycle's `actual_cycle_seconds` is taken from it, the vessel
    returns `IN_USE → AVAILABLE` and its `cycles_run_count` rises by one, and every
    loaded pallet advances `IN_VESSEL → TREATED`, moving its `units_in_vessel` into
    `units_treated`."

    Design: Difficulty/boundary_precision_check/actual_hold_exactly_equals_required_hold
    """
    world = setup_running_cycle()
    second_pallet = add_stored_pallet(world, "PAL-002", 800)
    second_vessel = commission_second_vessel()
    sibling = schedule_cycle(second_vessel["id"], world["family"]["id"])
    book_load(
        sibling["id"],
        second_pallet["id"],
        world["contract"]["id"],
        baskets_used=2,
        units_loaded=800,
        expected_cycle_version=sibling["version"],
    )
    start_cycle(sibling["id"])

    capture_cycle_log(
        world["cycle"]["id"],
        actual_pressure_mpa=600.0,
        actual_hold_seconds=180,
        come_up_seconds=100,
        water_temp_c=8.0,
    )
    capture_cycle_log(
        sibling["id"],
        actual_pressure_mpa=600.0,
        actual_hold_seconds=179,
        come_up_seconds=120,
        water_temp_c=7.0,
    )

    clean_pallet = read_lot(world["lot"]["id"])
    deviated_pallet = read_lot(second_pallet["id"])
    assert clean_pallet["units_treated"] == 1000
    assert clean_pallet["units_in_vessel"] == 0
    assert deviated_pallet["units_treated"] == 800
    assert deviated_pallet["units_in_vessel"] == 0
