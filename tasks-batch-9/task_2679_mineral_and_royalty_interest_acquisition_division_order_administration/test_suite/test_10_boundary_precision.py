"""Two inclusive boundaries: a fully consumed basket and an empty PAID set."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers.assertions import assert_money
from test_helpers.test_users import ADMIN_HEADERS

BASKET_EXACT_DEFECTS = [
    {"defect_type": "TAX_SALE_GAP", "affected_nma": 10.0000, "description": "Tax sale gap over ten net acres"},
    {"defect_type": "MISSING_HEIR", "affected_nma": 7.5000, "description": "One unlocated heir of the 1988 estate"},
]


def test_net_defect_total_equal_to_the_basket_moves_the_price_not_at_all(api):
    """9500.00 + 6500.00 lands exactly on a 16000.00 basket, so nothing is deducted.

    PRD: "If the running total is less than or equal to the agreement's
    `aggregate_defect_basket`, the adjustment is exactly 0.00 — the boundary is
    inclusive, so a total equal to the basket produces no price movement at all."

    Design: Difficulty/boundary_precision_check/defect_basket_exact_equality_produces_zero_adjustment
    """
    world = fx.psa_with_defects_ready(api, BASKET_EXACT_DEFECTS)
    assert_money(world["defects"][0]["net_defect_value"], "9500.00", "first net_defect_value")
    assert_money(world["defects"][1]["net_defect_value"], "6500.00", "second net_defect_value")

    psa = fx.close_curative(api, world["psa"]["id"])

    assert_money(psa["defect_adjustment_amount"], "0.00", "defect_adjustment_amount")
    assert_money(psa["adjusted_purchase_price"], "48000.00", "adjusted_purchase_price")
    assert psa["curative_status"] == "CURATIVE_CLOSED"
    assert psa["psa_status"] == "EXECUTED"


def test_consuming_the_whole_basket_does_not_cure_the_defects(api):
    """The swept defects stay UNCURED and the interest stays UNDER_PSA.

    PRD: "Defects that had already reached `CURED` or `WAIVED` are untouched and
    stay excluded — that exclusion is exactly what makes the cure loop
    economically worth running."

    Design: Difficulty/boundary_precision_check/defect_basket_exact_equality_produces_zero_adjustment
    """
    world = fx.psa_with_defects_ready(api, BASKET_EXACT_DEFECTS)

    fx.close_curative(api, world["psa"]["id"])

    for defect in world["defects"]:
        assert fx.read_defect(api, defect["id"])["defect_status"] == "UNCURED"
    assert fx.read_interest(api, world["interest"]["id"])["interest_status"] == "UNDER_PSA"


def test_tax_statement_over_an_empty_paid_set_returns_zeroes(api):
    """A held line is outside the source set, so every figure reads 0.00.

    PRD: "Its source set is every revenue line whose `check_status` is `PAID`,
    belonging to any division order whose `royalty_owner_id` is this owner, whose
    `production_month` falls in the twelve months from the January of the requested
    year through the December of that year, both ends inclusive."

    Design: Difficulty/boundary_precision_check/tax_statement_with_no_paid_details_returns_zeroed_statement
    """
    world = fx.variance_held_ready(api)
    assert world["detail"]["check_status"] == "VARIANCE_HELD"

    statement = validate_success(
        api.get_tax_statement(world["owner"]["id"], ADMIN_HEADERS, {"tax_year": 2026})
    )

    assert statement["detail_count"] == 0
    assert_money(statement["gross_royalty"], "0.00", "gross_royalty")
    assert_money(statement["severance_tax_withheld"], "0.00", "severance_tax_withheld")
    assert_money(statement["taxable_before_depletion"], "0.00", "taxable_before_depletion")
    assert_money(statement["depletion_allowance"], "0.00", "depletion_allowance")
    assert_money(statement["net_taxable"], "0.00", "net_taxable")


def test_zeroed_tax_statement_still_echoes_its_owner_and_year(api):
    """The computed read succeeds and identifies what it was computed for.

    PRD: "It takes a single `tax_year` and returns eight figures: the
    `royalty_owner_id` it was computed for, the `tax_year` echoed back,
    `gross_royalty`, `severance_tax_withheld`, `taxable_before_depletion`,
    `depletion_allowance`, `net_taxable` and `detail_count`."

    Design: Difficulty/boundary_precision_check/tax_statement_with_no_paid_details_returns_zeroed_statement
    """
    world = fx.variance_held_ready(api)

    statement = validate_success(
        api.get_tax_statement(world["owner"]["id"], ADMIN_HEADERS, {"tax_year": 2026})
    )

    assert statement["royalty_owner_id"] == world["owner"]["id"]
    assert statement["tax_year"] == 2026
