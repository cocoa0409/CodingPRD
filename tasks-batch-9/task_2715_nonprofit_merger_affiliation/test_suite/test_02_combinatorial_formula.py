"""Multi-step derived figures whose evaluation order is part of the contract.

PRD 2.6 states that "Rounding order is itself part of the contract wherever the
specification pins it. 3.2 pins the order for combined monthly expense, and 3.7
pins the order for the attorney-general fee tier; implementations that reorder
those steps will produce off-by-one-cent and off-by-one-tier results."
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    PLATFORM_ADMIN,
    TRUST_COUNSEL,
    make_strategy_officer_headers,
)


def _regulatory_review_deal(api, unrestricted_transfer_value_cents):
    """Walk a CA/CA deal to REGULATORY_REVIEW with a pinned unrestricted transfer value."""
    ctx = fx.setup_deal_structure_selected(
        api, unrestricted_transfer_value_cents=unrestricted_transfer_value_cents
    )
    ctx = fx.setup_deal_board_approval(api, ctx)
    ctx = fx.setup_deal_regulatory_review(api, ctx)
    assert ctx["deal"]["status"] == "REGULATORY_REVIEW"
    assert ctx["deal"]["ag_review_required"] is True
    return ctx


def _file(api, ctx, filing_type, legal_costs_cents):
    return validate_success(
        api.create_ag_filing(
            f.ag_filing_payload(
                ctx["deal"]["id"],
                state_code="CA",
                filing_type=filing_type,
                legal_costs_cents=legal_costs_cents,
            ),
            TRUST_COUNSEL,
        ),
        201,
    )


def test_monthly_expense_is_rounded_per_organization_at_registration(api):
    """Each organization's monthly expense is derived and stored before any deal sums it.

    PRD 3.1: "monthly_expense_cents is the organization's annual operating expense
    divided by twelve and rounded half up to a whole cent - a per-organization
    figure that is deliberately computed and stored before any deal ever sums it."
    An annual expense of 100000002 cents divides to exactly 8333333.5 cents, so the
    round-half-up step is decisive and each party stores 8333334.

    Design: Difficulty/combinatorial_formula/reserve_months_requires_per_organization_rounding_before_summation
    """
    ctx = fx.setup_two_orgs(api)

    a.assert_money_equals(
        ctx["org_a"]["monthly_expense_cents"], 8333334, "org_a.monthly_expense_cents"
    )
    a.assert_money_equals(
        ctx["org_b"]["monthly_expense_cents"], 8333334, "org_b.monthly_expense_cents"
    )
    for key in ("org_a", "org_b"):
        row = validate_success(api.get_organization(ctx[key]["id"], PLATFORM_ADMIN))
        a.assert_money_equals(
            row["monthly_expense_cents"], 8333334, f"{key}.monthly_expense_cents on read"
        )


def test_combined_monthly_expense_sums_two_already_rounded_figures(api):
    """The combined monthly expense adds the two rounded figures rather than dividing once.

    PRD 3.2: "each organization's annual expense is divided by twelve and rounded
    half up to whole cents first, and only then are the two rounded figures summed.
    Adding the two annual expenses together and dividing the total by twelve once is
    a different order that can land one cent lower ... the
    per-organization-then-sum order is the only sanctioned one." Two parties at
    100000002 cents annual therefore give 8333334 + 8333334 = 16666668, never the
    16666667 that summing first would produce.

    Design: Difficulty/combinatorial_formula/reserve_months_requires_per_organization_rounding_before_summation
    """
    ctx = fx.setup_deal_exploratory(api)
    scr = validate_success(
        api.create_alignment_assessment(
            f.alignment_assessment_payload(ctx["deal"]["id"], "SCREENING"),
            make_strategy_officer_headers(ctx["org_a"]["id"]),
        ),
        201,
    )

    a.assert_money_equals(
        scr["combined_monthly_expense_cents"], 16666668, "combined_monthly_expense_cents"
    )
    assert scr["combined_monthly_expense_cents"] != 16666667, (
        "summing the annual expenses and dividing once lands one cent lower"
    )
    a.assert_money_equals(
        scr["available_unrestricted_cents"], 99916670, "available_unrestricted_cents"
    )


def test_the_one_cent_of_rounding_order_moves_the_sustainability_tier(api):
    """The one-cent ordering difference crosses a reserve tier and changes the composite score.

    PRD 3.2: reserve_months is "available_unrestricted_cents divided by
    combined_monthly_expense_cents, rounded half up to two decimal places", and the
    sustainability component is a step function where "at least six months earns
    30.00 points, at least three but under six earns 20.00". Against the sanctioned
    16666668-cent denominator, 99916670 cents of available assets give 5.99 months
    and 20.00 points, so with 40.00 mission points for identical mission codes and
    0.00 overlap points for a deal with no programs the composite_score is 60.00 and
    composite_rating is MODERATE - not the 6.00 months, 30.00 points and 70.00
    score that the reordered denominator would produce.

    Design: Difficulty/combinatorial_formula/reserve_months_requires_per_organization_rounding_before_summation
    """
    ctx = fx.setup_deal_exploratory(api)
    scr = validate_success(
        api.create_alignment_assessment(
            f.alignment_assessment_payload(ctx["deal"]["id"], "SCREENING"),
            make_strategy_officer_headers(ctx["org_a"]["id"]),
        ),
        201,
    )

    a.assert_decimal_equals(scr["reserve_months"], 5.99, 2, "reserve_months")
    assert scr["reserve_months"] != 6.00
    a.assert_decimal_equals(scr["sustainability_points"], 20.00, 2, "sustainability_points")
    a.assert_decimal_equals(scr["mission_alignment_points"], 40.00, 2, "mission_alignment_points")
    a.assert_decimal_equals(scr["program_overlap_points"], 0.00, 2, "program_overlap_points")
    a.assert_decimal_equals(scr["composite_score"], 60.00, 2, "composite_score")
    a.assert_field(scr, "composite_rating", "MODERATE")


def test_fee_tier_is_read_from_the_fee_exclusive_provisional_total(api):
    """The filing fee tier is selected from the provisional total that excludes the fee.

    PRD 3.7: "Step one computes provisional_consideration_cents, the fee-exclusive
    provisional total: transferred_charitable_asset_value_cents plus
    legal_costs_cents. Step two selects the tier by reading only that provisional
    total: ... at one million dollars or above but below ten million dollars it is
    one thousand five hundred dollars ... Step three folds the fee in:
    closing_costs_cents is legal_costs_cents plus ag_filing_fee_cents, and
    total_consideration_cents is transferred_charitable_asset_value_cents plus
    closing_costs_cents." A recited asset value of 974999950 with 25000000 of legal
    costs gives a provisional total of 999999950 - below the ten-million-dollar
    ceiling - so the fee is 150000, closing costs are 25150000 and the total
    consideration is 1000149950 even though that final total sits above the
    ceiling. Because the recited value is at least five million dollars the
    required type is APPROVAL_PETITION, whose statutory period starts at forty-five
    days with no surcharge for a MERGER carrying no judicial basis.

    Design: Difficulty/combinatorial_formula/ag_filing_fee_tier_selected_from_fee_exclusive_provisional_total
    """
    ctx = _regulatory_review_deal(api, 974999950)
    filing = _file(api, ctx, "APPROVAL_PETITION", 25000000)

    a.assert_money_equals(
        filing["transferred_charitable_asset_value_cents"],
        974999950,
        "transferred_charitable_asset_value_cents",
    )
    a.assert_money_equals(
        filing["provisional_consideration_cents"], 999999950, "provisional_consideration_cents"
    )
    a.assert_money_equals(filing["ag_filing_fee_cents"], 150000, "ag_filing_fee_cents")
    assert filing["ag_filing_fee_cents"] != 500000, (
        "selecting the tier from the fee-inclusive total would charge the top tier"
    )
    a.assert_money_equals(filing["closing_costs_cents"], 25150000, "closing_costs_cents")
    a.assert_money_equals(
        filing["total_consideration_cents"], 1000149950, "total_consideration_cents"
    )
    a.assert_field(filing, "statutory_waiting_days", 45)
    a.assert_field(filing, "status", "SUBMITTED")
    a.assert_field(filing, "submitted_at", "2026-08-01T00:00:00.000Z")
    a.assert_field(filing, "review_deadline_at", "2026-09-15T00:00:00.000Z")
    a.assert_field(filing, "judicial_basis_present", False)


def test_a_provisional_total_landing_on_the_ceiling_falls_into_the_higher_tier(api):
    """A provisional total exactly on a tier ceiling is charged the higher tier.

    PRD 3.7: "Both tier comparisons are strictly less-than against their ceilings,
    so a provisional total landing exactly on a ceiling falls into the higher tier."
    A recited asset value of 974999950 with 25000050 of legal costs makes the
    fee-exclusive provisional total exactly one billion cents - ten million dollars
    - so the fee is the top-tier five thousand dollars, closing costs are 25500050
    and the total consideration is 1000500000.

    Design: Difficulty/combinatorial_formula/ag_filing_fee_tier_selected_from_fee_exclusive_provisional_total
    """
    ctx = _regulatory_review_deal(api, 974999950)
    filing = _file(api, ctx, "APPROVAL_PETITION", 25000050)

    a.assert_money_equals(
        filing["provisional_consideration_cents"], 1000000000, "provisional_consideration_cents"
    )
    a.assert_money_equals(filing["ag_filing_fee_cents"], 500000, "ag_filing_fee_cents")
    a.assert_money_equals(filing["closing_costs_cents"], 25500050, "closing_costs_cents")
    a.assert_money_equals(
        filing["total_consideration_cents"], 1000500000, "total_consideration_cents"
    )


def test_a_provisional_total_below_one_million_dollars_takes_the_lowest_tier(api):
    """A provisional total below one million dollars is charged the lowest fee tier.

    PRD 3.7: "below one million dollars the ag_filing_fee_cents is two hundred fifty
    dollars", and the required filing type is NOTICE where the recited asset value
    is under five million dollars and no contributing transferred fund is a
    permanent endowment. A recited value of 90000000 with 9999999 of legal costs
    gives a provisional total of 99999999 - one cent below the one-million-dollar
    ceiling - so the fee is 25000, closing costs are 10024999, the total
    consideration is 100024999 and the notice's statutory period is twenty days.

    Design: Difficulty/combinatorial_formula/ag_filing_fee_tier_selected_from_fee_exclusive_provisional_total
    """
    ctx = _regulatory_review_deal(api, 90000000)
    filing = _file(api, ctx, "NOTICE", 9999999)

    a.assert_money_equals(
        filing["provisional_consideration_cents"], 99999999, "provisional_consideration_cents"
    )
    a.assert_money_equals(filing["ag_filing_fee_cents"], 25000, "ag_filing_fee_cents")
    a.assert_money_equals(filing["closing_costs_cents"], 10024999, "closing_costs_cents")
    a.assert_money_equals(
        filing["total_consideration_cents"], 100024999, "total_consideration_cents"
    )
    a.assert_field(filing, "statutory_waiting_days", 20)
    a.assert_field(filing, "review_deadline_at", "2026-08-21T00:00:00.000Z")
