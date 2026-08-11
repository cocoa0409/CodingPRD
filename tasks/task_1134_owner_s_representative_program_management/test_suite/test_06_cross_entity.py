"""Cross-entity state dependencies (PRD §3.3, §3.8)."""
from test_helpers import (
    api_client, validate_error, get_success_data,
    create_active_program, create_program, create_and_approve_baseline,
    create_occupancy_plan, coordinate_occupancy_plan, mark_ready_occupancy_plan,
    create_contract, begin_negotiation, execute_contract, create_change_order,
    submit_change_order,
    create_baseline_payload,
    pm_headers, owner_headers,
    ApiErrorId,
)


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / change_order_submit_requires_contract_executed
# ---------------------------------------------------------------------------

def test_co_submit_fails_when_contract_not_executed(api):
    """PRD §3.3: "Submission moves a change order DRAFT → UNDER_REVIEW and
    enforces two state gates: the contract must be EXECUTED (else
    ERR_CONTRACT_NOT_EXECUTED, 409), and the program's contingency_posture must
    not be CRITICAL (else ERR_CONTINGENCY_POSTURE_CRITICAL, 409)".

    Design: Difficulty/cross_entity_state_dependency/change_order_submit_requires_contract_executed
    """
    prog = create_active_program(
        total_budget_cents=10_000_000, contingency_total_cents=1_000_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 10_000_000}], name="P-X1",
    )
    pid = prog["id"]
    ct1 = create_contract(pid, solicitation_estimate_cents=4_500_000,
                           vendor_name="V1", contract_type="CONTRACTOR")
    co1 = create_change_order(ct1["id"], amount_cents=100_000, title="CO1", reason="x")
    resp = api_client.submit_change_order(co1["id"], pm_headers())
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_EXECUTED)


def test_co_submit_succeeds_after_contract_executed(api):
    """PRD §3.3: "Submission moves a change order DRAFT → UNDER_REVIEW and
    enforces two state gates: the contract must be EXECUTED (else
    ERR_CONTRACT_NOT_EXECUTED, 409)".

    Design: Difficulty/cross_entity_state_dependency/change_order_submit_requires_contract_executed
    """
    prog = create_active_program(
        total_budget_cents=10_000_000, contingency_total_cents=1_000_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 10_000_000}], name="P-X1B",
    )
    pid = prog["id"]
    ct1 = create_contract(pid, solicitation_estimate_cents=4_500_000,
                           vendor_name="V1", contract_type="CONTRACTOR")
    co1 = create_change_order(ct1["id"], amount_cents=100_000, title="CO1", reason="x")
    resp = api_client.submit_change_order(co1["id"], pm_headers())
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_EXECUTED)
    # Flip the contract state
    begin_negotiation(ct1["id"])
    execute_contract(ct1["id"], 4_500_000)
    ok = submit_change_order(co1["id"])
    assert ok["status"] == "UNDER_REVIEW"


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / occupancy_plan_ready_requires_approved_baseline
# ---------------------------------------------------------------------------

def test_plan_mark_ready_fails_without_approved_baseline(api):
    """PRD §3.8: "Marking the plan ready moves COORDINATING → READY, which
    requires an APPROVED baseline to exist for the program (else
    ERR_NO_APPROVED_BASELINE, 409)".

    Design: Difficulty/cross_entity_state_dependency/occupancy_plan_ready_requires_approved_baseline
    """
    prog = create_program(name="P-X2")
    pid = prog["id"]
    # DRAFT baseline exists (never submitted)
    bl = get_success_data(api_client.create_baseline(
        create_baseline_payload(pid, total_budget_cents=1_000_000,
                                 contingency_total_cents=100_000,
                                 lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}]),
        pm_headers(),
    ))
    pl = create_occupancy_plan(pid, plan_name="PL", target_move_month="2026-10")
    coordinate_occupancy_plan(pl["id"])
    resp = api_client.mark_ready_occupancy_plan(pl["id"], pm_headers())
    validate_error(resp, ApiErrorId.ERR_NO_APPROVED_BASELINE)


def test_plan_mark_ready_succeeds_after_baseline_approved(api):
    """PRD §3.8: "Marking the plan ready moves COORDINATING → READY, which
    requires an APPROVED baseline to exist for the program (else
    ERR_NO_APPROVED_BASELINE, 409) and triggers computation of both readiness
    variants". PRD §3.8: "[readiness] is 0.00 when no waves are considered."

    Design: Difficulty/cross_entity_state_dependency/occupancy_plan_ready_requires_approved_baseline
    """
    prog = create_program(name="P-X2B")
    pid = prog["id"]
    bl = get_success_data(api_client.create_baseline(
        create_baseline_payload(pid, total_budget_cents=1_000_000,
                                 contingency_total_cents=100_000,
                                 lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}]),
        pm_headers(),
    ))
    pl = create_occupancy_plan(pid, plan_name="PL", target_move_month="2026-10")
    coordinate_occupancy_plan(pl["id"])
    resp = api_client.mark_ready_occupancy_plan(pl["id"], pm_headers())
    validate_error(resp, ApiErrorId.ERR_NO_APPROVED_BASELINE)
    # Approve baseline and retry
    api_client.submit_baseline(bl["id"], pm_headers())
    pv = get_success_data(api_client.get_program(pid, pm_headers()))["version"]
    api_client.decide_baseline(
        bl["id"], {"decision": "APPROVE", "expected_program_version": pv}, owner_headers(),
    )
    ready = get_success_data(api_client.mark_ready_occupancy_plan(pl["id"], pm_headers()))
    assert ready["status"] == "READY"
    # No waves yet: both readiness variants 0.00 per PRD §3.8
    assert float(ready["readiness_unweighted_pct"]) == 0.0
    assert float(ready["readiness_weighted_pct"]) == 0.0
