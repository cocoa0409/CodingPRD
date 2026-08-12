"""Composite setup helpers — multi-step fixture chains for PRD scenarios.

All fixtures use get_success_data() (lenient) for setup calls so failures
surface as clear "Setup failed" errors rather than confusing assertions.

PRD §2.6 OCC: charter/baseline decide calls must carry the CURRENT
Program.version in expected_program_version. Fixtures always re-read the
program version immediately before each decide call.
"""
from prd_bench_local_runner.testing import get_success_data, build_user_headers

from .api_client import api_client
from .factories import (
    create_program_payload, create_charter_payload, create_baseline_payload,
    create_contract_payload, create_change_order_payload, create_risk_entry_payload,
    create_drawdown_payload, create_owner_report_payload,
    create_stakeholder_group_payload, create_engagement_payload,
    create_occupancy_plan_payload, create_move_in_wave_payload,
    create_closeout_item_payload, create_lesson_entry_payload,
)


# ---------- Header helpers (opaque roles; user_id pins SoD pairs) ----------
def pm_headers(user_id="pm-1"):
    return build_user_headers(user_id, "OwnerRepPM")


def exec_headers(user_id="exec-1"):
    return build_user_headers(user_id, "OwnerRepExecutive")


def owner_headers(user_id="owner-1"):
    return build_user_headers(user_id, "Owner")


# ---------- Tier 1: Program initialization ----------
def create_program(name="P", org="OwnerOrg", pm_id="pm-1"):
    """POST /programs. Returns the created Program (CHARTERING, version 1)."""
    h = pm_headers(pm_id)
    resp = api_client.create_program(create_program_payload(program_name=name, owner_organization=org), h)
    return get_success_data(resp)


def get_program(program_id, user_id="pm-1"):
    """GET /programs/{id}. Returns latest Program."""
    return get_success_data(api_client.get_program(program_id, pm_headers(user_id)))


def _program_version(program_id):
    return get_program(program_id)["version"]


# ---------- Tier 2: Charter / Baseline approval ----------
def create_and_approve_charter(program_id, pm_id="pm-1", owner_id="owner-1"):
    """Create charter, submit, Owner-decide APPROVE with current program version.

    Returns the approved Charter."""
    pm = pm_headers(pm_id)
    ch = get_success_data(api_client.create_charter(create_charter_payload(program_id), pm))
    api_client.submit_charter(ch["id"], pm)
    pv = _program_version(program_id)
    decided = api_client.decide_charter(
        ch["id"],
        {"decision": "APPROVE", "expected_program_version": pv},
        owner_headers(owner_id),
    )
    return get_success_data(decided)


def create_and_approve_baseline(program_id, total_budget_cents=10_000_000,
                                 contingency_total_cents=1_000_000, lines=None,
                                 target_finish_date="2027-03-31",
                                 pm_id="pm-1", owner_id="owner-1"):
    """Create baseline, submit, Owner-decide APPROVE with current program version.

    Returns the approved Baseline."""
    pm = pm_headers(pm_id)
    payload = create_baseline_payload(
        program_id,
        total_budget_cents=total_budget_cents,
        contingency_total_cents=contingency_total_cents,
        lines=lines,
        target_finish_date=target_finish_date,
    )
    bl = get_success_data(api_client.create_baseline(payload, pm))
    api_client.submit_baseline(bl["id"], pm)
    pv = _program_version(program_id)
    decided = api_client.decide_baseline(
        bl["id"],
        {"decision": "APPROVE", "expected_program_version": pv},
        owner_headers(owner_id),
    )
    return get_success_data(decided)


def create_active_program(total_budget_cents=10_000_000,
                           contingency_total_cents=1_000_000,
                           lines=None,
                           target_finish_date="2027-03-31",
                           name="P",
                           pm_id="pm-1", owner_id="owner-1"):
    """Full boot: create program + approve charter + approve baseline + activate.

    Returns the Program in ACTIVE status.
    """
    prog = create_program(name=name, pm_id=pm_id)
    pid = prog["id"]
    create_and_approve_charter(pid, pm_id=pm_id, owner_id=owner_id)
    create_and_approve_baseline(
        pid,
        total_budget_cents=total_budget_cents,
        contingency_total_cents=contingency_total_cents,
        lines=lines,
        target_finish_date=target_finish_date,
        pm_id=pm_id, owner_id=owner_id,
    )
    activated = api_client.activate_program(pid, pm_headers(pm_id))
    return get_success_data(activated)


