"""Queue B — state_machines section corner tests."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_active_program, create_program, create_and_approve_charter,
    create_charter_payload, create_drawdown, release_drawdown,
    create_and_execute_contract, create_change_order, submit_change_order,
    recommend_change_order, decide_change_order,
    create_risk_entry, assess_risk, mitigate_risk, monitor_risk, realize_risk,
    create_owner_report, submit_owner_report, return_owner_report,
    create_closeout_item, submit_closeout_item, verify_closeout_item,
    reject_closeout_item,
    create_stakeholder_group, create_occupancy_plan, coordinate_occupancy_plan,
    create_move_in_wave, cancel_move_in_wave,
    pm_headers, owner_headers, exec_headers,
    ApiErrorId,
)


def test_charter_decide_from_draft_rejected(api):
    """PRD §3.1: charter lifecycle is DRAFT → SUBMITTED → Owner decision;
    §2.5 priority 5 state gates: "The target and parent entities must be in a
    state from which the requested transition exists" — DRAFT has no decide
    transition.

    Design: Corner/state_machines/charter_decide_from_draft_rejected
    """
    prog = create_program(name="P-SM1")
    pid = prog["id"]
    ch = get_success_data(api_client.create_charter(
        create_charter_payload(pid), pm_headers()))
    pv = get_success_data(api_client.get_program(pid, pm_headers()))["version"]
    resp = api_client.decide_charter(
        ch["id"], {"decision": "APPROVE", "expected_program_version": pv},
        owner_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)


def test_charter_superseded_terminal_lockdown(api):
    """PRD §3.1: "The supersession transition APPROVED → SUPERSEDED is
    system-driven only — it fires automatically when another charter of the
    same program is approved, never through a direct client action." Once
    SUPERSEDED, the charter has no further transitions.

    Design: Corner/state_machines/charter_superseded_terminal_lockdown
    """
    prog = create_program(name="P-SM2")
    pid = prog["id"]
    cha = get_success_data(api_client.create_charter(
        create_charter_payload(pid, objectives="a", scope_statement="a"), pm_headers()))
    api_client.submit_charter(cha["id"], pm_headers())
    pv1 = get_success_data(api_client.get_program(pid, pm_headers()))["version"]
    api_client.decide_charter(cha["id"],
                               {"decision": "APPROVE", "expected_program_version": pv1},
                               owner_headers())
    chb = get_success_data(api_client.create_charter(
        create_charter_payload(pid, objectives="b", scope_statement="b"), pm_headers()))
    api_client.submit_charter(chb["id"], pm_headers())
    pv2 = get_success_data(api_client.get_program(pid, pm_headers()))["version"]
    api_client.decide_charter(chb["id"],
                               {"decision": "APPROVE", "expected_program_version": pv2},
                               owner_headers())
    sta = get_success_data(api_client.get_charter(cha["id"], pm_headers()))
    assert sta["status"] == "SUPERSEDED"
    # Terminal lockdown: submit on SUPERSEDED is rejected
    resp = api_client.submit_charter(cha["id"], pm_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)
    # Program now points at the newer approved charter
    p = get_success_data(api_client.get_program(pid, pm_headers()))
    assert p["approved_charter_id"] == chb["id"]


def test_owner_report_return_resubmit_cycle(api):
    """PRD §3.6: "Submission — moving DRAFT → SUBMITTED, or RETURNED →
    SUBMITTED on resubmission — first recomputes every forecast field from
    current program state, then freezes them while the report is SUBMITTED,
    recording the operator in submitted_by_user_id." And: "Alternatively the
    Owner returns the report, moving SUBMITTED → RETURNED and recording a
    return_note".

    Design: Corner/state_machines/owner_report_return_resubmit_cycle
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="P-SM3",
    )
    pid = prog["id"]
    rep = create_owner_report(pid, period="2026-08")
    s1 = submit_owner_report(rep["id"], pm_id="pm-1")
    assert s1["status"] == "SUBMITTED"
    s2 = return_owner_report(rep["id"], return_note="fix forecast narrative")
    assert s2["status"] == "RETURNED"
    assert s2["return_note"] == "fix forecast narrative"
    s3 = submit_owner_report(rep["id"], pm_id="pm-1")
    assert s3["status"] == "SUBMITTED"
    assert s3["submitted_by_user_id"] == "pm-1"


def test_drawdown_release_terminal_lockdown(api):
    """PRD §3.5: "DRAWN and RELEASED are terminal." §2.5 priority 5 state
    gates reject transitions from terminal states.

    Design: Corner/state_machines/drawdown_release_terminal_lockdown
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="P-SM4",
    )
    pid = prog["id"]
    dd = create_drawdown(pid, 50_000, purpose="p")
    release_drawdown(dd["id"])
    resp = api_client.commit_drawdown(dd["id"], pm_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)


def test_closeout_item_reject_rework_loop(api):
    """PRD §3.9: "an OwnerRepPM submits evidence moving OPEN → SUBMITTED,
    recording submitted_by_user_id. ... alternatively the executive rejects,
    moving SUBMITTED → OPEN and recording a rejection_note for the rework
    loop." Also: "an OwnerRepExecutive moves SUBMITTED → VERIFIED ... recording
    verified_by_user_id".

    Design: Corner/state_machines/closeout_item_reject_rework_loop
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="P-SM5",
    )
    pid = prog["id"]
    ci = create_closeout_item(pid, item_type="PUNCH_LIST", title="punch")
    s1 = submit_closeout_item(ci["id"], pm_id="pm-1")
    assert s1["status"] == "SUBMITTED"
    s2 = reject_closeout_item(ci["id"], rejection_note="incomplete", exec_id="exec-1")
    assert s2["status"] == "OPEN"
    assert s2["rejection_note"] == "incomplete"
    s3 = submit_closeout_item(ci["id"], pm_id="pm-1")
    assert s3["status"] == "SUBMITTED"
    s4 = verify_closeout_item(ci["id"], exec_id="exec-1")
    assert s4["status"] == "VERIFIED"
    assert s4["verified_by_user_id"] == "exec-1"


