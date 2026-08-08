"""Cost-segregation depreciation: with-bonus vs without-bonus, and pinned per-component rounding.

Translates queue A (dual_variant_calc cost-seg, combinatorial per-component rounding) instances.
"""
from test_helpers import validate_success, get_success_data, TEST_USERS, fixtures

SM = TEST_USERS["study_manager_headers"]

# Three ALLOCATED components used by the dual-variant instance: year 2024 (bonus 60%).
DUAL_COMPS = [
    ("5yr", "FIVE_YEAR", 10000000),
    ("15yr", "FIFTEEN_YEAR", 20000000),
    ("39yr", "THIRTY_NINE_YEAR", 70000000),
]


def _dual_ctx(api):
    ctx = fixtures.setup_cost_seg_engineering(
        api, marginal_tax_rate=0.21, tax_year=2024,
        placed_in_service_date="2024-03-01T00:00:00.000Z",
        scope_overrides={"fee_type": "PERCENT", "fee_percent_bps": 2500})
    fixtures.add_allocated_components(api, ctx, DUAL_COMPS)
    return ctx


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/cost_seg_with_bonus_vs_without_bonus
# ---------------------------------------------------------------------------
def test_cost_seg_with_and_without_bonus_on_submit(api):
    """PRD §3.3: "The rounded per-component figures are summed to yield
    first_year_depreciation_cents." and "the rounded per-component figures are then summed to
    yield first_year_depreciation_no_bonus_cents."
    PRD §3.3: "The study's estimated_tax_benefit_cents for a cost-segregation study is the
    with-bonus first_year_depreciation_cents multiplied by the client's marginal_tax_rate,
    rounded to whole cents."

    2024 bonus 60%: with-bonus = 6800000+12400000+1794800 = 20994800; without-bonus =
    2000000+1000000+1794800 = 4794800; benefit = round(20994800 * 0.21) = 4408908.

    Design: Difficulty/dual_variant_calc/cost_seg_with_bonus_vs_without_bonus
    """
    ctx = _dual_ctx(api)
    data = validate_success(api.submit_review(ctx["study_id"], ctx["eng_headers"]), 200)
    assert data["first_year_depreciation_cents"] == 20994800
    assert data["first_year_depreciation_no_bonus_cents"] == 4794800
    assert data["estimated_tax_benefit_cents"] == 4408908


def test_cost_seg_benefit_recomputed_on_read(api):
    """PRD §3.3: "The study's depreciation figures are recomputed over its ALLOCATED
    components (components in PROPOSED or EXCLUDED are ignored) whenever the study is
    submitted for review and again whenever the study is read."

    The same figures must appear on a GET after submit-review.

    Design: Difficulty/dual_variant_calc/cost_seg_with_bonus_vs_without_bonus
    """
    ctx = _dual_ctx(api)
    fixtures.submit(api, ctx)
    data = validate_success(api.get_study(ctx["study_id"], SM), 200)
    assert data["first_year_depreciation_cents"] == 20994800
    assert data["first_year_depreciation_no_bonus_cents"] == 4794800
    assert data["estimated_tax_benefit_cents"] == 4408908


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/cost_seg_per_component_rounding_then_sum
# ---------------------------------------------------------------------------
def _rounding_ctx(api):
    ctx = fixtures.setup_cost_seg_engineering(
        api, marginal_tax_rate=0.21, tax_year=2024,
        placed_in_service_date="2024-06-01T00:00:00.000Z",
        scope_overrides={"fee_type": "FIXED", "fee_fixed_amount_cents": 100000})
    fixtures.add_allocated_components(api, ctx, [
        ("a", "FIFTEEN_YEAR", 10),
        ("b", "FIFTEEN_YEAR", 10),
    ])
    return ctx


def test_per_component_rounding_then_sum_on_submit(api):
    """PRD §2.5: "when a study's first-year depreciation is summed across its components, each
    component's first-year figure is rounded to whole cents individually and only then are the
    rounded per-component figures added together. The system must never sum the raw un-rounded
    products and round once at the end; per-component rounding precedes summation."

    Two FIFTEEN_YEAR components of 10 cents at rate 0.05: round(0.5)+round(0.5)=1+1=2, not
    round(20*0.05)=1.

    Design: Difficulty/combinatorial_formula/cost_seg_per_component_rounding_then_sum
    """
    ctx = _rounding_ctx(api)
    data = validate_success(api.submit_review(ctx["study_id"], ctx["eng_headers"]), 200)
    assert data["first_year_depreciation_no_bonus_cents"] == 2


def test_per_component_rounding_then_sum_on_read(api):
    """PRD §2.5: "The system must never sum the raw un-rounded products and round once at the
    end; per-component rounding precedes summation."
    PRD §3.3: "... recomputed ... again whenever the study is read."

    The pinned per-component-then-sum result (2) must also hold on a GET recompute.

    Design: Difficulty/combinatorial_formula/cost_seg_per_component_rounding_then_sum
    """
    ctx = _rounding_ctx(api)
    fixtures.submit(api, ctx)
    data = validate_success(api.get_study(ctx["study_id"], SM), 200)
    assert data["first_year_depreciation_no_bonus_cents"] == 2
