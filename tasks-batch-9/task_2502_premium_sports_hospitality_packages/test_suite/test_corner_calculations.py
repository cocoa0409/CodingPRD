"""Named constants and rounding disciplines inside the derived money figures.

Each probe below pins one arithmetic rule at the values where a plausible
mis-reading changes the answer: the four tier multipliers, the unit-count
volume ladder, the three channel commission rates, the four weighted risk
components, the deposit/second/remainder split of a payment schedule, the
priority-ranked allocation waterfall, the margin report's input-set filters,
the round-then-multiply shortfall liability, and the inclusive day marks of the
cancellation fee ladder.
"""

from typing import Any, Dict

import pytest

from test_helpers import (
    COMMERCIAL_DIRECTOR,
    RIGHTS_MANAGER,
    ApiClient,
    add_component,
    allocate_booking,
    assert_block_position,
    assert_booking_price_buildup,
    assert_daily_run_report,
    assert_deal_position,
    assert_fraction_4dp,
    assert_margin_report,
    assert_package_pricing,
    assert_risk_band,
    assert_schedule_amounts,
    assert_schedule_conservation,
    assert_settlement_identity,
    cancel_booking,
    commit_deal,
    confirm_tranche,
    daily_run,
    get_success_data,
    installments_of,
    make_block,
    make_booking,
    make_bronze_package,
    make_build,
    make_client,
    make_committed_deal,
    make_deal,
    make_event,
    make_published_bronze_package,
    make_ready_build,
    make_tranche,
    margin_report,
    margin_report_params,
    price_package,
    publish_package,
    read_block,
    read_event,
    release_deal,
    reset_clock,
    set_clock,
    unexposed_bronze_floor,
)

# The single component line every tier package below carries: 2 seats at 50000
# cents marked up 20 percent, so line_cost 100000 and line_price 120000.
_SHARED_LINE = {
    "component_type": "TICKET",
    "descriptor": "Category 1 seat pair",
    "quantity": 2,
    "unit_cost_cents": 50000,
    "markup_pct": 0.2000,
    "sequence_no": 1,
}

_TIER_NAMES = {
    "BRONZE": "Bronze Hospitality",
    "SILVER": "Silver Hospitality",
    "GOLD": "Gold Hospitality",
    "PLATINUM": "Platinum Hospitality",
}


def _read_deal(api: ApiClient, deal_id: str) -> Dict[str, Any]:
    """The stored rights deal, re-read so derived figures are current."""
    return get_success_data(api.get_rights_deal(deal_id, RIGHTS_MANAGER))


def _four_tier_packages_on_one_fixture(api: ApiClient) -> Dict[str, Dict[str, Any]]:
    """One fixture carrying four packages whose only difference is the tier.

    Every package gets a byte-identical component line, so the base cost and
    the component price subtotal are the same for all four and the tier
    multiplier is the only free variable in the list price.
    """
    reset_clock(api)
    event = make_event(api)
    priced: Dict[str, Dict[str, Any]] = {}
    for tier, name in _TIER_NAMES.items():
        package = make_bronze_package(api, event["id"], tier=tier, name=name)
        add_component(api, package["id"], **_SHARED_LINE)
        priced[tier] = price_package(api, package["id"])
    return priced


# --------------------------------------------------------------------------
# Tier multipliers
# --------------------------------------------------------------------------


def test_each_tier_multiplier_scales_the_same_component_subtotal(
    api: ApiClient,
) -> None:
    """One subtotal of 120000 read through the four declared multipliers.

    The four packages share a base cost of 100000 and a component price
    subtotal of 120000, so the list prices are 120000, 132000, 150000 and
    174000 respectively. BRONZE's multiplier of exactly 1.00 is still applied
    rather than special-cased away, which is why its list price equals its
    subtotal instead of its base cost.

    PRD §3.4: "A `BRONZE` package is multiplied by 1.00, a `SILVER` package by
    1.10, a `GOLD` package by 1.25 and a `PLATINUM` package by 1.45;
    `list_price_cents` is `component_price_subtotal_cents` multiplied by that
    tier multiplier and rounded half-up to a whole cent."

    Design: Corner/calculations/tier_multiplier_constants_drive_list_price_and_margin_for_all_four_tiers
    """
    priced = _four_tier_packages_on_one_fixture(api)

    for tier, package in priced.items():
        assert package["package_status"] == "PRICED", tier
        assert package["base_cost_cents"] == 100000, tier
        assert package["component_price_subtotal_cents"] == 120000, tier

    assert priced["BRONZE"]["list_price_cents"] == 120000
    assert priced["SILVER"]["list_price_cents"] == 132000
    assert priced["GOLD"]["list_price_cents"] == 150000
    assert priced["PLATINUM"]["list_price_cents"] == 174000

    assert priced["BRONZE"]["list_price_cents"] != 100000, (
        "100000 is the base cost, which is what applying the multiplier to the "
        "wrong operand would produce"
    )


