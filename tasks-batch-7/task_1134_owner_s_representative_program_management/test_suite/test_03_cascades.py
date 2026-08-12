"""Transitive cascades from change-order approval and risk realization (PRD §3.3, §3.4)."""
from test_helpers import (
    api_client, get_success_data, validate_error,
    create_active_program, create_and_execute_contract, create_contract,
    begin_negotiation, execute_contract,
    create_change_order, submit_change_order, recommend_change_order, decide_change_order,
    create_drawdown, create_owner_report,
    create_risk_entry, assess_risk, mitigate_risk, monitor_risk, realize_risk,
    pm_headers, owner_headers, ApiErrorId,
)


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / change_order_approval_cascade
# ---------------------------------------------------------------------------

def _setup_co_cascade_scenario():
    """ACTIVE program + EXECUTED contract + DRAFT report + submitted/recommended CO."""
    prog = create_active_program(
        total_budget_cents=10_000_000, contingency_total_cents=1_000_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 10_000_000}],
        name="P-CASC",
    )
    pid = prog["id"]
    ct1 = create_and_execute_contract(pid, 4_500_000,
                                       solicitation_estimate_cents=4_500_000,
                                       vendor_name="V1", contract_type="CONTRACTOR")
    rep = create_owner_report(pid, period="2026-08")
    eac0 = rep["eac_commitment_based_cents"]
    co = create_change_order(ct1["id"], amount_cents=700_000, title="CO", reason="cascade")
    submit_change_order(co["id"])
    recommend_change_order(co["id"], recommendation="APPROVE", analysis_note="ok")
    return pid, ct1, rep, eac0, co


def test_co_approval_link1_commitment_and_link2_drawdown(api):
    """PRD §3.3: "1. The contract's current_commitment_cents increases by the
    change order's amount_cents. 2. Triggered by link 1, the system auto-creates
    a ContingencyDrawdown whose source is CHANGE_ORDER, whose change_order_id is
    this change order, whose amount_cents equals the change order's amount, and
    whose initial status is COMMITTED; the new drawdown's id is written back to
    the change order's linked_drawdown_id."

    Design: Difficulty/transitive_cascade/change_order_approval_cascade
    """
    _, ct1, _, eac0, co = _setup_co_cascade_scenario()
    assert eac0 == 4_500_000  # baseline commitment pre-CO
    decided = decide_change_order(co["id"], decision="APPROVE")
    assert decided["status"] == "APPROVED"
    # link 1
    ct = get_success_data(api_client.get_contract(ct1["id"], pm_headers()))
    assert ct["current_commitment_cents"] == 5_200_000, (
        f"link 1 failed: expected 5200000, got {ct['current_commitment_cents']}"
    )
    # link 2
    dd_id = decided["linked_drawdown_id"]
    assert dd_id, "linked_drawdown_id must be set on approval"
    dd = get_success_data(api_client.get_drawdown(dd_id, pm_headers()))
    assert dd["status"] == "COMMITTED"
    assert dd["amount_cents"] == 700_000
    assert dd["source"] == "CHANGE_ORDER"


def test_co_approval_link3_pool_posture_and_link4_draft_report_refresh(api):
    """PRD §3.3: "3. Triggered by link 2's committed draw, the program pool
    moves: contingency_committed_cents increases by the amount,
    contingency_available_cents decreases by the amount, and
    contingency_posture is recomputed per §2.7. 4. Triggered by link 3's pool
    and posture change, the forecast fields of every OwnerReport in DRAFT for
    this program are recomputed (reports in RETURNED are not refreshed, and
    SUBMITTED or ACCEPTED reports remain frozen per §3.6)."

    Design: Difficulty/transitive_cascade/change_order_approval_cascade
    """
    pid, _, rep, _, co = _setup_co_cascade_scenario()
    decide_change_order(co["id"], decision="APPROVE")
    prog = get_success_data(api_client.get_program(pid, pm_headers()))
    # link 3: 700_000 committed; available = 1_000_000 - 700_000 = 300_000
    # ratio 0.30 exactly hits the inclusive WATCH floor -> NORMAL
    assert prog["contingency_committed_cents"] == 700_000
    assert prog["contingency_available_cents"] == 300_000
    assert prog["contingency_posture"] == "NORMAL"
    # link 4: DRAFT report refreshed
    refreshed = get_success_data(api_client.get_owner_report(rep["id"], pm_headers()))
    assert refreshed["eac_commitment_based_cents"] == 5_200_000
    assert refreshed["contingency_posture_snapshot"] == "NORMAL"


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / risk_realization_cascade
# ---------------------------------------------------------------------------

