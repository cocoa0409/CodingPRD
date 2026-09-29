"""The five-step liability rollup: penalty tiers, interest and the small-balance waiver."""
from test_helpers import (
    liability_preview,
    set_clock_date,
    setup_audit_with_findings,
    setup_draft_assessment,
)

SCOPE_START = "2026-01-01"
SCOPE_END = "2026-06-30"
LATER_CLOCK_DAY = "2026-07-30"

# 16 cents of consumable purchase price is exactly 1 cent of use tax at 625 bp.
PRICE_FOR_4762_CENTS = 76_192
PRICE_FOR_4688_CENTS = 75_000
PRICE_FOR_1_000_000_CENTS = 16_000_000
ONE_CENT_OF_TAX = 16


def _purchase(price_cents):
    return {
        "invoice_date": SCOPE_START,
        "purchase_price_cents": price_cents,
        "asset_class": "CONSUMABLE",
    }


def _drafted_on(prices, draft_clock_day=None):
    """A drafted notice whose whole deficiency is the listed untaxed purchases."""
    return setup_draft_assessment(
        draft_clock_day=draft_clock_day,
        purchase_specs=[_purchase(price) for price in prices],
    )


def test_a_provisional_total_of_exactly_five_thousand_cents_is_waived():
    """The threshold is inclusive, so the notice at exactly 5,000 cents loses its penalty.

    PRD 3.6: "If that provisional total is less than or equal to 5,000 cents — the
    comparison is inclusive, so a provisional total of exactly 5,000 cents is waived
    — then `penalty_waived_small_balance` becomes true, `penalty_cents` is set to 0,
    and `interest_cents` is recomputed from scratch on the bare tax:
    `tax_deficiency_cents` multiplied by 800 basis points, multiplied by
    `interest_days`, divided by the product of 10,000 and 365, rounded half up."

    Design: Difficulty/boundary_precision_check/small_balance_threshold_inclusive_at_exactly_5000
    """
    assessment = _drafted_on([PRICE_FOR_4762_CENTS])["assessment"]

    assert assessment["tax_deficiency_cents"] == 4_762
    assert assessment["penalty_rate_bp"] == 500
    assert assessment["interest_days"] == 0
    # 4,762 tax plus a 238-cent penalty plus no interest is exactly the threshold.
    assert assessment["provisional_total_due_cents"] == 5_000
    assert assessment["penalty_waived_small_balance"] is True
    assert assessment["penalty_cents"] == 0
    assert assessment["interest_cents"] == 0
    assert assessment["total_due_cents"] == 4_762
    assert assessment["balance_due_cents"] == 4_762


def test_one_cent_over_the_threshold_keeps_the_whole_penalty():
    """A single extra cent of tax pushes the provisional total past the waiver.

    PRD 3.6: "If the provisional total exceeds 5,000 cents,
    `penalty_waived_small_balance` stays false and nothing is recomputed."

    Design: Difficulty/boundary_precision_check/small_balance_threshold_inclusive_at_exactly_5000
    """
    assessment = _drafted_on([PRICE_FOR_4762_CENTS, ONE_CENT_OF_TAX])["assessment"]

    assert assessment["tax_deficiency_cents"] == 4_763
    assert assessment["penalty_rate_bp"] == 500
    assert assessment["penalty_cents"] == 238
    assert assessment["interest_days"] == 0
    assert assessment["provisional_total_due_cents"] == 5_001
    assert assessment["penalty_waived_small_balance"] is False
    assert assessment["total_due_cents"] == 5_001
    assert assessment["balance_due_cents"] == 5_001


def test_a_deficiency_of_exactly_one_million_cents_takes_the_lowest_rate():
    """Every tier threshold is strict, so the round million stays at 500 basis points.

    PRD 3.6: "Each threshold is strict, so a deficiency of exactly 1,000,000 cents
    takes the 500-point rate and a deficiency of 1,000,001 cents takes the
    1,000-point rate."

    Design: Difficulty/boundary_precision_check/penalty_tier_boundary_at_exactly_one_million_cents
    """
    assessment = _drafted_on([PRICE_FOR_1_000_000_CENTS])["assessment"]

    assert assessment["tax_deficiency_cents"] == 1_000_000
    assert assessment["penalty_rate_bp"] == 500
    assert assessment["penalty_cents"] == 50_000
    assert assessment["interest_days"] == 0
    assert assessment["interest_cents"] == 0
    assert assessment["total_due_cents"] == 1_050_000