def test_the_tier_margin_is_denominated_on_the_list_price_to_four_places(
    api: ApiClient,
) -> None:
    """Three non-terminating quotients rounded half-up to four places.

    The margins are 20000/120000, 32000/132000, 50000/150000 and 74000/174000,
    which give 0.1667, 0.2424, 0.3333 and 0.4253. A base-denominated margin
    would give the terminating 0.2000, 0.3200, 0.5000 and 0.7400 instead, so
    the denominator is pinned as well as the rounding.

    PRD §3.4: "The package's `margin_pct` is then the list price less the base
    cost, divided by the list price, rounded half-up to four decimal places —
    except that when `list_price_cents` comes out as 0 the margin is fixed at 0
    rather than divided by zero."

    Design: Corner/calculations/tier_multiplier_constants_drive_list_price_and_margin_for_all_four_tiers
    """
    priced = _four_tier_packages_on_one_fixture(api)

    assert_package_pricing(priced["BRONZE"], base_cost=100000, subtotal=120000,
                           list_price=120000, margin_pct=0.1667)
    assert_package_pricing(priced["SILVER"], base_cost=100000, subtotal=120000,
                           list_price=132000, margin_pct=0.2424)
    assert_package_pricing(priced["GOLD"], base_cost=100000, subtotal=120000,
                           list_price=150000, margin_pct=0.3333)
    assert_package_pricing(priced["PLATINUM"], base_cost=100000, subtotal=120000,
                           list_price=174000, margin_pct=0.4253)

    for tier, wrong in (("BRONZE", 0.2000), ("SILVER", 0.3200),
                        ("GOLD", 0.5000), ("PLATINUM", 0.7400)):
        assert abs(priced[tier]["margin_pct"] - wrong) > 0.00005, (
            f"{wrong} is the {tier} margin denominated on the base cost"
        )


# --------------------------------------------------------------------------
# The volume ladder, keyed on units
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "units,expected_band,expected_net",
    [
        (4, 0.0000, 465600),
        (5, 0.0400, 558720),
        (9, 0.0400, 1005696),
        (10, 0.0800, 1070880),
        (19, 0.0800, 2034672),
        (20, 0.1200, 2048640),
    ],
)
def test_the_volume_band_steps_at_five_ten_and_twenty_units(
    api: ApiClient, units: int, expected_band: float, expected_net: int,
) -> None:
    """Both sides of all three unit-count breakpoints on one published package.

    At a list price of 120000 the gross is 120000 times the unit count, the
    discount is the band read off the count alone, and the CORPORATE commission
    of 3 percent comes off the discounted subtotal. Five units already earn the
    first band while four earn nothing, which is what makes each comparison
    inclusive rather than strict.

    PRD §3.5: "`volume_discount_pct` is chosen from the unit count alone, never
    from any money amount: 0.1200 when `units` is at least 20, otherwise 0.0800
    when `units` is at least 10, otherwise 0.0400 when `units` is at least 5,
    and otherwise 0.0000."

    Design: Corner/calculations/volume_discount_tier_boundaries_at_five_ten_and_twenty_units
    """
    floor = unexposed_bronze_floor(api)
    assert floor["package"]["list_price_cents"] == 120000

    booking = make_booking(api, floor["client"]["id"], floor["package"]["id"],
                           channel="CORPORATE", units=units)

    assert_fraction_4dp(booking["volume_discount_pct"], expected_band)
    assert booking["gross_price_cents"] == 120000 * units
    assert booking["net_price_cents"] == expected_net


def test_the_volume_discount_is_flat_on_the_whole_gross_not_marginal(
    api: ApiClient,
) -> None:
    """Nine units pay 4 percent on all nine and ten units 8 percent on all ten.

    The nine-unit booking grosses 1080000 and discounts by 43200; the ten-unit
    booking grosses 1200000 and discounts by 96000, which is far more than one
    extra unit's worth. A marginal ladder that charged the higher rate only on
    the units above ten would discount 1200000 by 48000 and net 1117440. The
    twenty-unit booking also carries a zero guarantee surcharge, because the
    fixture's ticket deal has released its whole contracted quantity and is
    therefore outside the exposure set.

    PRD §3.5: "The volume discount in cents is the gross price multiplied by
    that fraction, rounded half-up to a whole cent, and
    `discounted_subtotal_cents` is the gross price less that rounded discount."

    PRD §3.5: "Exposure means the package's fixture has at least one rights deal
    for `TICKET` inventory whose `deal_status` is `COMMITTED`,
    `PARTIALLY_RELEASED` or `SHORTFALL_DECLARED` and whose `released_units` is
    strictly below its `contracted_units`."

    Design: Corner/calculations/volume_discount_tier_boundaries_at_five_ten_and_twenty_units
    """
    floor = unexposed_bronze_floor(api)
    deal = _read_deal(api, floor["deal"]["id"])
    assert deal["deal_status"] == "FULLY_RELEASED"
    assert deal["released_units"] == deal["contracted_units"] == 60

    nine = make_booking(api, floor["client"]["id"], floor["package"]["id"],
                        channel="CORPORATE", units=9)
    ten = make_booking(api, floor["client"]["id"], floor["package"]["id"],
                       channel="CORPORATE", units=10)
    twenty = make_booking(api, floor["client"]["id"], floor["package"]["id"],
                          channel="CORPORATE", units=20)

    assert_booking_price_buildup(nine, gross=1080000, volume_discount_pct=0.0400,
                                 discounted_subtotal=1036800, commission=31104,
                                 surcharge=0, net=1005696)
    assert_booking_price_buildup(ten, gross=1200000, volume_discount_pct=0.0800,
                                 discounted_subtotal=1104000, commission=33120,
                                 surcharge=0, net=1070880)
    assert ten["net_price_cents"] != 1117440, (
        "1117440 is what a marginal ladder charging 8 percent only above ten "
        "units would produce"
    )
    assert twenty["gross_price_cents"] == 2400000
    assert twenty["guarantee_surcharge_cents"] == 0
    assert twenty["net_price_cents"] == 2048640


