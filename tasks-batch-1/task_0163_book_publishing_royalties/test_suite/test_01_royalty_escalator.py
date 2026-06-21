"""Tiered royalty escalator: marginal-rate selection, per-format rounding order,
and tier boundary precision.

These tests exercise the depth-design instances under rules
combinatorial_formula and boundary_precision_check, plus the corner-design
calculation instances for the escalator.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    fixtures,
    TEST_USERS,
)

PUB = TEST_USERS["publisher_headers"]


# ==========================================================================
# Queue A — combinatorial_formula
# ==========================================================================
def test_escalator_straddles_two_tiers_from_nonzero_baseline(api):
    """PRD §3.7: "Starting at a running position equal to the cumulative baseline
    and a remaining quantity equal to the period's net units, the escalator
    considers each tier in turn"

    PRD §3.7: "The cumulative baseline, the count of units already earned across
    prior finalized periods, is the contract's `lifetime_net_units`; it reflects
    finalized periods only, so draft or closed siblings never contribute to it."

    Period 2 of net 5000 starts at cum_before=6000, straddling tier2 (5001..10000
    @0.125) and tier3 (10001..@0.15): 4000 units @0.125*3000 + 1000 units
    @0.15*3000 = 1500000 + 450000 = 1950000.

    Design: Difficulty/combinatorial_formula/tiered_royalty_escalator_three_input_nonlinear
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.STANDARD_TIERS, advance_cents=0, reserve_pct=0.25, reserve_hold_periods=2
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]

    fixtures.run_period_to_finalize(cid, fid, "P1", 1, 6000, 0)

    p2 = fixtures.run_period_to_closed(cid, fid, "P2", 2, 5000, 0)
    s2 = get_success_data(api.generate_statement(p2["id"], PUB))

    assert s2["gross_royalty_cents"] == 1950000, (
        f"expected 1950000, got {s2['gross_royalty_cents']}"
    )
    contract = validate_success(api.get_contract(cid, PUB))
    assert contract["lifetime_net_units"] == 6000


def test_per_format_then_sum_rounding_order_pinned(api):
    """PRD §3.7: "the gross royalty is computed per format and then summed: each
    format's units run the escalator against the same shared cumulative-baseline
    window, formats taken in ascending order of their `created_at`, each format's
    subtotal rounded to whole cents, and only then are the per-format subtotals
    added together."

    PRD §3.7: "This per-format-then-sum order is canonical and can legitimately
    differ by a cent from the alternative of summing raw values and rounding once;
    the summing-then-rounding-once interpretation is the wrong one."

    Two formats each at 333c sell 1 unit at tier-1 rate 0.10: per-unit 33.3c;
    round(33.3)+round(33.3) = 33+33 = 66, not round(66.6)=67.

    Design: Difficulty/combinatorial_formula/per_format_then_sum_rounding_order_pinned
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER,
        advance_cents=0,
        reserve_pct=0,
        reserve_hold_periods=1,
        publish=True,
    )
    cid = base["contract"]["id"]
    tid = base["title"]["id"]
    fa = base["format"]  # HARDCOVER 3000 — we need 333c formats instead

    # The base format is 3000c; build the two 333c formats this scenario needs.
    # Replace by creating a fresh title under a new contract sized exactly.
    # Simpler: build bespoke contract here.
    author = fixtures.create_author()
    contract = fixtures.create_contract(author["id"], advance_cents=0, reserve_pct=0, reserve_hold_periods=1)
    fixtures.add_tiers(contract["id"], fixtures.SINGLE_TIER)
    title = fixtures.add_title(contract["id"], name="Two Format Book")
    fa = fixtures.add_format(title["id"], format_type="HARDCOVER", list_price_cents=333)
    fb = fixtures.add_format(title["id"], format_type="EBOOK", list_price_cents=333)
    get_success_data(api.activate_contract(contract["id"], PUB))
    get_success_data(api.publish_title(title["id"], PUB))

    period = fixtures.open_period(contract["id"], "P1", 1)
    fixtures.post_sales(period["id"], fa["id"], units_sold=1, units_returned=0)
    fixtures.post_sales(period["id"], fb["id"], units_sold=1, units_returned=0)
    fixtures.close_period(period["id"])

    s1 = get_success_data(api.generate_statement(period["id"], PUB))
    assert s1["gross_royalty_cents"] == 66, (
        f"per_format_then_sum pins 66, got {s1['gross_royalty_cents']}"
    )
    assert s1["gross_royalty_cents"] != 67


# ==========================================================================
# Queue A — boundary_precision_check
# ==========================================================================
def test_tier_upper_unit_5000_inclusive_5001_crosses(api):
    """PRD §3.7: "the `upper_unit` is the inclusive index at which it ends"

    PRD §3.7: "it determines the segment available between the running position
    (or the tier's start, whichever is further along) and the tier's inclusive
    top ... it takes from that tier the smaller of the remaining quantity and the
    segment's width"

    Net 5001 from baseline 0: 5000 units in tier-1 (5000*0.10*3000=1500000) plus
    1 unit in tier-2 (1*0.125*3000=375) = 1500375; the 5001st unit is the first
    tier-2 unit.

    Design: Difficulty/boundary_precision_check/tier_boundary_5000_inclusive_vs_5001_crosses
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.STANDARD_TIERS, advance_cents=0, reserve_pct=0, reserve_hold_periods=1
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]

    period = fixtures.run_period_to_closed(cid, fid, "P1", 1, 5001, 0)
    s1 = get_success_data(api.generate_statement(period["id"], PUB))

    assert s1["gross_royalty_cents"] == 1500375, (
        f"expected 1500375, got {s1['gross_royalty_cents']}"
    )
    assert s1["gross_royalty_cents"] != 1500300