# ---------- Tier 3: Contract lifecycle ----------
def create_contract(program_id, solicitation_estimate_cents=1_000_000,
                     vendor_name="V1", contract_type="CONTRACTOR", pm_id="pm-1"):
    resp = api_client.create_contract(
        create_contract_payload(
            program_id, vendor_name=vendor_name,
            contract_type=contract_type,
            solicitation_estimate_cents=solicitation_estimate_cents,
        ),
        pm_headers(pm_id),
    )
    return get_success_data(resp)


def begin_negotiation(contract_id, pm_id="pm-1"):
    return get_success_data(api_client.begin_negotiation(contract_id, pm_headers(pm_id)))


def counter_contract(contract_id, counter_amount_cents, pm_id="pm-1"):
    return get_success_data(api_client.counter_contract(
        contract_id, {"counter_amount_cents": counter_amount_cents}, pm_headers(pm_id)))


def execute_contract(contract_id, awarded_amount_cents, exec_id="exec-1"):
    return get_success_data(api_client.execute_contract(
        contract_id, {"awarded_amount_cents": awarded_amount_cents}, exec_headers(exec_id)))


def create_and_execute_contract(program_id, awarded_amount_cents,
                                 solicitation_estimate_cents=None,
                                 vendor_name="V1", contract_type="CONTRACTOR",
                                 pm_id="pm-1", exec_id="exec-1",
                                 negotiate=True):
    """Create contract, begin negotiation, execute. Returns EXECUTED Contract."""
    est = solicitation_estimate_cents if solicitation_estimate_cents is not None else awarded_amount_cents
    ct = create_contract(
        program_id,
        solicitation_estimate_cents=est,
        vendor_name=vendor_name,
        contract_type=contract_type,
        pm_id=pm_id,
    )
    begin_negotiation(ct["id"], pm_id=pm_id)
    return execute_contract(ct["id"], awarded_amount_cents, exec_id=exec_id)


# ---------- Tier 4: ChangeOrder lifecycle ----------
def create_change_order(contract_id, amount_cents=100_000, title="CO", reason="r",
                         supersedes_id=None, pm_id="pm-1"):
    payload = create_change_order_payload(
        contract_id, title=title, reason=reason, amount_cents=amount_cents,
    )
    if supersedes_id is not None:
        payload["supersedes_id"] = supersedes_id
    return get_success_data(api_client.create_change_order(payload, pm_headers(pm_id)))


def submit_change_order(co_id, pm_id="pm-1"):
    return get_success_data(api_client.submit_change_order(co_id, pm_headers(pm_id)))


def recommend_change_order(co_id, recommendation="APPROVE", analysis_note="ok", pm_id="pm-1"):
    return get_success_data(api_client.recommend_change_order(
        co_id, {"recommendation": recommendation, "analysis_note": analysis_note},
        pm_headers(pm_id)))


def decide_change_order(co_id, decision="APPROVE", owner_id="owner-1"):
    return get_success_data(api_client.decide_change_order(
        co_id, {"decision": decision}, owner_headers(owner_id)))


def create_submitted_change_order(contract_id, amount_cents=100_000, pm_id="pm-1"):
    """Create CO in DRAFT then submit -> UNDER_REVIEW."""
    co = create_change_order(contract_id, amount_cents=amount_cents, pm_id=pm_id)
    return submit_change_order(co["id"], pm_id=pm_id)


def create_recommended_change_order(contract_id, amount_cents=100_000,
                                     recommendation="APPROVE", pm_id="pm-1"):
    """Create + submit + recommend -> RECOMMEND_* state."""
    co = create_submitted_change_order(contract_id, amount_cents=amount_cents, pm_id=pm_id)
    return recommend_change_order(co["id"], recommendation=recommendation, pm_id=pm_id)


def approve_change_order(co_id, owner_id="owner-1"):
    return decide_change_order(co_id, decision="APPROVE", owner_id=owner_id)