# --------------------------------------------------------------------------
# Channel commission rates
# --------------------------------------------------------------------------


def test_the_three_channel_commission_rates_split_one_discounted_subtotal(
    api: ApiClient,
) -> None:
    """Fifteen units down each channel, so only the commission rate moves.

    All three bookings gross 1800000, take the 0.0800 band on their identical
    unit count and discount to 1656000. The commissions are 0, 49680 and 165600,
    so the nets are strictly ordered and their pairwise differences are exactly
    the commission differences. A gross-based partner commission would be
    180000 rather than 165600.

    PRD §3.5: "`partner_commission_cents` is the discounted subtotal multiplied
    by the commission rate for the booking's `channel` — 0.0000 for
    `INDIVIDUAL`, 0.0300 for `CORPORATE` and 0.1000 for `TRAVEL_PARTNER` —
    rounded half-up to a whole cent."

    Design: Corner/calculations/channel_commission_constants_differ_on_identical_unit_counts
    """
    floor = unexposed_bronze_floor(api)
    client_id = floor["client"]["id"]
    package_id = floor["package"]["id"]

    individual = make_booking(api, client_id, package_id,
                              channel="INDIVIDUAL", units=15)
    corporate = make_booking(api, client_id, package_id,
                             channel="CORPORATE", units=15)
    partner = make_booking(api, client_id, package_id,
                           channel="TRAVEL_PARTNER", units=15)

    for booking in (individual, corporate, partner):
        assert booking["gross_price_cents"] == 1800000
        assert booking["discounted_subtotal_cents"] == 1656000
        assert_fraction_4dp(booking["volume_discount_pct"], 0.0800)

    assert individual["partner_commission_cents"] == 0
    assert individual["net_price_cents"] == 1656000
    assert corporate["partner_commission_cents"] == 49680
    assert corporate["net_price_cents"] == 1606320
    assert partner["partner_commission_cents"] == 165600
    assert partner["net_price_cents"] == 1490400

    assert partner["partner_commission_cents"] != 180000, (
        "180000 is ten percent of the gross rather than of the discounted "
        "subtotal"
    )
    assert (individual["net_price_cents"] > corporate["net_price_cents"]
            > partner["net_price_cents"])
    assert (individual["net_price_cents"] - corporate["net_price_cents"]
            == corporate["partner_commission_cents"])
    assert (corporate["net_price_cents"] - partner["net_price_cents"]
            == partner["partner_commission_cents"] - corporate["partner_commission_cents"])


# --------------------------------------------------------------------------
# The weighted risk score and its two band boundaries
# --------------------------------------------------------------------------