def _setup_risk_cascade_scenario():
    """ACTIVE program; manual reserve 750_000 -> available 250_000 (WATCH);
    DRAFT report; R1 progressed to MONITORING; one gated CO (DRAFT)."""
    prog = create_active_program(
        total_budget_cents=10_000_000, contingency_total_cents=1_000_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 10_000_000}],
        name="P-RISK",
    )
    pid = prog["id"]
    ct1 = create_and_execute_contract(pid, 1_000_000,
                                       solicitation_estimate_cents=1_000_000,
                                       vendor_name="V1", contract_type="CONTRACTOR")
    create_drawdown(pid, 750_000, purpose="reserve")
    rep = create_owner_report(pid, period="2026-08")
    post0 = rep["contingency_posture_snapshot"]
    r1 = create_risk_entry(pid, probability_pct=100, impact_cents=200_000,
                            title="R1", category="COST")
    assess_risk(r1["id"], 100, 200_000)
    mitigate_risk(r1["id"], mitigation_plan="mitigate")
    monitor_risk(r1["id"])
    co = create_change_order(ct1["id"], amount_cents=50_000, title="CO", reason="gated")
    return pid, ct1, rep, post0, r1, co


def test_risk_realization_link1_drawdown_and_link2_pool_posture_flip(api):
    """PRD §3.4: "first, realized_loss_cents records the actual loss and the
    system auto-creates a ContingencyDrawdown whose source is RISK_REALIZATION,
    whose risk_entry_id is this entry, whose amount_cents equals the actual
    loss, and whose initial status is COMMITTED, writing the new drawdown's id
    to the entry's linked_drawdown_id; second, that committed draw moves the
    pool — contingency_committed_cents increases by the loss,
    contingency_available_cents decreases by the loss, and posture is
    recomputed".

    Design: Difficulty/transitive_cascade/risk_realization_cascade
    """
    pid, _, _, post0, r1, _ = _setup_risk_cascade_scenario()
    assert post0 == "WATCH"
    realized = realize_risk(r1["id"], 200_000)
    assert realized["status"] == "REALIZED"
    dd_id = realized["linked_drawdown_id"]
    assert dd_id, "linked_drawdown_id must be set"
    dd = get_success_data(api_client.get_drawdown(dd_id, pm_headers()))
    assert dd["status"] == "COMMITTED"
    assert dd["source"] == "RISK_REALIZATION"
    assert dd["amount_cents"] == 200_000
    # link 2: 1_000_000 - 750_000 - 200_000 = 50_000 -> ratio 0.05 -> CRITICAL
    prog = get_success_data(api_client.get_program(pid, pm_headers()))
    assert prog["contingency_available_cents"] == 50_000
    assert prog["contingency_posture"] == "CRITICAL"


def test_risk_realization_link3_draft_report_refresh_and_posture_gate(api):
    """PRD §3.4: "third, the forecast fields of every DRAFT OwnerReport for the
    program are recomputed (again, RETURNED reports are not refreshed)." PRD
    §3.3: "the program's contingency_posture must not be CRITICAL (else
    ERR_CONTINGENCY_POSTURE_CRITICAL, 409)".

    Design: Difficulty/transitive_cascade/risk_realization_cascade
    """
    pid, _, rep, _, r1, co = _setup_risk_cascade_scenario()
    realize_risk(r1["id"], 200_000)
    # link 3: DRAFT report snapshot flipped to CRITICAL
    refreshed = get_success_data(api_client.get_owner_report(rep["id"], pm_headers()))
    assert refreshed["contingency_posture_snapshot"] == "CRITICAL"
    # posture gate now blocks a new CO submit
    resp = api_client.submit_change_order(co["id"], pm_headers())
    validate_error(resp, ApiErrorId.ERR_CONTINGENCY_POSTURE_CRITICAL)
