"""Queue B — endpoints section corner tests (non-stub only)."""
from test_helpers import (
    api_client, validate_paginated, validate_error, get_success_data,
    create_active_program, create_risk_entry, assess_risk,
    create_stakeholder_group, create_occupancy_plan, coordinate_occupancy_plan,
    mark_ready_occupancy_plan, execute_occupancy_plan,
    create_move_in_wave, confirm_move_in_wave,
    pm_headers, ApiErrorId,
)


def test_risk_list_filtered_by_status(api):
    """PRD §4 endpoint table: "GET /risk-entries — List risk entries,
    filterable by program_id, status, linked_drawdown_id".

    Design: Corner/endpoints/risk_list_filtered_by_status
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="P-FLT",
    )
    pid = prog["id"]
    ra = create_risk_entry(pid, probability_pct=10, impact_cents=1_000,
                            title="RA", category="COST")
    assess_risk(ra["id"], 10, 1_000)  # ASSESSED
    rb = create_risk_entry(pid, probability_pct=100, impact_cents=100_000_000,
                            title="RB", category="SITE")
    assess_risk(rb["id"], 100, 100_000_000)  # ESCALATED
    items, meta = validate_paginated(
        api_client.list_risk_entries(pm_headers(),
                                       params={"program_id": pid, "status": "ESCALATED"}))
    assert len(items) == 1
    assert items[0]["id"] == rb["id"]


def test_wave_confirm_requires_plan_ready(api):
    """PRD §3.8: "Confirmation moves a wave SCHEDULED → CONFIRMED and re-runs
    two checks: the plan must be READY or EXECUTING (else ERR_PLAN_NOT_READY,
    409), and the dock overlap rule is re-checked against the current set of
    occupying waves (else ERR_DOCK_OVERLAP)."

    Design: Corner/endpoints/wave_confirm_requires_plan_ready
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="P-COND",
    )
    pid = prog["id"]
    g1 = create_stakeholder_group(pid, group_name="G1", contact_email="g1@x.com")
    pl = create_occupancy_plan(pid, plan_name="PL", target_move_month="2026-10")
    coordinate_occupancy_plan(pl["id"])
    w1 = create_move_in_wave(pl["id"], g1["id"], wave_name="W1", dock_resource="DOCK_A",
                              move_start="2026-10-01T08:00:00Z",
                              move_end="2026-10-01T12:00:00Z", criticality_weight=1)
    # Plan still COORDINATING -> confirm fails
    resp = api_client.confirm_move_in_wave(w1["id"], pm_headers())
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_READY)
    # Flip plan to READY then EXECUTING; confirm succeeds
    mark_ready_occupancy_plan(pl["id"])
    execute_occupancy_plan(pl["id"])
    conf = confirm_move_in_wave(w1["id"])
    assert conf["status"] == "CONFIRMED"