def test_program_reopen_branch_from_closing(api):
    """PRD §3.9: "Should closing prove premature, an OwnerRepPM may reopen
    the program CLOSING → ACTIVE with no further preconditions."

    Design: Corner/state_machines/program_reopen_branch_from_closing
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="P-SM6",
    )
    pid = prog["id"]
    s1 = get_success_data(api_client.begin_closing_program(pid, pm_headers()))
    assert s1["status"] == "CLOSING"
    s2 = get_success_data(api_client.reopen_program(pid, pm_headers()))
    assert s2["status"] == "ACTIVE"


def test_risk_realized_terminal_no_further_assess(api):
    """PRD §3.4: "REALIZED and CLOSED are terminal." A subsequent assess is
    rejected as an invalid transition per §2.5 priority 5.

    Design: Corner/state_machines/risk_realized_terminal_no_further_assess
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="P-SM7",
    )
    pid = prog["id"]
    r = create_risk_entry(pid, probability_pct=50, impact_cents=100_000,
                           title="R1", category="SITE")
    assess_risk(r["id"], 50, 100_000)
    mitigate_risk(r["id"], mitigation_plan="m")
    monitor_risk(r["id"])
    realized = realize_risk(r["id"], 50_000)
    assert realized["status"] == "REALIZED"
    resp = api_client.assess_risk(r["id"],
                                   {"probability_pct": 10, "impact_cents": 100},
                                   pm_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)


def test_wave_cancel_frees_dock_interval(api):
    """PRD §3.8: "Cancellation from SCHEDULED or CONFIRMED moves the wave to
    CANCELLED, likewise frees the dock interval". And: "Only waves in
    SCHEDULED or CONFIRMED on the same dock_resource within the same program
    occupy a dock — COMPLETE waves no longer occupy it, and CANCELLED waves
    are excluded entirely."

    Design: Corner/state_machines/wave_cancel_frees_dock_interval
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="P-SM8",
    )
    pid = prog["id"]
    g1 = create_stakeholder_group(pid, group_name="G1", contact_email="g1@x.com")
    pl = create_occupancy_plan(pid, plan_name="PL", target_move_month="2026-10")
    coordinate_occupancy_plan(pl["id"])
    w1 = create_move_in_wave(pl["id"], g1["id"], wave_name="W1", dock_resource="DOCK_A",
                              move_start="2026-10-01T08:00:00Z",
                              move_end="2026-10-01T12:00:00Z", criticality_weight=1)
    cancelled = cancel_move_in_wave(w1["id"])
    assert cancelled["status"] == "CANCELLED"
    # Now an overlapping wave on the same dock is accepted
    w2 = create_move_in_wave(pl["id"], g1["id"], wave_name="W2", dock_resource="DOCK_A",
                              move_start="2026-10-01T09:00:00Z",
                              move_end="2026-10-01T11:00:00Z", criticality_weight=1)
    assert w2["status"] == "SCHEDULED"


def test_contract_complete_blocked_by_open_change_order(api):
    """PRD §3.2: "An OwnerRepPM finally moves a contract EXECUTED →
    COMPLETED, which is only possible when the contract has no open change
    orders — zero change orders in DRAFT, UNDER_REVIEW, RECOMMEND_APPROVAL,
    RECOMMEND_REJECTION, or APPROVED — otherwise the completion is rejected
    with ERR_OPEN_CHANGE_ORDERS_EXIST."

    Design: Corner/state_machines/contract_complete_blocked_by_open_change_order
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="P-SM9",
    )
    pid = prog["id"]
    ct1 = create_and_execute_contract(pid, 400_000, solicitation_estimate_cents=400_000,
                                       vendor_name="V1", contract_type="CONTRACTOR")
    co = create_change_order(ct1["id"], amount_cents=50_000, title="CO", reason="r")
    submit_change_order(co["id"])
    resp = api_client.complete_contract(ct1["id"], pm_headers())
    validate_error(resp, ApiErrorId.ERR_OPEN_CHANGE_ORDERS_EXIST)
    # Decide the CO -> REJECTED (terminal) -> completion now succeeds
    recommend_change_order(co["id"], recommendation="REJECT", analysis_note="no")
    decide_change_order(co["id"], decision="REJECT")
    done = get_success_data(api_client.complete_contract(ct1["id"], pm_headers()))
    assert done["status"] == "COMPLETED"
