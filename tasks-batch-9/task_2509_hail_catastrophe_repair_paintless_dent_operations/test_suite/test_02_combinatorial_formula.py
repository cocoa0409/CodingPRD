"""Formulas whose nested caps, branch weights and step order all have to line up."""

from test_helpers import (
    assert_money_chain,
    assert_supplement_state,
    bring_vehicle_to,
    create_storm_event,
    file_supplement,
    read_damage_lines,
    read_vehicle,
    review_supplement,
    set_clock,
    setup_operational_facility,
    CLOCK_T0,
)


def test_the_confidence_branch_alone_moves_the_score_by_sixteen_points(api):
    """PRD §3.1: "A severity weight is chosen from the provenance of the swath
    data: 2.2 when `swath_confidence` is `GROUND_TRUTHED`, and 1.6 when it is
    `MODELED`, because ground-truthed hail reports earn more confidence than a
    model run."

    PRD §3.1: "That raw value is then rounded half up to an integer and clamped
    into the range 0 through 100 inclusive — anything negative becomes 0 and
    anything above 100 becomes 100 — and the result is stored as
    `targeting_score`."

    Design: Difficulty/combinatorial_formula/targeting_score_nested_min_max_with_confidence_branch
    """
    set_clock(api, CLOCK_T0)

    ground_truthed = create_storm_event(api, name="GT Baseline")
    modeled = create_storm_event(
        api, name="Modeled Twin", swath_confidence="MODELED"
    )

    assert ground_truthed["targeting_score"] == 72
    assert modeled["targeting_score"] == 56
    assert (
        ground_truthed["targeting_score"] - modeled["targeting_score"] == 16
    ), "only the severity weight differs between the two registrations"
    assert ground_truthed["status"] == "EVALUATING"
    assert modeled["status"] == "EVALUATING"
    assert ground_truthed["swath_confidence"] == "GROUND_TRUTHED"
    assert modeled["swath_confidence"] == "MODELED"


def test_every_cap_in_the_score_binds_at_once_without_the_swath_bonus(api):
    """PRD §3.1: "The hail diameter is then capped at 60 millimetres — stones
    larger than that add no further points — and the **severity term** is the
    severity weight multiplied by that capped diameter, divided by two."

    PRD §3.1: "The **density term** rewards vehicle population at one point per
    5,000 vehicles, with the population itself capped at 250,000 vehicles before
    the division. A flat **swath bonus** of 8 points is added when
    `swath_area_km2` is at least 400 square kilometres, and nothing is added
    below that threshold. A **competition penalty** of 1.5 points is subtracted
    for each competing team, counting at most 12 competitors."

    Design: Difficulty/combinatorial_formula/targeting_score_nested_min_max_with_confidence_branch
    """
    set_clock(api, CLOCK_T0)

    monster = create_storm_event(
        api,
        name="Triple Cap Monster",
        region_state_code="TX",
        max_hail_size_mm=85,
        swath_area_km2=100,
        swath_confidence="GROUND_TRUTHED",
        vehicle_population_estimate=300000,
        competitor_shop_count=20,
    )

    # 66 severity + 50 density + 0 swath bonus - 18 competition.
    assert monster["targeting_score"] == 98
    assert monster["status"] == "EVALUATING"
    assert monster["demobilized_at"] is None
    # The inputs themselves are stored uncapped; only the score sees the caps.
    assert monster["max_hail_size_mm"] == 85
    assert monster["vehicle_population_estimate"] == 300000
    assert monster["competitor_shop_count"] == 20


def test_the_estimate_total_is_the_sum_of_the_already_rounded_panel_charges(api):
    """PRD §3.5: "With the sheet pinned, every damage line of the vehicle is
    priced under both variants, processed in `created_at` ascending order so that
    per-panel rounding is reproducible."

    PRD §3.5: "Both variants price every panel, and the vehicle's two totals are
    then the sums of the rounded per-panel values: `matrix_variant_total_cents`
    is the sum of every `pdr_line_cents` (post-cap, where a cap applied), and
    `conventional_variant_total_cents` is the sum of every
    `conventional_line_cents`."

    Design: Difficulty/combinatorial_formula/per_panel_rounding_before_summation_pins_estimate_total
    """
    scenario = setup_operational_facility(api)
    car = bring_vehicle_to(api, scenario, "ESTIMATED", damage_profile="three_panel")
    vehicle = car["vehicle"]
    lines = read_damage_lines(api, car["vehicle_id"])

    assert vehicle["matrix_variant_total_cents"] == 202886
    assert sum(line["pdr_line_cents"] for line in lines) == 202886
    # Summing the unrounded panel charges and rounding once at the end would
    # have produced 202887; the total is one cent lower because each panel is
    # rounded on its own first.
    assert vehicle["matrix_variant_total_cents"] != 202887
    assert vehicle["conventional_variant_total_cents"] == 257750
    assert sum(line["conventional_line_cents"] for line in lines) == 257750


