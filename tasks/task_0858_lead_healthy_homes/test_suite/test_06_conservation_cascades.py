"""Cascades and conserved quantities: withdraw depth-3, money conservation, hazard conservation.

Queue A: transitive_cascade, compensating_invariant.
Queue B: state_machines.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    build_remediation_scenario, setup_case, TEST_USERS,
)

CM = TEST_USERS["case_manager_headers"]
IC = TEST_USERS["intake_headers"]


# ─── transitive_cascade / withdraw_case_depth3_order_project_grant ─────
def test_withdraw_cascades_void_order_and_cancel_project(api):
    """PRD §3.9: "every hazard-control order of the case still in `ISSUED`,
    `IN_REMEDIATION`, or `CLEARANCE_PENDING` is voided — and each such void carries its
    own cascade: it reverts that order's `CONTROLLED` hazards to `OPEN` (adjusting the
    case counts) and cancels the order's non-terminal remediation projects."

    Design: Difficulty/transitive_cascade/withdraw_case_depth3_order_project_grant
    """
    ctx = build_remediation_scenario(stage="approved", income_tier="VERY_LOW",
                                     num_hazards=2, grant_budget=5000000)
    case = validate_success(api_client.withdraw_case(ctx["case_id"], CM), 200)
    assert case["case_status"] == "WITHDRAWN"
    order = validate_success(api_client.get_order(ctx["order_id"], CM), 200)
    assert order["status"] == "VOID"
    proj = validate_success(api_client.get_remediation_project(ctx["proj_id"], CM), 200)
    assert proj["status"] == "CANCELLED"


def test_withdraw_releases_grant_reservation(api):
    """PRD §3.9: "each of those project cancellations releases the grant reservation the
    project held, returning `reserved_cents` and `available_cents` to their pre-approval
    values."

    Design: Difficulty/transitive_cascade/withdraw_case_depth3_order_project_grant
    """
    ctx = build_remediation_scenario(stage="approved", income_tier="VERY_LOW",
                                     num_hazards=2, grant_budget=5000000)
    validate_success(api_client.withdraw_case(ctx["case_id"], CM), 200)
    gf = validate_success(api_client.get_grant_fund(ctx["gf_id"], CM), 200)
    assert gf["reserved_cents"] == 0
    assert gf["available_cents"] == 5000000


# ─── compensating_invariant / grant_money_conservation_on_approve_then_cancel ─
def test_approve_reserves_then_cancel_releases_money(api):
    """PRD §3.6: "if the project had reserved funds — that is, it had reached `APPROVED`
    or `IN_PROGRESS` — the fund's `reserved_cents` is decreased by `estimated_cost_cents`
    and `available_cents` recomputed, the compensating release that returns the fund to
    its pre-approval balance."

    Design: Difficulty/compensating_invariant/grant_money_conservation_on_approve_then_cancel
    """
    ctx = build_remediation_scenario(stage="approved", income_tier="VERY_LOW",
                                     num_hazards=2, grant_budget=5000000)
    gf_before = validate_success(api_client.get_grant_fund(ctx["gf_id"], CM), 200)
    assert gf_before["reserved_cents"] == 625000
    assert gf_before["available_cents"] == 4375000
    proj = validate_success(api_client.cancel_project(ctx["proj_id"], CM), 200)
    assert proj["status"] == "CANCELLED"


def test_cancel_restores_grant_ledger_with_no_drift(api):
    """PRD §2.6: "A forward reservation made at project approval and its compensating
    release made at cancellation must return `reserved_cents` and `available_cents` to
    exactly their pre-approval values, with no drift."

    Design: Difficulty/compensating_invariant/grant_money_conservation_on_approve_then_cancel
    """
    ctx = build_remediation_scenario(stage="approved", income_tier="VERY_LOW",
                                     num_hazards=2, grant_budget=5000000)
    validate_success(api_client.cancel_project(ctx["proj_id"], CM), 200)
    gf = validate_success(api_client.get_grant_fund(ctx["gf_id"], CM), 200)
    assert gf["reserved_cents"] == 0
    assert gf["available_cents"] == 5000000


# ─── compensating_invariant / hazard_count_conservation_on_clearance_then_void ─
def test_clearance_pass_controls_hazards_before_void(api):
    """PRD §2.9: "A clearance pass moves findings from open to controlled —
    decrementing `open_hazard_count` and incrementing `controlled_hazard_count` by the
    same number — and an order void moves them back, but neither changes
    `total_hazard_count`."

    Design: Difficulty/compensating_invariant/hazard_count_conservation_on_clearance_then_void
    """
    ctx = build_remediation_scenario(stage="cleared", income_tier="VERY_LOW",
                                     num_hazards=2, grant_budget=5000000)
    case = validate_success(api_client.get_case(ctx["case_id"], IC), 200)
    assert case["open_hazard_count"] == 0
    assert case["controlled_hazard_count"] == 2
    assert case["total_hazard_count"] == 2


def test_order_void_reverts_hazards_conserving_total(api):
    """PRD §3.5: "Voiding an order sets its `status` to `VOID` and performs the
    compensating reversion: every `CONTROLLED` hazard finding of the source
    investigation reverts to `OPEN`, the case's `controlled_hazard_count` is decremented
    and its `open_hazard_count` incremented by the number reverted (again conserving
    `total_hazard_count`)".

    Design: Difficulty/compensating_invariant/hazard_count_conservation_on_clearance_then_void
    """
    ctx = build_remediation_scenario(stage="cleared", income_tier="VERY_LOW",
                                     num_hazards=2, grant_budget=5000000)
    order = validate_success(api_client.void_order(ctx["order_id"], CM), 200)
    assert order["status"] == "VOID"
    case = validate_success(api_client.get_case(ctx["case_id"], IC), 200)
    assert case["open_hazard_count"] == 2
    assert case["controlled_hazard_count"] == 0
    assert case["total_hazard_count"] == 2


# ─── Corner: state_machines / withdraw_already_withdrawn_case_rejected ─
def test_withdraw_already_withdrawn_case_rejected(api):
    """PRD §3.9: "Both `CLOSED` and `WITHDRAWN` are terminal for the environmental
    track."
    PRD §2.8: "the target is in a state from which the requested transition is defined,
    else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/withdraw_already_withdrawn_case_rejected
    """
    ctx = setup_case(income_tier="LOW", bll=22.0)
    validate_success(api_client.withdraw_case(ctx["case_id"], CM), 200)
    res = api_client.withdraw_case(ctx["case_id"], CM)
    validate_error(res, "ERR_INVALID_STATE")