def create_approved_change_order(contract_id, amount_cents=100_000,
                                  pm_id="pm-1", owner_id="owner-1"):
    """Create + submit + recommend APPROVE + Owner decide APPROVE. Returns APPROVED CO."""
    co = create_recommended_change_order(contract_id, amount_cents=amount_cents,
                                          recommendation="APPROVE", pm_id=pm_id)
    return approve_change_order(co["id"], owner_id=owner_id)


# ---------- Tier 5: RiskEntry lifecycle ----------
def create_risk_entry(program_id, probability_pct=50, impact_cents=400_000,
                       title="R", category="COST", pm_id="pm-1"):
    return get_success_data(api_client.create_risk_entry(
        create_risk_entry_payload(
            program_id, title=title, category=category,
            probability_pct=probability_pct, impact_cents=impact_cents,
        ),
        pm_headers(pm_id),
    ))


def assess_risk(risk_id, probability_pct, impact_cents, pm_id="pm-1"):
    return get_success_data(api_client.assess_risk(
        risk_id, {"probability_pct": probability_pct, "impact_cents": impact_cents},
        pm_headers(pm_id)))


def mitigate_risk(risk_id, mitigation_plan="mitigate", pm_id="pm-1"):
    return get_success_data(api_client.mitigate_risk(
        risk_id, {"mitigation_plan": mitigation_plan}, pm_headers(pm_id)))


def monitor_risk(risk_id, pm_id="pm-1"):
    return get_success_data(api_client.monitor_risk(risk_id, pm_headers(pm_id)))


def realize_risk(risk_id, actual_loss_cents, pm_id="pm-1"):
    return get_success_data(api_client.realize_risk(
        risk_id, {"actual_loss_cents": actual_loss_cents}, pm_headers(pm_id)))


def close_risk(risk_id, pm_id="pm-1"):
    return get_success_data(api_client.close_risk(risk_id, pm_headers(pm_id)))


def create_risk_in_state(program_id, target_state, probability_pct=50,
                          impact_cents=400_000, pm_id="pm-1", title="R", category="COST"):
    """Walk a risk to a target state. Only the common states needed by tests.

    target_state in {ASSESSED, ESCALATED, MITIGATING, MONITORING, REALIZED, CLOSED}.
    Caller is responsible for choosing probability*impact that reaches the
    correct threshold branch.
    """
    r = create_risk_entry(program_id, probability_pct=probability_pct,
                           impact_cents=impact_cents, title=title,
                           category=category, pm_id=pm_id)
    if target_state == "ASSESSED":
        return assess_risk(r["id"], probability_pct, impact_cents, pm_id=pm_id)
    if target_state == "ESCALATED":
        return assess_risk(r["id"], probability_pct, impact_cents, pm_id=pm_id)
    if target_state == "MITIGATING":
        assess_risk(r["id"], probability_pct, impact_cents, pm_id=pm_id)
        return mitigate_risk(r["id"], pm_id=pm_id)
    if target_state == "MONITORING":
        assess_risk(r["id"], probability_pct, impact_cents, pm_id=pm_id)
        mitigate_risk(r["id"], pm_id=pm_id)
        return monitor_risk(r["id"], pm_id=pm_id)
    if target_state == "REALIZED":
        # caller must pass through MONITORING or ESCALATED and provide actual_loss via separate call
        raise ValueError("Use realize_risk() directly after reaching ESCALATED/MONITORING")
    if target_state == "CLOSED":
        assess_risk(r["id"], probability_pct, impact_cents, pm_id=pm_id)
        return close_risk(r["id"], pm_id=pm_id)
    raise ValueError(f"unsupported target_state {target_state}")


# ---------- Tier 6: Drawdown lifecycle ----------
def create_drawdown(program_id, amount_cents, purpose="reserve", pm_id="pm-1"):
    return get_success_data(api_client.create_drawdown(
        create_drawdown_payload(program_id, purpose=purpose, amount_cents=amount_cents),
        pm_headers(pm_id),
    ))


def commit_drawdown(dd_id, pm_id="pm-1"):
    return get_success_data(api_client.commit_drawdown(dd_id, pm_headers(pm_id)))


