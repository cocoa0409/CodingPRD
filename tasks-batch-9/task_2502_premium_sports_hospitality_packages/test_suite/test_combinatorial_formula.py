"""Multi-operand formulae whose operand pairing and rounding order are pinned.

Two of them carry a boundary that a plausible mis-reading moves: the package
pricing pass, which rounds each component line before summing rather than after,
and the booking price build-up, which keys both of its percentages on the
discounted subtotal rather than on the gross or the net.
"""

from typing import Any, Dict

from test_helpers import (
    COMMERCIAL_MANAGER,
    ApiClient,
    assert_booking_price_buildup,
    assert_fraction_4dp,
    assert_package_pricing,
    assert_schedule_amounts,
    assert_schedule_conservation,
    add_gold_components,
    get_success_data,
    installments_of,
    make_booking,
    make_client,
    make_committed_deal,
    make_event,
    make_package,
    make_published_gold_package,
    price_package,
    reset_clock,
)


def _priced_gold_package_with_four_half_cent_lines(api: ApiClient) -> Dict[str, Any]:
    """The canonical GOLD package, whose four raw line prices all end in .5.

    No rights deal is created: pricing, unlike publication, does not require
    ticket supply to stand behind the package.
    """
    reset_clock(api)
    event = make_event(api)
    package = make_package(api, event["id"])
    components = add_gold_components(api, package["id"])
    priced = price_package(api, package["id"])
    return {"event": event, "package": priced, "components": components}


