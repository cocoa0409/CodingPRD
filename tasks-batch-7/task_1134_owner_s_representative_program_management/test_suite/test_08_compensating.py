"""Compensating invariant tests (PRD §2.7, §3.2, §3.3, §3.5)."""
from test_helpers import (
    api_client, get_success_data,
    create_active_program, create_drawdown, commit_drawdown, release_drawdown,
    create_and_execute_contract, create_change_order, submit_change_order,
    recommend_change_order, decide_change_order,
    pm_headers, owner_headers, assert_pool_conservation,
)


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / contingency_reserve_release_conservation
# ---------------------------------------------------------------------------

def test_pool_conservation_through_reserve_commit_release(api):
    """PRD §2.7: "The pool obeys a conservation invariant at all times: the
    pool total is exactly the sum of reserved, committed, drawn, and available.
    No operation may create or destroy contingency; drawdown lifecycle
    transitions and the change-order and risk cascades merely move amounts
    among the four buckets."

    Design: Difficulty/compensating_invariant/contingency_reserve_release_conservation
    """
    prog = create_active_program(
        total_budget_cents=10_000_000, contingency_total_cents=1_000_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 10_000_000}], name="P-POOL",
    )
    pid = prog["id"]
    dd = create_drawdown(pid, 400_000, purpose="round trip")
    # after reserve
    p = get_success_data(api_client.get_program(pid, pm_headers()))
    assert_pool_conservation(p)
    st1 = commit_drawdown(dd["id"])
    assert st1["status"] == "COMMITTED"
    p = get_success_data(api_client.get_program(pid, pm_headers()))
    assert_pool_conservation(p)
    st2 = release_drawdown(dd["id"])
    assert st2["status"] == "RELEASED"
    p = get_success_data(api_client.get_program(pid, pm_headers()))
    assert_pool_conservation(p)
    # pool restored exactly
    assert p["contingency_total_cents"] == 1_000_000
    assert p["contingency_reserved_cents"] == 0
    assert p["contingency_committed_cents"] == 0
    assert p["contingency_drawn_cents"] == 0
    assert p["contingency_available_cents"] == 1_000_000


def test_pool_conservation_reserve_then_release_from_reserved(api):
    """PRD §3.5: "Release moves RESERVED → RELEASED or COMMITTED → RELEASED:
    the source bucket (reserved or committed, respectively) decreases and
    contingency_available_cents increases by the amount."

    Design: Difficulty/compensating_invariant/contingency_reserve_release_conservation
    """
    prog = create_active_program(
        total_budget_cents=10_000_000, contingency_total_cents=1_000_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 10_000_000}], name="P-POOL2",
    )
    pid = prog["id"]
    dd = create_drawdown(pid, 400_000, purpose="from reserved")
    assert dd["status"] == "RESERVED"
    p = get_success_data(api_client.get_program(pid, pm_headers()))
    assert p["contingency_reserved_cents"] == 400_000
    assert p["contingency_available_cents"] == 600_000
    release_drawdown(dd["id"])
    p = get_success_data(api_client.get_program(pid, pm_headers()))
    assert_pool_conservation(p)
    assert p["contingency_reserved_cents"] == 0
    assert p["contingency_available_cents"] == 1_000_000


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / contract_commitment_approve_void_conservation
# ---------------------------------------------------------------------------

def _setup_co_conservation_scenario():
    prog = create_active_program(
        total_budget_cents=10_000_000, contingency_total_cents=1_000_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 10_000_000}], name="P-COMMIT",
    )
    pid = prog["id"]
    ct1 = create_and_execute_contract(pid, 4_500_000,
                                       solicitation_estimate_cents=4_500_000,
                                       vendor_name="V1", contract_type="CONTRACTOR")
    co = create_change_order(ct1["id"], amount_cents=200_000, title="CO", reason="round trip")
    submit_change_order(co["id"])
    recommend_change_order(co["id"], recommendation="APPROVE", analysis_note="ok")
    return pid, ct1, co


def test_co_approve_raises_commitment_then_void_restores(api):
    """PRD §3.2: "a contract's current_commitment_cents ... equals the
    awarded_amount_cents plus the sum of amount_cents over the contract's
    APPROVED change orders, minus the sum of amount_cents over its VOID change
    orders. Because a voided change order was necessarily approved first, each
    approve/void pair nets to zero, and an approval followed by its void leaves
    the commitment unchanged."

    Design: Difficulty/compensating_invariant/contract_commitment_approve_void_conservation
    """
    _, ct1, co = _setup_co_conservation_scenario()
    decide_change_order(co["id"], decision="APPROVE")
    ct = get_success_data(api_client.get_contract(ct1["id"], pm_headers()))
    assert ct["current_commitment_cents"] == 4_700_000
    get_success_data(api_client.void_change_order(
        co["id"], {"void_reason": "compensate"}, owner_headers()))
    ct2 = get_success_data(api_client.get_contract(ct1["id"], pm_headers()))
    assert ct2["current_commitment_cents"] == 4_500_000


def test_co_void_releases_linked_drawdown_and_restores_pool(api):
    """PRD §3.3: "Voiding runs the mirror-image compensation cascade: the
    contract's current_commitment_cents decreases by the amount; the linked
    drawdown (found via linked_drawdown_id) moves to RELEASED; the pool
    releases it — contingency_committed_cents decreases by the amount,
    contingency_available_cents increases by the amount, and posture is
    recomputed".

    Design: Difficulty/compensating_invariant/contract_commitment_approve_void_conservation
    """
    pid, _, co = _setup_co_conservation_scenario()
    decided = decide_change_order(co["id"], decision="APPROVE")
    dd_id = decided["linked_drawdown_id"]
    vst = get_success_data(api_client.void_change_order(
        co["id"], {"void_reason": "compensate"}, owner_headers()))
    assert vst["status"] == "VOID"
    dd = get_success_data(api_client.get_drawdown(dd_id, pm_headers()))
    assert dd["status"] == "RELEASED"
    p = get_success_data(api_client.get_program(pid, pm_headers()))
    assert p["contingency_available_cents"] == 1_000_000
    assert p["contingency_committed_cents"] == 0