def draw_drawdown(dd_id, pm_id="pm-1"):
    return get_success_data(api_client.draw_drawdown(dd_id, pm_headers(pm_id)))


def release_drawdown(dd_id, pm_id="pm-1"):
    return get_success_data(api_client.release_drawdown(dd_id, pm_headers(pm_id)))


# ---------- Tier 7: OwnerReport lifecycle ----------
def create_owner_report(program_id, period="2026-08", pm_id="pm-1"):
    return get_success_data(api_client.create_owner_report(
        create_owner_report_payload(program_id, period=period), pm_headers(pm_id)))


def submit_owner_report(report_id, pm_id="pm-1"):
    return get_success_data(api_client.submit_owner_report(report_id, pm_headers(pm_id)))


def accept_owner_report(report_id, owner_id="owner-1"):
    return get_success_data(api_client.accept_owner_report(report_id, owner_headers(owner_id)))


def return_owner_report(report_id, return_note="revise", owner_id="owner-1"):
    return get_success_data(api_client.return_owner_report(
        report_id, {"return_note": return_note}, owner_headers(owner_id)))


# ---------- Tier 8: Stakeholder / Engagement ----------
def create_stakeholder_group(program_id, group_name="G1", group_type="USER_GROUP",
                              contact_email="g1@x.com", pm_id="pm-1"):
    return get_success_data(api_client.create_stakeholder_group(
        create_stakeholder_group_payload(
            program_id, group_name=group_name, group_type=group_type,
            contact_email=contact_email,
        ),
        pm_headers(pm_id),
    ))


def create_engagement(stakeholder_group_id, title="E",
                       scheduled_start="2026-09-02T09:00:00Z",
                       scheduled_end="2026-09-02T10:00:00Z", pm_id="pm-1"):
    return get_success_data(api_client.create_engagement(
        create_engagement_payload(
            stakeholder_group_id, title=title,
            scheduled_start=scheduled_start, scheduled_end=scheduled_end,
        ),
        pm_headers(pm_id),
    ))


def schedule_engagement(eng_id, pm_id="pm-1"):
    return get_success_data(api_client.schedule_engagement(eng_id, pm_headers(pm_id)))


# ---------- Tier 9: Occupancy / Wave ----------
def create_occupancy_plan(program_id, plan_name="PL", target_move_month="2026-10", pm_id="pm-1"):
    return get_success_data(api_client.create_occupancy_plan(
        create_occupancy_plan_payload(
            program_id, plan_name=plan_name, target_move_month=target_move_month),
        pm_headers(pm_id),
    ))


def coordinate_occupancy_plan(plan_id, pm_id="pm-1"):
    return get_success_data(api_client.coordinate_occupancy_plan(plan_id, pm_headers(pm_id)))


def mark_ready_occupancy_plan(plan_id, pm_id="pm-1"):
    return get_success_data(api_client.mark_ready_occupancy_plan(plan_id, pm_headers(pm_id)))


def execute_occupancy_plan(plan_id, pm_id="pm-1"):
    return get_success_data(api_client.execute_occupancy_plan(plan_id, pm_headers(pm_id)))


def create_move_in_wave(occupancy_plan_id, stakeholder_group_id, wave_name="W",
                        dock_resource="DOCK_A",
                        move_start="2026-10-01T08:00:00Z",
                        move_end="2026-10-01T12:00:00Z",
                        criticality_weight=1, pm_id="pm-1"):
    return get_success_data(api_client.create_move_in_wave(
        create_move_in_wave_payload(
            occupancy_plan_id, stakeholder_group_id,
            wave_name=wave_name, dock_resource=dock_resource,
            move_start=move_start, move_end=move_end,
            criticality_weight=criticality_weight,
        ),
        pm_headers(pm_id),
    ))


def confirm_move_in_wave(wave_id, pm_id="pm-1"):
    return get_success_data(api_client.confirm_move_in_wave(wave_id, pm_headers(pm_id)))


def complete_move_in_wave(wave_id, pm_id="pm-1"):
    return get_success_data(api_client.complete_move_in_wave(wave_id, pm_headers(pm_id)))