def test_the_weighted_risk_score_crosses_elevated_then_critical_as_promises_lapse(
    api: ApiClient,
) -> None:
    """One component at a time is added, so a wrong weight moves the band.

    The fixture is 184 days out and stays over 120 days out throughout, so the
    horizon term is 0 at every observation, and the fixture never leaves
    SCHEDULED, so the status term is 0 as well. A single 10-unit booking on a
    two-ticket package commits 20 ticket units against 0 released, a ratio of
    exactly 1, so the gap term saturates at 40 and the posture is already
    ELEVATED on the inclusive boundary. Letting the first 30-unit promise lapse
    adds 30 * 30/60 == 15 against a promised quantity of 60 contracted units,
    giving 55, which is still ELEVATED. Letting the second 30-unit promise lapse
    takes the lapsed quantity to 60, saturating the lapse term at 30 for a total
    of exactly 70, which tips the posture to CRITICAL on the second inclusive
    boundary.

    PRD §3.9: "The **gap component** is 40 multiplied by the following fraction,
    itself capped at 1: the committed quantity less the released quantity,
    floored at 0, divided by the committed quantity or by 1 where the committed
    quantity is 0."

    PRD §3.9: "The **lapse component** is 30 multiplied by the lapsed quantity
    divided by the promised quantity, or by 1 where the promised quantity is 0,
    again capped at 1."

    PRD §3.9: "the promised quantity, being the total of `contracted_units`
    across the fixture's rights deals whose `deal_status` is anything other than
    `TERMINATED`"

    PRD §3.9: "`risk_posture` is a band over that score, and both boundaries are
    inclusive: `CRITICAL` when `fulfillment_risk_score` is 70 or more,
    `ELEVATED` when it is 40 or more, and `NORMAL` otherwise."

    Design: Corner/calculations/risk_score_weighted_sum_crosses_elevated_then_critical_band
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"], contracted_units=60,
                               guaranteed_minimum_units=20, unit_cost_cents=8000)
    package = make_bronze_package(api, event["id"])
    add_component(api, package["id"], **_SHARED_LINE)
    priced = price_package(api, package["id"])
    published = publish_package(api, priced["id"], priced["version"])
    client = make_client(api)

    booking = make_booking(api, client["id"], published["id"],
                           channel="CORPORATE", units=10)
    assert booking["guarantee_surcharge_cents"] == 38640
    assert booking["net_price_cents"] == 1109520
    assert_risk_band(read_event(api, event["id"]), score=40, posture="ELEVATED")

    make_tranche(api, deal["id"], promised_units=30,
                 promised_release_at="2026-09-01T00:00:00.000Z")
    set_clock(api, "2026-09-02T00:00:00Z")
    first_sweep = daily_run(api)
    assert_daily_run_report(first_sweep, lapsed=1, shortfall=1)
    assert_risk_band(read_event(api, event["id"]), score=55, posture="ELEVATED")

    make_tranche(api, deal["id"], promised_units=30,
                 promised_release_at="2026-10-01T00:00:00.000Z")
    set_clock(api, "2026-10-02T00:00:00Z")
    second_sweep = daily_run(api)
    assert_daily_run_report(second_sweep, lapsed=1)
    assert_risk_band(read_event(api, event["id"]), score=70, posture="CRITICAL")

    settled = _read_deal(api, deal["id"])
    assert_deal_position(settled, released=0, shortfall=20, liability=96000,
                         status="SHORTFALL_DECLARED")


def test_the_horizon_component_steps_at_the_thirty_and_fourteen_day_marks(
    api: ApiClient,
) -> None:
    """A fixture with no bookings, so the whole score is the horizon term.

    The deal guarantees nothing and there are no bookings, so the committed
    quantity is 0 and the gap term is 0; the four promises total the contracted
    60 units and none of them is ever allowed to lapse, so the lapse term stays
    0 too. Reading the score at 31, 30, 15 and 14 whole days out gives 0, 10, 10
    and 20, which pins both comparisons as inclusive. Each reading follows a
    mutation, because moving the clock on its own recomputes nothing.

    PRD §3.9: "The **horizon component** is 20 when the fixture is at most 14
    whole days away, 10 when it is at most 30 whole days away, and 0 otherwise."

    PRD §2.4: "Setting the clock recomputes nothing on its own; it merely changes
    what every subsequent rule observes."

    Design: Corner/calculations/risk_horizon_component_steps_at_the_thirty_and_fourteen_day_marks
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"], contracted_units=60,
                               guaranteed_minimum_units=0, unit_cost_cents=8000)

    observed = []
    for moment in ("2027-01-01T15:00:00Z", "2027-01-02T15:00:00Z",
                   "2027-01-17T15:00:00Z", "2027-01-18T15:00:00Z"):
        set_clock(api, moment)
        make_tranche(api, deal["id"], promised_units=15,
                     promised_release_at="2027-01-31T00:00:00.000Z")
        observed.append(read_event(api, event["id"]))

    assert_risk_band(observed[0], score=0, posture="NORMAL")
    assert observed[1]["fulfillment_risk_score"] == 10
    assert observed[2]["fulfillment_risk_score"] == 10, (
        "15 whole days out is still the mid band, not yet the near band"
    )
    assert_risk_band(observed[3], score=20, posture="NORMAL")


# --------------------------------------------------------------------------
# The payment schedule: the residual line and the floored due dates
# --------------------------------------------------------------------------


