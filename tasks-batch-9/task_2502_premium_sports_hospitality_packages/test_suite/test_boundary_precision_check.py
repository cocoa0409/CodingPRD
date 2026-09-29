"""Boundaries where one unit either side of the line changes the answer.

The guarantee comparison is inclusive, so a release landing exactly on the
guarantee leaves nothing short, and the pricing pass has a cardinality boundary
at one component line, below which it refuses rather than dividing by zero.
"""

from typing import Any, Dict

from test_helpers import (
    COMMERCIAL_MANAGER,
    ERR_PACKAGE_HAS_NO_COMPONENTS,
    RIGHTS_MANAGER,
    ApiClient,
    add_component,
    assert_deal_position,
    assert_fraction_4dp,
    assert_package_pricing,
    assert_total_count,
    commit_deal,
    confirm_tranche,
    get_success_data,
    make_deal,
    make_event,
    make_package,
    make_tranche,
    price_package,
    reset_clock,
    validate_error,
)


def _two_deals_differing_only_in_the_guarantee(api: ApiClient) -> Dict[str, Any]:
    """Two committed deals, guarantees 60 and 61, each promising 60 units.

    Everything else about them is identical — same fixture, same contracted 100
    units, same 8000-cent unit cost, same single PENDING tranche — so a single
    unit of guarantee is the only thing that can explain any divergence.
    """
    reset_clock(api)
    event = make_event(api)

    on_boundary = make_deal(api, event["id"], rights_holder_name="Meridian FC Boundary",
                            inventory_type="TICKET", contracted_units=100,
                            guaranteed_minimum_units=60, unit_cost_cents=8000)
    commit_deal(api, on_boundary["id"])
    boundary_tranche = make_tranche(api, on_boundary["id"], promised_units=60)

    one_over = make_deal(api, event["id"], rights_holder_name="Meridian FC OneOver",
                         inventory_type="HOSPITALITY_SPACE", contracted_units=100,
                         guaranteed_minimum_units=61, unit_cost_cents=8000)
    commit_deal(api, one_over["id"])
    over_tranche = make_tranche(api, one_over["id"], promised_units=60)

    return {
        "event": event,
        "on_boundary": on_boundary,
        "boundary_tranche": boundary_tranche,
        "one_over": one_over,
        "over_tranche": over_tranche,
    }


def _draft_package_with_no_component_lines(api: ApiClient) -> Dict[str, Any]:
    """A DRAFT package on a SCHEDULED fixture, carrying no component lines."""
    reset_clock(api)
    event = make_event(api)
    package = make_package(api, event["id"], name="Empty Shell", tier="GOLD",
                           tickets_per_package=2, hotel_nights=0,
                           transport_included=False, min_margin_pct=0.1000)
    return {"event": event, "package": package}


def _read_deal(api: ApiClient, deal_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_rights_deal(deal_id, RIGHTS_MANAGER))


def _read_package(api: ApiClient, package_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_package_product(package_id, COMMERCIAL_MANAGER))


# --------------------------------------------------------------------------
# The guarantee comparison, tested at exact equality
# --------------------------------------------------------------------------


def test_a_release_landing_exactly_on_the_guarantee_leaves_no_shortfall(
    api: ApiClient,
) -> None:
    """Sixty released against a guarantee of sixty is not short by one.

    The comparison is inclusive, so the deal carries no shortfall units at all
    and its liability is the plain 60 * 8000 == 480000 with no shortfall leg.
    Because 60 released is still below the 100 contracted, the deal reads
    PARTIALLY_RELEASED rather than shortfall-declared.

    PRD §3.2: "Second, `shortfall_units` is 0 whenever `released_units` is
    greater than or equal to `guaranteed_minimum_units` — a release that lands
    exactly on the guarantee leaves no shortfall — and is otherwise the
    guarantee minus the released quantity."

    Design: Difficulty/boundary_precision_check/released_units_exactly_equals_guaranteed_minimum_leaves_zero_shortfall
    """
    scenario = _two_deals_differing_only_in_the_guarantee(api)

    confirmed = confirm_tranche(api, scenario["boundary_tranche"]["id"],
                                scenario["on_boundary"]["id"], 60)
    assert confirmed["tranche_state"] == "CONFIRMED"
    assert confirmed["confirmed_units"] == 60

    deal = _read_deal(api, scenario["on_boundary"]["id"])
    assert_deal_position(deal, released=60, shortfall=0, liability=480000,
                         status="PARTIALLY_RELEASED")


