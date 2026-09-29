"""The two article-processing-charge waterfalls: nested rounding and surcharge relief."""

from test_helpers import assertions as a
from test_helpers import fixtures as fx


def test_net_apc_rounds_at_every_step_before_the_next_step_consumes_it():
    """A non-round list price makes all three roundings observable.

    PRD: "Pricing runs in a fixed waterfall, and each step rounds to a whole cent before the next step consumes it."

    Design: Difficulty/combinatorial_formula/apc_net_amount_nested_rounding_order_pinned
    """
    world = fx.setup_nested_rounding_invoice_world()

    invoice = fx.issue_invoice(
        world["manuscript"]["id"], page_charge_count=0, color_figure_count=0
    )

    a.assert_invoice_amounts(
        invoice,
        base_cents=148778,
        waiver_pct=25,
        waiver_cents=37195,
        institutional_pct=15,
        institutional_cents=16737,
        net_apc_cents=94846,
    )


def test_institutional_discount_is_taken_from_the_post_waiver_remainder():
    """Both discounts against the list base would give a different number of cents.

    PRD: "Computing both discounts against `base_cents` and subtracting them together yields a different number of cents and is not what this system does."

    Design: Difficulty/combinatorial_formula/apc_net_amount_nested_rounding_order_pinned
    """
    world = fx.setup_nested_rounding_invoice_world()

    invoice = fx.issue_invoice(
        world["manuscript"]["id"], page_charge_count=0, color_figure_count=0
    )

    assert invoice["institutional_cents"] == 16737, (
        "the discount is taken from base_cents less waiver_cents"
    )
    assert invoice["institutional_cents"] != 22317, (
        "22317 is the discount taken from base_cents, which is not the pinned base"
    )
    assert invoice["net_apc_cents"] != 89266, (
        "89266 is the result of subtracting both discounts computed against base_cents"
    )


def test_issued_invoice_freezes_the_licence_and_raises_the_receivable():
    """The surcharge-free invoice carries its net straight through to the ledger.

    PRD: "The created invoice begins at status `ISSUED`, freezes `license_at_issue` from the manuscript's `oa_license` at that instant, and leaves `waiver_reason` and `settled_at` absent."

    Design: Difficulty/combinatorial_formula/apc_net_amount_nested_rounding_order_pinned
    """
    world = fx.setup_nested_rounding_invoice_world()

    invoice = fx.issue_invoice(
        world["manuscript"]["id"], page_charge_count=0, color_figure_count=0
    )

    a.assert_fields(invoice, license_at_issue="CC_BY_NC_ND", status="ISSUED", auto_waived=False)
    a.assert_invoice_amounts(
        invoice,
        raw_surcharge_cents=0,
        provisional_total_cents=94846,
        surcharge_relief_pct=0,
        total_due_cents=94846,
    )
    a.assert_journal_ledgers(
        fx.get_journal(world["journal"]["id"]), apc_receivable_cents=94846
    )


def test_relief_bracket_is_keyed_on_the_provisional_total():
    """Net plus raw surcharge selects the bracket, and nothing else does.

    PRD: "**Step two** forms `provisional_total_cents` as `net_apc_cents` plus `raw_surcharge_cents`, and keys the relief bracket on that provisional figure and on nothing else: `surcharge_relief_pct` is 20 when `provisional_total_cents` is at least 250000 cents, otherwise 10 when it is at least 150000 cents, otherwise 0."

    Design: Difficulty/combinatorial_formula/surcharge_relief_bracket_not_re_derived_from_final_total
    """
    world = fx.setup_surcharge_bracket_invoice_world()

    invoice = fx.issue_invoice(
        world["manuscript"]["id"], page_charge_count=8, color_figure_count=0
    )

    a.assert_invoice_amounts(
        invoice,
        net_apc_cents=120000,
        waiver_pct=0,
        institutional_pct=0,
        raw_surcharge_cents=32000,
        provisional_total_cents=152000,
        surcharge_relief_pct=10,
    )


def test_relief_bracket_is_not_re_derived_from_the_final_total():
    """The relief pulls the total under its own bracket floor, and the bracket still stands.

    PRD: "The evaluation order is pinned to exactly one pass: even when the relief pulls `total_due_cents` back below the bracket floor that triggered it, the bracket is **never** re-derived from `total_due_cents`."

    Design: Difficulty/combinatorial_formula/surcharge_relief_bracket_not_re_derived_from_final_total
    """
    world = fx.setup_surcharge_bracket_invoice_world()

    invoice = fx.issue_invoice(
        world["manuscript"]["id"], page_charge_count=8, color_figure_count=0
    )

    assert invoice["total_due_cents"] == 148800
    assert invoice["total_due_cents"] < 150000, (
        "the final total falls below the 150000-cent bracket floor"
    )
    assert invoice["surcharge_relief_pct"] == 10, (
        "the bracket stays where the provisional total put it"
    )


def test_relief_reduces_the_surcharge_alone():
    """The net charge is untouched by the relief; only the surcharge shrinks.

    PRD: "**Step three** applies the relief to the surcharge alone: `surcharge_cents` is `raw_surcharge_cents` less the result of `raw_surcharge_cents` multiplied by `surcharge_relief_pct` divided by 100, rounded half up to a whole cent — the single rounding in this whole computation."

    Design: Difficulty/combinatorial_formula/surcharge_relief_bracket_not_re_derived_from_final_total
    """
    world = fx.setup_surcharge_bracket_invoice_world()

    invoice = fx.issue_invoice(
        world["manuscript"]["id"], page_charge_count=8, color_figure_count=0
    )

    a.assert_invoice_amounts(
        invoice, net_apc_cents=120000, surcharge_cents=28800, total_due_cents=148800
    )
    a.assert_journal_ledgers(
        fx.get_journal(world["journal"]["id"]), apc_receivable_cents=148800
    )
