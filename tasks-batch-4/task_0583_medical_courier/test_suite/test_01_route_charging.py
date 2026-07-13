"""Route charging: the provisional charge at dispatch and the final charge at completion."""
from test_helpers import (
    validate_success,
    TEST_USERS,
    fixtures,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Provisional (dispatch) vs final (completion) — the same route, two figures
# ---------------------------------------------------------------------------
def test_provisional_charge_rounds_whole_route_mileage_once(api):
    """PRD §3.4: "The mileage subtotal is `planned_total_miles` multiplied by
    `per_mile_rate_cents`, with that single product rounded half-up to whole cents."
    PRD §3.4: "The stop subtotal is `per_stop_fee_cents` multiplied by the count of
    every stop on the route, regardless of state."
    PRD §3.4: "The temperature subtotal is `temp_handling_fee_cents` multiplied by the
    number of specimens whose `temp_requirement` is anything other than `AMBIENT`."

    Two stops at 500 each, 6.0 planned miles at 133 c/mile rounded once (798), and one
    REFRIGERATED specimen at 800: a SCHEDULED run carries no surcharge, so the
    provisional charge is 2598.

    Design: Difficulty/dual_variant_calc/route_charge_provisional_vs_final
    """
    ctx = fixtures.setup_dispatched_route()
    route = validate_success(api.get_route(ctx["route"]["id"], DISPATCHER))
    assert route["provisional_charge_cents"] == 2598, (
        f"Expected provisional 2598 (1000 stops + 798 miles + 800 temp), "
        f"got {route['provisional_charge_cents']}"
    )


def test_final_charge_rounds_each_completed_leg_then_sums(api):
    """PRD §3.7: "rather than rounding the whole route's mileage once, the final charge
    rounds each served leg independently and then sums."
    PRD §3.7: "Each such stop contributes its `leg_charge_cents`, equal to
    `per_stop_fee_cents` plus the product of that stop's `actual_leg_miles` and
    `per_mile_rate_cents` rounded half-up to whole cents."

    Legs of 2.5 and 3.5 actual miles round to 333 and 466 cents, so the leg-and-stop
    subtotal is 833 + 966 = 1799; plus the 800-cent temperature subtotal for the one
    delivered REFRIGERATED specimen the final charge is 2599.

    Design: Difficulty/dual_variant_calc/route_charge_provisional_vs_final
    """
    ctx = fixtures.setup_completed_route()
    route = validate_success(api.get_route(ctx["route"]["id"], DISPATCHER))
    assert route["final_charge_cents"] == 2599, (
        f"Expected final 2599 (833 + 966 legs + 800 temp), got {route['final_charge_cents']}"
    )


def test_provisional_and_final_charges_diverge_on_the_same_route(api):
    """PRD §3.7: "Because the provisional charge rounds the planned mileage once while
    the final charge rounds each completed leg before summing, the two figures diverge
    whenever per-leg rounding and whole-route rounding differ, and they also diverge
    whenever stops were missed or temperature specimens went undelivered."

    Design: Difficulty/dual_variant_calc/route_charge_provisional_vs_final
    """
    ctx = fixtures.setup_completed_route()
    route = validate_success(api.get_route(ctx["route"]["id"], DISPATCHER))
    assert route["provisional_charge_cents"] == 2598
    assert route["final_charge_cents"] == 2599
    assert route["provisional_charge_cents"] != route["final_charge_cents"], (
        "Per-leg rounding (2599) must diverge from whole-route rounding (2598)"
    )


# ---------------------------------------------------------------------------
# The provisional formula: conditional STAT branch and its capped surcharge
# ---------------------------------------------------------------------------
def test_stat_provisional_charge_adds_uncapped_surcharge(api):
    """PRD §3.4: "On a `STAT` run a surcharge is added equal to the base multiplied by
    `stat_surcharge_pct`, rounded half-up to whole cents, then capped so the surcharge
    is the smaller of that rounded amount and `stat_surcharge_cap_cents`; on a
    `SCHEDULED` run the surcharge is zero."

    Base 2598 * 0.30 = 779.4 -> 779, well under the 10000 cap, so the STAT provisional
    charge is 2598 + 779 = 3377.

    Design: Difficulty/combinatorial_formula/provisional_charge_conditional_capped_mode_a
    """
    ctx = fixtures.setup_dispatched_route(route={"run_type": "STAT"})
    route = validate_success(api.get_route(ctx["route"]["id"], DISPATCHER))
    assert route["provisional_charge_cents"] == 3377, (
        f"Expected 2598 base + 779 surcharge = 3377, got {route['provisional_charge_cents']}"
    )


def test_stat_provisional_surcharge_is_capped_at_the_rate_card_ceiling(api):
    """PRD §3.4: "On a `STAT` run a surcharge is added equal to the base multiplied by
    `stat_surcharge_pct`, rounded half-up to whole cents, then capped so the surcharge
    is the smaller of that rounded amount and `stat_surcharge_cap_cents`; on a
    `SCHEDULED` run the surcharge is zero."

    With a cap of 100 cents the uncapped 779-cent surcharge is clamped to 100, so the
    provisional charge is 2598 + 100 = 2698.

    Design: Difficulty/combinatorial_formula/provisional_charge_conditional_capped_mode_a
    """
    ctx = fixtures.setup_dispatched_route(
        rate_card={"stat_surcharge_cap_cents": 100},
        route={"run_type": "STAT"},
    )
    route = validate_success(api.get_route(ctx["route"]["id"], DISPATCHER))
    assert route["provisional_charge_cents"] == 2698, (
        f"Expected 2598 base + 100 capped surcharge = 2698, got {route['provisional_charge_cents']}"
    )


def test_scheduled_provisional_charge_carries_no_surcharge(api):
    """PRD §3.4: "On a `STAT` run a surcharge is added equal to the base multiplied by
    `stat_surcharge_pct`, rounded half-up to whole cents, then capped so the surcharge
    is the smaller of that rounded amount and `stat_surcharge_cap_cents`; on a
    `SCHEDULED` run the surcharge is zero."

    The very same manifest, run SCHEDULED rather than STAT, stops at the 2598 base.

    Design: Difficulty/combinatorial_formula/provisional_charge_conditional_capped_mode_a
    """
    ctx = fixtures.setup_dispatched_route(route={"run_type": "SCHEDULED"})
    route = validate_success(api.get_route(ctx["route"]["id"], DISPATCHER))
    assert route["provisional_charge_cents"] == 2598, (
        f"A SCHEDULED run takes no surcharge; expected 2598, got {route['provisional_charge_cents']}"
    )


# ---------------------------------------------------------------------------
# The final formula: rounding order matters
# ---------------------------------------------------------------------------
def test_each_completed_leg_rounds_its_own_mileage(api):
    """PRD §3.7: "Each such stop contributes its `leg_charge_cents`, equal to
    `per_stop_fee_cents` plus the product of that stop's `actual_leg_miles` and
    `per_mile_rate_cents` rounded half-up to whole cents."

    2.5 miles * 133 = 332.5 rounds half-up to 333 (leg 833); 3.5 * 133 = 465.5 rounds
    half-up to 466 (leg 966).

    Design: Difficulty/combinatorial_formula/final_charge_per_leg_rounding_order_mode_b
    """
    ctx = fixtures.setup_completed_route()
    stop_1 = validate_success(api.get_stop(ctx["stops"][0]["id"], DISPATCHER))
    stop_2 = validate_success(api.get_stop(ctx["stops"][1]["id"], DISPATCHER))
    assert stop_1["leg_charge_cents"] == 833, (
        f"Expected 500 + round_half_up(2.5*133) = 833, got {stop_1['leg_charge_cents']}"
    )
    assert stop_2["leg_charge_cents"] == 966, (
        f"Expected 500 + round_half_up(3.5*133) = 966, got {stop_2['leg_charge_cents']}"
    )


def test_final_charge_sums_already_rounded_legs(api):
    """PRD §3.7: "The leg-and-stop subtotal is the sum of those already-rounded per-leg
    charges."
    PRD §3.7: "A final temperature subtotal is `temp_handling_fee_cents` multiplied by
    the number of specimens whose `temp_requirement` is other than `AMBIENT` and whose
    `custody_status` is `DELIVERED`."

    Summing the rounded legs (833 + 966 = 1799) and adding the 800-cent temperature
    subtotal yields 2599 — one cent more than rounding the 6.0-mile total once.

    Design: Difficulty/combinatorial_formula/final_charge_per_leg_rounding_order_mode_b
    """
    ctx = fixtures.setup_completed_route()
    route = validate_success(api.get_route(ctx["route"]["id"], DISPATCHER))
    stop_1 = validate_success(api.get_stop(ctx["stops"][0]["id"], DISPATCHER))
    stop_2 = validate_success(api.get_stop(ctx["stops"][1]["id"], DISPATCHER))

    assert stop_1["leg_charge_cents"] + stop_2["leg_charge_cents"] == 1799
    assert route["final_charge_cents"] == 2599, (
        f"Expected 1799 legs + 800 temp = 2599, got {route['final_charge_cents']}"
    )