def test_each_panel_rounds_half_up_on_its_own_before_the_total(api):
    """PRD §3.5: "The panel's raw paintless charge is the per-dent rate
    multiplied by `dent_count`, multiplied by the tier multiplier, multiplied by
    the aluminum multiplier, plus `r_and_i_hours` multiplied by the sheet's
    `labor_rate_cents_per_hour`. That raw charge is rounded half up to whole
    cents and stored as `pdr_line_cents`."

    PRD §2.7: "First, **per-panel rounding precedes summation**: each damage
    line's paintless charge is rounded to whole cents on its own, and only the
    rounded per-panel values are summed into the vehicle's variant total.
    Summing unrounded panel values and rounding once at the end produces a
    different answer and is incorrect."

    Design: Difficulty/combinatorial_formula/per_panel_rounding_before_summation_pins_estimate_total
    """
    scenario = setup_operational_facility(api)
    car = bring_vehicle_to(api, scenario, "ESTIMATED", damage_profile="three_panel")
    lines = read_damage_lines(api, car["vehicle_id"])

    # Two of the three panels carry a fractional cent that is dropped, and the
    # middle panel is already exact.
    per_panel = {line["panel_code"]: line["pdr_line_cents"] for line in lines}
    assert per_panel["HOOD"] == 110778
    assert per_panel["ROOF"] == 42945
    assert per_panel["LEFT_QUARTER"] == 49163
    assert sum(per_panel.values()) == 202886


def _approved_forty_five_thousand_supplement(api):
    """A triaged, authorized car that has just had a 45,000c supplement blessed."""
    scenario = setup_operational_facility(api)
    car = bring_vehicle_to(api, scenario, "AUTHORIZED", damage_profile="three_panel")
    supplement = file_supplement(api, car["vehicle_id"], 45000)
    supplement = review_supplement(
        api, supplement["id"], scenario["insurer_id"], "APPROVE"
    )
    return scenario, car, supplement


def test_the_admin_fee_is_added_before_the_discount_is_taken(api):
    """PRD §3.6: "Step two, `admin_fee_cents` is the pinned sheet's
    `admin_fee_pct` multiplied by that subtotal, rounded half up to whole cents,
    and then reduced to the sheet's `admin_fee_cap_cents` whenever the rounded
    fee would exceed the cap — the fee is whichever of the two is smaller."

    PRD §2.7: "Second, in the billable waterfall the administrative fee is keyed
    on the repair subtotal while the volume discount is keyed on the gross amount
    that already contains that fee; the fee is never keyed on the discounted
    amount, and the chain is never iterated to a fixed point."

    Design: Difficulty/combinatorial_formula/net_billable_pinned_evaluation_order_fee_before_discount
    """
    scenario, car, supplement = _approved_forty_five_thousand_supplement(api)
    assert_supplement_state(
        supplement, status="APPROVED", round_index=1, approved_amount_cents=45000
    )

    vehicle = read_vehicle(api, car["vehicle_id"])
    assert vehicle["approved_repair_cents"] == 202886
    assert vehicle["approved_supplement_cents"] == 45000
    assert_money_chain(
        vehicle,
        admin_fee_cents=12394,
        gross_billable_cents=260280,
        discount_cents=5206,
        net_billable_cents=255074,
    )
    # Taking the discount first and charging the fee on the discounted figure
    # would have produced these instead.
    assert vehicle["admin_fee_cents"] != 12754
    assert vehicle["discount_cents"] != 4958


def test_the_discount_tier_is_read_from_the_gross_not_from_the_subtotal(api):
    """PRD §3.6: "Step four selects a volume discount rate from the gross amount,
    checking the higher tier first: 4 percent when `gross_billable_cents` is at
    or above 500,000 cents (5,000 dollars), otherwise 2 percent when it is at or
    above 250,000 cents (2,500 dollars), and otherwise 0 percent."

    PRD §3.6: "Step three, `gross_billable_cents` is the subtotal plus the
    administrative fee."

    Design: Difficulty/combinatorial_formula/net_billable_pinned_evaluation_order_fee_before_discount
    """
    scenario, car, _ = _approved_forty_five_thousand_supplement(api)
    vehicle = read_vehicle(api, car["vehicle_id"])

    subtotal = vehicle["approved_repair_cents"] + vehicle["approved_supplement_cents"]
    assert subtotal == 247886
    # The subtotal on its own sits below the 2 percent floor; only the
    # administrative fee carries the gross over it.
    assert subtotal < 250000
    assert vehicle["gross_billable_cents"] == 260280
    assert vehicle["gross_billable_cents"] >= 250000
    assert vehicle["discount_cents"] == 5206
    assert vehicle["net_billable_cents"] == 255074