def _odd_cent_bronze_floor(api: ApiClient) -> Dict[str, Any]:
    """A published BRONZE package whose single line prices to an odd cent.

    One restricted-view seat at 10001 cents marked up 50 percent gives a raw
    line price of 15001.5, so the line rounds up to 15002 and the BRONZE
    multiplier of 1.00 leaves the list price there. The fixture also carries a
    ticket deal that has released its whole contracted quantity, which is what
    lets the package be published at all while keeping the guarantee surcharge
    at 0.
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"], contracted_units=60,
                               guaranteed_minimum_units=40, unit_cost_cents=8000)
    release_deal(api, deal["id"], 60)
    package = make_bronze_package(api, event["id"], name="Odd-Cent Bronze")
    component = add_component(api, package["id"],
                              descriptor="Single restricted-view seat",
                              quantity=1, unit_cost_cents=10001, markup_pct=0.5000)
    priced = price_package(api, package["id"])
    published = publish_package(api, priced["id"], priced["version"])
    client = make_client(api)
    return {
        "event": event,
        "deal": deal,
        "component": component,
        "package": published,
        "client": client,
    }


def test_the_schedule_remainder_line_absorbs_the_residual_cents(
    api: ApiClient,
) -> None:
    """Both rounded lines round up, so the subtracted line comes out smaller.

    The one-unit booking nets 14552, of which thirty percent is 4365.6 and forty
    percent 5820.8; both round up, to 4366 and 5821, so the third line is
    14552 - 4366 - 5821 == 4365 — strictly less than the deposit. Computing the
    third line as its own rounded thirty percent would give 4366 and over-bill by
    a cent, which the conservation identity would then break.

    PRD §3.6: "The first line's `amount_cents` is thirty percent of the payable
    amount rounded half-up; the second line's is forty percent of the payable
    amount rounded half-up; and the third line's is the payable amount less the
    first two lines, computed by subtraction so that residual cents land on the
    last line and the three lines sum exactly to the payable amount with no
    drift."

    Design: Corner/calculations/payment_schedule_remainder_lands_on_the_last_line_and_dates_are_floored
    """
    floor = _odd_cent_bronze_floor(api)

    assert floor["component"]["line_cost_cents"] == 10001
    assert floor["component"]["line_price_cents"] == 15002
    assert_package_pricing(floor["package"], base_cost=10001, subtotal=15002,
                           list_price=15002, margin_pct=0.3334)

    booking = make_booking(api, floor["client"]["id"], floor["package"]["id"],
                           channel="CORPORATE", units=1)
    assert booking["partner_commission_cents"] == 450
    assert booking["guarantee_surcharge_cents"] == 0
    assert booking["net_price_cents"] == 14552

    lines = installments_of(api, booking["id"])
    assert len(lines) == 3
    assert all(line["installment_kind"] == "SCHEDULE" for line in lines)
    assert_schedule_amounts(lines, [4366, 5821, 4365])
    assert_schedule_conservation(lines, net_price_cents=14552)
    assert lines[2]["amount_cents"] < lines[0]["amount_cents"], (
        "the subtracted line is a cent smaller than the deposit here, because "
        "both rounded lines rounded up"
    )
    assert lines[2]["sequence_no"] == 3
    assert lines[2]["amount_cents"] != 4366, (
        "4366 is a third line computed as its own rounded thirty percent rather "
        "than by subtraction"
    )


def test_the_schedule_due_dates_floor_forward_then_collapse_inside_thirty_days(
    api: ApiClient,
) -> None:
    """The three anchors, then the floors, then the single-line collapse.

    At 184 days out the anchors are all distinct and strictly increasing: three
    days after the clock, ninety days before the fixture and thirty days before
    it. At exactly 30 days out the schedule is still three lines of 4366, 5821
    and 4365, but both fixture-derived anchors now precede the deposit date, so
    all three lines fall due on the same day. At 29 days out a single line for
    the whole 14552 replaces the three.

    PRD §3.6: "The first line falls due three days after the logical clock."

    PRD §3.6: "The second falls due ninety days before the fixture, or on the
    first line's due date if that is later."

    PRD §3.6: "The third falls due thirty days before the fixture, or on the
    second line's due date if that is later."

    PRD §3.6: "When the fixture is fewer than 30 days away, the schedule
    collapses to a single line for the whole payable amount, due three days after
    the logical clock."

    Design: Corner/calculations/payment_schedule_remainder_lands_on_the_last_line_and_dates_are_floored
    """
    floor = _odd_cent_bronze_floor(api)
    client_id = floor["client"]["id"]
    package_id = floor["package"]["id"]

    far = make_booking(api, client_id, package_id, channel="CORPORATE", units=1)
    far_lines = installments_of(api, far["id"])
    assert [line["due_at"] for line in far_lines] == [
        "2026-08-04T00:00:00.000Z",
        "2026-11-03T15:00:00.000Z",
        "2027-01-02T15:00:00.000Z",
    ]

    set_clock(api, "2027-01-02T15:00:00Z")
    boundary = make_booking(api, client_id, package_id, channel="CORPORATE", units=1)
    boundary_lines = installments_of(api, boundary["id"])
    assert len(boundary_lines) == 3, (
        "exactly 30 days out is still inside the three-line schedule, because "
        "the collapse needs fewer than 30 days"
    )
    assert_schedule_amounts(boundary_lines, [4366, 5821, 4365])
    assert [line["due_at"] for line in boundary_lines] == [
        "2027-01-05T15:00:00.000Z",
        "2027-01-05T15:00:00.000Z",
        "2027-01-05T15:00:00.000Z",
    ]

    set_clock(api, "2027-01-03T15:00:00Z")
    inside = make_booking(api, client_id, package_id, channel="CORPORATE", units=1)
    inside_lines = installments_of(api, inside["id"])
    assert len(inside_lines) == 1
    assert_schedule_amounts(inside_lines, [14552])
    assert inside_lines[0]["due_at"] == "2027-01-06T15:00:00.000Z"
    assert_schedule_conservation(inside_lines, net_price_cents=14552)


# --------------------------------------------------------------------------
# The allocation waterfall
# --------------------------------------------------------------------------


def test_the_waterfall_fills_blocks_by_priority_rank_then_parks_the_remainder(
    api: ApiClient,
) -> None:
    """Two fifty-unit releases across blocks of 30, 40 and 20 units.

    The first release fills the rank-1 block exactly, so it is EXHAUSTED, gives
    the rank-2 block only the 20 units that remain, so it stays OPEN because 20
    is not its 40-unit target, and leaves the rank-3 block starved at 0 units and
    still OPEN. The second release finishes ranks 2 and 3 without touching the
    already-filled rank-1 block, and the 10 units nobody can absorb surface as
    the deal's unallocated quantity rather than being forced into a full block:
    90 absorbed against 100 released.

    PRD §3.3: "The distribution pass then walks the candidates in order and gives
    each block the lesser of its own `target_units` and the quantity still
    remaining, writes that figure to `allocated_units`, sets `block_state` to
    `EXHAUSTED` when the figure equals `target_units` and to `OPEN` otherwise,
    and subtracts the figure from the remaining quantity."

    PRD §3.3: "Whatever remains after the last candidate is recorded as the
    deal's `unallocated_units`."

    Design: Corner/calculations/waterfall_fills_blocks_by_priority_rank_then_parks_the_remainder
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"], contracted_units=100,
                               guaranteed_minimum_units=0, unit_cost_cents=8000)
    corporate = make_block(api, deal["id"], channel="CORPORATE",
                           target_units=30, priority_rank=1)
    individual = make_block(api, deal["id"], channel="INDIVIDUAL",
                            target_units=40, priority_rank=2)
    partner = make_block(api, deal["id"], channel="TRAVEL_PARTNER",
                         target_units=20, priority_rank=3)
    first = make_tranche(api, deal["id"], promised_units=50,
                         promised_release_at="2026-09-01T00:00:00.000Z")
    second = make_tranche(api, deal["id"], promised_units=50,
                          promised_release_at="2026-10-01T00:00:00.000Z")

    confirm_tranche(api, first["id"], deal["id"], 50)

    assert_block_position(read_block(api, corporate["id"]), allocated=30,
                          committed=0, released_back=0, state="EXHAUSTED")
    assert_block_position(read_block(api, individual["id"]), allocated=20,
                          committed=0, released_back=0, state="OPEN")
    assert_block_position(read_block(api, partner["id"]), allocated=0,
                          committed=0, released_back=0, state="OPEN")
    assert_deal_position(_read_deal(api, deal["id"]), released=50, shortfall=0,
                         liability=400000, status="PARTIALLY_RELEASED",
                         unallocated=0)

    confirm_tranche(api, second["id"], deal["id"], 50)

    filled = [read_block(api, block["id"])
              for block in (corporate, individual, partner)]
    assert [block["allocated_units"] for block in filled] == [30, 40, 20]
    assert all(block["block_state"] == "EXHAUSTED" for block in filled)
    assert sum(block["allocated_units"] for block in filled) == 90, (
        "no block may be filled past its own target to make the remainder "
        "disappear"
    )
    assert_deal_position(_read_deal(api, deal["id"]), released=100, shortfall=0,
                         liability=800000, status="FULLY_RELEASED", unallocated=10)


