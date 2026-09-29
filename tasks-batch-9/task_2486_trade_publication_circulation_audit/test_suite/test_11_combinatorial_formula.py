"""Multi-step formulas whose evaluation order is pinned: credit rounding and the cap closed form."""

from test_helpers.assertions import assert_credit_buckets, assert_pct
from test_helpers.fixtures import (
    add_complete_rule_set,
    certify_statement,
    move_clock,
    open_statement,
    qualify_subscriber,
    read_contract,
    register_contract,
    register_publication,
    settle_guarantees,
)

PERIOD_START = "2026-07-01T00:00:00Z"
PERIOD_END = "2026-09-01T00:00:00Z"


def enrol(publication_id, company_name, subscription_class, copies, **extra):
    """Qualify one recipient of the given class at the default clock."""
    return qualify_subscriber(
        publication_id,
        signed_at="2026-07-01T00:00:00Z",
        captured_at="2026-07-15T00:00:00Z",
        company_name=company_name,
        subscription_class=subscription_class,
        copies=copies,
        **extra,
    )


def filed_statement_for(publication_id, expected_total):
    move_clock("2026-10-01T00:00:00Z")
    statement = open_statement(
        publication_id,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        basis="AS_OF_PERIOD_END",
    )
    assert statement["total_qualified_copies"] == expected_total
    filed = certify_statement(statement["id"])
    assert filed["declared_total_copies"] == expected_total
    return filed


def test_makegood_credit_rounds_per_insertion_before_multiplying():
    """Rounding per insertion first yields 4,808,796 cents, not 4,808,790.

    "at a gross rate of 850,000 cents per insertion, a shortfall of 31.43 percent,
    a tier factor of 1.50 and twelve insertions, the pinned order gives a
    per-insertion credit of 400,733 cents and a total of 4,808,796 cents, whereas
    rounding after the multiplication would give 4,808,790."

    Design: Difficulty/combinatorial_formula/makegood_credit_rounding_order_per_insertion_then_multiply
    """
    publication = register_publication(
        name="Rounding Order Monthly",
        industry_code="MANUFACTURING",
        controlled_cap_pct=25.00,
    )
    add_complete_rule_set(publication["id"])
    enrol(publication["id"], "Golf Paid Works", "PAID", 600, paid_amount_cents=48000)
    enrol(publication["id"], "Hotel Requested Works", "QUALIFIED_NON_PAID", 300)
    enrol(publication["id"], "India Directed Works", "CONTROLLED", 400)

    contract = register_contract(
        publication["id"],
        advertiser_name="Precision Rounding Media",
        insertion_count=12,
        gross_rate_cents_per_insertion=850000,
        guaranteed_rate_base=1750,
        shortfall_tolerance_pct=2.00,
    )
    assert contract["makegood_credit_pool_cents"] == 10200000

    filed = filed_statement_for(publication["id"], 1200)

    obligations = settle_guarantees(filed["id"])
    assert len(obligations) == 1
    obligation = obligations[0]
    assert obligation["shortfall_copies"] == 550
    assert_pct(obligation["shortfall_pct"], 31.43)
    assert_pct(obligation["tier_factor"], 1.50)
    assert obligation["per_insertion_credit_cents"] == 400733
    assert obligation["credit_cents"] == 4808796
    # The multiply-then-round order would have produced six cents less.
    assert obligation["credit_cents"] != 4808790
    # 4,808,796 cents buys five whole insertions at 850,000 each, remainder dropped.
    assert obligation["bonus_insertions"] == 5
    assert obligation["status"] == "PENDING"

    ledger = read_contract(contract["id"])
    assert_credit_buckets(
        ledger,
        pool=10200000,
        committed=4808796,
        waived=0,
        available=5391204,
    )