def _exposed_travel_partner_floor(api: ApiClient) -> Dict[str, Any]:
    """A published GOLD package on a fixture that is still owing units.

    The ticket deal is COMMITTED with nothing released, so released_units (0) is
    strictly below contracted_units (100) and the fixture is in the exposure set
    that switches the guarantee surcharge on.
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"], contracted_units=100,
                              guaranteed_minimum_units=40, unit_cost_cents=8000)
    package = make_published_gold_package(api, event["id"])
    client = make_client(api, name="Aventine Travel Group", client_type="TRAVEL_PARTNER")
    return {"event": event, "deal": deal, "package": package, "client": client}


# --------------------------------------------------------------------------
# Rounding at the line, then summing
# --------------------------------------------------------------------------


def test_each_component_line_is_rounded_at_the_line_before_being_summed(
    api: ApiClient,
) -> None:
    """Four raw line prices of x.5 cents each round up individually.

    The lines are 49980 at 0.1750 (raw 58726.5), 54980 at 0.0750 (raw 59103.5),
    7772 at 0.1250 (raw 8743.5) and 12340 at 0.2250 (raw 15116.5). Rounding each
    at the line and then summing gives 141692; summing the raw prices and
    rounding once gives 141690, which is the value this test rules out.

    PRD §3.4: "For each line, `line_cost_cents` is that line's `unit_cost_cents`
    multiplied by its `quantity`, and `line_price_cents` is that line cost
    multiplied by one plus the line's `markup_pct`, rounded half-up to a whole
    cent **at the line**."

    Design: Difficulty/combinatorial_formula/component_line_rounding_before_summation_not_after
    """
    scenario = _priced_gold_package_with_four_half_cent_lines(api)

    expected_lines = [(49980, 58727), (54980, 59104), (7772, 8744), (12340, 15117)]
    stored = []
    for component in scenario["components"]:
        row = get_success_data(api.get_package_component(component["id"], COMMERCIAL_MANAGER))
        stored.append((row["sequence_no"], row["line_cost_cents"], row["line_price_cents"]))
    stored.sort()

    assert [(cost, price) for _, cost, price in stored] == expected_lines

    package = scenario["package"]
    assert package["component_price_subtotal_cents"] == 141692
    assert package["component_price_subtotal_cents"] != 141690, (
        "141690 is the figure produced by summing the raw line prices and "
        "rounding the total once"
    )
    assert sum(price for _, _, price in stored) == package["component_price_subtotal_cents"]
    assert sum(cost for _, cost, _ in stored) == package["base_cost_cents"] == 125072


def test_the_tier_multiplier_is_applied_to_the_already_rounded_subtotal(
    api: ApiClient,
) -> None:
    """GOLD's 1.25 multiplies 141692, not the raw component sum of 141690.

    The list price is round_half_up(141692 * 1.25) == 177115 exactly, and the
    margin that follows from it is (177115 - 125072) / 177115 == 0.2938. Had the
    subtotal been the raw sum, the list price would have been
    round_half_up(177112.5) == 177113 and the margin a different fraction.

    PRD §3.4: "`list_price_cents` is `component_price_subtotal_cents` multiplied
    by that tier multiplier and rounded half-up to a whole cent."

    Design: Difficulty/combinatorial_formula/component_line_rounding_before_summation_not_after
    """
    scenario = _priced_gold_package_with_four_half_cent_lines(api)
    package = scenario["package"]

    assert_package_pricing(
        package,
        base_cost=125072,
        subtotal=141692,
        list_price=177115,
        margin_pct=0.2938,
        status="PRICED",
    )
    assert package["list_price_cents"] != 177113, (
        "177113 is round_half_up(141690 * 1.25), the figure that follows from "
        "rounding the subtotal instead of the lines"
    )


# --------------------------------------------------------------------------
# Percentages keyed on the discounted subtotal
# --------------------------------------------------------------------------


def test_commission_and_surcharge_are_both_keyed_on_the_discounted_subtotal(
    api: ApiClient,
) -> None:
    """Three money bases are available and the pinned rule uses the middle one.

    A 12-unit TRAVEL_PARTNER booking at a list price of 177115 grosses 2125380,
    takes the 0.0800 volume band on its unit count, and discounts to 1955350.
    The 10% commission is 195535 and the 3.5% surcharge is 68437 — both read off
    1955350. All three candidate bases sit inside the same surcharge band, so
    only the choice of base can explain the figures.

    PRD §3.5: "`guarantee_surcharge_cents` is keyed on the discounted subtotal as
    well, never on the net price, and it is charged only where the fixture is
    actually exposed."

    Design: Difficulty/combinatorial_formula/booking_net_price_percentages_keyed_on_discounted_subtotal_not_net
    """
    scenario = _exposed_travel_partner_floor(api)
    assert scenario["deal"]["deal_status"] == "COMMITTED"
    assert scenario["deal"]["released_units"] == 0
    assert scenario["package"]["list_price_cents"] == 177115

    booking = make_booking(api, scenario["client"]["id"], scenario["package"]["id"],
                           channel="TRAVEL_PARTNER", units=12)

    assert_booking_price_buildup(
        booking,
        gross=2125380,
        volume_discount_pct=0.0800,
        discounted_subtotal=1955350,
        commission=195535,
        surcharge=68437,
        net=1828252,
    )
    assert booking["partner_commission_cents"] not in (212538, 182825), (
        "212538 is ten percent of the gross and 182825 ten percent of the net"
    )
    assert booking["guarantee_surcharge_cents"] not in (74388, 63989), (
        "74388 is 3.5 percent of the gross and 63989 of the net"
    )
    assert booking["net_price_cents"] != 1691378, (
        "1691378 is what subtracting the surcharge instead of adding it gives"
    )
    assert booking["fulfillment_status"] == "RESERVED"
    assert booking["payment_status"] == "UNPAID"
    assert booking["paid_cents"] == 0


def test_the_volume_band_is_chosen_from_the_unit_count_and_not_from_money(
    api: ApiClient,
) -> None:
    """Twelve units take the 0.0800 band, and the discount cents follow from it.

    The band boundary is a unit count, so a 12-unit booking sits in the
    "at least 10" band regardless of how much money is involved, and the
    discount in cents is round_half_up(2125380 * 0.0800) == 170030, leaving a
    discounted subtotal of 1955350.

    PRD §3.5: "`volume_discount_pct` is chosen from the unit count alone, never
    from any money amount: 0.1200 when `units` is at least 20, otherwise 0.0800
    when `units` is at least 10, otherwise 0.0400 when `units` is at least 5, and
    otherwise 0.0000."

    Design: Difficulty/combinatorial_formula/booking_net_price_percentages_keyed_on_discounted_subtotal_not_net
    """
    scenario = _exposed_travel_partner_floor(api)
    booking = make_booking(api, scenario["client"]["id"], scenario["package"]["id"],
                           channel="TRAVEL_PARTNER", units=12)

    assert_fraction_4dp(booking["volume_discount_pct"], 0.0800)
    assert booking["gross_price_cents"] == 2125380
    assert (booking["gross_price_cents"]
            - booking["discounted_subtotal_cents"]) == 170030


def test_the_generated_schedule_splits_the_net_with_the_residual_cent_last(
    api: ApiClient,
) -> None:
    """Thirty and forty percent of 1828252, with the remainder by subtraction.

    The fixture is 184 days away, so the schedule has three lines: 548476,
    731301 and 548475. The last line is computed by subtraction, which is why it
    is a cent smaller than the first rather than a cent larger. The three due
    dates are three days after the clock, ninety days before the fixture and
    thirty days before it.

    PRD §3.6: "The first line's `amount_cents` is thirty percent of the payable
    amount rounded half-up; the second line's is forty percent of the payable
    amount rounded half-up; and the third line's is the payable amount less the
    first two lines, computed by subtraction so that residual cents land on the
    last line and the three lines sum exactly to the payable amount with no
    drift."

    Design: Difficulty/combinatorial_formula/booking_net_price_percentages_keyed_on_discounted_subtotal_not_net
    """
    scenario = _exposed_travel_partner_floor(api)
    booking = make_booking(api, scenario["client"]["id"], scenario["package"]["id"],
                           channel="TRAVEL_PARTNER", units=12)

    lines = installments_of(api, booking["id"])
    assert len(lines) == 3
    assert_schedule_amounts(lines, [548476, 731301, 548475])
    assert_schedule_conservation(lines, net_price_cents=1828252)
    assert [line["due_at"] for line in lines] == [
        "2026-08-04T00:00:00.000Z",
        "2026-11-03T15:00:00.000Z",
        "2027-01-02T15:00:00.000Z",
    ]
    assert all(line["installment_kind"] == "SCHEDULE" for line in lines)
    assert all(line["installment_state"] == "SCHEDULED" for line in lines)