# --------------------------------------------------------------------------
# The margin report's input sets
# --------------------------------------------------------------------------


def _margin_report_floor(api: ApiClient) -> Dict[str, Any]:
    """A fixture with one excluded sibling for every input-set filter.

    A twenty-unit deal guaranteeing all twenty units is released in full, one
    booking is cancelled while another is allocated, and one build is driven to
    READY while an otherwise identical build is left PLANNED.
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"], contracted_units=20,
                               guaranteed_minimum_units=20, unit_cost_cents=8000)
    block = make_block(api, deal["id"], channel="CORPORATE", target_units=20,
                       priority_rank=1)
    release_deal(api, deal["id"], 20)
    package = make_published_bronze_package(api, event["id"])
    client = make_client(api)

    cancelled = make_booking(api, client["id"], package["id"],
                             channel="CORPORATE", units=5)
    cancelled = cancel_booking(api, cancelled["id"])
    live = make_booking(api, client["id"], package["id"],
                        channel="CORPORATE", units=5)
    live = allocate_booking(api, live["id"], block["id"])

    ready = make_ready_build(api, event["id"], zone_code="ZONE_A",
                             space_units=30, catering_covers=20, staff_count=5,
                             build_cost_cents=120000, catering_cost_cents=60000,
                             staffing_cost_cents=40000)
    planned = make_build(api, event["id"], zone_code="ZONE_B",
                         space_units=10, catering_covers=8, staff_count=2,
                         build_cost_cents=50000, catering_cost_cents=20000,
                         staffing_cost_cents=10000)
    return {
        "event": event,
        "deal": deal,
        "block": block,
        "package": package,
        "client": client,
        "cancelled": cancelled,
        "live": live,
        "ready_build": ready,
        "planned_build": planned,
    }


def test_the_margin_cost_base_excludes_the_planned_build_and_the_cancelled_net(
    api: ApiClient,
) -> None:
    """Every filter is probed by an excluded element beside an included twin.

    The READY build's 220000 is in the cost base while the PLANNED build's 80000
    is not, so the cost base is 380000 rather than 460000; the rights leg is the
    released deal's frozen 160000. The live 5-unit booking's 558720 is the whole
    provisional revenue, because the cancelled booking's net price is invisible to
    this variant. The unsold position is the 20 released units less the 10
    committed to the block, carried at the deal's own acquisition cost.

    PRD §3.9: "`build_cost_cents` is the total of `total_cost_cents` across the
    fixture's hospitality builds whose `build_state` is `APPROVED`, `READY` or
    `CLOSED`; builds that are still `PLANNED` and builds that were `CANCELLED`
    never enter the cost base."

    PRD §3.9: "Under `PROVISIONAL`, `revenue_cents` is the total of
    `net_price_cents` across the fixture's bookings whose `fulfillment_status` is
    `RESERVED`, `ALLOCATED`, `CREDENTIALED`, `DELIVERED` or `REBOOK_PENDING` —
    every live booking is assumed to convert — and `unsold_exposure_cents` is the
    full-cost exposure carried at one hundred percent of acquisition cost."

    PRD §3.9: "While the fixture's `status` is `SCHEDULED`, `POSTPONED` or
    `RESCHEDULED` the report defaults to `PROVISIONAL`; once the fixture's
    `status` is `COMPLETED` or `CANCELLED` it defaults to `FINAL`."

    Design: Corner/calculations/margin_report_cost_base_excludes_planned_builds_and_cancelled_revenue
    """
    floor = _margin_report_floor(api)
    assert floor["cancelled"]["cancellation_fee_cents"] == 55872
    assert floor["live"]["net_price_cents"] == 558720
    assert floor["ready_build"]["build_state"] == "READY"
    assert floor["ready_build"]["total_cost_cents"] == 220000
    assert floor["planned_build"]["build_state"] == "PLANNED"
    assert floor["planned_build"]["total_cost_cents"] == 80000

    report = margin_report(api, floor["event"]["id"])

    assert_margin_report(report, variant="PROVISIONAL", revenue=558720,
                         rights_cost=160000, build_cost=220000, cost=380000,
                         unsold_units=10, unsold_exposure=80000, margin=178720,
                         net_margin=98720, margin_pct=0.1767)
    assert report["build_cost_cents"] != 460000, (
        "460000 is what including the PLANNED build in the cost base would give"
    )
    assert report["revenue_cents"] != 1117440, (
        "1117440 is what counting the cancelled booking's net price as revenue "
        "would give"
    )


def test_completing_the_fixture_switches_the_variant_without_moving_the_cost_base(
    api: ApiClient,
) -> None:
    """The default flips to the realised basis; the explicit variant overrides it.

    Completion moves the READY build to CLOSED and the PLANNED build to
    CANCELLED, and the cost base is unchanged at 380000 — which is only true if
    the filter is the declared three-state set rather than "not cancelled". The
    realised revenue is the delivered booking's 558720 plus the retained 55872
    fee, and the unsold exposure is written down by the salvage recovery to
    52000. Asking the completed fixture for the forward-looking variant returns
    exactly the pre-completion reading, so it is the variant and not the fixture's
    status that drives the figures.

    PRD §3.9: "Under `FINAL`, `revenue_cents` is the total of `net_price_cents`
    across only the bookings whose `fulfillment_status` is `DELIVERED`, plus the
    total of `cancellation_fee_cents` across the bookings whose
    `fulfillment_status` is `CANCELLED` — realised delivery revenue plus retained
    cancellation fees — and `unsold_exposure_cents` is the full-cost exposure
    written down by the salvage recovery, that is, the full-cost exposure
    multiplied by one less thirty-five percent, rounded half-up to a whole cent."

    PRD §3.9: "Either variant may be requested explicitly for the same data by
    supplying `variant` as `PROVISIONAL` or `FINAL`, so a live fixture can be read
    on a realised basis and a finished one on a forward-looking basis."

    Design: Corner/calculations/margin_report_cost_base_excludes_planned_builds_and_cancelled_revenue
    """
    floor = _margin_report_floor(api)

    set_clock(api, "2027-02-02T00:00:00Z")
    completed = get_success_data(api.complete_event(floor["event"]["id"],
                                                   RIGHTS_MANAGER))
    assert completed["status"] == "COMPLETED"

    final = margin_report(api, floor["event"]["id"])
    assert_margin_report(final, variant="FINAL", revenue=614592,
                         rights_cost=160000, build_cost=220000, cost=380000,
                         unsold_units=10, unsold_exposure=52000, margin=234592,
                         net_margin=182592, margin_pct=0.2971)
    assert final["build_cost_cents"] == 220000, (
        "the closed build is still in the cost base and the cancelled build is "
        "still out of it, so completion moved neither"
    )

    override = get_success_data(
        api.get_margin_report(floor["event"]["id"], COMMERCIAL_DIRECTOR,
                              margin_report_params("PROVISIONAL"))
    )
    assert override["variant"] == "PROVISIONAL"
    assert override["revenue_cents"] == 558720, (
        "the delivered booking is inside the live set while the retained "
        "cancellation fee is not"
    )
    assert override["unsold_exposure_cents"] == 80000
    assert override["net_margin_cents"] == 98720
    assert_fraction_4dp(override["margin_pct"], 0.1767)


# --------------------------------------------------------------------------
# The shortfall unit cost: round once, then multiply
# --------------------------------------------------------------------------


def test_the_shortfall_unit_cost_is_rounded_once_before_it_is_multiplied(
    api: ApiClient,
) -> None:
    """A unit cost of 8333 makes the two orderings disagree by four cents.

    Sixty percent of 8333 is 4999.8, which rounds to 5000 per unit, so a 20-unit
    shortfall is worth 100000. Multiplying first and rounding once at the end
    gives 99996 instead. Releasing 10 of the guaranteed 20 units then mixes the
    two terms: the released units are charged at their exact 8333 while the
    remaining shortfall stays on the already-rounded 5000, giving 133330 rather
    than 133328.

    PRD §3.1: "Third, the shortfall unit cost is obtained by taking sixty percent
    of `unit_cost_cents` and rounding that single per-unit figure half-up to a
    whole cent, and `minimum_liability_cents` is then `released_units` multiplied
    by `unit_cost_cents`, plus `shortfall_units` multiplied by that already-rounded
    shortfall unit cost."

    PRD §3.1: "Rounding happens once, on the per-unit figure, before the
    multiplication by the shortfall quantity — not after it."

    Design: Corner/calculations/shortfall_liability_rounds_the_unit_cost_once_before_multiplying
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_deal(api, event["id"], contracted_units=40,
                     guaranteed_minimum_units=20, unit_cost_cents=8333)
    assert deal["deal_status"] == "DRAFT"

    committed = commit_deal(api, deal["id"])
    assert_deal_position(committed, released=0, shortfall=20, liability=100000,
                         status="COMMITTED")
    assert committed["minimum_liability_cents"] != 99996, (
        "99996 is round_half_up(20 * 8333 * 0.60), the multiply-then-round figure"
    )

    tranche = make_tranche(api, deal["id"], promised_units=10,
                           promised_release_at="2026-10-01T00:00:00.000Z")
    confirmed = confirm_tranche(api, tranche["id"], deal["id"], 10)
    assert confirmed["tranche_state"] == "CONFIRMED"

    after = _read_deal(api, deal["id"])
    assert_deal_position(after, released=10, shortfall=10, liability=133330,
                         status="SHORTFALL_DECLARED")
    assert after["minimum_liability_cents"] != 133328, (
        "133328 is what rounding after the multiplication would give on the "
        "shortfall term"
    )


