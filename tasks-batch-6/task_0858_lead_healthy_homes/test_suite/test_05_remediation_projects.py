"""Remediation projects: subsidy sizing, cost reconciliation, start gate, OCC, fiscal gate.

Queue A: dual_variant_calc, combinatorial_formula, priority_pair_validation_conflict,
cross_entity_state_dependency.
Queue B: calculations, errors, endpoints, cross_cutting.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    build_remediation_scenario, make_contractor_headers, TEST_USERS,
)

CM = TEST_USERS["case_manager_headers"]
PA = TEST_USERS["program_admin_headers"]


# ─── dual_variant_calc / estimated_vs_final_remediation_cost ───────────
def test_estimated_subsidy_reserved_at_approve(api):
    """PRD §3.6: "a base unit subsidy of 250000 cents (2,500 dollars) is multiplied by
    the hazard count and by the income multiplier for the tier — 1.5 for
    `EXTREMELY_LOW`, 1.25 for `VERY_LOW`, 1.0 for `LOW`, and 0.75 for `MODERATE`."
    PRD §3.6: "A successful approval moves the project `PROPOSED → APPROVED`, increases
    the fund's `reserved_cents` by `estimated_cost_cents`".

    Design: Difficulty/dual_variant_calc/estimated_vs_final_remediation_cost
    """
    ctx = build_remediation_scenario(stage="approved", income_tier="VERY_LOW",
                                     num_hazards=2, grant_budget=5000000)
    proj = validate_success(api_client.get_remediation_project(ctx["proj_id"], CM), 200)
    assert proj["estimated_cost_cents"] == 625000
    gf = validate_success(api_client.get_grant_fund(ctx["gf_id"], CM), 200)
    assert gf["reserved_cents"] == 625000


def test_final_cost_reconciled_and_capped_at_complete(api):
    """PRD §3.6: "`final_cost_cents` is set to the sum of the submitted line items'
    `amount_cents`. The fund is then reconciled — its `reserved_cents` is decreased by
    the project's `estimated_cost_cents`, and its `spent_cents` is increased by the
    smaller of `estimated_cost_cents` and `final_cost_cents`, so the grant never pays
    out more than the reserved subsidy and any overrun falls on the owner."

    Design: Difficulty/dual_variant_calc/estimated_vs_final_remediation_cost
    """
    ctx = build_remediation_scenario(stage="cleared", income_tier="VERY_LOW",
                                     num_hazards=2, grant_budget=5000000)
    proj = validate_success(api_client.complete_project(
        ctx["proj_id"], {"line_items": [{"description": "paint abatement", "amount_cents": 400000}]},
        make_contractor_headers(ctx["con_id"])), 200)
    assert proj["status"] == "COMPLETED"
    assert proj["estimated_cost_cents"] == 625000
    assert proj["final_cost_cents"] == 400000
    gf = validate_success(api_client.get_grant_fund(ctx["gf_id"], CM), 200)
    assert gf["spent_cents"] == 400000
    assert gf["reserved_cents"] == 0
    assert gf["available_cents"] == 4600000


# ─── combinatorial_formula / grant_subsidy_tiered_min_cap ──────────────
def test_subsidy_capped_at_maximum(api):
    """PRD §3.6: "That raw product is rounded half up to whole cents, and then the
    result is capped at a maximum subsidy of 1500000 cents (15,000 dollars); the
    smaller of the rounded amount and the cap becomes `estimated_cost_cents`."

    Design: Difficulty/combinatorial_formula/grant_subsidy_tiered_min_cap
    """
    ctx = build_remediation_scenario(stage="approved", income_tier="EXTREMELY_LOW",
                                     num_hazards=5, grant_budget=5000000)
    order = validate_success(api_client.get_order(ctx["order_id"], CM), 200)
    assert order["hazard_count"] == 5
    proj = validate_success(api_client.get_remediation_project(ctx["proj_id"], CM), 200)
    # raw = 250000 * 5 * 1.5 = 1875000, capped at 1500000
    assert proj["estimated_cost_cents"] == 1500000


def test_capped_subsidy_reserved_against_fund(api):
    """PRD §3.6: "A successful approval moves the project `PROPOSED → APPROVED`,
    increases the fund's `reserved_cents` by `estimated_cost_cents`, recomputes
    `available_cents`, and increments the fund's `version` by 1."

    Design: Difficulty/combinatorial_formula/grant_subsidy_tiered_min_cap
    """
    ctx = build_remediation_scenario(stage="approved", income_tier="EXTREMELY_LOW",
                                     num_hazards=5, grant_budget=5000000)
    gf = validate_success(api_client.get_grant_fund(ctx["gf_id"], CM), 200)
    assert gf["reserved_cents"] == 1500000
    assert gf["available_cents"] == 3500000


# ─── priority_pair_validation_conflict / state_beats_fiscal_on_project_approve ─
def test_reapprove_approved_project_returns_invalid_state_over_fiscal(api):
    """PRD §2.8: "on project approval a **state** failure (order not `ISSUED`, priority
    7) takes precedence over an **insufficient-funds** failure (`ERR_GRANT_INSUFFICIENT`,
    priority 16): when both would fail, the state error wins."
    PRD §2.8: "the target is in a state from which the requested transition is defined,
    else `ERR_INVALID_STATE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_project_approve
    """
    ctx = build_remediation_scenario(stage="approved", income_tier="VERY_LOW",
                                     num_hazards=2, grant_budget=1000000)
    gf = validate_success(api_client.get_grant_fund(ctx["gf_id"], CM), 200)
    res = api_client.approve_project(
        ctx["proj_id"], {"expected_grant_fund_version": gf["version"]}, CM)
    validate_error(res, "ERR_INVALID_STATE")


def test_reapprove_leaves_project_and_ledger_unchanged(api):
    """PRD §2.8: "on project approval a **state** failure (order not `ISSUED`, priority
    7) takes precedence over an **insufficient-funds** failure (`ERR_GRANT_INSUFFICIENT`,
    priority 16): when both would fail, the state error wins."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_project_approve
    """
    ctx = build_remediation_scenario(stage="approved", income_tier="VERY_LOW",
                                     num_hazards=2, grant_budget=1000000)
    gf = validate_success(api_client.get_grant_fund(ctx["gf_id"], CM), 200)
    api_client.approve_project(ctx["proj_id"], {"expected_grant_fund_version": gf["version"]}, CM)
    proj = validate_success(api_client.get_remediation_project(ctx["proj_id"], CM), 200)
    assert proj["status"] == "APPROVED"
    gf_after = validate_success(api_client.get_grant_fund(ctx["gf_id"], CM), 200)
    assert gf_after["reserved_cents"] == 625000


# ─── cross_entity_state_dependency / project_start_requires_contractor_active ─
def test_start_rejected_when_contractor_suspended(api):
    """PRD §3.6: "Starting requires the project to be `APPROVED`, the linked order still
    in `ISSUED`, and the contractor to be certified and current — its
    `certification_status` must be `ACTIVE` and its `certification_expires_at` must be
    strictly after the current logical clock; otherwise the start is rejected with
    `ERR_CONTRACTOR_NOT_CERTIFIED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/project_start_requires_contractor_active
    """
    ctx = build_remediation_scenario(stage="approved", income_tier="VERY_LOW",
                                     num_hazards=2, grant_budget=5000000)
    validate_success(
        api_client.contractor_certification(ctx["con_id"], {"action": "SUSPEND"}, PA), 200)
    res = api_client.start_project(ctx["proj_id"], make_contractor_headers(ctx["con_id"]))
    validate_error(res, "ERR_CONTRACTOR_NOT_CERTIFIED")


def test_start_rejection_leaves_project_approved(api):
    """PRD §3.6: "A successful start moves the project `APPROVED → IN_PROGRESS`".
    PRD §3.6: "otherwise the start is rejected with `ERR_CONTRACTOR_NOT_CERTIFIED`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/project_start_requires_contractor_active
    """
    ctx = build_remediation_scenario(stage="approved", income_tier="VERY_LOW",
                                     num_hazards=2, grant_budget=5000000)
    validate_success(
        api_client.contractor_certification(ctx["con_id"], {"action": "SUSPEND"}, PA), 200)
    api_client.start_project(ctx["proj_id"], make_contractor_headers(ctx["con_id"]))
    proj = validate_success(api_client.get_remediation_project(ctx["proj_id"], CM), 200)
    assert proj["status"] == "APPROVED"


# ─── Corner: calculations / grant_subsidy_moderate_tier_multiplier ─────
def test_moderate_tier_subsidy_multiplier(api):
    """PRD §3.6: "a base unit subsidy of 250000 cents (2,500 dollars) is multiplied by
    the hazard count and by the income multiplier for the tier — 1.5 for
    `EXTREMELY_LOW`, 1.25 for `VERY_LOW`, 1.0 for `LOW`, and 0.75 for `MODERATE`."

    Design: Corner/calculations/grant_subsidy_moderate_tier_multiplier
    """
    ctx = build_remediation_scenario(stage="approved", income_tier="MODERATE",
                                     num_hazards=2, grant_budget=5000000)
    proj = validate_success(api_client.get_remediation_project(ctx["proj_id"], CM), 200)
    assert proj["estimated_cost_cents"] == 375000
    gf = validate_success(api_client.get_grant_fund(ctx["gf_id"], CM), 200)
    assert gf["reserved_cents"] == 375000
    assert gf["available_cents"] == 4625000


# ─── Corner: errors / approve_over_budget_returns_grant_insufficient ───
def test_approve_over_budget_returns_grant_insufficient(api):
    """PRD §3.6: "Approval requires that this estimated subsidy not exceed the fund's
    `available_cents`; if it does, the approval is rejected with `ERR_GRANT_INSUFFICIENT`
    (HTTP 402)."

    Design: Corner/errors/approve_over_budget_returns_grant_insufficient
    """
    ctx = build_remediation_scenario(stage="proposed", income_tier="VERY_LOW",
                                     num_hazards=2, grant_budget=500000)
    res = api_client.approve_project(
        ctx["proj_id"], {"expected_grant_fund_version": ctx["gf_v"]}, CM)
    validate_error(res, "ERR_GRANT_INSUFFICIENT")
    gf = validate_success(api_client.get_grant_fund(ctx["gf_id"], CM), 200)
    assert gf["reserved_cents"] == 0


# ─── Corner: cross_cutting / approve_with_stale_grant_version_rejected ─
def test_approve_with_stale_grant_version_rejected(api):
    """PRD §2.5: "If that value does not equal the fund's current `version`, the
    approval is rejected with `ERR_STALE_GRANT_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting/approve_with_stale_grant_version_rejected
    """
    ctx = build_remediation_scenario(stage="proposed", income_tier="VERY_LOW",
                                     num_hazards=2, grant_budget=5000000)
    res = api_client.approve_project(
        ctx["proj_id"], {"expected_grant_fund_version": ctx["gf_v"] - 1}, CM)
    validate_error(res, "ERR_STALE_GRANT_VERSION")
    proj = validate_success(api_client.get_remediation_project(ctx["proj_id"], CM), 200)
    assert proj["status"] == "PROPOSED"


# ─── Corner: cross_cutting / grant_version_increments_on_approve ───────
def test_grant_version_increments_on_approve(api):
    """PRD §2.5: "A successful approval increments the fund's `version` by 1."
    PRD §3.6: "increases the fund's `reserved_cents` by `estimated_cost_cents`".

    Design: Corner/cross_cutting/grant_version_increments_on_approve
    """
    ctx = build_remediation_scenario(stage="proposed", income_tier="VERY_LOW",
                                     num_hazards=2, grant_budget=5000000)
    assert ctx["gf_v"] == 1
    validate_success(api_client.approve_project(
        ctx["proj_id"], {"expected_grant_fund_version": ctx["gf_v"]}, CM), 200)
    gf = validate_success(api_client.get_grant_fund(ctx["gf_id"], CM), 200)
    assert gf["version"] == 2
    assert gf["reserved_cents"] == 625000


# ─── Corner: endpoints / remediation_projects_filtered_by_grant_fund_id ─
def test_remediation_projects_filtered_by_grant_fund_id(api):
    """PRD §3.6: "Projects can be fetched individually or listed with filters for
    `order_id`, `contractor_id`, and `grant_fund_id`."

    Design: Corner/endpoints/remediation_projects_filtered_by_grant_fund_id
    """
    ctx = build_remediation_scenario(stage="proposed", income_tier="VERY_LOW",
                                     num_hazards=1, grant_budget=5000000)
    data, meta = validate_paginated(
        api_client.list_remediation_projects(CM, params={"grant_fund_id": ctx["gf_id"]}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == ctx["proj_id"]
