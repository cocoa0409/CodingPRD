"""Cost estimation: provisional vs final variants, per-line rounding, finalize guards."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    scenario_developing_proposal, add_line_item, finalize,
    TEST_USERS,
)

REVIEWER = TEST_USERS["reviewer_headers"]


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / cost_estimate_provisional_vs_final_diverge
# ---------------------------------------------------------------------------

DIVERGE_LINES = [
    {"label": "Structure", "unit_cost_cents": 10000, "quantity": 3, "contingency_pct": 0.07},
    {"label": "Surfacing", "unit_cost_cents": 4999, "quantity": 2, "contingency_pct": 0.15},
]


def test_provisional_estimate_uses_as_entered_contingency_no_overhead(api):
    """PRD §3.4: "The provisional estimate applies each line's contingency exactly
    as entered and adds no overhead."
    PRD §3.4: "The line's own recorded `line_provisional_cents` is that gross amount
    multiplied by one plus the greater of its `contingency_pct` and zero, then rounded
    half up to whole cents."

    Design: Difficulty/dual_variant_calc/cost_estimate_provisional_vs_final_diverge
    """
    sc = scenario_developing_proposal(api)
    for li in DIVERGE_LINES:
        add_line_item(api, sc["pid"], **li)
    prop = validate_success(api.get_proposal(sc["pid"], REVIEWER))
    assert prop["provisional_estimate_cents"] == 43598, (
        f"provisional must be 43598 (32100 + 11498), got {prop['provisional_estimate_cents']}"
    )


def test_final_estimate_floors_contingency_then_overhead_diverges_from_provisional(api):
    """PRD §3.4: "each line's contingency is floored to a minimum of ten percent: the
    per-line amount is the line's gross multiplied by one plus the greater of the line's
    `contingency_pct` and 0.10, rounded half up to whole cents."
    PRD §3.4: "a single program overhead of five percent is applied to that subtotal —
    the subtotal multiplied by 1.05 — and that result is rounded half up to whole cents
    one final time."

    Design: Difficulty/dual_variant_calc/cost_estimate_provisional_vs_final_diverge
    """
    sc = scenario_developing_proposal(api)
    for li in DIVERGE_LINES:
        add_line_item(api, sc["pid"], **li)
    finalized = validate_success(api.finalize_cost(sc["pid"], REVIEWER))
    assert finalized["estimated_cost_cents"] == 46723, (
        f"final must be 46723 (subtotal 44498 * 1.05), got {finalized['estimated_cost_cents']}"
    )
    assert finalized["status"] == "COSTED"
    assert finalized["provisional_estimate_cents"] == 43598
    assert finalized["estimated_cost_cents"] != finalized["provisional_estimate_cents"], (
        "final and provisional must diverge here"
    )


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / cost_rounding_order_round_per_line_then_sum
# ---------------------------------------------------------------------------

def test_each_line_rounds_before_summing_provisional(api):
    """PRD §3.4: "The line's own recorded `line_provisional_cents` is that gross amount
    multiplied by one plus the greater of its `contingency_pct` and zero, then rounded
    half up to whole cents."

    Design: Difficulty/combinatorial_formula/cost_rounding_order_round_per_line_then_sum
    """
    sc = scenario_developing_proposal(api)
    li1 = validate_success(
        api.add_cost_line_item(sc["pid"], {"label": "l1", "unit_cost_cents": 333, "quantity": 1, "contingency_pct": 0.10}, REVIEWER),
        expected_status=201,
    )
    li2 = validate_success(
        api.add_cost_line_item(sc["pid"], {"label": "l2", "unit_cost_cents": 333, "quantity": 1, "contingency_pct": 0.10}, REVIEWER),
        expected_status=201,
    )
    assert li1["line_provisional_cents"] == 366, f"333*1.10=366.3 -> 366, got {li1['line_provisional_cents']}"
    assert li2["line_provisional_cents"] == 366


def test_provisional_is_sum_of_rounded_lines_not_rounded_sum(api):
    """PRD §3.4: "The proposal's `provisional_estimate_cents` is the sum of these per-line
    provisional amounts: the rounding is pinned per line, so each line is rounded first and
    only then are the rounded lines summed."

    Design: Difficulty/combinatorial_formula/cost_rounding_order_round_per_line_then_sum
    """
    sc = scenario_developing_proposal(api)
    add_line_item(api, sc["pid"], label="l1", unit_cost_cents=333, quantity=1, contingency_pct=0.10)
    add_line_item(api, sc["pid"], label="l2", unit_cost_cents=333, quantity=1, contingency_pct=0.10)
    prop = validate_success(api.get_proposal(sc["pid"], REVIEWER))
    # round-per-line-then-sum = 366 + 366 = 732 (NOT round(366.3+366.3)=733).
    assert prop["provisional_estimate_cents"] == 732, (
        f"expected 732 (366+366), got {prop['provisional_estimate_cents']}"
    )


# ---------------------------------------------------------------------------
# Corner: entities / corner_single_line_provisional_estimate_computed
# ---------------------------------------------------------------------------

def test_single_line_provisional_estimate_computed(api):
    """PRD §3.4: "The line's own recorded `line_provisional_cents` is that gross amount
    multiplied by one plus the greater of its `contingency_pct` and zero, then rounded half
    up to whole cents."

    Design: Corner/entities/corner_single_line_provisional_estimate_computed
    """
    sc = scenario_developing_proposal(api)
    li = validate_success(
        api.add_cost_line_item(sc["pid"], {"label": "x", "unit_cost_cents": 40000, "quantity": 1, "contingency_pct": 0.20}, REVIEWER),
        expected_status=201,
    )
    assert li["line_provisional_cents"] == 48000, f"40000*1.20=48000, got {li['line_provisional_cents']}"
    prop = validate_success(api.get_proposal(sc["pid"], REVIEWER))
    assert prop["provisional_estimate_cents"] == 48000


# ---------------------------------------------------------------------------
# Corner: validations / corner_finalize_cost_without_line_items_rejected
# ---------------------------------------------------------------------------

def test_finalize_cost_without_line_items_rejected(api):
    """PRD §3.4: "finalizing a proposal that has no line items is rejected with
    `ERR_NO_LINE_ITEMS` (HTTP 422)."

    Design: Corner/validations/corner_finalize_cost_without_line_items_rejected
    """
    sc = scenario_developing_proposal(api)
    resp = api.finalize_cost(sc["pid"], REVIEWER)
    validate_error(resp, ApiErrorId.ERR_NO_LINE_ITEMS.value)
