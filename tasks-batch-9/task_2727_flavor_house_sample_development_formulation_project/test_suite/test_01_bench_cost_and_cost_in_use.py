"""Bench cost roll-up, the two cost-in-use figures, and the empty-set guard."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import create_formula_payload
from test_helpers.fixtures import (
    citrus_accepted_brief,
    citrus_costed_formula,
    citrus_draft_formula,
    cost_formula,
    read_component,
    read_formula,
)
from test_helpers.test_users import FLAVORIST_SUBMITTER


def test_costing_writes_bench_and_firm_cost_in_use_from_one_component_set(api):
    """One costing pass writes two different cents-per-tonne figures.

    The PRD pins the bench-provisional figure as "the formula's
    `bench_cost_per_kg_cents` multiplied by the brief's `dosage_pct`,
    multiplied by 10, rounded half up to whole cents" at list prices, while
    the production-firm figure applies "the annual-volume price break" and
    is then "inflated to allow for a production yield loss of 2.5 percent".
    At bench 2977, dosage 2.5 and annual volume 1200 kg those are 74425 and
    73275 respectively.

    Design: Difficulty/dual_variant_calc/cost_in_use_bench_vs_firm_variant_divergence
    """
    scenario = citrus_draft_formula(api)

    response = api.cost_formula(scenario["formula"]["id"], FLAVORIST_SUBMITTER)
    costed = get_success_data(response, 200)

    assert costed["bench_cost_per_kg_cents"] == 2977
    assert costed["bench_cost_in_use_cents_per_tonne"] == 74425
    assert costed["firm_cost_in_use_cents_per_tonne"] == 73275
    assert (costed["bench_cost_in_use_cents_per_tonne"]
            != costed["firm_cost_in_use_cents_per_tonne"])
    assert costed["status"] == "COSTED"
    assert costed["cost_stale"] is False


def test_firm_cost_in_use_applies_the_volume_break_then_the_yield_loss(api):
    """The firm figure discounts first and inflates for yield loss second.

    The PRD says "the bench cost per kilogram is multiplied by one minus the
    discount fraction, then divided by one minus the yield-loss fraction, and
    the result is rounded half up to whole cents", and that firm cost per
    kilogram "is finally converted to a per-tonne cost-in-use exactly as the
    bench figure was".  2977 x 0.96 / 0.975 rounds to 2931 per kilogram, and
    2931 x 2.5 x 10 is 73275.

    Design: Difficulty/dual_variant_calc/cost_in_use_bench_vs_firm_variant_divergence
    """
    scenario = citrus_costed_formula(api)
    formula = read_formula(api, scenario["formula"]["id"])

    assert formula["bench_cost_per_kg_cents"] == 2977
    assert formula["firm_cost_in_use_cents_per_tonne"] == 73275
    assert formula["firm_cost_in_use_cents_per_tonne"] % 10 == 5
    assert (formula["firm_cost_in_use_cents_per_tonne"]
            < formula["bench_cost_in_use_cents_per_tonne"])


def test_only_the_bench_figure_gates_submission_when_the_firm_figure_is_lower(api):
    """The submit gate reads the bench figure even though the firm figure is lower.

    The PRD says "`bench_cost_in_use_cents_per_tonne` must not exceed the
    brief's `cost_in_use_cap_cents_per_tonne`, with equality passing" and
    that "`firm_cost_in_use_cents_per_tonne` is reported but is never the
    gate".  With the cap set one cent below the bench figure the submission
    is refused, although the firm figure of 73275 sits comfortably under it.

    Design: Difficulty/dual_variant_calc/cost_in_use_bench_vs_firm_variant_divergence
    """
    scenario = citrus_costed_formula(api, cost_in_use_cap_cents_per_tonne=74424)
    formula = scenario["formula"]

    assert formula["bench_cost_in_use_cents_per_tonne"] == 74425
    assert formula["firm_cost_in_use_cents_per_tonne"] == 73275

    response = api.submit_formula(formula["id"], FLAVORIST_SUBMITTER)
    validate_error(response, ApiErrorId.ERR_COST_IN_USE_CAP_EXCEEDED.value)

    assert read_formula(api, formula["id"])["status"] == "COSTED"


def test_each_component_line_is_rounded_before_the_contributions_are_summed(api):
    """Per-line rounding precedes summation, so the header reads 2977.

    The PRD pins the order: "The line's `contribution_cents` is that unit
    price multiplied by the line's `weight_pct`, divided by 100, and rounded
    half up to a whole number of cents. Only once every line has its own
    rounded contribution does the formula's `bench_cost_per_kg_cents` come
    out as the plain sum of those already-rounded per-line contributions."

    Design: Difficulty/combinatorial_formula/bench_cost_rounds_per_component_line_before_summing
    """
    scenario = citrus_draft_formula(api)
    c1, c2, c3 = scenario["components"]

    cost_formula(api, scenario["formula"]["id"])

    assert read_component(api, c1["id"])["contribution_cents"] == 1700
    assert read_component(api, c2["id"])["contribution_cents"] == 123
    assert read_component(api, c3["id"])["contribution_cents"] == 1154

    formula = read_formula(api, scenario["formula"]["id"])
    assert formula["bench_cost_per_kg_cents"] == 2977
    assert formula["bench_cost_per_kg_cents"] != 2978


def test_the_stored_line_contributions_reconcile_with_the_formula_header(api):
    """The header equals the plain sum of the persisted line contributions.

    The PRD calls `bench_cost_per_kg_cents` "the plain sum of those
    already-rounded per-line contributions", so the three stored figures must
    add up to the header exactly.

    Design: Difficulty/combinatorial_formula/bench_cost_rounds_per_component_line_before_summing
    """
    scenario = citrus_draft_formula(api)
    costed = cost_formula(api, scenario["formula"]["id"])

    contributions = [read_component(api, component["id"])["contribution_cents"]
                     for component in scenario["components"]]

    assert contributions == [1700, 123, 1154]
    assert sum(contributions) == costed["bench_cost_per_kg_cents"] == 2977


def test_component_contributions_are_null_until_the_formula_is_costed(api):
    """A line carries no contribution while the formula is still in DRAFT.

    The PRD says the server "leaves the line's `contribution_cents` null
    until the owning formula is costed".

    Design: Difficulty/combinatorial_formula/bench_cost_rounds_per_component_line_before_summing
    """
    scenario = citrus_draft_formula(api)

    for component in scenario["components"]:
        assert read_component(api, component["id"])["contribution_cents"] is None

    formula = read_formula(api, scenario["formula"]["id"])
    assert formula["status"] == "DRAFT"
    assert formula["bench_cost_per_kg_cents"] is None


def test_costing_a_formula_with_no_component_lines_is_refused(api):
    """An empty formula is refused by the cardinality guard, not the weight rule.

    The PRD says "It must hold at least one component line, since an empty
    formula has no cost; a `component_count` of zero is
    `ERR_FORMULA_NO_COMPONENTS`", and §2.11 orders "the empty-formula check
    (`ERR_FORMULA_NO_COMPONENTS`), then the weight-sum rule
    (`ERR_WEIGHT_SUM_INVALID`)".

    Design: Difficulty/boundary_precision_check/costing_an_empty_component_set_is_rejected
    """
    brief = citrus_accepted_brief(api)
    created = get_success_data(
        api.create_formula(create_formula_payload(brief["id"], name="Empty Trial F4"),
                           FLAVORIST_SUBMITTER),
        201)

    assert created["component_count"] == 0
    assert float(created["total_weight_pct"]) == 0.0

    response = api.cost_formula(created["id"], FLAVORIST_SUBMITTER)
    validate_error(response, ApiErrorId.ERR_FORMULA_NO_COMPONENTS.value)


def test_a_rejected_empty_costing_leaves_every_cost_field_null(api):
    """The refused costing must not write a zero cost or advance the status.

    The PRD says a new formula lands "in `DRAFT` with `component_count` at 0
    and `total_weight_pct` at 0, with every cost and claim field null", and
    costing "drives `DRAFT → COSTED`" only when its four preconditions hold.

    Design: Difficulty/boundary_precision_check/costing_an_empty_component_set_is_rejected
    """
    brief = citrus_accepted_brief(api)
    created = get_success_data(
        api.create_formula(create_formula_payload(brief["id"], name="Empty Trial F4"),
                           FLAVORIST_SUBMITTER),
        201)

    validate_error(api.cost_formula(created["id"], FLAVORIST_SUBMITTER),
                   ApiErrorId.ERR_FORMULA_NO_COMPONENTS.value)

    formula = read_formula(api, created["id"])
    assert formula["status"] == "DRAFT"
    assert formula["bench_cost_per_kg_cents"] is None
    assert formula["bench_cost_in_use_cents_per_tonne"] is None
    assert formula["firm_cost_in_use_cents_per_tonne"] is None
    assert formula["cost_stale"] is False
