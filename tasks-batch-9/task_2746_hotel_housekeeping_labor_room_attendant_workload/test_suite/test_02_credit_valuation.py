"""Credit valuation of a single room, and the wage tier that prices the shift."""

from test_helpers import (
    ASSIGN_ASSIGNED,
    COMPLIANCE_COMPLIANT,
    ROSTER_CLOSED,
    SERVICE_DEEP_CLEAN,
    assert_cents,
    assert_credits,
    assert_snapped_to_quarter,
    assert_whole_minutes,
    build_scenario,
    read_roster,
)


def _suite_only_shift(api):
    """A property whose only room type is a suite valued above the credit ceiling."""
    return build_scenario(
        api,
        room_type_codes=("SUITE",),
        rooms=[("201", "SUITE")],
        linen={"total_owned_sets": 20},
    )


def test_suite_deep_clean_snaps_to_a_quarter_then_clamps_to_the_credit_ceiling(api):
    """A 3.50-credit deep clean snaps to 3.50 and is then clamped down to 3.00.

    PRD 3.4: "A room type whose deep-clean value is 3.50 credits therefore snaps
    to 3.50 and is clamped down to 3.00."

    Design: Difficulty/combinatorial_formula/suite_deep_clean_credits_snap_to_quarter_then_clamp_to_ceiling
    """
    scenario = _suite_only_shift(api)

    assignment = scenario.assign("201", SERVICE_DEEP_CLEAN)

    assert assignment["status"] == ASSIGN_ASSIGNED
    assert_credits(assignment["credits"], 3.00, "assignment credits")
    assert assignment["credits"] != 3.50, (
        "the room type's 3.50 deep-clean value must not survive the ceiling clamp"
    )
    assert_snapped_to_quarter(assignment["credits"], "assignment credits")


def test_clamped_suite_credits_are_what_the_ordinance_totals_absorb(api):
    """The roster's ordinance totals read the clamped figure and the snapshotted footage.

    PRD 3.4: "Creation also snapshots the room type's `square_feet` into the
    assignment's own `square_feet_snapshot`."

    Design: Difficulty/combinatorial_formula/suite_deep_clean_credits_snap_to_quarter_then_clamp_to_ceiling
    """
    scenario = _suite_only_shift(api)

    assignment = scenario.assign("201", SERVICE_DEEP_CLEAN)

    assert assignment["square_feet_snapshot"] == 780, (
        f"square_feet_snapshot should be 780, got {assignment['square_feet_snapshot']}"
    )
    roster = read_roster(api, scenario.roster_id)
    assert_credits(roster["assigned_credits"], 3.00, "assigned_credits")
    assert roster["assigned_square_feet"] == 780
    assert roster["compliance_state"] == COMPLIANCE_COMPLIANT


def _overtime_shift(api):
    """One departure clean and one passing inspection, on a 3576-cents-per-hour wage."""
    scenario = build_scenario(
        api,
        rooms=[{"number": "101", "occupancy_state": "DUE_OUT"}],
        linen={"total_owned_sets": 20},
        worker_overrides={"hourly_rate_cents": 3576},
    )
    first = scenario.clean(
        "101",
        "CHECKOUT",
        "2026-08-03T10:00:00.000Z",
        "2026-08-03T10:30:00.000Z",
    )
    scenario.inspect(first["id"])
    return scenario


def test_ordinance_premium_tier_is_keyed_on_the_base_wage_not_on_the_total(api):
    """A 29800-cent base wage takes the four-percent band, giving 30992 cents in total.

    PRD 3.7: "The competing reading, keying the tier on the total that already
    contains the premium, is rejected: it would lift a base wage of 29800 cents
    into the higher band and produce 31886 cents instead of the correct 30992."

    Design: Difficulty/combinatorial_formula/labor_cost_premium_tier_keyed_on_base_wage_not_on_total
    """
    scenario = _overtime_shift(api)

    roster = scenario.close_roster(500, 40)

    assert_cents(roster["base_wage_cents"], 29800, "base_wage_cents")
    assert_cents(roster["ordinance_premium_cents"], 1192, "ordinance_premium_cents")
    assert_cents(roster["total_labor_cost_cents"], 30992, "total_labor_cost_cents")
    assert roster["total_labor_cost_cents"] != 31886, (
        "keying the premium tier on the premium-inclusive total is the rejected reading"
    )


def test_overtime_minutes_are_what_switch_the_ordinance_premium_on(api):
    """Paid minutes above the standard shift produce the overtime that earns the premium.

    PRD 3.7: "The premium applies only when the shift earned it: either
    `overtime_minutes` is greater than zero, or the roster's `compliance_state`
    as recomputed by this very close is `WAIVER_GRANTED`."

    Design: Difficulty/combinatorial_formula/labor_cost_premium_tier_keyed_on_base_wage_not_on_total
    """
    scenario = _overtime_shift(api)

    roster = scenario.close_roster(500, 40)

    assert_whole_minutes(roster["paid_minutes"], 500, "paid_minutes")
    assert_whole_minutes(roster["overtime_minutes"], 20, "overtime_minutes")
    assert roster["ordinance_premium_cents"] > 0, (
        "a shift carrying overtime minutes must attract the ordinance premium"
    )
    assert roster["status"] == ROSTER_CLOSED
