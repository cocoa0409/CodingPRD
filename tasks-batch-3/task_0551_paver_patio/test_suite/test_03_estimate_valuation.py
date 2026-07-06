"""Generating the estimate: preconditions, permit determination, and the dual-variant valuation.

Note on scope: this domain's project valuation has a labor leg (paver base + wall labor). The
PRD (§3.3 steps 3-4) keys that leg on *billable* quantities, so the estimate-variant totals are
fixed by the PRD but not by any single pre-computed constant that survives the two-reader test.
These tests therefore assert the PRD-stated relationships (contract == estimated, divergence) and
the as-built total, which the PRD fixes uniquely from installed quantities.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_project, assert_balance_consistent, TEST_USERS,
)
from test_helpers import fixtures as fx

DESIGN = TEST_USERS["design_consultant_headers"]


def test_generate_estimate_without_approved_design(api):
    """PRD §3.3: "Three preconditions must hold, each with its own code: at least one design
    revision on the project must be `APPROVED` (else `ERR_DESIGN_NOT_APPROVED`), at least one site
    measurement must exist (else `ERR_NO_MEASUREMENT`), and at least one line item must exist (else
    `ERR_NO_LINE_ITEMS`), all 409."

    Design: Corner/validations/generate_estimate_without_approved_design_returns_error
    """
    ctx = fx.setup_estimate_missing_approved_design(api)
    resp = api.generate_estimate(ctx["project_id"], DESIGN)
    validate_error(resp, ApiErrorId.ERR_DESIGN_NOT_APPROVED)


def test_generate_estimate_without_line_items(api):
    """PRD §3.3: "Three preconditions must hold, each with its own code: at least one design
    revision on the project must be `APPROVED` (else `ERR_DESIGN_NOT_APPROVED`), at least one site
    measurement must exist (else `ERR_NO_MEASUREMENT`), and at least one line item must exist (else
    `ERR_NO_LINE_ITEMS`), all 409."

    Design: Corner/validations/generate_estimate_without_line_items_returns_error
    """
    ctx = fx.setup_estimate_missing_line_items(api)
    resp = api.generate_estimate(ctx["project_id"], DESIGN)
    validate_error(resp, ApiErrorId.ERR_NO_LINE_ITEMS)


def test_wall_height_exactly_48_requires_permit(api):
    """PRD §3.3: "permit determination sets `permit_required` to true exactly when the largest
    `wall_height_in` across the project's site measurements is at least 48 inches (a wall of 47
    inches does not require a permit; 48 does)."
    PRD §3.3: "A `DesignConsultant` generates the estimate, which advances the project from `DRAFT`
    to `QUOTED`."

    Design: Difficulty/boundary_precision_check/permit_wall_height_threshold_at_48
    """
    ctx = fx.setup_permit_boundary_project(api, wall_height_in=48)
    data = validate_success(api.generate_estimate(ctx["project_id"], DESIGN))
    assert_project(data)
    assert data["permit_required"] is True, "wall_height 48 (>=48) must set permit_required true"
    assert data["status"] == "QUOTED", f"expected QUOTED, got {data['status']}"


def test_wall_height_47_does_not_require_permit(api):
    """PRD §3.3: "permit determination sets `permit_required` to true exactly when the largest
    `wall_height_in` across the project's site measurements is at least 48 inches (a wall of 47
    inches does not require a permit; 48 does)."

    Design: Difficulty/boundary_precision_check/permit_wall_height_threshold_at_48
    """
    ctx = fx.setup_permit_boundary_project(api, wall_height_in=47)
    data = validate_success(api.generate_estimate(ctx["project_id"], DESIGN))
    assert data["permit_required"] is False, "wall_height 47 (<48) must leave permit_required false"


def test_wall_height_48_sets_permit_required_on_estimate(api):
    """PRD §3.3: "permit determination sets `permit_required` to true exactly when the largest
    `wall_height_in` across the project's site measurements is at least 48 inches (a wall of 47
    inches does not require a permit; 48 does)."

    Design: Difficulty/combinatorial_formula/labor_tier_plus_complex_site_multiplier
    """
    ctx = fx.setup_labor_tier_project(api)
    data = validate_success(api.generate_estimate(ctx["project_id"], DESIGN))
    assert data["permit_required"] is True, "a 48in wall measurement must set permit_required true"
    assert data["status"] == "QUOTED", f"expected QUOTED, got {data['status']}"


def test_generate_estimate_sets_contract_value_equal_to_estimated_total(api):
    """PRD §3.3: "Generating the estimate also sets `contract_value_cents` equal to
    `estimated_total_cents` and `balance_due_cents` equal to the contract value (nothing has been
    paid yet)."

    Design: Difficulty/combinatorial_formula/labor_tier_plus_complex_site_multiplier
    """
    ctx = fx.setup_labor_tier_project(api)
    data = validate_success(api.generate_estimate(ctx["project_id"], DESIGN))
    assert data["contract_value_cents"] == data["estimated_total_cents"], \
        "contract_value_cents must equal estimated_total_cents at generate-estimate"
    assert data["balance_due_cents"] == data["contract_value_cents"], \
        "balance_due_cents must equal contract_value_cents when nothing is paid"


def test_large_project_receives_prompt_pay_discount(api):
    """PRD §3.3: "If the pre-tax subtotal is at least 2,000,000 cents ($20,000), the discount is
    two percent of the pre-tax subtotal, rounded half up to whole cents; otherwise it is zero. This
    value is stored in `prompt_pay_discount_cents`."

    Design: Difficulty/combinatorial_formula/prompt_pay_discount_evaluation_order
    """
    ctx = fx.setup_prompt_pay_project(api)
    data = validate_success(api.generate_estimate(ctx["project_id"], DESIGN))
    # A 3000-sqft paver project's material subtotal alone clears the 2,000,000c threshold,
    # so the pre-tax subtotal does too and the discount must be strictly positive.
    assert data["prompt_pay_discount_cents"] > 0, \
        f"expected a positive prompt-pay discount, got {data['prompt_pay_discount_cents']}"


def test_prompt_pay_project_contract_equals_estimated(api):
    """PRD §3.3: "Generating the estimate also sets `contract_value_cents` equal to
    `estimated_total_cents` and `balance_due_cents` equal to the contract value (nothing has been
    paid yet)."

    Design: Difficulty/combinatorial_formula/prompt_pay_discount_evaluation_order
    """
    ctx = fx.setup_prompt_pay_project(api)
    data = validate_success(api.generate_estimate(ctx["project_id"], DESIGN))
    assert data["contract_value_cents"] == data["estimated_total_cents"], \
        "contract_value_cents must equal estimated_total_cents at generate-estimate"
    assert data["balance_due_cents"] == data["contract_value_cents"], \
        "balance_due_cents must equal contract_value_cents when nothing is paid"


def test_as_built_valuation_uses_installed_quantities(api):
    """PRD §3.9: "the project is valued in its as-built variant: the same eleven-step valuation of
    §3.3 is re-run, but each line's quantity is its actual `installed_quantity` (with no waste
    applied) and each line's price is its locked `pinned_unit_price_cents` rather than the live
    catalog price. The result is written to `final_billed_total_cents`; it diverges from the estimate
    whenever installed quantities differ from the billable ones."

    Design: Difficulty/dual_variant_calc/project_valuation_estimate_vs_as_built
    """
    ctx = fx.setup_dual_variant_completed(api)
    project = ctx["project"]
    assert project["status"] == "COMPLETED", f"expected COMPLETED, got {project['status']}"
    # As-built uses installed quantities (260/40/1) and pinned prices (850/2200/180000) uniformly,
    # so the final billed total is fixed by the PRD independent of the estimate labor basis.
    assert project["final_billed_total_cents"] == 741453, \
        f"expected as-built total 741453, got {project['final_billed_total_cents']}"


def test_estimate_and_as_built_totals_diverge(api):
    """PRD §3.9: "The result is written to `final_billed_total_cents`; it diverges from the estimate
    whenever installed quantities differ from the billable ones."

    Design: Difficulty/dual_variant_calc/project_valuation_estimate_vs_as_built
    """
    ctx = fx.setup_dual_variant_completed(api)
    project = ctx["project"]
    assert project["estimated_total_cents"] > 0, "estimate must have been recorded at generate-estimate"
    assert project["final_billed_total_cents"] != project["estimated_total_cents"], (
        "installed quantities (260) differ from billable (275) here, so the as-built total must "
        "diverge from the estimate"
    )