def test_one_cent_past_the_million_doubles_the_negligence_rate():
    """The rate is an average rate on the whole deficiency, not a marginal one.

    PRD 3.6: "The rate is an average rate applied to the whole deficiency, not a
    marginal rate applied to slices of it."
    PRD 3.6: "The `penalty_cents` is then `tax_deficiency_cents` multiplied by
    `penalty_rate_bp`, divided by 10,000 and rounded half up."

    Design: Difficulty/boundary_precision_check/penalty_tier_boundary_at_exactly_one_million_cents
    """
    assessment = _drafted_on([PRICE_FOR_1_000_000_CENTS, ONE_CENT_OF_TAX])["assessment"]

    assert assessment["tax_deficiency_cents"] == 1_000_001
    assert assessment["penalty_rate_bp"] == 1_000
    # The whole deficiency is taxed at the higher rate, not just the last cent.
    assert assessment["penalty_cents"] == 100_000
    assert assessment["total_due_cents"] == 1_100_001


def test_waiving_the_penalty_recomputes_the_interest_on_the_bare_tax():
    """After the penalty goes, the interest that was charged on it goes too.

    PRD 3.6: "Forgetting to recompute the interest after zeroing the penalty is the
    classic error here."
    PRD 3.6: "The `interest_days` is the whole number of calendar days from the
    audit's `scope_period_end` to the current logical clock date, floored at zero —
    so a rollup run on the scope's last day, or earlier, carries zero interest days
    — plus the sum of `tolled_days` over the `DECIDED` appeal proceedings of prior
    assessments of the same audit, which is how time spent under protest on a
    vacated notice follows the audit onto its replacement."

    Design: Difficulty/combinatorial_formula/small_balance_waiver_recomputes_interest_on_bare_tax
    """
    assessment = _drafted_on(
        [PRICE_FOR_4688_CENTS], draft_clock_day=LATER_CLOCK_DAY
    )["assessment"]

    assert assessment["tax_deficiency_cents"] == 4_688
    assert assessment["penalty_rate_bp"] == 500
    assert assessment["interest_days"] == 30
    # 4,688 tax + 234 penalty + 32 interest on both of them.
    assert assessment["provisional_total_due_cents"] == 4_954
    assert assessment["penalty_waived_small_balance"] is True
    assert assessment["penalty_cents"] == 0
    # Interest on the bare tax alone, one cent less than interest on tax plus penalty.
    assert assessment["interest_cents"] == 31
    assert assessment["total_due_cents"] == 4_719
    assert assessment["balance_due_cents"] == 4_719


def test_the_stored_provisional_total_keeps_the_figure_the_threshold_tested():
    """The pre-waiver total survives on the notice beside the lower final total.

    PRD 3.6: "Note that `provisional_total_due_cents` is a stored field and keeps
    the pre-waiver figure the threshold was tested against; it is not overwritten by
    step five."
    PRD 3.6: "The small-balance test is emphatically not re-applied to this
    recomputed total, and a waiver once granted never un-waives itself even though
    removing the penalty may have dropped the total further below the threshold."

    Design: Difficulty/combinatorial_formula/small_balance_waiver_recomputes_interest_on_bare_tax
    """
    ctx = setup_audit_with_findings(purchase_specs=[_purchase(PRICE_FOR_4688_CENTS)])
    set_clock_date(LATER_CLOCK_DAY)

    preview = liability_preview(ctx["audit"]["id"])

    assert preview["projection_status"] == "CURRENT"
    assert preview["penalty_waived_small_balance"] is True
    assert preview["provisional_total_due_cents"] == 4_954
    assert preview["total_due_cents"] == 4_719
    assert preview["total_due_cents"] < preview["provisional_total_due_cents"]
    assert preview["interest_cents"] == 31