def test_one_unit_below_the_guarantee_declares_a_shortfall_priced_per_unit(
    api: ApiClient,
) -> None:
    """The sibling deal, short by exactly one unit, diverges on every figure.

    The identical 60-unit confirmation against a guarantee of 61 leaves one unit
    short, so the liability gains a single shortfall leg: 60 * 8000 plus
    1 * round_half_up(8000 * 0.60) == 480000 + 4800 == 484800, and the status
    function declares the shortfall. The 4800 difference between the two deals
    is the per-unit shortfall cost, rounded once before it is multiplied.

    PRD §3.2: "Rounding happens once, on the per-unit figure, before the
    multiplication by the shortfall quantity — not after it."

    Design: Difficulty/boundary_precision_check/released_units_exactly_equals_guaranteed_minimum_leaves_zero_shortfall
    """
    scenario = _two_deals_differing_only_in_the_guarantee(api)

    confirm_tranche(api, scenario["boundary_tranche"]["id"],
                    scenario["on_boundary"]["id"], 60)
    on_boundary = _read_deal(api, scenario["on_boundary"]["id"])

    confirmed = confirm_tranche(api, scenario["over_tranche"]["id"],
                                scenario["one_over"]["id"], 60)
    assert confirmed["tranche_state"] == "CONFIRMED"
    one_over = _read_deal(api, scenario["one_over"]["id"])

    assert_deal_position(one_over, released=60, shortfall=1, liability=484800,
                         status="SHORTFALL_DECLARED")

    # Identical releases, divergent positions: one unit of guarantee is the
    # only difference between the two deals.
    assert on_boundary["released_units"] == one_over["released_units"] == 60
    assert on_boundary["shortfall_units"] != one_over["shortfall_units"]
    assert on_boundary["deal_status"] != one_over["deal_status"]
    assert (one_over["minimum_liability_cents"]
            - on_boundary["minimum_liability_cents"]) == 4800


# --------------------------------------------------------------------------
# The pricing pass's cardinality boundary at one component line
# --------------------------------------------------------------------------


def test_pricing_a_package_with_no_component_lines_is_refused_outright(
    api: ApiClient,
) -> None:
    """Cardinality zero is a rejection, not a zero-valued price.

    The package already opens with every derived money field at 0, so the guard
    is not there to produce zeros — it is there to stop the margin division
    happening at all. The refused call leaves the package in DRAFT with its
    pricing stamps unset and no component rows behind it.

    PRD §3.4: "A package with no component lines at all cannot be priced and is
    refused with `ERR_PACKAGE_HAS_NO_COMPONENTS`."

    Design: Difficulty/boundary_precision_check/pricing_package_with_zero_components_hits_empty_collection_guard
    """
    scenario = _draft_package_with_no_component_lines(api)
    package_id = scenario["package"]["id"]
    assert_package_pricing(scenario["package"], base_cost=0, subtotal=0,
                           list_price=0, margin_pct=0.0, status="DRAFT")

    response = api.price_package_product(package_id, COMMERCIAL_MANAGER)
    validate_error(response, ERR_PACKAGE_HAS_NO_COMPONENTS, 422)

    unchanged = _read_package(api, package_id)
    assert_package_pricing(unchanged, base_cost=0, subtotal=0, list_price=0,
                           margin_pct=0.0, status="DRAFT")
    assert unchanged["priced_by_user_id"] is None
    assert unchanged["priced_at"] is None

    assert_total_count(
        api.list_package_components(COMMERCIAL_MANAGER,
                                    {"package_product_id": package_id}), 0
    )


def test_a_single_component_line_is_the_smallest_priceable_package(
    api: ApiClient,
) -> None:
    """Cardinality one, the smallest legal input set, prices successfully.

    Adding one line of 10000 at a markup of 0.1000 to the same package that was
    just refused takes it to PRICED with a base cost of 10000, a subtotal of
    round_half_up(10000 * 1.1000) == 11000, a GOLD list price of
    round_half_up(11000 * 1.25) == 13750 and a margin of
    (13750 - 10000) / 13750 == 0.2727. The guard therefore sits exactly at "at
    least one", not at two.

    PRD §3.4: "The package's `margin_pct` is then the list price less the base
    cost, divided by the list price, rounded half-up to four decimal places —
    except that when `list_price_cents` comes out as 0 the margin is fixed at 0
    rather than divided by zero."

    Design: Difficulty/boundary_precision_check/pricing_package_with_zero_components_hits_empty_collection_guard
    """
    scenario = _draft_package_with_no_component_lines(api)
    package_id = scenario["package"]["id"]
    validate_error(api.price_package_product(package_id, COMMERCIAL_MANAGER),
                   ERR_PACKAGE_HAS_NO_COMPONENTS, 422)

    line = add_component(api, package_id, component_type="TICKET",
                         descriptor="Single seat", quantity=1,
                         unit_cost_cents=10000, markup_pct=0.1000, sequence_no=1)
    priced = price_package(api, package_id)

    assert_package_pricing(priced, base_cost=10000, subtotal=11000,
                           list_price=13750, margin_pct=0.2727, status="PRICED")
    assert_fraction_4dp(priced["margin_pct"], 0.2727)

    stored_line = get_success_data(
        api.get_package_component(line["id"], COMMERCIAL_MANAGER)
    )
    assert stored_line["line_cost_cents"] == 10000
    assert stored_line["line_price_cents"] == 11000
