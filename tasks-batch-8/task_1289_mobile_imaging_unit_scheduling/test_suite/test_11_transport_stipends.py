"""Transport-leg stipends: per-leg rounding order, plan totals, overnight per
diem."""
from test_helpers import (
    TEST_USERS,
    plan_transport_leg,
    setup_bookable_day,
    validate_success,
)

OPS = TEST_USERS["operations_director_headers"]


def test_leg_stipend_rounded_per_leg(api):
    """PRD §3.2: "A new leg starts `PLANNED` and immediately earns its stipend:
    `stipend_cents` is the leg's `distance_miles` multiplied by the fleet
    mileage rate of 67 cents per mile, rounded half-up to whole cents, plus a
    flat per diem of 15,000 cents when `overnight` is true."

    Design: Difficulty/combinatorial_formula/route_stipend_per_leg_rounding_order
    """
    bundle = setup_bookable_day()
    day = bundle["site_day"]

    leg1 = plan_transport_leg(day["id"], distance_miles=10.01, drive_minutes=20)
    leg2 = plan_transport_leg(
        day["id"], origin_name=bundle["facility"]["name"], destination_name="Depot",
        distance_miles=10.01, drive_minutes=20,
    )
    # round_half_up(10.01 * 67) = round_half_up(670.67) = 671 per leg.
    assert leg1["stipend_cents"] == 671, (
        f"Per-leg stipend must be 671, got {leg1['stipend_cents']}"
    )
    assert leg2["stipend_cents"] == 671, (
        f"Per-leg stipend must be 671, got {leg2['stipend_cents']}"
    )


def test_plan_total_sums_per_leg_stipends(api):
    """PRD §3.2: "The plan's `total_travel_stipend_cents` is then recomputed as
    the sum of the per-leg stipends across all of the plan's site days — each
    leg rounded first, then summed, in that pinned order — and legs keep their
    stipend even if they later end `FAILED` or `CANCELLED`, because the cost
    was committed at dispatch planning."

    Design: Difficulty/combinatorial_formula/route_stipend_per_leg_rounding_order
    """
    bundle = setup_bookable_day()
    day = bundle["site_day"]

    plan_transport_leg(day["id"], distance_miles=10.01, drive_minutes=20)
    plan_transport_leg(
        day["id"], origin_name=bundle["facility"]["name"], destination_name="Depot",
        distance_miles=10.01, drive_minutes=20,
    )
    plan = validate_success(api.get_route_plan(bundle["plan"]["id"], OPS))
    # Per-leg-then-sum: 671 + 671 = 1342. Sum-then-round of 20.02 * 67 would
    # give 1341 and is non-conformant.
    assert plan["total_travel_stipend_cents"] == 1342, (
        f"Plan total must round each leg first, then sum: expected 1342, "
        f"got {plan['total_travel_stipend_cents']}"
    )


def test_overnight_leg_adds_per_diem(api):
    """PRD §3.2: "A new leg starts `PLANNED` and immediately earns its stipend:
    `stipend_cents` is the leg's `distance_miles` multiplied by the fleet
    mileage rate of 67 cents per mile, rounded half-up to whole cents, plus a
    flat per diem of 15,000 cents when `overnight` is true."

    Design: Corner/calculations/overnight_leg_adds_per_diem
    """
    bundle = setup_bookable_day()
    leg = plan_transport_leg(
        bundle["site_day"]["id"], distance_miles=10.01, drive_minutes=20, overnight=True
    )
    # round_half_up(10.01 * 67) = 671, plus the 15000 per diem.
    assert leg["stipend_cents"] == 15671, (
        f"Overnight leg must add the 15000 per diem after mileage rounding: "
        f"expected 15671, got {leg['stipend_cents']}"
    )
