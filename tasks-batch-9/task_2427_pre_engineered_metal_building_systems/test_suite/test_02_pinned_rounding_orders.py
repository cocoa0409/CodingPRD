"""The two rounding orders the specification pins.

Both are cases where a mathematically equivalent-looking reordering stores a
different number: the component weight rollup rounds per line before summing,
and the price pipeline selects the volume discount tier from a base that already
contains freight.
"""

import pytest

from test_helpers import (
    STANDARD_KITS,
    append_components,
    assert_rate,
    assert_weight,
    chain_locked_configuration,
    create_design,
    create_quote,
    full_bom,
    get_design,
)

#: ``unit_weight_lbs`` then ``line_weight_lbs`` for the weighted marks of the
#: detailed bill, each rounded at its own step.
PER_LINE_WEIGHTS = [
    ("C-1", 1527.58, 15275.80),
    ("R-1", 2495.88, 24958.80),
    ("C-2", 1106.18, 2212.36),
    ("P-1", 84.66, 3386.40),
    ("G-1", 63.82, 1021.12),
]


def _detailed_design():
    """A DRAFT design carrying the nine-line detailed bill of material."""
    chain = chain_locked_configuration()
    configuration = chain["configuration"]
    design = create_design(configuration["id"], configuration["version"])
    # The bill without its base detail: eight weighted marks plus one knee.
    rows = append_components(design["id"], full_bom()[:-1])
    return design, {row["mark"]: row for row in rows}


@pytest.mark.parametrize("mark,unit_weight,line_weight", PER_LINE_WEIGHTS)
def test_01_each_line_rounds_its_unit_weight_before_multiplying_by_quantity(
    mark, unit_weight, line_weight
):
    """A line's own rounding happens twice: at the unit, then at the line.

    PRD §3.6: "For each component of the design in ``created_at`` ascending
    order, ``unit_weight_lbs`` is ``length_ft`` multiplied by ``weight_per_ft``
    rounded half up to two decimal places, and ``line_weight_lbs`` is that
    already-rounded ``unit_weight_lbs`` multiplied by ``quantity``, again
    rounded half up to two decimal places."

    PRD §2.7: "The component weight rollup rounds each component's unit weight
    first, multiplies by quantity, rounds that line, and only then sums the
    lines — it never sums raw products and rounds once at the end."

    Design: Difficulty/combinatorial_formula/pinned_per_line_rounding_order_in_design_weight_rollup
    """
    _, rows = _detailed_design()

    component = rows[mark]
    assert_weight(component["unit_weight_lbs"], unit_weight)
    assert_weight(component["line_weight_lbs"], line_weight)
    # The line weight is the rounded unit weight times the quantity exactly.
    assert_weight(
        component["line_weight_lbs"],
        round(component["unit_weight_lbs"] * component["quantity"], 2),
    )


def test_02_frame_rollup_sums_already_rounded_lines_not_raw_products():
    """Summing raw products and rounding once would store a different total.

    PRD §3.6: "The design's ``frame_weight_lbs`` is then the sum of
    ``line_weight_lbs`` over only those components whose ``component_class`` is
    ``PRIMARY_FRAME_MEMBER`` or ``SECONDARY_MEMBER``, rounded half up to two
    decimal places, and ``shippable_weight_lbs`` is the sum of
    ``line_weight_lbs`` over every component of the design regardless of class,
    likewise rounded half up to two decimal places."

    PRD §3.6: "Summing raw products of ``length_ft``, ``weight_per_ft`` and
    ``quantity`` and rounding once at the end is not the rule and will produce a
    different stored total."

    Design: Difficulty/combinatorial_formula/pinned_per_line_rounding_order_in_design_weight_rollup
    """
    design, _ = _detailed_design()

    detailed = get_design(design["id"])
    # 15275.80 + 24958.80 + 2212.36 + 3386.40 + 1021.12.
    assert_weight(detailed["frame_weight_lbs"], 46854.48)
    assert_weight(
        detailed["frame_weight_lbs"], sum(line for _, _, line in PER_LINE_WEIGHTS)
    )
    # The single-rounding shortcut over raw products yields 46854.22 instead.
    assert detailed["frame_weight_lbs"] != pytest.approx(46854.22, abs=0.001)


