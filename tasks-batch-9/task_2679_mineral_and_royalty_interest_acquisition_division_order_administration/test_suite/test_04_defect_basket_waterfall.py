"""The defect basket waterfall: per-defect rounding, then accumulation."""

from test_helpers import fixtures as fx
from test_helpers.assertions import assert_money

THREE_DEFECTS = [
    {"defect_type": "MISSING_HEIR", "affected_nma": 10.0000, "description": "Unlocated heir of the 1988 estate"},
    {"defect_type": "UNRELEASED_LEASE", "affected_nma": 7.5000, "description": "Unreleased 1978 lease of record"},
    {"defect_type": "TAX_SALE_GAP", "affected_nma": 2.5000, "description": "Tax sale gap in the 1960s chain"},
]


def test_each_defect_is_valued_off_the_unadjusted_purchase_price(api):
    """Allocated and net defect values come from purchase_price and the deductible.

    PRD: "Its `net_defect_value` — the figure that will actually enter the basket
    — is `allocated_value` less the agreement's `individual_defect_threshold`,
    floored at zero (so a defect smaller than the per-defect deductible
    contributes exactly 0.00 rather than a negative number), rounded half-up to
    cents."

    Design: Difficulty/combinatorial_formula/defect_basket_per_defect_rounding_then_sum
    """
    world = fx.psa_with_defects_ready(api, THREE_DEFECTS)
    first, second, third = world["defects"]

    assert_money(first["allocated_value"], "12000.00", "allocated_value of the 10-acre defect")
    assert_money(first["net_defect_value"], "9500.00", "net_defect_value of the 10-acre defect")
    assert_money(second["allocated_value"], "9000.00", "allocated_value of the 7.5-acre defect")
    assert_money(second["net_defect_value"], "6500.00", "net_defect_value of the 7.5-acre defect")
    assert_money(third["allocated_value"], "3000.00", "allocated_value of the 2.5-acre defect")
    assert_money(third["net_defect_value"], "500.00", "net_defect_value of the 2.5-acre defect")


def test_closing_curative_sweeps_every_open_defect_to_uncured(api):
    """The sweep runs before the waterfall and catches all three RAISED defects.

    PRD: "The first thing it does is sweep: every defect of this agreement still
    sitting in `RAISED`, in `CURE_SUBMITTED` or in `CURE_REJECTED` is driven to
    `UNCURED`."

    Design: Difficulty/combinatorial_formula/defect_basket_per_defect_rounding_then_sum
    """
    world = fx.psa_with_defects_ready(api, THREE_DEFECTS)

    fx.close_curative(api, world["psa"]["id"])

    for defect in world["defects"]:
        reread = fx.read_defect(api, defect["id"])
        assert reread["defect_status"] == "UNCURED", (
            f"defect {defect['id']} should have been swept to UNCURED"
        )


def test_basket_absorbs_the_first_tranche_and_only_the_excess_moves_the_price(api):
    """9500.00 + 6500.00 + 500.00 against a 16000.00 basket deducts exactly 500.00.

    PRD: "Otherwise the adjustment is the running total less the
    `aggregate_defect_basket`, rounded half-up to cents."

    Design: Difficulty/combinatorial_formula/defect_basket_per_defect_rounding_then_sum
    """
    world = fx.psa_with_defects_ready(api, THREE_DEFECTS)

    psa = fx.close_curative(api, world["psa"]["id"])

    assert_money(psa["defect_adjustment_amount"], "500.00", "defect_adjustment_amount")
    assert_money(psa["adjusted_purchase_price"], "47500.00", "adjusted_purchase_price")
    assert_money(psa["purchase_price"], "48000.00", "purchase_price")
    assert psa["curative_status"] == "CURATIVE_CLOSED"
    assert psa["psa_status"] == "EXECUTED"
    assert psa["funding_status"] == "UNFUNDED"