def test_makegood_credit_rounding_order_holds_at_the_middle_tier_boundary():
    """A per-insertion credit of 12,345.6 cents rounds up before the multiplication.

    "`per_insertion_credit_cents` is the contract's
    `gross_rate_cents_per_insertion` multiplied by `shortfall_pct` divided by one
    hundred, multiplied by `tier_factor`, and that product is rounded half up to a
    whole cent *first*; only then is `credit_cents` obtained by multiplying
    `per_insertion_credit_cents` by the contract's `insertion_count`."

    Design: Difficulty/combinatorial_formula/makegood_credit_rounding_order_per_insertion_then_multiply
    """
    publication = register_publication(
        name="Tier Boundary Monthly", industry_code="LOGISTICS"
    )
    add_complete_rule_set(publication["id"])
    enrol(publication["id"], "Juliet Paid Freight", "PAID", 900, paid_amount_cents=72000)

    contract = register_contract(
        publication["id"],
        advertiser_name="Midband Media",
        insertion_count=12,
        gross_rate_cents_per_insertion=123456,
        guaranteed_rate_base=1000,
        shortfall_tolerance_pct=2.00,
    )
    assert contract["makegood_credit_pool_cents"] == 1481472

    filed = filed_statement_for(publication["id"], 900)

    obligation = settle_guarantees(filed["id"])[0]
    assert obligation["shortfall_copies"] == 100
    # 100 of 1,000 is exactly 10.00 percent, the inclusive top of the middle band.
    assert_pct(obligation["shortfall_pct"], 10.00)
    assert_pct(obligation["tier_factor"], 1.00)
    # 123,456 cents at 10.00 percent is 12,345.6 cents, which rounds up to 12,346.
    assert obligation["per_insertion_credit_cents"] == 12346
    assert obligation["credit_cents"] == 148152
    # Multiplying first and rounding afterwards would have given 148,147.
    assert obligation["credit_cents"] != 148147
    assert obligation["bonus_insertions"] == 1

    ledger = read_contract(contract["id"])
    assert_credit_buckets(
        ledger, pool=1481472, committed=148152, waived=0, available=1333320
    )


def test_controlled_allowance_closed_form_binds_against_the_final_total():
    """The allowance comes from the core over one hundred minus the cap, not from the core alone.

    "Second, the controlled allowance is the core multiplied by
    `controlled_cap_pct`, divided by one hundred minus `controlled_cap_pct`, with
    the quotient truncated down to a whole number of copies."

    Design: Difficulty/combinatorial_formula/controlled_cap_allowance_closed_form_against_final_total
    """
    publication = register_publication(
        name="Closed Form Monthly",
        industry_code="MANUFACTURING",
        controlled_cap_pct=25.00,
    )
    add_complete_rule_set(publication["id"])
    enrol(publication["id"], "Kilo Paid Works", "PAID", 900, paid_amount_cents=72000)
    enrol(publication["id"], "Lima Directed Works", "CONTROLLED", 400)

    move_clock("2026-10-01T00:00:00Z")
    statement = open_statement(
        publication["id"],
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        basis="AS_OF_PERIOD_END",
    )
    assert statement["paid_copies"] == 900
    assert statement["qualified_non_paid_copies"] == 0
    # 900 * 25 / 75 is 300, not the naive 900 * 25 / 100 of 225.
    assert statement["controlled_copies_included"] == 300
    assert statement["controlled_copies_excess"] == 100
    assert statement["total_qualified_copies"] == 1200
    # The cap binds against the final total, which already contains the 300.
    assert statement["controlled_copies_included"] * 100 == (
        25 * statement["total_qualified_copies"]
    )


def test_controlled_allowance_truncates_the_remainder_into_excess():
    """A fractional allowance is truncated, so the remainder copy always sits outside.

    "Truncating the allowance rather than rounding it means any remainder copy
    always lands in `controlled_copies_excess`."

    Design: Difficulty/combinatorial_formula/controlled_cap_allowance_closed_form_against_final_total
    """
    binding = register_publication(
        name="Truncated Allowance Monthly",
        industry_code="MANUFACTURING",
        controlled_cap_pct=40.00,
    )
    add_complete_rule_set(binding["id"])
    enrol(binding["id"], "Mike Paid Works", "PAID", 1000, paid_amount_cents=80000)
    enrol(binding["id"], "November Directed Works", "CONTROLLED", 700)

    slack = register_publication(
        name="Slack Allowance Monthly",
        industry_code="MANUFACTURING",
        controlled_cap_pct=40.00,
    )
    add_complete_rule_set(slack["id"])
    enrol(slack["id"], "Oscar Paid Works", "PAID", 1000, paid_amount_cents=80000)
    enrol(slack["id"], "Papa Directed Works", "CONTROLLED", 500)

    move_clock("2026-10-01T00:00:00Z")
    capped = open_statement(
        binding["id"],
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        basis="AS_OF_PERIOD_END",
    )
    # 1000 * 40 / 60 is 666.66..., truncated to 666 rather than rounded to 667.
    assert capped["controlled_copies_included"] == 666
    assert capped["controlled_copies_excess"] == 34
    assert capped["total_qualified_copies"] == 1666

    uncapped = open_statement(
        slack["id"],
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        basis="AS_OF_PERIOD_END",
    )
    # The allowance is still 666, but the raw figure is smaller, so it does not bind.
    assert uncapped["controlled_copies_included"] == 500
    assert uncapped["controlled_copies_excess"] == 0
    assert uncapped["total_qualified_copies"] == 1500