def test_03_a_connection_detail_weighs_nothing_and_shippable_spans_every_class():
    """Panels and anchors ship without being billed as frame steel.

    PRD §3.6: "A ``CONNECTION_DETAIL`` component has ``unit_weight_lbs`` of 0
    and ``line_weight_lbs`` of 0 — a detail is a drawing, not steel."

    PRD §3.6: "The two totals differ in scope, and the difference matters: panel
    bundles and anchor packages ship but are not billed as frame steel."

    PRD §3.6: "``component_count`` is the plain count of component rows on the
    design."

    Design: Difficulty/combinatorial_formula/pinned_per_line_rounding_order_in_design_weight_rollup
    """
    design, rows = _detailed_design()

    knee = rows["K-1"]
    assert_weight(knee["unit_weight_lbs"], 0)
    assert_weight(knee["line_weight_lbs"], 0)

    detailed = get_design(design["id"])
    assert detailed["component_count"] == 9
    # 46854.48 frame + 297.24 roof panels + 139.20 wall panels + 33.00 anchors.
    assert_weight(detailed["shippable_weight_lbs"], 47323.92)
    assert detailed["shippable_weight_lbs"] > detailed["frame_weight_lbs"]


def test_04_freight_sits_inside_the_base_that_selects_the_volume_tier():
    """The discount base is subtotal plus adjustment plus freight, in that order.

    PRD §3.4: "*Step four* forms the discount base.
    ``pre_discount_total_cents`` is ``subtotal_cents`` plus the quote's
    ``adjustment_cents`` plus ``freight_cost_cents``."

    PRD §3.4: "The steps run in exactly the order given below and in no other
    order, because the volume tier is keyed on a base that already contains
    freight — freight therefore participates in selecting the discount rate that
    is then applied to freight itself."

    Design: Difficulty/combinatorial_formula/freight_inclusive_volume_tier_pinned_evaluation_order
    """
    chain = chain_locked_configuration(kits=STANDARD_KITS)

    quote = create_quote(
        chain["builder"]["id"],
        chain["configuration"]["id"],
        freight_distance_miles=240,
        adjustment_cents=14980169,
    )

    assert quote["subtotal_cents"] == 9853859
    assert quote["freight_cost_cents"] == 165972
    # 9853859 + 14980169 + 165972 lands exactly on the 25,000,000 threshold;
    # without freight the base would be 24834028 and miss it.
    assert quote["pre_discount_total_cents"] == 25000000
    assert (
        quote["subtotal_cents"]
        + quote["adjustment_cents"]
        + quote["freight_cost_cents"]
        == quote["pre_discount_total_cents"]
    )


def test_05_volume_tier_is_inclusive_at_its_boundary_and_adds_to_the_tier_rate():
    """A base of exactly 25,000,000 cents earns the two percent tier.

    PRD §3.4: "``volume_discount_rate`` is selected from
    ``pre_discount_total_cents`` by descending threshold: a base of one million
    dollars or more (100,000,000 cents or more) earns 0.06; otherwise a base of
    five hundred thousand dollars or more (50,000,000 cents or more) earns 0.04;
    otherwise a base of two hundred and fifty thousand dollars or more
    (25,000,000 cents or more) earns 0.02; anything below that earns nothing."

    PRD §3.4: "Each threshold is inclusive at its boundary."

    PRD §3.4: "``total_discount_rate`` is the sum of the tier rate and the
    volume rate, capped at 0.12 — that is, the smaller of 0.12 and the sum — so
    a ``GOLD`` builder on a million-dollar base is capped at twelve percent
    rather than the fourteen percent the two components would otherwise give."

    Design: Difficulty/combinatorial_formula/freight_inclusive_volume_tier_pinned_evaluation_order
    """
    chain = chain_locked_configuration(kits=STANDARD_KITS)

    quote = create_quote(
        chain["builder"]["id"],
        chain["configuration"]["id"],
        freight_distance_miles=240,
        adjustment_cents=14980169,
    )

    assert_rate(quote["tier_discount_rate"], 0.03)
    assert_rate(quote["volume_discount_rate"], 0.02)
    assert_rate(quote["total_discount_rate"], 0.05)


def test_06_the_freight_inclusive_rate_is_applied_back_to_the_whole_base():
    """Excluding freight from tier selection would price the quote higher.

    PRD §3.4: "*Step six* produces the price. The price in cents is
    ``pre_discount_total_cents`` multiplied by one minus
    ``total_discount_rate``, rounded half up to whole cents."

    PRD §3.4: "Under the ``PRELIMINARY`` variant the result is stored as the
    quote's ``quoted_price_cents``; under the ``FINAL`` variant it is stored as
    the order's ``final_price_cents``."

    Design: Difficulty/combinatorial_formula/freight_inclusive_volume_tier_pinned_evaluation_order
    """
    chain = chain_locked_configuration(kits=STANDARD_KITS)

    quote = create_quote(
        chain["builder"]["id"],
        chain["configuration"]["id"],
        freight_distance_miles=240,
        adjustment_cents=14980169,
    )

    # 25,000,000 x (1 - 0.05).
    assert quote["quoted_price_cents"] == 23750000
    # A tier chosen from a freight-free base would have given 0.03 and 24250000.
    assert quote["quoted_price_cents"] != 24250000