def test_zero_net_units_period_yields_zero_reserve(api):
    """PRD §3.8: "its `reserve_units` is the period's net units multiplied by the
    contract's `reserve_pct`, rounded half up to a whole number (and may be 0)"

    PRD §3.8: "its per-unit liquidation value, `reserve_unit_value_cents`, is
    `reserve_held_cents` divided by `reserve_units` when `reserve_units` is
    greater than 0 and otherwise 0"

    A period whose only record is sold=0/returned=0 has net 0: gross 0, reserve
    held 0, reserve_units 0, unit value 0 (no division by zero).

    Design: Difficulty/boundary_precision_check/zero_net_units_empty_period_yields_zero_reserve
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER, advance_cents=0, reserve_pct=0.25, reserve_hold_periods=1
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]

    period = fixtures.run_period_to_closed(cid, fid, "P1", 1, 0, 0)
    s1 = get_success_data(api.generate_statement(period["id"], PUB))
    s1 = fixtures.finalize_statement(s1["id"], cid)

    assert s1["gross_royalty_cents"] == 0
    assert s1["reserve_held_cents"] == 0

    reserve = fixtures.find_reserve_from_statement(s1["id"])
    assert reserve is not None, "finalize must create a HELD reserve even when sized 0"
    assert reserve["reserve_units"] == 0
    assert reserve["reserve_unit_value_cents"] == 0


# ==========================================================================
# Queue B — corner calculations
# ==========================================================================
def test_tier1_only_marginal_rate_no_leak(api):
    """PRD §3.7: "it values those taken units at the per-unit royalty for that
    tier — the tier's `rate` times the relevant list price — and accumulates that
    segment's value rounded half up to whole cents into `gross_royalty_cents`"

    Net 4999 from baseline 0 stays entirely in tier-1: 4999*0.10*3000 = 1499700;
    no higher-tier rate leaks in.

    Design: Corner/calculations/tier1_only_marginal_rate
    """
    author = fixtures.create_author()
    contract = fixtures.create_contract(author["id"], advance_cents=0, reserve_pct=0, reserve_hold_periods=1)
    fixtures.add_tiers(
        contract["id"],
        [{"lower_unit": 1, "upper_unit": 5000, "rate": 0.10}, {"lower_unit": 5001, "rate": 0.125}],
    )
    title = fixtures.add_title(contract["id"], name="Tier Book")
    fmt = fixtures.add_format(title["id"], list_price_cents=3000)
    get_success_data(api.activate_contract(contract["id"], PUB))
    get_success_data(api.publish_title(title["id"], PUB))

    period = fixtures.run_period_to_closed(contract["id"], fmt["id"], "P1", 1, 4999, 0)
    s1 = get_success_data(api.generate_statement(period["id"], PUB))
    assert s1["gross_royalty_cents"] == 1499700


def test_reserve_held_is_quarter_of_gross(api):
    """PRD §3.8: "its `reserve_held_cents` is the period's `gross_royalty_cents`
    multiplied by the contract's `reserve_pct`, rounded half up to whole cents"

    PRD §3.9: "`royalty_credited_cents` is `gross_royalty_cents` minus the
    period's `reserve_held_cents`"

    Gross 1875000 (6000 units across tier1+tier2) with reserve_pct=0.25:
    reserve_held 468750 = round_half_up(1875000*0.25), royalty_credited 1406250.

    Design: Corner/calculations/reserve_held_is_quarter_of_gross
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.STANDARD_TIERS, advance_cents=0, reserve_pct=0.25, reserve_hold_periods=2
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]

    period = fixtures.run_period_to_closed(cid, fid, "P1", 1, 6000, 0)
    s1 = get_success_data(api.generate_statement(period["id"], PUB))

    assert s1["gross_royalty_cents"] == 1875000
    assert s1["reserve_held_cents"] == 468750
    assert s1["royalty_credited_cents"] == 1406250
