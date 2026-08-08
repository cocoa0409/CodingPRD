"""R&D credit: ASC vs REGULAR methods, ASC conditional branch, contract-research cap, startup rate.

Translates queue A (dual_variant_calc R&D, combinatorial ASC branch) and queue B
(contract-research cap, ASC startup rate) instances.
"""
from test_helpers import validate_success, get_success_data, TEST_USERS, fixtures
import test_helpers.factories as f

SM = TEST_USERS["study_manager_headers"]

# QUALIFIED lines: WAGES 4000000 + SUPPLIES 2000000 + CONTRACT_RESEARCH capped 1950000 = 7950000.
QRE_LINES = [
    ("WAGES", 5000000, 0.80),
    ("SUPPLIES", 2000000, 1.00),
    ("CONTRACT_RESEARCH", 3000000, 0.80),
]

ASC_SCOPE = {
    "fee_fixed_amount_cents": 500000,
    "fixed_base_pct": 0.03,
    "avg_annual_gross_receipts_cents": 100000000,
    "prior_qre_year1_cents": 6000000,
    "prior_qre_year2_cents": 4000000,
    "prior_qre_year3_cents": 2000000,
}


def _asc_ctx(api):
    ctx = fixtures.setup_rd_engineering(api, credit_method="ASC", tax_year=2024,
                                        scope_overrides=ASC_SCOPE)
    fixtures.add_qualified_qre(api, ctx, QRE_LINES)
    return ctx


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/rd_credit_asc_vs_regular
# ---------------------------------------------------------------------------
def test_rd_credit_asc_and_regular_on_submit(api):
    """PRD §3.4: "When that average is greater than 0, rd_credit_asc_cents is 14 percent of the
    current-year total minus half of the average prior amount, rounded to whole cents, and
    floored at 0 so it is never negative."
    PRD §3.4: "Then rd_credit_regular_cents is 20 percent of the current-year total minus that
    base amount, rounded to whole cents, and floored at 0."
    PRD §3.4: "The study's estimated_tax_benefit_cents for an R&D study is rd_credit_asc_cents
    when the study's credit_method is ASC and rd_credit_regular_cents when it is REGULAR."

    current_qre=7950000, avg_prior=4000000 → ASC=round(0.14*(7950000-2000000))=833000;
    base=max(round(0.5*7950000),round(0.03*100000000))=3975000 → REGULAR=round(0.20*3975000)=795000.

    Design: Difficulty/dual_variant_calc/rd_credit_asc_vs_regular
    """
    ctx = _asc_ctx(api)
    data = validate_success(api.submit_review(ctx["study_id"], ctx["eng_headers"]), 200)
    assert data["rd_credit_asc_cents"] == 833000
    assert data["rd_credit_regular_cents"] == 795000
    assert data["estimated_tax_benefit_cents"] == 833000


def test_rd_credit_both_methods_recomputed_on_read(api):
    """PRD §3.4: "When the study is submitted for review, and again whenever it is read, the
    credit is recomputed over the study's QUALIFIED lines."

    Both method figures must appear on a GET after submit-review.

    Design: Difficulty/dual_variant_calc/rd_credit_asc_vs_regular
    """
    ctx = _asc_ctx(api)
    fixtures.submit(api, ctx)
    data = validate_success(api.get_study(ctx["study_id"], SM), 200)
    assert data["rd_credit_asc_cents"] == 833000
    assert data["rd_credit_regular_cents"] == 795000


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/rd_asc_three_input_conditional_branch
# ---------------------------------------------------------------------------
def test_asc_positive_avg_prior_branch_on_submit(api):
    """PRD §3.4: "the three-year average prior qualified research is the exact average of
    prior_qre_year1_cents, prior_qre_year2_cents, and prior_qre_year3_cents — their sum
    divided by three, without pre-rounding. When that average is greater than 0,
    rd_credit_asc_cents is 14 percent of the current-year total minus half of the average
    prior amount, rounded to whole cents, and floored at 0 so it is never negative."

    avg_prior=(6000000+4000000+2000000)/3=4000000>0 → 0.14*(7950000-2000000)=833000.

    Design: Difficulty/combinatorial_formula/rd_asc_three_input_conditional_branch
    """
    ctx = _asc_ctx(api)
    data = validate_success(api.submit_review(ctx["study_id"], ctx["eng_headers"]), 200)
    assert data["rd_credit_asc_cents"] == 833000


def test_asc_positive_avg_prior_branch_on_read(api):
    """PRD §3.4: "When that average is greater than 0, rd_credit_asc_cents is 14 percent of the
    current-year total minus half of the average prior amount, rounded to whole cents, and
    floored at 0 so it is never negative."
    PRD §3.4: "... and again whenever it is read, the credit is recomputed ..."

    The positive-avg_prior branch result (833000) must also hold on a GET recompute.

    Design: Difficulty/combinatorial_formula/rd_asc_three_input_conditional_branch
    """
    ctx = _asc_ctx(api)
    fixtures.submit(api, ctx)
    data = validate_success(api.get_study(ctx["study_id"], SM), 200)
    assert data["rd_credit_asc_cents"] == 833000


# ---------------------------------------------------------------------------
# Corner/calculations/contract_research_qualified_amount_capped_at_65
# ---------------------------------------------------------------------------
def test_contract_research_qualified_amount_capped_at_65(api):
    """PRD §3.4: "for a CONTRACT_RESEARCH line, the effective percentage is the smaller of
    qualified_percent and the contract-research cap of 0.65, so no more than sixty-five percent
    of a contract-research expense can ever count as qualified."

    gross 3000000 at 0.80 is capped to 0.65 → round(3000000*0.65)=1950000.

    Design: Corner/calculations/contract_research_qualified_amount_capped_at_65
    """
    ctx = fixtures.setup_rd_engineering(api, credit_method="ASC", tax_year=2024)
    q = get_success_data(api.add_qre_line_item(
        ctx["study_id"], f.qre_line_payload("CONTRACT_RESEARCH", 3000000, 0.80), ctx["eng_headers"]))
    data = validate_success(api.qualify_qre(q["id"], ctx["eng_headers"]), 200)
    assert data["qualified_amount_cents"] == 1950000
    assert data["status"] == "QUALIFIED"


# ---------------------------------------------------------------------------
# Corner/calculations/asc_startup_rate_when_no_prior_qre
# ---------------------------------------------------------------------------
def test_asc_startup_rate_when_no_prior_qre(api):
    """PRD §3.4: "When the average prior amount is 0, the study is treated as a startup and
    rd_credit_asc_cents is 6 percent of the current-year total, rounded to whole cents."

    priors 0/0/0 → avg_prior 0 → round(0.06*7950000)=477000.

    Design: Corner/calculations/asc_startup_rate_when_no_prior_qre
    """
    ctx = fixtures.setup_rd_engineering(
        api, credit_method="ASC", tax_year=2024,
        scope_overrides={"prior_qre_year1_cents": 0, "prior_qre_year2_cents": 0,
                         "prior_qre_year3_cents": 0})
    fixtures.add_qualified_qre(api, ctx, QRE_LINES)
    data = validate_success(api.submit_review(ctx["study_id"], ctx["eng_headers"]), 200)
    assert data["rd_credit_asc_cents"] == 477000