# --------------------------------------------------------------------------
# The cancellation fee ladder
# --------------------------------------------------------------------------


def test_the_cancellation_fee_pct_steps_at_the_four_inclusive_day_marks(
    api: ApiClient,
) -> None:
    """Eight identical bookings cancelled on both sides of all four marks.

    Every booking nets 558720, so the fee is the whole difference between one
    band and the next. Ninety days out earns 0.10 and eighty-nine 0.25; sixty
    earns 0.25 and fifty-nine 0.50; thirty earns 0.50 and twenty-nine 0.80; seven
    earns 0.80 and six the full 1.00. A strict comparison instead of an inclusive
    one would move exactly the four boundary days. Nothing was pre-paid, so each
    settlement lands at the degenerate end of its identity: no refund and a
    balance equal to the whole fee.

    PRD §3.8: "The fee percentage is read off a days-to-event ladder in which
    every comparison is inclusive: 0.10 when the fixture is at least 90 days
    away, otherwise 0.25 when it is at least 60 days away, otherwise 0.50 when it
    is at least 30 days away, otherwise 0.80 when it is at least 7 days away,
    otherwise 1.00."

    PRD §3.8: "`cancellation_fee_cents` is the booking's `net_price_cents`
    multiplied by that percentage, rounded half-up to a whole cent."

    Design: Corner/calculations/tier_schedule_fee_pct_switches_at_the_ninety_sixty_thirty_and_seven_day_marks
    """
    floor = unexposed_bronze_floor(api)
    bookings = [
        make_booking(api, floor["client"]["id"], floor["package"]["id"],
                     channel="CORPORATE", units=5)
        for _ in range(8)
    ]
    assert all(booking["net_price_cents"] == 558720 for booking in bookings)

    ladder = [
        ("2026-11-03T15:00:00Z", 55872),
        ("2026-11-04T15:00:00Z", 139680),
        ("2026-12-03T15:00:00Z", 139680),
        ("2026-12-04T15:00:00Z", 279360),
        ("2027-01-02T15:00:00Z", 279360),
        ("2027-01-03T15:00:00Z", 446976),
        ("2027-01-25T15:00:00Z", 446976),
        ("2027-01-26T15:00:00Z", 558720),
    ]

    for booking, (moment, expected_fee) in zip(bookings, ladder):
        set_clock(api, moment)
        settled = cancel_booking(api, booking["id"])
        assert settled["cancellation_fee_cents"] == expected_fee, moment
        assert settled["settlement_variant"] == "TIER_SCHEDULE", moment
        assert settled["refund_cents"] == 0, moment
        assert settled["balance_due_cents"] == expected_fee, moment
        assert_settlement_identity(settled, pre_paid_cents=0)