def cancel_move_in_wave(wave_id, pm_id="pm-1"):
    return get_success_data(api_client.cancel_move_in_wave(wave_id, pm_headers(pm_id)))


# ---------- Tier 10: Closeout / Lesson ----------
def create_closeout_item(program_id, item_type="PUNCH_LIST", title="item", pm_id="pm-1"):
    return get_success_data(api_client.create_closeout_item(
        create_closeout_item_payload(program_id, item_type=item_type, title=title),
        pm_headers(pm_id),
    ))


def submit_closeout_item(item_id, pm_id="pm-1"):
    return get_success_data(api_client.submit_closeout_item(item_id, pm_headers(pm_id)))


def verify_closeout_item(item_id, exec_id="exec-1"):
    return get_success_data(api_client.verify_closeout_item(item_id, exec_headers(exec_id)))


def reject_closeout_item(item_id, rejection_note="incomplete", exec_id="exec-1"):
    return get_success_data(api_client.reject_closeout_item(
        item_id, {"rejection_note": rejection_note}, exec_headers(exec_id)))


def create_lesson_entry(program_id, category="COST", lesson_text="lesson",
                          recommendation="rec", pm_id="pm-1"):
    return get_success_data(api_client.create_lesson_entry(
        create_lesson_entry_payload(
            program_id, category=category,
            lesson_text=lesson_text, recommendation=recommendation),
        pm_headers(pm_id),
    ))


# ---------- Composite setups shared across many test cases ----------
def setup_minimal_active_program(budget=10_000_000, contingency=1_000_000,
                                  lines=None, name="P", pm_id="pm-1", owner_id="owner-1"):
    """The canonical starting state: an ACTIVE program with one approved charter
    and one approved baseline. Returns (program_dict, program_id)."""
    prog = create_active_program(
        total_budget_cents=budget,
        contingency_total_cents=contingency,
        lines=lines,
        name=name,
        pm_id=pm_id, owner_id=owner_id,
    )
    return prog, prog["id"]


def setup_active_program_with_contract(budget=10_000_000, contingency=1_000_000,
                                        awarded=4_500_000,
                                        pm_id="pm-1", exec_id="exec-1", owner_id="owner-1",
                                        name="P"):
    """ACTIVE program + one EXECUTED contract. Returns (program_id, contract)."""
    prog, pid = setup_minimal_active_program(budget=budget, contingency=contingency,
                                               name=name, pm_id=pm_id, owner_id=owner_id)
    ct = create_and_execute_contract(pid, awarded, pm_id=pm_id, exec_id=exec_id)
    return pid, ct


def setup_active_program_with_group(budget=10_000_000, contingency=1_000_000,
                                      pm_id="pm-1", owner_id="owner-1", name="P"):
    """ACTIVE program + one stakeholder group. Returns (program_id, group)."""
    prog, pid = setup_minimal_active_program(budget=budget, contingency=contingency,
                                               name=name, pm_id=pm_id, owner_id=owner_id)
    g = create_stakeholder_group(pid, pm_id=pm_id)
    return pid, g


def setup_active_program_with_plan_coordinating(budget=10_000_000, contingency=1_000_000,
                                                  pm_id="pm-1", owner_id="owner-1", name="P"):
    """ACTIVE program + group + plan in COORDINATING. Returns (program_id, group, plan)."""
    pid, g = setup_active_program_with_group(budget=budget, contingency=contingency,
                                                pm_id=pm_id, owner_id=owner_id, name=name)
    pl = create_occupancy_plan(pid, pm_id=pm_id)
    coordinate_occupancy_plan(pl["id"], pm_id=pm_id)
    return pid, g, pl


def setup_active_program_with_plan_ready(budget=10_000_000, contingency=1_000_000,
                                           pm_id="pm-1", owner_id="owner-1", name="P"):
    """ACTIVE program + group + plan in READY. Returns (program_id, group, plan)."""
    pid, g, pl = setup_active_program_with_plan_coordinating(
        budget=budget, contingency=contingency, pm_id=pm_id, owner_id=owner_id, name=name)
    pl = mark_ready_occupancy_plan(pl["id"], pm_id=pm_id)
    return pid, g, pl
